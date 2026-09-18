"""Bootstrap ONLY an empty, explicitly local test database. Never production.

The Supabase bootstrap includes destructive drops and cron jobs. This local-only
adapter requires an empty *_local database and excludes the cloud purge job.
Run after creating the local PostgreSQL role/database and backend/.env.
"""
import asyncio
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse
import asyncpg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


async def main():
    load_dotenv(ROOT/'backend/.env')
    url = os.environ['DATABASE_URL']
    parsed = urlparse(url)
    if os.environ.get('APP_ENV') != 'test' or parsed.hostname not in ('127.0.0.1','localhost') or not parsed.path.endswith('_local'):
        raise RuntimeError('Refusing to bootstrap anything except an explicitly local test database.')
    username, dbname = parsed.username, parsed.path[1:]
    if not re.fullmatch(r'[a-z][a-z0-9_]*',username) or not re.fullmatch(r'[a-z][a-z0-9_]*',dbname):
        raise RuntimeError('Invalid local role/database identifier.')
    admin = ['runuser','-u','postgres','--','psql','-v','ON_ERROR_STOP=1']
    def sql(statement):
        return subprocess.run(admin+['-tAc',statement],capture_output=True,text=True,check=True).stdout.strip()
    if not sql(f"SELECT 1 FROM pg_roles WHERE rolname='{username}'"):
        password = parsed.password.replace("'", "''")
        sql(f"CREATE ROLE {username} LOGIN PASSWORD '{password}'")
    if not sql(f"SELECT 1 FROM pg_database WHERE datname='{dbname}'"):
        sql(f'CREATE DATABASE {dbname} OWNER {username}')
    conn = await asyncpg.connect(url)
    try:
        count = await conn.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        if count:
            print('Existing local database preserved; bootstrap skipped.')
            return
        source = (ROOT/'backend/schema.sql').read_text().split('-- PURGE JOB')[0]
        source = '\n'.join(line for line in source.splitlines() if 'create extension if not exists pg_cron' not in line)
        async with conn.transaction():
            await conn.execute(source)
        print('Empty local database initialized without cron or external jobs.')
    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(main())