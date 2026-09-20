"""Signed provider events, deduplicated and ordered by provider timestamps."""
import hashlib
import json
from datetime import datetime, timezone
from database import get_pool


def provider_time(value):
    try:
        return datetime.fromtimestamp(int(value), timezone.utc) if int(value) > 0 else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


async def ingest(event, event_id=None):
    raw = json.dumps(event, sort_keys=True)
    key = event_id or hashlib.sha256(raw.encode()).hexdigest()
    await get_pool().execute('INSERT INTO billing_events(event_id,event_type,payload) VALUES($1,$2,$3::jsonb) ON CONFLICT DO NOTHING', key, event.get('event', ''), raw)
    return await apply(key)


async def apply(key):
    async with get_pool().acquire() as conn, conn.transaction():
        row = await conn.fetchrow('SELECT * FROM billing_events WHERE event_id=$1 FOR UPDATE', key)
        if row['processed_at']:
            return {'ok': True, 'duplicate': True}
        event = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
        payload = event.get('payload', {})
        remote = payload.get('subscription', {}).get('entity', {})
        payment = payload.get('payment', {}).get('entity', {})
        sub_id = remote.get('id') or payment.get('subscription_id')
        sub = await conn.fetchrow('SELECT * FROM billing_subscriptions WHERE gateway_subscription_id=$1', sub_id)
        if not sub:
            await conn.execute("UPDATE billing_events SET detail='Waiting for local subscription record.' WHERE event_id=$1", key)
            return {'ok': True, 'queued': True}
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'billing:' + str(sub['user_id']))
        sub = await conn.fetchrow('SELECT * FROM billing_subscriptions WHERE id=$1 FOR UPDATE', sub['id'])
        occurred = provider_time(event.get('created_at'))
        if not occurred:
            await conn.execute("UPDATE billing_events SET detail='Missing provider event timestamp; needs reconciliation.' WHERE event_id=$1", key)
            return {'ok': True, 'needs_reconciliation': True}
        stale = sub['provider_event_at'] and occurred < sub['provider_event_at']
        kind = event.get('event', '')
        terminal = sub['status'] in ('cancelled', 'completed', 'expired')
        if stale or (terminal and kind in ('subscription.charged','subscription.authenticated','subscription.activated')):
            await conn.execute("UPDATE billing_events SET processed_at=now(),detail='Ignored stale or terminal-state transition.' WHERE event_id=$1", key)
            return {'ok': True, 'ignored': True}
        if kind == 'subscription.charged':
            start, end = provider_time(remote.get('current_start')), provider_time(remote.get('current_end'))
            if not start or not end or end <= start or payment.get('status') not in (None, 'captured'):
                await conn.execute("UPDATE billing_events SET detail='Missing paid provider period; no access extended.' WHERE event_id=$1", key)
                return {'ok': True, 'needs_reconciliation': True}
            await conn.execute("UPDATE billing_subscriptions SET status='active',current_period_start=$2,current_period_end=$3,provider_event_at=$4,updated_at=now() WHERE id=$1", sub['id'], start, end, occurred)
            await conn.execute("INSERT INTO payment_state(user_id,status,plan,billing,billing_managed) VALUES($1,'active',$2,$3,true) ON CONFLICT(user_id) DO UPDATE SET status='active',plan=excluded.plan,billing=excluded.billing,billing_managed=true,updated_at=now()", sub['user_id'], sub['plan'], sub['billing'])
        elif kind in ('subscription.halted','subscription.cancelled','subscription.completed','subscription.expired','subscription.authenticated'):
            state = kind.split('.')[1]
            if state != 'authenticated' or sub['status'] not in ('active', 'halted'):
                await conn.execute("UPDATE billing_subscriptions SET status=$2,provider_event_at=$3,cancelled_at=CASE WHEN $2='cancelled' THEN $3 ELSE cancelled_at END,updated_at=now() WHERE id=$1", sub['id'], state, occurred)
        await conn.execute('UPDATE billing_events SET processed_at=now(),detail=NULL WHERE event_id=$1', key)
        return {'ok': True}


async def drain():
    for row in await get_pool().fetch("SELECT event_id FROM billing_events WHERE processed_at IS NULL AND received_at>now()-interval '7 days' ORDER BY received_at LIMIT 30"):
        await apply(row['event_id'])