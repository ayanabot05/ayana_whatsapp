"""Versioned additive migrations; never execute the destructive bootstrap schema."""
from pathlib import Path
from database import get_pool


async def apply_care_migration():
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('ayana:migrations', 0))")
        await conn.execute("CREATE TABLE IF NOT EXISTS app_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        for name in ('004_reliable_care','005_account_sessions'):
            if not await conn.fetchval('SELECT 1 FROM app_migrations WHERE name=$1',name):
                sql = (Path(__file__).parents[1]/f'migrations/{name}.sql').read_text()
                await conn.execute(sql)
                await conn.execute('INSERT INTO app_migrations(name) VALUES($1)',name)