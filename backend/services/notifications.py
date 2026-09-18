"""Durable per-recipient reply delivery and recipient-specific WhatsApp windows.

An HTTP acceptance is not delivery. Unknown acceptance is never blindly retried.
Contact changes and submission share a recipient lock; already submitted messages
cannot be recalled. Historical replies are not bulk replayed.
"""
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
    for kind, recipients in [('user',users),('sibling',siblings)]:
        for recipient in recipients:
            phone = validate_phone(recipient['phone'])
            if phone in seen:
                continue
            seen.add(phone)
            await conn.execute('INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING', reply['id'], kind, recipient['id'])


async def recipient_for(conn, notification, owner_id):
    if notification['recipient_kind'] == 'user':
        return await conn.fetchrow('SELECT * FROM users WHERE id=$1 AND (id=$2 OR household_owner_id=$2) AND deleted_at IS NULL', notification['recipient_id'], owner_id)
    return await conn.fetchrow('SELECT * FROM care_circle_siblings WHERE id=$1 AND owner_id=$2 AND verified', notification['recipient_id'], owner_id)


async def reply_details(conn, reply_id):
    row = await conn.fetchrow("SELECT r.*,coalesce(nullif(p.preferred_name,''),p.name) AS parent_name,p.timezone,p.deleted_at AS parent_deleted_at,l.category FROM parent_replies r JOIN parents p ON p.id=r.parent_id LEFT JOIN message_logs l ON l.id=r.message_log_id WHERE r.id=$1", reply_id)
    if not row:
        return None
    reply = dict(row)
    reply['prompt'] = (reply['category'] or 'care update').replace('_',' ')
    try:
        tz = ZoneInfo(reply['timezone'])
    except (ValueError, TypeError, KeyError):
        tz = timezone.utc
    reply['display_time'] = reply['created_at'].astimezone(tz).strftime('%d %b, %I:%M %p %Z')
    return reply


async def window_open(conn, phone, changed_at=None):
    inbound = await conn.fetchval('SELECT last_inbound_at FROM recipient_sessions WHERE phone=$1', phone)
    return bool(inbound and inbound > datetime.now(timezone.utc)-timedelta(hours=24) and (not changed_at or inbound >= changed_at))


async def send_audio(phone, reply):
    audio = None
    if reply.get('media_storage_path') and storage.is_enabled():
        url = await asyncio.to_thread(storage.signed_url, reply['media_storage_path'], 300)
        audio = {'link':url}
    elif reply.get('media_id'):
        audio = {'id':reply['media_id']}
    if not audio:
        return {'status':'unavailable', 'detail':'Audio not available; open the reply in your dashboard.'}
    return await post_meta({'messaging_product':'whatsapp','to':phone,'type':'audio','audio':audio})


async def deliver(notification_id):
    # Claim commits BEFORE any network call. Crash recovery will mark uncertain,
    # not re-submit a possibly accepted message.
    n = await get_pool().fetchrow("UPDATE reply_notifications SET status='sending',attempts=attempts+1,updated_at=now() WHERE id=$1 AND status IN ('pending','retry','awaiting_template','disabled') AND next_attempt_at<=now() RETURNING *", notification_id)
    if not n:
        return
    try:
        async with get_pool().acquire() as conn, conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'recipient:' + str(n['recipient_id']))
            reply = await reply_details(conn,n['reply_id'])
            recipient = await recipient_for(conn,n,reply['user_id']) if reply else None
            if not recipient or reply['parent_deleted_at']:
                await conn.execute("UPDATE reply_notifications SET status='cancelled',updated_at=now() WHERE id=$1", n['id'])
                return
            if reply['created_at'] < datetime.now(timezone.utc)-timedelta(hours=24):
                await conn.execute("UPDATE reply_notifications SET status='expired',detail='Historical notifications are not replayed automatically.',updated_at=now() WHERE id=$1", n['id'])
                return
            recipient = dict(recipient)
            phone = validate_phone(recipient['phone'])
            opened = await window_open(conn,phone,recipient.get('phone_changed_at'))
            result = await send_update(phone, reply, opened, recipient.get('language') or 'en')
            status = 'accepted' if result['status']=='sent' else result['status']
            if result.get('error_code') == 131047:
                status = 'awaiting_template'
                await conn.execute('DELETE FROM recipient_sessions WHERE phone=$1',phone)
            if result.get('error_code') in RETRYABLE_CODES and n['attempts'] < 3:
                status = 'retry'
            await conn.execute("UPDATE reply_notifications SET to_phone=$2,status=$3,sid=$4,detail=$5,error_code=$6,next_attempt_at=now()+interval '15 minutes',updated_at=now() WHERE id=$1", n['id'],phone,status,result.get('sid'),result.get('detail'),result.get('error_code'))
            if status not in ('accepted','delivered','read') and n['email_status'] != 'sent':
                email = await send_update_email(recipient,reply,n['id'])
                await conn.execute('UPDATE reply_notifications SET email_status=$2,email_id=$3 WHERE id=$1',n['id'],email['status'],email.get('id'))
            if opened and reply['is_voice'] and status == 'accepted':
                audio = await send_audio(phone,reply)
                await conn.execute('UPDATE reply_notifications SET audio_sid=$2,audio_status=$3 WHERE id=$1',n['id'],audio.get('sid'),audio['status'])
    except Exception as exc:
        logger.exception('Notification %s requires inspection (%s)',notification_id,type(exc).__name__)
        await get_pool().execute("UPDATE reply_notifications SET status='uncertain',detail='Submission interrupted; no automatic resend.',updated_at=now() WHERE id=$1",notification_id)


