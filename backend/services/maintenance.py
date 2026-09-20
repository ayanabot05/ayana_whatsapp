"""Existing debug/analytics retention, off the startup path."""
from database import get_pool


async def purge_operational_logs():
    async with get_pool().acquire() as conn, conn.transaction():
        if not await conn.fetchval("SELECT pg_try_advisory_xact_lock(hashtextextended('ayana:operational-retention',0))"):
            return
        await conn.execute("DELETE FROM webhook_debug WHERE created_at<now()-interval '14 days'")
        await conn.execute("DELETE FROM analytics_events WHERE created_at<now()-interval '90 days'")