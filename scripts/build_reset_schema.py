"""Generate a destructive AYANA-only reset script. Does not connect to a DB."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    schema = (ROOT / 'backend/schema_complete.sql').read_text(encoding='utf-8')
    tables = re.findall(r'^CREATE TABLE public\.(\w+) \(', schema, re.M)
    if len(tables) != 52 or len(set(tables)) != len(tables):
        raise RuntimeError('Schema table inventory changed; review reset scope before generating.')
    body = schema[schema.index('-- PostgreSQL database dump'):]
    header = """-- DESTRUCTIVE: permanently deletes ALL AYANA account, parent, billing,
-- message, reply, report and delivery data, then recreates the latest schema.
-- Export a backup first. Stop the backend/scheduler before running this file.
-- Run the ENTIRE file in the target database's SQL editor as its owner.
-- No passwords are embedded. Restart the backend afterwards to seed staff
-- accounts from ADMIN_EMAIL/ADMIN_PASSWORD and EMPLOYEE_EMAIL/EMPLOYEE_PASSWORD.
-- Only known AYANA public tables are targeted; Supabase auth/storage are untouched.
-- No CASCADE: unexpected external dependencies cause a rollback, not their deletion.
BEGIN;
SET LOCAL lock_timeout = '15s';

-- Retire the obsolete AYANA retention job if this database installed pg_cron.
DO $$ BEGIN
  IF to_regclass('cron.job') IS NOT NULL THEN
    EXECUTE 'SELECT cron.unschedule(jobid) FROM cron.job WHERE jobname = ''ayana-nightly-purge''';
  END IF;
END $$;
DROP FUNCTION IF EXISTS public.purge_expired_data();

DROP TABLE IF EXISTS
"""
    drops = ',\n'.join('    public.' + table for table in tables) + ';\n'
    functions = '\nDROP FUNCTION IF EXISTS public.care_schedule_effective_from();\n\n'
    output = ROOT / 'backend/reset_schema.sql'
    output.write_text(header + drops + functions + body, encoding='utf-8')
    print(f'Generated {output.name}: {len(tables)} AYANA tables; no database accessed.')


if __name__ == '__main__':
    main()
