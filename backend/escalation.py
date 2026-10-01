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
    from services.family_access import recipients, recipient
    outcomes, seen = [], set()
    for recipient_kind, person in await recipients(conn, parent['user_id']):
        if person['phone'] in seen:
            continue
        seen.add(person['phone'])
        lang = person.get('language') if person.get('language') in ('en','te','hi') else 'en'
        name = parent.get('preferred_name') or parent['name']
        params = {'1':name,'2':str(missed)} if kind=='main' else {'1':name}
        # Serialize with an email-authorized number change before reading contact.
        async with get_pool().acquire() as contact_conn, contact_conn.transaction():
            await contact_conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','recipient:'+str(person['id']))
            current = await recipient(contact_conn,parent['user_id'],recipient_kind,person['id'])
            if not current:
                continue
            phone = current['phone']
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
        if local-first_delivery<timedelta(minutes=30):
            return
        await conn.execute('INSERT INTO care_watch(parent_id,day_key) VALUES($1,$2) ON CONFLICT DO NOTHING',parent['id'],day)
        watch = await conn.fetchrow('SELECT * FROM care_watch WHERE parent_id=$1 AND day_key=$2',parent['id'],day)
        replied = await conn.fetchval('SELECT EXISTS(SELECT 1 FROM parent_replies WHERE parent_id=$1 AND created_at BETWEEN $2 AND $3)',parent['id'],first_delivery,local)
        if replied:
            return
        if middle <= local < middle + timedelta(minutes=30) and first_delivery < middle and not watch['first_warn_sent']:
            # The child's approved wording says a new check-in was sent. Only
            # send it after Meta accepts the parent nudge. Claims deduplicate
            # each recipient separately when only part of the family succeeds.
            lang = parent.get('language') or 'en'
            name = parent.get('preferred_name') or parent['name']
            key = f"warning:first_parent:{parent['id']}:{day}"
            result = await _send_claimed(key, parent, parent['phone'],
                f'ayana_first_warn_parent_{lang}', lang, {'1': name})
            if result.get('status') in ('sent', 'delivered', 'read'):
                if not result.get('already_attempted'):
                    await conn.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,body,msg_type,status,sid,event_key,created_at) VALUES($1,$2,$3,'reengagement',$4,'reengagement','sent',$5,$6,$7)",
                        parent['user_id'],parent['id'],day,result.get('body') or 'Midday check-in',result.get('sid'),key,local)
                sent = await _notify_family_warning(conn,parent,day,'first')
                await conn.execute('UPDATE care_watch SET first_warn_sent=$3,updated_at=now() WHERE parent_id=$1 AND day_key=$2',parent['id'],day,sent)
        if local>=end and not watch['main_warn_sent']:
            sent = await _notify_family_warning(conn,parent,day,'main',len(logs))
            await conn.execute('UPDATE care_watch SET main_warn_sent=$3,updated_at=now() WHERE parent_id=$1 AND day_key=$2',parent['id'],day,sent)


async def run_care_watch_impl():
    if not whatsapp_enabled():
        return
    for row in await get_pool().fetch('SELECT * FROM parents WHERE deleted_at IS NULL'):
        try:
            await _watch_parent(dict(row))
        except Exception:
            logger.exception('Care watch failed for parent %s',row['id'])