async def drain_notifications():
    await get_pool().execute("UPDATE reply_notifications SET status='uncertain',detail='Submission interrupted; inspect receipts.',updated_at=now() WHERE status='sending' AND updated_at<now()-interval '5 minutes'")
    rows = await get_pool().fetch("SELECT id FROM reply_notifications WHERE status IN ('pending','retry','awaiting_template','disabled') AND next_attempt_at<=now() ORDER BY created_at LIMIT 30")
    for row in rows:
        await deliver(row['id'])


async def record_recipient_inbound(phone, timestamp, context_id=None, requested=False, wam_id=None):
    phone = validate_phone(phone)
    stamp = min(timestamp, datetime.now(timezone.utc))
    await get_pool().execute('INSERT INTO recipient_sessions(phone,last_inbound_at) VALUES($1,$2) ON CONFLICT(phone) DO UPDATE SET last_inbound_at=greatest(recipient_sessions.last_inbound_at,excluded.last_inbound_at)',phone,stamp)
    if not context_id or not requested or stamp < datetime.now(timezone.utc)-timedelta(hours=24):
        return
    # Only the recipient of this exact notification may request its contents.
    async with get_pool().acquire() as conn, conn.transaction():
        n = await conn.fetchrow('SELECT * FROM reply_notifications WHERE sid=$1 AND to_phone=$2',context_id,phone)
        if not n:
            return
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','recipient:' + str(n['recipient_id']))
        reply = await reply_details(conn,n['reply_id'])
        recipient = await recipient_for(conn,n,reply['user_id'])
        if not recipient or validate_phone(recipient['phone']) != phone or reply['parent_deleted_at']:
            return
        if wam_id:
            claimed = await conn.fetchval('INSERT INTO care_send_claims(event_key,parent_id) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING event_key','child-button:'+wam_id,reply['parent_id'])
            if not claimed:
                return
        if reply['is_voice']:
            result = await send_audio(phone,reply)
            await conn.execute('UPDATE reply_notifications SET audio_sid=$2,audio_status=$3 WHERE id=$1',n['id'],result.get('sid'),result['status'])
        else:
            await send_update(phone,reply,True,dict(recipient).get('language') or 'en')
        if wam_id:
            await conn.execute("UPDATE care_send_claims SET status='handled' WHERE event_key=$1",'child-button:'+wam_id)


async def persist_receipt(status):
    sid, state = status.get('id'), status.get('status')
    if not sid or state not in ('sent','delivered','read','failed'):
        return
    errors = status.get('errors') or [{}]
    error = errors[0]
    state = 'accepted' if state == 'sent' else state
    async with get_pool().acquire() as conn, conn.transaction():
        n = await conn.fetchrow('SELECT * FROM reply_notifications WHERE sid=$1 FOR UPDATE',sid)
        if n:
            ranks = {'accepted':1,'delivered':2,'read':3}
            if ranks.get(n['status'],0) > ranks.get(state,0) and n['status'] in ('delivered','read'):
                return
            await conn.execute('UPDATE reply_notifications SET status=$2,error_code=$3,detail=$4,updated_at=now() WHERE id=$1',n['id'],state,error.get('code'),error.get('title'))
            if state == 'failed' and n['email_status'] != 'sent':
                reply = await reply_details(conn,n['reply_id'])
                recipient = await recipient_for(conn,n,reply['user_id'])
                if recipient:
                    email = await send_update_email(dict(recipient),reply,n['id'])
                    await conn.execute('UPDATE reply_notifications SET email_status=$2,email_id=$3 WHERE id=$1',n['id'],email['status'],email.get('id'))
        await conn.execute('UPDATE reply_notifications SET audio_status=$2 WHERE audio_sid=$1',sid,state)