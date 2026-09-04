import os
from pathlib import Path
from dotenv import load_dotenv
import asyncpg

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---------------------------------------------------------------------------
# Connection string
# ---------------------------------------------------------------------------
# Get this from Supabase: Project Settings -> Database -> Connection string
# -> "Transaction" mode (port 6543). Transaction-mode pooling is what you
# want for a normal web backend making short-lived queries (as opposed to
# "Session" mode, which is for long-lived connections / prepared statements).
#
# .env example:
#   SUPABASE_DB_URL=postgresql://postgres.xxxxx:[password]@aws-0-xx.pooler.supabase.com:6543/postgres
SUPABASE_DB_URL = os.environ["SUPABASE_DB_URL"]

# Module-level pool, created once at app startup via init_db().
pool: asyncpg.Pool | None = None


async def init_db():
    """
    Call this once at startup (server.py's FastAPI startup event / lifespan),
    same place the old code called ensure_indexes(). Indexes themselves now
    live in schema.sql (created once, up front) — there's nothing left to
    "ensure" at every boot, so this function's only job is opening the pool.
    """
    global pool
    pool = await asyncpg.create_pool(
        SUPABASE_DB_URL,
        min_size=int(os.environ.get("DB_MIN_POOL_SIZE", "5")),
        max_size=int(os.environ.get("DB_MAX_POOL_SIZE", "20")),
        # Supavisor (Supabase's pooler) is already pooling connections on its
        # side in transaction mode — it does not support prepared statements
        # across requests, so this must stay disabled.
        statement_cache_size=0,
    )


async def close_db():
    """Call on shutdown (mirrors the old close_redis()-style cleanup)."""
    global pool
    if pool is not None:
        await pool.close()
        pool = None


def get_pool() -> asyncpg.Pool:
    """
    Every other file imports this instead of a Mongo-style `db` object.
    Usage pattern, e.g. in auth.py:

        from database import get_pool

        async def get_user_by_email(email: str):
            async with get_pool().acquire() as conn:
                return await conn.fetchrow(
                    "select * from users where email = $1", email
                )

    Each file's queries get rewritten from Mongo's find_one/insert_one/
    update_one style into plain SQL as we go through server.py, auth.py,
    escalation.py etc. one at a time — that rewrite is where the actual
    query logic changes; this file only provides the connection.
    """
    if pool is None:
        raise RuntimeError("Database pool not initialized — call init_db() at startup first.")
    return pool