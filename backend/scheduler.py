"""Small job coordinator. Schedule interpretation lives in schedule_source.

Parent-local slots are claimed before sending. No activation backfill, expired
slot catch-up or automatic retry of an uncertain provider acceptance.
"""
import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import get_pool
from pricing import plan_limits, resolve_plan_id
from services.schedule_source import eligible, local_now, load_schedule, event_key
from services import inbox, notifications
from whatsapp import send_dynamic_checkin, send_reengagement, whatsapp_enabled
from escalation import run_care_watch_impl

logger = logging.getLogger(__name__)
_scheduler = None
_LAST_RUN = {}
MAX_DAILY_MESSAGES = 15
MAX_SCHEDULER_RETRIES = 3
MAX_LATE_MINUTES = 30
MIN_SEND_GAP_SECONDS = 120


def scheduler_heartbeat():
    return {'running':bool(_scheduler and _scheduler.running),'last_runs':dict(_LAST_RUN),'jobs':[{'id':j.id,'next_run':j.next_run_time.isoformat() if j.next_run_time else None} for j in (_scheduler.get_jobs() if _scheduler else [])]}


async def _with_lock(name, ttl_seconds, fn):
    # Session advisory lock does not expire mid-send, unlike the former 55s lease.
    async with get_pool().acquire() as conn:
        won = await conn.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))','job:'+name)
        if not won:
            return
        try:
            await fn()
            _LAST_RUN[name] = datetime.now(timezone.utc).isoformat()
        finally:
            await conn.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))','job:'+name)


async def _deliver_parent(parent, now):
    async with get_pool().acquire() as conn, conn.transaction():
        if not await conn.fetchval('SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))','care-parent:'+str(parent['id'])):
            return
        activation = await conn.fetchrow('SELECT * FROM activation_state WHERE user_id=$1',parent['user_id'])
        if not activation or not activation['whatsapp_activated']:
            return
        local = local_now(parent,now)
        schedule, items = await load_schedule(conn,parent)
        if not eligible(parent,local,schedule):
            return
        last = await conn.fetchval('SELECT max(created_at) FROM message_logs WHERE parent_id=$1',parent['id'])
        if last and now-last < timedelta(seconds=MIN_SEND_GAP_SECONDS):
            return
        plan = await conn.fetchval('SELECT plan FROM payment_state WHERE user_id=$1',parent['user_id'])
        limits = plan_limits(resolve_plan_id(plan or 'nitya'))
        day = local.strftime('%Y-%m-%d')
        sent = await conn.fetchval("SELECT count(*) FROM message_logs WHERE parent_id=$1 AND day_key=$2 AND status='sent'",parent['id'],day)
        if sent >= MAX_DAILY_MESSAGES:
            return
        since = max(filter(None,[parent['created_at'],activation['activated_at']]))
        for item in items:
            hour,minute = map(int,item['time'].split(':'))
            scheduled = local.replace(hour=hour,minute=minute,second=0,microsecond=0)
            if scheduled < since or scheduled > local or local-scheduled > timedelta(minutes=MAX_LATE_MINUTES):
                continue
            key = event_key(parent['id'],day,item)
            claim = await conn.fetchrow('SELECT * FROM care_send_claims WHERE event_key=$1',key)
            if claim and claim['status'] != 'failed':
                continue
            # Historical sends from the previous worker are not replayed.
            previous = await conn.fetchval("SELECT 1 FROM message_logs WHERE parent_id=$1 AND day_key=$2 AND category=$3 AND (slot_time=$4 OR slot_time IS NULL) AND event_key IS NULL AND status='sent' LIMIT 1",parent['id'],day,item['category'],item['time'])
            if previous:
                continue
            failures = await conn.fetchrow("SELECT count(*) AS n,max(created_at) AS last FROM message_logs WHERE event_key=$1 AND status='failed'",key)
            if failures['n'] >= MAX_SCHEDULER_RETRIES or (failures['last'] and now-failures['last'] < timedelta(minutes=5*max(1,failures['n']))):
                continue
            kind = item['type']
            if item['category'] == 'water':
                # Water has its own dedicated daily allowance (1), matching
                # models.limit_messages. It never consumes medicine (reminder)
                # capacity, and does not compete with the other activities.
                count = await conn.fetchval("SELECT count(*) FROM message_logs WHERE parent_id=$1 AND day_key=$2 AND category='water' AND status='sent'",parent['id'],day)
                if count >= 1:
                    continue
            else:
                limit_key = {'checkin':'checkins','reminder':'reminders','activity':'activities'}[kind]
                count = await conn.fetchval("SELECT count(*) FROM message_logs WHERE parent_id=$1 AND day_key=$2 AND msg_type=$3 AND category<>'water' AND status='sent'",parent['id'],day,kind)
                if count >= limits.get(limit_key,0):
                    continue
            # Separate committed claim survives a crash during the provider call.
            won = await get_pool().fetchval("INSERT INTO care_send_claims(event_key,parent_id) VALUES($1,$2) ON CONFLICT(event_key) DO UPDATE SET status='sending' WHERE care_send_claims.status='failed' RETURNING event_key",key,parent['id'])
            if not won:
                continue
            try:
                result = await send_dynamic_checkin(parent,item['category'],local.timetuple().tm_yday,limits.get('variants_per_slot',3),medicine_name=item.get('medicine_name',''))
            except Exception:
                result = {'status':'uncertain','detail':'Submission interrupted. Inspect provider receipts before retrying.'}
            state = result.get('status','failed')
            await conn.execute('INSERT INTO message_logs(user_id,parent_id,day_key,category,body,msg_type,status,detail,sid,slot_time,event_key,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)',parent['user_id'],parent['id'],day,item['category'],item.get('medicine_name') or item['category'],kind,state,result.get('detail'),result.get('sid'),item['time'],key,now)
            await conn.execute('UPDATE care_send_claims SET status=$2 WHERE event_key=$1',key,state)
            # One event per parent per tick; the global gap also covers escalation.
            break


