"""Restore the fresh schema on localhost and compare it with the migrated DB."""
import asyncio
import uuid
from pathlib import Path
import asyncpg


async def signature(conn):
    await conn.execute('SET search_path TO public')
    columns = await conn.fetch("""SELECT table_name,column_name,data_type,is_nullable,column_default
        FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position""")
    constraints = await conn.fetch("""SELECT r.relname,c.conname,pg_get_constraintdef(c.oid)
        FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid
        JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname='public'
        ORDER BY r.relname,c.conname""")
    return [tuple(r) for r in columns], [tuple(r) for r in constraints]


async def main():
    prefix = 'postgresql://ayana_test@127.0.0.1:55439/'
    name = 'ayana_schema_' + uuid.uuid4().hex[:8] + '_local'
    admin = await asyncpg.connect(prefix + 'postgres')
    await admin.execute('CREATE DATABASE ' + name)
    await admin.close()
    source = await asyncpg.connect(prefix + 'ayana_delivery_local')
    target = await asyncpg.connect(prefix + name)
    sql = (Path(__file__).resolve().parents[1] / 'backend/schema_complete.sql').read_text(encoding='utf-8')
    try:
        await target.execute(sql)
        assert await signature(source) == await signature(target), 'Schema columns or constraints differ'
        try:
            await target.execute(sql)
        except asyncpg.RaiseError as exc:
            assert 'Existing AYANA tables' in str(exc)
            await target.execute('ROLLBACK')
        else:
            raise AssertionError('Fresh schema must refuse an existing database')
        assert await signature(source) == await signature(target), 'Refusal changed schema'
        reset_path = Path(__file__).resolve().parents[1] / 'backend/reset_schema.sql'
        if reset_path.exists():
            await target.execute("INSERT INTO public.users(name,email,phone,password_hash) VALUES('Reset test','reset@example.test','+10000000099','test-only')")
            await target.execute(reset_path.read_text(encoding='utf-8'))
            assert await target.fetchval('SELECT count(*) FROM public.users') == 0
            assert await signature(source) == await signature(target), 'Reset schema differs'
            print('PASS: destructive reset erased the disposable test record and recreated the same schema.')
        count = await target.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        print(f'PASS: {count} tables restored; columns and constraints match; second run safely refused.')
    finally:
        await source.close()
        await target.close()


if __name__ == '__main__':
    asyncio.run(main())
