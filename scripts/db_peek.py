import asyncio, asyncpg, os, sys
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

QUERIES = {
    "users": "select id, email, name, role, household_owner_id, created_at::date from users where deleted_at is null order by created_at desc limit 10",
    "parents": "select id, user_id, name, phone, language, timezone from parents where deleted_at is null order by created_at desc limit 10",
    "payment": "select user_id, plan, status, billing from payment_state",
    "orphans": "select count(*) from parent_replies where parent_id is null",
    "replies": "select from_phone, parent_id, intent, body, created_at from parent_replies order by created_at desc limit 8",
    "logs": "select parent_id, day_key, category, msg_type, status, reply_status, created_at from message_logs order by created_at desc limit 8",
    "report_cols": "select column_name from information_schema.columns where table_name='monthly_reports'",
}

async def main():
    c = await asyncpg.connect(os.environ["SUPABASE_DB_URL"], statement_cache_size=0)
    keys = sys.argv[1:] or list(QUERIES)
    for k in keys:
        q = QUERIES.get(k, k)
        rows = await c.fetch(q)
        print(f"== {k}")
        for r in rows:
            print(dict(r))
    await c.close()

asyncio.run(main())