async def _deliver_due_messages_impl():
    if not whatsapp_enabled():
        return
    now = datetime.now(timezone.utc)
    for row in await get_pool().fetch('SELECT * FROM parents WHERE deleted_at IS NULL'):
        try:
            await _deliver_parent(dict(row),now)
        except Exception:
            logger.exception('Parent scheduler failed for %s',row['id'])


async def _check_reengagement_impl():
    if not whatsapp_enabled():
        return
    for row in await get_pool().fetch('SELECT * FROM parents WHERE deleted_at IS NULL'):
        parent = dict(row)
        try:
            async with get_pool().acquire() as conn, conn.transaction():
                if not await conn.fetchval('SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))','care-parent:'+str(parent['id'])):
                    continue
                active = await conn.fetchval('SELECT whatsapp_activated FROM activation_state WHERE user_id=$1',parent['user_id'])
                schedule, _ = await load_schedule(conn,parent)
                local = local_now(parent)
                if not active or not eligible(parent,local,schedule):
                    continue
                delivered = await conn.fetchval("SELECT count(*) FROM message_logs WHERE parent_id=$1 AND day_key=$2 AND delivery_status IN ('delivered','read')",parent['id'],local.strftime('%Y-%m-%d'))
                if not delivered:
                    continue
                last = await conn.fetchval('SELECT max(created_at) FROM message_logs WHERE parent_id=$1',parent['id'])
                if last and datetime.now(timezone.utc)-last<timedelta(minutes=15):
                    continue
                count = await conn.fetchval('SELECT count(*) FROM message_logs WHERE parent_id=$1 AND day_key=$2',parent['id'],local.strftime('%Y-%m-%d'))
                if count>=MAX_DAILY_MESSAGES:
                    continue
                result = await send_reengagement(parent,(schedule or {}).get('reengagement_hours',4))
                if result.get('status') in ('sent','uncertain'):
                    await conn.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,detail,sid) VALUES($1,$2,$3,'reengagement','reengagement',$4,$5,$6)",parent['user_id'],parent['id'],local.strftime('%Y-%m-%d'),result['status'],result.get('detail'),result.get('sid'))
        except Exception:
            logger.exception('Reengagement failed for %s',parent['id'])


async def _deliver_due_messages():
    await _with_lock('delivery',0,_deliver_due_messages_impl)


async def _check_reengagement():
    await _with_lock('reengagement',0,_check_reengagement_impl)


async def _run_care_watch():
    if whatsapp_enabled():
        await _with_lock('care_watch',0,run_care_watch_impl)


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone='UTC')
    for fn, minutes, job in [(_deliver_due_messages,1,'delivery'),(_check_reengagement,15,'reengagement'),(_run_care_watch,5,'care_watch'),(inbox.drain,1,'inbox'),(notifications.drain_notifications,1,'notifications')]:
        _scheduler.add_job(fn,'interval',minutes=minutes,id='ayana_'+job,max_instances=1,coalesce=True)
    _scheduler.start()


def shutdown_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None