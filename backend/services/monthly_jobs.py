"""Generate the previous calendar month's report from 9am on the first, with catch-up."""
import logging
from datetime import datetime, timedelta, timezone
from database import get_pool
from services import billing_access
from services.schedule_source import local_now

logger=logging.getLogger(__name__)


async def drain(now=None):
    now=now or datetime.now(timezone.utc)
    pool=get_pool()
    for row in await pool.fetch("SELECT p.* FROM parents p JOIN activation_state a ON a.user_id=p.user_id WHERE p.deleted_at IS NULL AND a.whatsapp_activated=true"):
        parent=dict(row)
        local=local_now(parent,now)
        if local.day==1 and local.hour<9:
            continue
        previous=local.replace(day=1)-timedelta(days=1)
        period=previous.strftime('%Y-%m')
        if parent['created_at'].astimezone(local.tzinfo).strftime('%Y-%m')>period:
            continue
        async with pool.acquire() as conn:
            if not (await billing_access.access(conn,parent['user_id']))['allowed']:
                continue
        await pool.execute("""INSERT INTO monthly_report_jobs(parent_id,period) VALUES($1,$2)
            ON CONFLICT(parent_id,period) DO UPDATE SET status='pending',attempts=0,next_attempt_at=now()
            WHERE monthly_report_jobs.status='cancelled'""",parent['id'],period)
    await pool.execute("UPDATE monthly_report_jobs SET status='retry' WHERE status='running' AND next_attempt_at<now()-interval '30 minutes'")
    for _ in range(10):
        job=await pool.fetchrow("""UPDATE monthly_report_jobs SET status='running',attempts=attempts+1,next_attempt_at=now()+interval '15 minutes'
            WHERE (parent_id,period)=(SELECT parent_id,period FROM monthly_report_jobs WHERE status IN ('pending','retry')
                AND attempts<8 AND next_attempt_at<=now() ORDER BY period,parent_id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *""")
        if not job:
            break
        try:
            async with pool.acquire() as conn:
                parent=await conn.fetchrow('SELECT * FROM parents WHERE id=$1 AND deleted_at IS NULL',job['parent_id'])
                entitlement=await billing_access.access(conn,parent['user_id']) if parent else {'allowed':False}
            if not entitlement['allowed']:
                state,detail='cancelled','Care access is no longer active.'
            else:
                from monthly_report import generate_monthly_report
                year,month=map(int,job['period'].split('-'))
                await generate_monthly_report(parent['user_id'],parent['id'],entitlement['plan'],year,month,notify=True)
                state,detail='complete',None
        except Exception as exc:
            logger.exception('Monthly report generation failed')
            state,detail=('retry' if job['attempts']<8 else 'failed'),type(exc).__name__
        await pool.execute('UPDATE monthly_report_jobs SET status=$3,detail=$4 WHERE parent_id=$1 AND period=$2',job['parent_id'],job['period'],state,detail)
