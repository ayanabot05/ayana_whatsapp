import asyncio
import json
import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")


# ---------------------------------------------------------------------------
# JSONB codec (Mongo -> Supabase migration fix).
# Strings are assumed to be already JSON-encoded and are passed through, so
# both `json.dumps(val)` + `::jsonb` and raw dict/list writes work.
# ---------------------------------------------------------------------------
def _jsonb_dumps(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.execute("SET search_path TO public, pg_catalog")
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename,
            encoder=_jsonb_dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


# ---------------------------------------------------------------------------
# Connection string (Supabase transaction pooler, port 6543)
# ---------------------------------------------------------------------------
SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
if not SUPABASE_DB_URL:
    raise RuntimeError("SUPABASE_DB_URL or DATABASE_URL must be set")

pool: asyncpg.Pool | None = None


async def _noop_reset(conn: asyncpg.Connection) -> None:
    # Ensure search_path is always public in transaction pooling mode
    await conn.execute("SET search_path TO public, pg_catalog")
    return None


async def init_db():
    global pool
    pool = await asyncpg.create_pool(
        SUPABASE_DB_URL,
        min_size=int(os.environ.get("DB_MIN_POOL_SIZE", "10")),
        max_size=int(os.environ.get("DB_MAX_POOL_SIZE", "20")),
        reset=_noop_reset,
        max_inactive_connection_lifetime=float(os.environ.get("DB_MAX_INACTIVE_SEC", "1800")),
        # Supavisor transaction mode does not support prepared statements.
        statement_cache_size=0,
        init=_init_connection,
    )


async def close_db():
    global pool
    if pool is not None:
        await pool.close()
        pool = None


# ---------------------------------------------------------------------------
# Request-scoped transaction connection
# ---------------------------------------------------------------------------
# Stores (connection, owner_task). The owner check matters: asyncio.create_task
# copies the current context, so without it a fire-and-forget task (audit
# writes, notifications) started inside the transaction would inherit the
# connection and use it concurrently -> "another operation is in progress".
_transaction_scope: ContextVar = ContextVar("ayana_transaction_scope", default=None)


class _ScopedPool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection

    def __getattr__(self, name):
        return getattr(self.connection, name)


@asynccontextmanager
async def atomic_care_save():
    """Reuse route validation under one request-local transaction."""
    async with get_pool().acquire() as conn, conn.transaction():
        token = _transaction_scope.set((conn, asyncio.current_task()))
        try:
            yield conn
        finally:
            _transaction_scope.reset(token)


def get_raw_pool() -> asyncpg.Pool:
    """The real pool, never the transaction-scoped connection."""
    if pool is None:
        raise RuntimeError("Database pool not initialized — call init_db() at startup first.")
    return pool


def get_pool():
    """
    Returns the transaction connection only for the task that opened the
    transaction; every other task (including children spawned inside it)
    gets the real pool.
    """
    scope = _transaction_scope.get()
    if scope is not None:
        conn, owner = scope
        if owner is asyncio.current_task():
            return _ScopedPool(conn)
    return get_raw_pool()