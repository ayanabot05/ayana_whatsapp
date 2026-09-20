"""Receipts may precede send commit; keep unmatched receipts for reconciliation."""
import hashlib
import json
from database import get_pool
from services import notifications


async def ingest(status):
    encoded = json.dumps(status, sort_keys=True)
    key = hashlib.sha256(encoded.encode()).hexdigest()
    await get_pool().execute('INSERT INTO provider_receipts(event_key,payload) VALUES($1,$2::jsonb) ON CONFLICT DO NOTHING', key, encoded)
    await apply(key, status)


async def apply(key, status):
    sid, state = status.get('id'), status.get('status')
    if not sid or state not in ('sent','delivered','read','failed'):
        return
    async with get_pool().acquire() as conn:
        known = await conn.fetchval('''SELECT EXISTS(SELECT 1 FROM message_logs WHERE sid=$1)
            OR EXISTS(SELECT 1 FROM notification_attempts WHERE sid=$1)
            OR EXISTS(SELECT 1 FROM reply_notifications WHERE sid=$1 OR audio_sid=$1)
            OR EXISTS(SELECT 1 FROM child_content_requests WHERE sid=$1)
            OR EXISTS(SELECT 1 FROM welcome_deliveries WHERE sid=$1)
            OR EXISTS(SELECT 1 FROM care_send_claims WHERE sid=$1)
            OR EXISTS(SELECT 1 FROM moments WHERE sid=$1)''', sid)
        if not known:
            return
    await notifications.persist_receipt(status)
    error = (status.get('errors') or [{}])[0]
    code = error.get('code')
    async with get_pool().acquire() as conn, conn.transaction():
        if state in ('delivered', 'read'):
            await conn.execute("UPDATE message_logs SET status='sent',delivery_status=$2,delivered_at=coalesce(delivered_at,now()),read_at=CASE WHEN $2='read' THEN coalesce(read_at,now()) ELSE read_at END WHERE sid=$1 AND delivery_status IS DISTINCT FROM 'read'", sid, state)
            await conn.execute("UPDATE care_send_claims SET status=$2 WHERE sid=$1 AND status IS DISTINCT FROM 'read'", sid, state)
        elif state == 'sent':
            await conn.execute("UPDATE message_logs SET delivery_status=coalesce(delivery_status,'sent') WHERE sid=$1", sid)
        else:
            await conn.execute("UPDATE message_logs SET status='failed',delivery_status='failed',detail=$2 WHERE sid=$1 AND coalesce(delivery_status,'') NOT IN ('delivered','read')", sid, error.get('title') or 'Delivery rejected')
            retry_state = 'failed' if code in notifications.RETRYABLE_CODES | {131047} else 'blocked'
            claims = await conn.fetch("UPDATE care_send_claims SET status=$2,detail=$3 WHERE sid=$1 AND status NOT IN ('delivered','read') RETURNING event_key,parent_id", sid, retry_state, error.get('title'))
            if code == 131047:
                await conn.execute("UPDATE wa_sessions w SET session_open=false WHERE EXISTS (SELECT 1 FROM message_logs l WHERE l.sid=$1 AND l.parent_id=w.parent_id AND w.last_inbound_at<=l.created_at)", sid)
            for claim in claims:
                parts = claim['event_key'].split(':')
                if len(parts) >= 5 and parts[0] == 'warning' and parts[1] in ('main', 'first'):
                    await conn.execute(f'UPDATE care_watch SET {parts[1]}_warn_sent=false WHERE parent_id=$1 AND day_key=$2', claim['parent_id'], parts[3])
        welcome_state = 'retry' if state == 'failed' and code in notifications.RETRYABLE_CODES else 'awaiting_inbound' if state == 'failed' and code in (131047,131049) else 'accepted' if state == 'sent' else state
        await conn.execute("UPDATE welcome_deliveries SET status=$2,detail=coalesce($3,detail),next_attempt_at=now()+interval '15 minutes',updated_at=now() WHERE sid=$1 AND status NOT IN ('delivered','read')", sid, welcome_state, error.get('title'))
        await conn.execute("UPDATE moments SET delivery_status=$2 WHERE sid=$1 AND coalesce(delivery_status,'') NOT IN ('delivered','read')", sid, state)
        await conn.execute('UPDATE provider_receipts SET processed_at=now() WHERE event_key=$1', key)


async def drain():
    for row in await get_pool().fetch("SELECT * FROM provider_receipts WHERE processed_at IS NULL AND received_at>now()-interval '7 days' ORDER BY received_at LIMIT 100"):
        await apply(row['event_key'], json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload'])