"""Acknowledge webhooks only after durable storage; retry processing, not delivery."""
import hashlib
import json
import logging
from database import get_pool

logger = logging.getLogger(__name__)
_processor = None
_warned_unconfigured = False


def configure(processor):
    global _processor
    _processor = processor


async def enqueue(payload):
    encoded = json.dumps(payload,sort_keys=True,separators=(',',':'))
    key = hashlib.sha256(encoded.encode()).hexdigest()
    await get_pool().execute('INSERT INTO inbound_events(wam_id,payload) VALUES($1,$2::jsonb) ON CONFLICT DO NOTHING',key,encoded)
    # Proof that Meta's webhook actually reached this server and was stored.
    logger.info('[inbox] stored inbound event %s', key[:12])


async def drain():
    global _warned_unconfigured
    if _processor is None:
        # Previously silent: events would pile up as 'pending' forever.
        if not _warned_unconfigured:
            logger.warning('[inbox] no processor configured; inbound events (including child replies) are NOT being processed. Call inbox.configure(...) at startup.')
            _warned_unconfigured = True
        return
    await get_pool().execute("UPDATE inbound_events SET status='pending' WHERE status='processing' AND next_attempt_at<now()-interval '5 minutes' AND attempts<5")
    await get_pool().execute("UPDATE inbound_events SET status='failed',detail='Processing exhausted after interrupted attempts.' WHERE status='processing' AND next_attempt_at<now()-interval '5 minutes' AND attempts>=5")
    for _ in range(20):
        event = await get_pool().fetchrow("UPDATE inbound_events SET status='processing',attempts=attempts+1,next_attempt_at=now()+interval '1 minute' WHERE wam_id=(SELECT wam_id FROM inbound_events WHERE status='pending' AND next_attempt_at<=now() AND attempts<5 ORDER BY received_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *")
        if not event:
            break
        try:
            payload = json.loads(event['payload']) if isinstance(event['payload'],str) else event['payload']
            await _processor(payload)
            await get_pool().execute("UPDATE inbound_events SET status='processed',detail=NULL WHERE wam_id=$1",event['wam_id'])
        except Exception as exc:
            logger.exception('Inbound processing failed for %s',event['wam_id'])
            await get_pool().execute("UPDATE inbound_events SET status=$2,detail=$3 WHERE wam_id=$1",event['wam_id'],'failed' if event['attempts']>=5 else 'pending',type(exc).__name__)