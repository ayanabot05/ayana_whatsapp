"""Daily family alert for repeated failed or unconfirmed parent deliveries."""
from datetime import datetime, timedelta, timezone
from database import get_pool
from services import billing_access, family_delivery
from services.schedule_source import local_now, eligible, load_schedule


async def drain(now=None):
    now=now or datetime.now(timezone.utc)
    pool=get_pool()
    for row in await pool.fetch('SELECT * FROM parents WHERE deleted_at IS NULL'):
        parent=dict(row)
        local=local_now(parent,now)
        async with pool.acquire() as conn, conn.transaction():
            if not await conn.fetchval('SELECT whatsapp_activated FROM activation_state WHERE user_id=$1',parent['user_id']):
                continue
            schedule,_=await load_schedule(conn,parent,now)
            if not eligible(parent,local,schedule,check_hours=False) or not (await billing_access.access(conn,parent['user_id']))['allowed']:
                continue
            # Count distinct scheduled slots, not retry attempts. A later
            # delivered attempt resolves that slot; unknown submissions never
            # get described as confirmed failures.
            count=await conn.fetchval("""SELECT count(*) FROM (
                SELECT event_key FROM message_logs WHERE parent_id=$1 AND day_key=$2 AND event_key IS NOT NULL
                AND coalesce(skipped,false)=false AND status NOT IN ('skipped','simulated')
                AND msg_type IN ('checkin','activity','reminder','safety') GROUP BY event_key
                HAVING NOT bool_or(coalesce(delivery_status,'') IN ('delivered','read'))
                AND max(created_at)<=$3) slots""",parent['id'],local.date().isoformat(),now-timedelta(hours=1))
            if count<2:
                continue
            name=parent.get('preferred_name') or parent['name']
            day=local.date().isoformat()
            detail=f"AYANA could not confirm delivery of {count} scheduled messages to {name}. Please check their phone or contact them directly."
            won=await conn.fetchval('INSERT INTO parent_delivery_alerts(parent_id,day_key,failures,detail) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING RETURNING parent_id',parent['id'],day,count,detail)
            if won:
                await family_delivery.enqueue(conn,parent,'delivery_alert',day,{'name':name,'day':day,'count':count})
        if won:
            from services.cache import bump_version
            await bump_version(parent['user_id'])
