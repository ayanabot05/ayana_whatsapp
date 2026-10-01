"""Initialize the isolated localhost delivery test cluster; never reads .env."""
import asyncio
from pathlib import Path
import asyncpg


async def main():
    conn = await asyncpg.connect('postgresql://ayana_test@127.0.0.1:55439/postgres')
    if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname='ayana_delivery_local'"):
        await conn.execute('CREATE DATABASE ayana_delivery_local')
    await conn.close()
    conn = await asyncpg.connect('postgresql://ayana_test@127.0.0.1:55439/ayana_delivery_local')
    try:
        if await conn.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"):
            print('Existing local database preserved.')
            return
        source = (Path(__file__).resolve().parents[1] / 'backend/schema_complete.sql').read_text(encoding='utf-8')
        await conn.execute(source)
        print('Isolated local database initialized.')
    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
