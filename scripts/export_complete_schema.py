"""Export the migrated, isolated test database as a fresh-install SQL script."""
import asyncio
import re
import subprocess
from pathlib import Path
import asyncpg

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'postgresql://ayana_test@127.0.0.1:55439/ayana_delivery_local'


async def main():
    dump = subprocess.run([r'C:\Program Files\PostgreSQL\18\bin\pg_dump.exe', '--schema-only',
        '--no-owner', '--no-privileges', '--schema=public', SOURCE], check=True, capture_output=True, encoding='utf-8').stdout
    dump = '\n'.join(line for line in dump.splitlines() if not line.startswith('\\')
        and not line.startswith('SET transaction_timeout') and line != 'SET row_security = off;')
    dump = dump.replace('CREATE SCHEMA public;', 'CREATE SCHEMA IF NOT EXISTS public;')
    tables = re.findall(r'CREATE TABLE public\.(\w+)', dump)
    conn = await asyncpg.connect(SOURCE)
    migrations = await conn.fetch('SELECT name FROM app_migrations ORDER BY name')
    await conn.close()
    names = ','.join("'" + name + "'" for name in tables)
    header = f'''-- AYANA complete fresh-install schema: {len(tables)} tables.
-- Generated from the base schema + startup DDL + applied versioned migrations.
-- No user data, credentials, DROP TABLE, or automatic retention/deletion jobs.
-- FOR A NEW EMPTY DATABASE ONLY. Existing databases must use app migrations.
-- All work is transactional; existing app tables cause an error before creation.
BEGIN;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public'
             AND table_name IN ({names})) THEN
    RAISE EXCEPTION 'Existing AYANA tables found. Use additive migrations; do not recreate tables.';
  END IF;
END $$;
'''
    history = '\n'.join("INSERT INTO public.app_migrations(name) VALUES ('"+row['name']+"');" for row in migrations)
    target = ROOT / 'backend/schema_complete.sql'
    target.write_text(header + dump + '\n' + history + '\nCOMMIT;\n', encoding='utf-8')
    (ROOT / 'backend/schema.sql').write_text(target.read_text(encoding='utf-8'), encoding='utf-8')
    print(f'Created {target.name}: {len(tables)} tables, {len(migrations)} migration records.')


if __name__ == '__main__':
    asyncio.run(main())
