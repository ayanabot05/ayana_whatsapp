"""Silence checks based on delivered messages, not mere account age.

Never resend a delivered slot simply because a parent has not replied. A single
midday nudge and the approved child warnings replace the old retry burst loop.
"""
import logging
from datetime import datetime, timezone, timedelta
from database import get_pool
from services.schedule_source import eligible, local_now, load_schedule
from whatsapp import _send_content_template_with_retry, whatsapp_enabled

logger = logging.getLogger(__name__)


async def record_parent_reply_time(parent_id, ts=None):
    ts = ts or datetime.now(timezone.utc)
    await get_pool().execute('UPDATE care_watch SET last_reply_at=$2 WHERE parent_id=$1 AND day_key=$3',parent_id,ts,ts.strftime('%Y-%m-%d'))


async def _claim(key,parent_id):
    return await get_pool().fetchval("INSERT INTO care_send_claims(event_key,parent_id,attempts) VALUES($1,$2,1) ON CONFLICT(event_key) DO UPDATE SET status='sending',attempts=care_send_claims.attempts+1,created_at=now() WHERE care_send_claims.status='failed' AND care_send_claims.attempts<3 AND care_send_claims.created_at<now()-interval '15 minutes' RETURNING event_key",key,parent_id)


async def _send_claimed(key,parent,phone,template,lang,params):
    if not await _claim(key,parent['id']):
        state = await get_pool().fetchval('SELECT status FROM care_send_claims WHERE event_key=$1',key)
        return {'status':state,'already_attempted':True}
    try:
        result = await _send_content_template_with_retry(phone,template,lang,params,'care_warning')
    except Exception:
        result = {'status':'uncertain','detail':'Warning submission interrupted.'}
    await get_pool().execute('UPDATE care_send_claims SET status=$2,sid=$3,detail=$4 WHERE event_key=$1',key,result.get('status','failed'),result.get('sid'),result.get('detail'))
    return result


async def _notify_family_warning(conn,parent,day,kind,missed=0):
    members = await conn.fetch('SELECT * FROM users WHERE (id=$1 OR household_owner_id=$1) AND deleted_at IS NULL',parent['user_id'])
    siblings = await conn.fetch('SELECT * FROM care_circle_siblings WHERE owner_id=$1 AND verified',parent['user_id'])
    outcomes, seen = [], set()
    for row in [*members,*siblings]:
        person = dict(row)
        if person['phone'] in seen:
            continue
        seen.add(person['phone'])
        lang = person.get('language') if person.get('language') in ('en','te','hi') else 'en'
        name = parent.get('preferred_name') or parent['name']
        params = {'1':name,'2':str(missed)} if kind=='main' else {'1':name}
        # Serialize with an email-authorized number change before reading contact.
        async with get_pool().acquire() as contact_conn, contact_conn.transaction():
            await contact_conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','recipient:'+str(person['id']))
            table = 'users' if 'password_hash' in person else 'care_circle_siblings'
            if table == 'users':
                phone = await contact_conn.fetchval('SELECT phone FROM users WHERE id=$1 AND (id=$2 OR household_owner_id=$2) AND deleted_at IS NULL', person['id'], parent['user_id'])
            else:
                phone = await contact_conn.fetchval('SELECT phone FROM care_circle_siblings WHERE id=$1 AND owner_id=$2 AND verified', person['id'], parent['user_id'])
            if not phone:
                continue
            key = f"warning:{kind}:{parent['id']}:{day}:{person['id']}"
            result = await _send_claimed(key,parent,phone,f'ayana_{kind}_warn_child_{lang}',lang,params)
        outcomes.append(result.get('status') in ('sent','delivered','read'))
    return bool(outcomes) and all(outcomes)


