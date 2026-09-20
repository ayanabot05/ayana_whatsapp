"""Durable welcomes. A unique row is atomically claimed before submission."""
import json
from datetime import datetime, timezone, timedelta
from database import get_pool
from whatsapp import _send_content_template_with_retry, whatsapp_enabled
from services.notification_transport import post_meta

RETRYABLE = {130429, 131000, 131016, 131056}


def _safe_lang(value):
    return value if value in ('en', 'te', 'hi') else 'en'


async def enqueue(conn, key, phone, payload, recipient_id=None, kind=None, version=0):
    await conn.execute('''INSERT INTO welcome_deliveries(event_key,phone,payload,recipient_id,recipient_kind,contact_version)
        VALUES($1,$2,$3::jsonb,$4,$5,$6) ON CONFLICT(event_key) DO NOTHING''',
        key, phone, json.dumps(payload), recipient_id, kind, version)


async def queue_child(owner, conn=None):
    if not owner.get('email_verified_at'):
        return
    conn = conn or get_pool()
    await enqueue(conn, f"child:{owner['id']}:email-verified", owner['phone'],
                  {'name': owner['name'].split()[0], 'language': _safe_lang(owner.get('language')), 'purpose': 'child'},
                  owner['id'], 'user', owner.get('contact_version', 0))


async def send_once(key, phone, name, checking_for, language):
    await enqueue(get_pool(), key, phone, {'name': name, 'checking_for': checking_for, 'language': _safe_lang(language), 'purpose': 'parent'})
    return await deliver(key)


async def deliver(key):
    if not whatsapp_enabled():
        return {'status': 'disabled'}
    job = await get_pool().fetchrow('''UPDATE welcome_deliveries SET status='sending',attempts=attempts+1,updated_at=now()
        WHERE event_key=$1 AND status IN ('pending','retry','disabled','awaiting_consent') AND next_attempt_at<=now() AND attempts<4 RETURNING *''', key)
    if not job:
        existing = await get_pool().fetchrow('SELECT * FROM welcome_deliveries WHERE event_key=$1', key)
        return dict(existing) if existing else {'status': 'missing'}
    try:
        payload = json.loads(job['payload']) if isinstance(job['payload'], str) else job['payload']
        if not payload:
            await get_pool().execute("UPDATE welcome_deliveries SET status='needs_review',detail='Legacy welcome has no recoverable payload.' WHERE event_key=$1", key)
            return {'status': 'needs_review'}
        async with get_pool().acquire() as conn, conn.transaction():
            phone = job['phone']
            if job['recipient_id']:
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'recipient:' + str(job['recipient_id']))
                table = {'user': 'users', 'sibling': 'care_circle_siblings', 'parent': 'parents'}[job['recipient_kind']]
                recipient = await conn.fetchrow(f'SELECT * FROM {table} WHERE id=$1', job['recipient_id'])
                if not recipient or dict(recipient).get('deleted_at') or dict(recipient).get('opted_out_at'):
                    await conn.execute("UPDATE welcome_deliveries SET status='cancelled' WHERE event_key=$1", key)
                    return {'status': 'cancelled'}
                phone = recipient['phone']
                if payload['purpose'] == 'child':
                    consent = await conn.fetchval("SELECT agreed FROM consent_logs WHERE user_id=$1 AND consent_type='child' ORDER BY created_at DESC LIMIT 1", recipient['id'])
                    if not recipient['email_verified_at'] or not consent:
                        await conn.execute("UPDATE welcome_deliveries SET status='awaiting_consent',attempts=greatest(attempts-1,0),next_attempt_at=now()+interval '5 minutes' WHERE event_key=$1", key)
                        return {'status': 'awaiting_consent'}
            language = _safe_lang(payload['language'])
            from services.notifications import window_open
            opened = await window_open(conn, phone, dict(recipient).get('phone_changed_at')) if job['recipient_id'] else False
            if payload['purpose'] == 'child':
                if opened:
                    body = f"Hi {payload['name']}! Your verified AYANA account is ready. Your selected WhatsApp number will receive your family's care updates."
                    result = await post_meta({'messaging_product': 'whatsapp', 'to': phone, 'type': 'text', 'text': {'body': body}})
                else:
                    result = await _send_content_template_with_retry(phone, f'ayana_child_welcome_{language}', language, {'1': payload['name']}, 'child_welcome')
            elif payload['purpose'] == 'sibling' and opened:
                body = f"Hi {payload['name']}! You are connected to {payload['checking_for']}'s AYANA care updates."
                result = await post_meta({'messaging_product': 'whatsapp', 'to': phone, 'type': 'text', 'text': {'body': body}})
            else:
                result = await _send_content_template_with_retry(phone, f'ayana_opener_{language}', language, {'1': payload['name'], '2': payload['checking_for']}, 'opener')
            state = 'accepted' if result.get('status') == 'sent' else result.get('status', 'failed')
            if state == 'failed' and (not result.get('error_code') or result['error_code'] in RETRYABLE) and job['attempts'] < 4:
                state = 'retry'
            elif result.get('error_code') in (131049, 131047):
                state = 'awaiting_inbound'
            await conn.execute('UPDATE welcome_deliveries SET phone=$2,status=$3,sid=$4,detail=$5,next_attempt_at=now()+interval \'15 minutes\',updated_at=now() WHERE event_key=$1', key, phone, state, result.get('sid'), result.get('detail'))
            return {'status': state, 'detail': result.get('detail')}
    except Exception:
        await get_pool().execute("UPDATE welcome_deliveries SET status='uncertain',detail='Submission interrupted; reconcile before retrying.',updated_at=now() WHERE event_key=$1", key)
        return {'status': 'uncertain'}


async def drain():
    await get_pool().execute("UPDATE welcome_deliveries SET status='uncertain',detail='Interrupted welcome submission.',updated_at=now() WHERE status='sending' AND updated_at<now()-interval '5 minutes'")
    rows = await get_pool().fetch("SELECT event_key FROM welcome_deliveries WHERE status IN ('pending','retry','disabled','awaiting_consent') AND next_attempt_at<=now() AND attempts<4 ORDER BY created_at LIMIT 20")
    for row in rows:
        await deliver(row['event_key'])


async def inbound_recovery(phone, stamp):
    if stamp < datetime.now(timezone.utc)-timedelta(hours=24):
        return
    # A genuine inbound permits free-form welcome recovery, not Marketing bypass.
    await get_pool().execute("UPDATE welcome_deliveries SET status='retry',attempts=0,next_attempt_at=now() WHERE phone=$1 AND recipient_kind IN ('user','sibling') AND status IN ('awaiting_inbound','failed','disabled')", phone)
    await get_pool().execute("UPDATE users SET needs_inbound_click=false WHERE phone=$1", phone)


async def welcome_parent_and_child(parent, owner, require_activation=False):
    if require_activation and not await get_pool().fetchval('SELECT whatsapp_activated FROM activation_state WHERE user_id=$1', parent['user_id']):
        return
    if parent.get('opted_out_at') or parent.get('deleted_at'):
        return
    await enqueue(get_pool(), f"parent:{parent['id']}", parent['phone'], {'name': parent.get('preferred_name') or parent['name'], 'checking_for': owner['name'].split()[0], 'language': _safe_lang(parent.get('language')), 'purpose': 'parent'}, parent['id'], 'parent')
    await queue_child(owner)
    await drain()