"""Shared delivery-stats helper used by admin dashboards and per-user views."""
from typing import Optional


async def delivery_funnel(conn, user_id: Optional[str] = None) -> dict:
    """sent → delivered → read + failed for real (SID-bearing) outbound messages.
    Scoped to a user when user_id is given, else global."""
    where = "where (sid is not null or status in ('sent','simulated','failed'))"
    args: list = []
    if user_id:
        where += " and user_id = $1::uuid"
        args = [user_id]
    row = await conn.fetchrow(
        f"""
        select
            count(*) filter (where status in ('sent','simulated') or delivery_status is not null) as sent,
            count(*) filter (where delivery_status in ('delivered','read'))                        as delivered,
            count(*) filter (where delivery_status = 'read')                                       as read,
            count(*) filter (where delivery_status = 'failed' or status = 'failed')                as failed
        from message_logs {where}
        """,
        *args,
    )
    return {
        "sent": row["sent"] or 0,
        "delivered": row["delivered"] or 0,
        "read": row["read"] or 0,
        "failed": row["failed"] or 0,
    }