async def _watch_parent(parent):
    async with get_pool().acquire() as conn, conn.transaction():
        if not await conn.fetchval('SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))','care-parent:'+str(parent['id'])):
            return
        active = await conn.fetchval('SELECT whatsapp_activated FROM activation_state WHERE user_id=$1',parent['user_id'])
        local = local_now(parent)
        schedule, _ = await load_schedule(conn,parent)
        if not active or not eligible(parent,local,schedule,check_hours=False):
            return
        from services.billing_access import access
        if not (await access(conn, parent['user_id']))['allowed']:
            return
        day = local.strftime('%Y-%m-%d')
        start = local.replace(hour=6,minute=0,second=0,microsecond=0)
        end = local.replace(hour=22,minute=0,second=0,microsecond=0)
        middle = local.replace(hour=14,minute=0,second=0,microsecond=0)
        if local<middle or local>=end+timedelta(hours=1):
            return
        logs = await conn.fetch("SELECT * FROM message_logs WHERE parent_id=$1 AND day_key=$2 AND msg_type IN ('checkin','reminder','activity') AND delivery_status IN ('delivered','read') AND created_at BETWEEN $3 AND $4 ORDER BY created_at",parent['id'],day,start,min(local,end))
        if not logs:
            return
        first_delivery = logs[0]['delivered_at'] or logs[0]['created_at']
        if datetime.now(timezone.utc)-first_delivery<timedelta(minutes=30):
            return
        await conn.execute('INSERT INTO care_watch(parent_id,day_key) VALUES($1,$2) ON CONFLICT DO NOTHING',parent['id'],day)
        watch = await conn.fetchrow('SELECT * FROM care_watch WHERE parent_id=$1 AND day_key=$2',parent['id'],day)
        replied = await conn.fetchval('SELECT EXISTS(SELECT 1 FROM parent_replies WHERE parent_id=$1 AND created_at BETWEEN $2 AND $3)',parent['id'],first_delivery,local)
        if replied:
            return
        if local>=end and not watch['main_warn_sent']:
            sent = await _notify_family_warning(conn,parent,day,'main',len(logs))
            await conn.execute('UPDATE care_watch SET main_warn_sent=$3,updated_at=now() WHERE parent_id=$1 AND day_key=$2',parent['id'],day,sent)
        elif local<end and not watch['first_warn_sent']:
            if not eligible(parent,local,schedule):
                return
            # Only morning deliveries qualify for the morning-specific template.
            if not any(log['created_at']<middle for log in logs):
                return
            recent = await conn.fetchval('SELECT max(created_at) FROM message_logs WHERE parent_id=$1',parent['id'])
            total = await conn.fetchval('SELECT count(*) FROM message_logs WHERE parent_id=$1 AND day_key=$2',parent['id'],day)
            if total>=15 or (recent and datetime.now(timezone.utc)-recent<timedelta(seconds=120)):
                return
            lang = parent.get('language') if parent.get('language') in ('en','te','hi') else 'en'
            key = f"nudge:{parent['id']}:{day}"
            result = await _send_claimed(key,parent,parent['phone'],f'ayana_first_warn_parent_{lang}',lang,{'1':parent.get('preferred_name') or parent['name']})
            if not result.get('already_attempted'):
                await conn.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,detail,sid,event_key) VALUES($1,$2,$3,'midday_nudge','reengagement',$4,$5,$6,$7)",parent['user_id'],parent['id'],day,result.get('status','failed'),result.get('detail'),result.get('sid'),key)
            if result.get('status') in ('sent','delivered','read'):
                sent = await _notify_family_warning(conn,parent,day,'first')
                await conn.execute('UPDATE care_watch SET first_warn_sent=$3,updated_at=now() WHERE parent_id=$1 AND day_key=$2',parent['id'],day,sent)


async def run_care_watch_impl():
    if not whatsapp_enabled():
        return
    for row in await get_pool().fetch('SELECT * FROM parents WHERE deleted_at IS NULL'):
        try:
            await _watch_parent(dict(row))
        except Exception:
            logger.exception('Care watch failed for parent %s',row['id'])