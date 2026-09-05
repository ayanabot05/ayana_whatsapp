import json
import os
from pathlib import Path
from dotenv import load_dotenv
import asyncpg

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")


# ---------------------------------------------------------------------------
# JSONB codec — critical fix for the incomplete Mongo→Supabase migration.
#
# Without this, every `select` that returns a jsonb column comes back as a
# raw JSON string ("[]", "{}", "[\"Bangaram\"]") instead of a Python
# list/dict. Downstream code that does `parent["habits"].get("tea_type")`
# or `parent["nicknames"][0]` then crashes with AttributeError, which
# manifests as the 500 on /activation/activate (render_slot_body chokes
# on the string).
#
# The encoder is intentionally forgiving: much of the existing code base
# already does `json.dumps(val)` before passing the value with a `::jsonb`
# cast — if we passed those strings back through json.dumps() we'd double-
# encode. So: if we get a string, assume it's already JSON and pass it
# through untouched; otherwise dump it. Both write patterns work.
# ---------------------------------------------------------------------------
def _jsonb_dumps(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value  # already a JSON-encoded string, pass through
    return json.dumps(value, default=str)


async def _init_connection(conn: asyncpg.Connection) -> None:
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename,
            encoder=_jsonb_dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )

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
SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
if not SUPABASE_DB_URL:
    raise RuntimeError("SUPABASE_DB_URL or DATABASE_URL must be set")

# Module-level pool, created once at app startup via init_db().
pool: asyncpg.Pool | None = None


async def _noop_reset(conn: asyncpg.Connection) -> None:
    # asyncpg's default release() runs a RESET/CLOSE/UNLISTEN query on every
    # pool release — a full extra round-trip to Supabase per acquire() block
    # (~0.3s cross-region). Supavisor in transaction mode already resets
    # session state, so skip it. Open transactions are still rolled back.
    return None


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
        min_size=int(os.environ.get("DB_MIN_POOL_SIZE", "10")),
        max_size=int(os.environ.get("DB_MAX_POOL_SIZE", "20")),
        reset=_noop_reset,
        # Keep connections warm: opening a new one costs ~1s cross-region.
        max_inactive_connection_lifetime=float(os.environ.get("DB_MAX_INACTIVE_SEC", "1800")),
        # Supavisor (Supabase's pooler) is already pooling connections on its
        # side in transaction mode — it does not support prepared statements
        # across requests, so this must stay disabled.
        statement_cache_size=0,
        # Register the JSONB codec on every new connection so reads decode
        # to real Python dicts/lists, not raw JSON strings.
        init=_init_connection,
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