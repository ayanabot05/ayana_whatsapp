"""Recipient-aware outbox. Acceptance, media and fallback have independent state."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from database import get_pool
from services.notification_transport import send_update, send_update_email, post_meta
from validation import validate_phone
import storage

logger = logging.getLogger(__name__)
RETRYABLE_CODES = {130429, 131000, 131016, 131056}


async def enqueue_reply(conn, reply):
    if reply['created_at'] < datetime.now(timezone.utc)-timedelta(hours=24):
        return
    users = await conn.fetch('SELECT id,phone FROM users WHERE (id=$1 OR household_owner_id=$1) AND deleted_at IS NULL ORDER BY created_at', reply['user_id'])
    siblings = await conn.fetch('SELECT id,phone FROM care_circle_siblings WHERE owner_id=$1 AND verified', reply['user_id'])
    seen = set()
    for kind, people in [('user', users), ('sibling', siblings)]:
        for person in people:
            try:
                phone = validate_phone(person['phone'])
            except ValueError:
                logger.warning('Invalid recipient phone on %s', person['id'])
                continue
            if phone not in seen:
                seen.add(phone)
                await conn.execute('INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING', reply['id'], kind, person['id'])


async def recipient_for(conn, n, owner_id):
    if n['recipient_kind'] == 'user':
        return await conn.fetchrow('SELECT * FROM users WHERE id=$1 AND (id=$2 OR household_owner_id=$2) AND deleted_at IS NULL', n['recipient_id'], owner_id)
    return await conn.fetchrow('SELECT * FROM care_circle_siblings WHERE id=$1 AND owner_id=$2 AND verified', n['recipient_id'], owner_id)


async def reply_details(conn, reply_id):
    row = await conn.fetchrow("""SELECT r.*,coalesce(nullif(p.preferred_name,''),p.name) AS parent_name,p.timezone,p.deleted_at AS parent_deleted_at,l.category,l.created_at AS sent_at
        FROM parent_replies r JOIN parents p ON p.id=r.parent_id LEFT JOIN message_logs l ON l.parent_id=r.parent_id AND
        (l.sid=r.context_id OR (r.context_id IS NULL AND r.association_source='explicit' AND l.id=r.message_log_id)) WHERE r.id=$1""", reply_id)
    if not row:
        return None
    reply = dict(row)
    reply['prompt'] = (reply['category'] or 'general message').replace('_', ' ')
    zone = ZoneInfo(reply['timezone'] or 'Asia/Kolkata')
    reply['display_time'] = reply['created_at'].astimezone(zone).strftime('%d %b, %I:%M %p %Z')
    reply['local_date'] = (reply.get('sent_at') or reply['created_at']).astimezone(zone).date().isoformat()
    return reply


async def window_open(conn, phone, changed_at=None):
    inbound = await conn.fetchval('SELECT last_inbound_at FROM recipient_sessions WHERE phone=$1', phone)
    return bool(inbound and inbound > datetime.now(timezone.utc)-timedelta(hours=24) and (not changed_at or inbound >= changed_at))


async def recover_contact(conn, kind, recipient_id, phone):
    # Old submitted/uncertain deliveries are immutable, never replayed to a new number.
    await conn.execute("""UPDATE reply_notifications n SET status='pending',to_phone=$3,sid=NULL,attempts=0,next_attempt_at=now(),detail=NULL
        FROM parent_replies r WHERE r.id=n.reply_id AND n.recipient_kind=$1 AND n.recipient_id=$2
        AND n.status IN ('pending','retry','awaiting_template','disabled','failed','blocked_policy')
        AND r.created_at>now()-interval '24 hours'""", kind, recipient_id, phone)


async def send_audio(phone, reply):
    try:
        if reply.get('media_storage_path') and storage.is_enabled():
            audio = {'link': await asyncio.to_thread(storage.signed_url, reply['media_storage_path'], 300)}
        elif reply.get('media_id'):
            audio = {'id': reply['media_id']}
        else:
            return {'status': 'unavailable', 'detail': 'Recording is not available yet.'}
        return await post_meta({'messaging_product': 'whatsapp', 'to': phone, 'type': 'audio', 'audio': audio})
    except Exception as exc:
        logger.warning('Audio submission interrupted (%s)', type(exc).__name__)
        return {'status': 'uncertain'}


def outcome(result, attempts):
    code = result.get('error_code')
    if code == 131047 and attempts < 4:
        return 'awaiting_template'
    if code in RETRYABLE_CODES and attempts < 4:
        return 'retry'
    if code == 131049:
        return 'blocked_policy'
    return 'accepted' if result.get('status') == 'sent' else result.get('status', 'failed')


async def deliver(notification_id):
    n = await get_pool().fetchrow("UPDATE reply_notifications SET status='sending',attempts=attempts+1,updated_at=now() WHERE id=$1 AND status IN ('pending','retry','awaiting_template','disabled') AND next_attempt_at<=now() AND attempts<4 RETURNING *", notification_id)
    if not n:
        return
    try:
        async with get_pool().acquire() as conn, conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'recipient:' + str(n['recipient_id']))
            reply = await reply_details(conn, n['reply_id'])
            recipient = await recipient_for(conn, n, reply['user_id']) if reply else None
            if not recipient or reply['parent_deleted_at']:
                await conn.execute("UPDATE reply_notifications SET status='cancelled',updated_at=now() WHERE id=$1", n['id'])
                return
            if reply['created_at'] < datetime.now(timezone.utc)-timedelta(hours=24):
                await conn.execute("UPDATE reply_notifications SET status='expired',detail='Historical updates are not replayed.',updated_at=now() WHERE id=$1", n['id'])
                return
            recipient = dict(recipient)
            phone = validate_phone(recipient['phone'])
            opened = await window_open(conn, phone, recipient.get('phone_changed_at'))
            result = await send_update(phone, reply, opened, recipient.get('language') or 'en')
            state = outcome(result, n['attempts'])
            if result.get('error_code') == 131047:
                await conn.execute('DELETE FROM recipient_sessions WHERE phone=$1', phone)
            if result.get('sid'):
                await conn.execute('INSERT INTO notification_attempts(sid,notification_id,phone,status) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING', result['sid'], n['id'], phone, state)
            await conn.execute("UPDATE reply_notifications SET to_phone=$2,status=$3,sid=$4,detail=$5,error_code=$6,next_attempt_at=now()+interval '5 minutes',updated_at=now(),audio_status=CASE WHEN $7 THEN 'pending' ELSE audio_status END WHERE id=$1", n['id'], phone, state, result.get('sid'), result.get('detail'), result.get('error_code'), bool(opened and reply['is_voice'] and state == 'accepted'))
    except Exception as exc:
        logger.exception('Notification %s interrupted (%s)', notification_id, type(exc).__name__)
        await get_pool().execute("UPDATE reply_notifications SET status='uncertain',detail='Submission interrupted; reconcile before retrying.',updated_at=now() WHERE id=$1", notification_id)


async def deliver_audio(n):
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'recipient:' + str(n['recipient_id']))
        reply = await reply_details(conn, n['reply_id'])
        recipient = await recipient_for(conn, n, reply['user_id']) if reply else None
        if not recipient or validate_phone(recipient['phone']) != n['to_phone'] or not await window_open(conn, n['to_phone'], dict(recipient).get('phone_changed_at')):
            await conn.execute("UPDATE reply_notifications SET audio_status='awaiting_request' WHERE id=$1", n['id'])
            return
        # Separate committed claim; an audio timeout cannot undo text acceptance.
        won = await get_pool().fetchval("UPDATE reply_notifications SET audio_status='sending',audio_attempts=audio_attempts+1,audio_next_attempt_at=now()+interval '5 minutes' WHERE id=$1 AND audio_status IN ('pending','retry') RETURNING id", n['id'])
        if not won:
            return
        result = await send_audio(n['to_phone'], reply)
        state = result['status']
        if state in ('failed', 'unavailable') and n['audio_attempts'] < 3:
            state = 'retry'
        await conn.execute('UPDATE reply_notifications SET audio_status=$2,audio_sid=$3 WHERE id=$1', n['id'], state, result.get('sid'))


async def fallback_email(n):
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'recipient:' + str(n['recipient_id']))
        reply = await reply_details(conn, n['reply_id'])
        recipient = await recipient_for(conn, n, reply['user_id']) if reply else None
        if not recipient or reply['parent_deleted_at']:
            return
        result = await send_update_email(dict(recipient), reply, n['id'])
        await conn.execute("UPDATE reply_notifications SET email_status=$2,email_id=$3,email_attempts=email_attempts+1,email_next_attempt_at=now()+interval '15 minutes' WHERE id=$1", n['id'], result['status'], result.get('id'))


async def drain_notifications():
    pool = get_pool()
    await pool.execute("UPDATE reply_notifications SET status='uncertain',detail='Interrupted submission.',updated_at=now() WHERE status='sending' AND updated_at<now()-interval '5 minutes'")
    await pool.execute("UPDATE reply_notifications SET audio_status='uncertain' WHERE audio_status='sending' AND audio_next_attempt_at<now()-interval '5 minutes'")
    for n in await pool.fetch("SELECT id FROM reply_notifications WHERE status IN ('pending','retry','awaiting_template','disabled') AND next_attempt_at<=now() AND attempts<4 ORDER BY created_at LIMIT 30"):
        await deliver(n['id'])
    for n in await pool.fetch("SELECT * FROM reply_notifications WHERE audio_status IN ('pending','retry') AND audio_attempts<4 AND audio_next_attempt_at<=now() ORDER BY created_at LIMIT 20"):
        await deliver_audio(n)
    for n in await pool.fetch("SELECT * FROM reply_notifications WHERE status IN ('failed','retry','blocked_policy','awaiting_template','uncertain','disabled') AND (status<>'uncertain' OR updated_at<now()-interval '5 minutes') AND coalesce(email_status,'')<>'sent' AND email_attempts<4 AND email_next_attempt_at<=now() AND created_at>now()-interval '24 hours' ORDER BY created_at LIMIT 20"):
        await fallback_email(n)
    await drain_requests()


async def record_recipient_inbound(phone, timestamp, context_id=None, requested=False, wam_id=None):
    phone = validate_phone(phone)
    stamp = min(timestamp, datetime.now(timezone.utc))
    await get_pool().execute('INSERT INTO recipient_sessions(phone,last_inbound_at) VALUES($1,$2) ON CONFLICT(phone) DO UPDATE SET last_inbound_at=greatest(recipient_sessions.last_inbound_at,excluded.last_inbound_at)', phone, stamp)
    from services.welcomes import inbound_recovery
    await inbound_recovery(phone, stamp)
    if not context_id or not requested or not wam_id or stamp < datetime.now(timezone.utc)-timedelta(hours=24):
        return
    async with get_pool().acquire() as conn:
        n = await conn.fetchrow('SELECT n.* FROM reply_notifications n LEFT JOIN notification_attempts a ON a.notification_id=n.id WHERE (a.sid=$1 AND a.phone=$2) OR (n.sid=$1 AND n.to_phone=$2) LIMIT 1', context_id, phone)
        if n:
            await conn.execute('INSERT INTO child_content_requests(wam_id,notification_id,phone) VALUES($1,$2,$3) ON CONFLICT DO NOTHING', wam_id, n['id'], phone)


async def drain_requests():
    pool = get_pool()
    await pool.execute("UPDATE child_content_requests SET status='uncertain' WHERE status='sending' AND next_attempt_at<now()-interval '5 minutes'")
    for row in await pool.fetch("SELECT wam_id FROM child_content_requests WHERE status IN ('pending','retry') AND attempts<3 AND next_attempt_at<=now() ORDER BY created_at LIMIT 20"):
        request = await pool.fetchrow("UPDATE child_content_requests SET status='sending',attempts=attempts+1,next_attempt_at=now()+interval '5 minutes' WHERE wam_id=$1 AND status IN ('pending','retry') RETURNING *", row['wam_id'])
        if not request:
            continue
        n = await pool.fetchrow('SELECT * FROM reply_notifications WHERE id=$1', request['notification_id'])
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'recipient:' + str(n['recipient_id']))
            reply = await reply_details(conn, n['reply_id'])
            recipient = await recipient_for(conn, n, reply['user_id']) if reply else None
            if not recipient or reply['parent_deleted_at'] or validate_phone(recipient['phone']) != request['phone'] or not await window_open(conn, request['phone'], dict(recipient).get('phone_changed_at')):
                await conn.execute("UPDATE child_content_requests SET status='cancelled' WHERE wam_id=$1", request['wam_id'])
                continue
            result = await send_audio(request['phone'], reply) if reply['is_voice'] else await post_meta({'messaging_product': 'whatsapp', 'to': request['phone'], 'type': 'text', 'text': {'body': (reply['body'] or reply.get('transcription') or 'No text in this reply.')[:4096]}})
            state = 'retry' if result.get('error_code') in RETRYABLE_CODES and request['attempts'] < 3 else result['status']
            await conn.execute('UPDATE child_content_requests SET status=$2,sid=$3 WHERE wam_id=$1', request['wam_id'], state, result.get('sid'))
            if reply['is_voice']:
                await conn.execute('UPDATE reply_notifications SET audio_status=$2,audio_sid=$3 WHERE id=$1', n['id'], state, result.get('sid'))


async def persist_receipt(status):
    sid, state = status.get('id'), status.get('status')
    if not sid or state not in ('sent', 'delivered', 'read', 'failed'):
        return
    error = (status.get('errors') or [{}])[0]
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute('UPDATE notification_attempts SET status=$2 WHERE sid=$1 AND status NOT IN (\'delivered\',\'read\')', sid, state)
        n = await conn.fetchrow('SELECT * FROM reply_notifications WHERE sid=$1 FOR UPDATE', sid)
        if n:
            new = outcome({'status': state, 'error_code': error.get('code')}, n['attempts'])
            ranks = {'accepted': 1, 'delivered': 2, 'read': 3}
            if n['status'] not in ('delivered', 'read') or ranks.get(new, 0) > ranks.get(n['status'], 0):
                await conn.execute("UPDATE reply_notifications SET status=$2,error_code=$3,detail=$4,next_attempt_at=now()+interval '5 minutes',updated_at=now() WHERE id=$1", n['id'], new, error.get('code'), error.get('title'))
                if error.get('code') == 131047:
                    await conn.execute('DELETE FROM recipient_sessions WHERE phone=$1 AND last_inbound_at<=$2', n['to_phone'], n['updated_at'])
        audio_state = 'retry' if state == 'failed' and error.get('code') in RETRYABLE_CODES else 'awaiting_request' if state == 'failed' and error.get('code') == 131047 else 'accepted' if state == 'sent' else state
        await conn.execute("UPDATE reply_notifications SET audio_status=$2 WHERE audio_sid=$1 AND audio_status NOT IN ('delivered','read')", sid, audio_state)
        await conn.execute("UPDATE child_content_requests SET status=$2 WHERE sid=$1 AND status NOT IN ('delivered','read')", sid, state)