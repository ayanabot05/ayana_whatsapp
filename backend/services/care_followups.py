"""One unanswered follow-up, only for a delivered medication or safety slot."""
from datetime import datetime, timedelta, timezone
from database import get_pool
from services.schedule_source import eligible, local_now, load_schedule, event_key
from whatsapp import send_dynamic_checkin, whatsapp_enabled


async def drain():
    if not whatsapp_enabled():
        return
    now = datetime.now(timezone.utc)
    pool = get_pool()
    for row in await pool.fetch('SELECT * FROM parents WHERE deleted_at IS NULL'):
        parent = dict(row)
        async with pool.acquire() as conn, conn.transaction():
            if not await conn.fetchval('SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))', 'care-parent:' + str(parent['id'])):
                continue
            if not await conn.fetchval('SELECT whatsapp_activated FROM activation_state WHERE user_id=$1', parent['user_id']):
                continue
            from services.billing_access import access
            if not (await access(conn, parent['user_id']))['allowed']:
                continue
            local = local_now(parent, now)
            day = local.date().isoformat()
            schedule, items = await load_schedule(conn, parent, now)
            if not eligible(parent, local, schedule):
                continue
            last = await conn.fetchval('SELECT max(created_at) FROM message_logs WHERE parent_id=$1', parent['id'])
            if last and now - last < timedelta(seconds=120):
                continue
            if await conn.fetchval('SELECT count(*) FROM message_logs WHERE parent_id=$1 AND day_key=$2', parent['id'], day) >= 15:
                continue
            for item in items:
                if item['category'] != 'medicine' and item['type'] != 'safety':
                    continue
                original_key = event_key(parent['id'], day, item)
                original = await conn.fetchrow("""SELECT l.* FROM message_logs l
                    WHERE l.event_key=$1 AND l.delivery_status IN ('delivered','read')
                    AND coalesce(l.delivered_at,l.created_at)<=$2
                    AND NOT EXISTS(SELECT 1 FROM parent_replies r WHERE r.parent_id=l.parent_id
                        AND (r.context_id=l.sid OR (r.association_source='explicit' AND r.message_log_id=l.id)))
                    ORDER BY l.created_at DESC LIMIT 1""", original_key, now - timedelta(hours=1))
                if not original:
                    continue
                key = original_key + ':followup'
                # This committed unique claim survives a timeout or worker restart.
                if not await pool.fetchval('INSERT INTO care_send_claims(event_key,parent_id) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING event_key', key, parent['id']):
                    continue
                try:
                    result = await send_dynamic_checkin(parent, item['category'], local.timetuple().tm_yday, 3, medicine_name=item.get('medicine_name', ''), location_label=item.get('location_label') or '')
                except Exception:
                    result = {'status':'uncertain','detail':'Follow-up submission interrupted; inspect receipts.'}
                state = result.get('status', 'failed')
                await conn.execute('''INSERT INTO message_logs(user_id,parent_id,day_key,category,body,msg_type,status,detail,sid,slot_time,event_key)
                    VALUES($1,$2,$3,$4,$5,'followup',$6,$7,$8,$9,$10)''', parent['user_id'], parent['id'], day, item['category'], result.get('body') or original['body'], state, result.get('detail'), result.get('sid'), item['time'], key)
                await conn.execute('UPDATE care_send_claims SET status=$2,sid=$3,detail=$4,attempts=1 WHERE event_key=$1', key, state, result.get('sid'), result.get('detail'))
                break
