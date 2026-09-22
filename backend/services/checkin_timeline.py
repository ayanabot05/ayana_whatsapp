"""Parent-local date retrieval with exact reply contexts, including late replies."""
from datetime import date, datetime, time, timedelta, timezone
from fastapi import HTTPException
from database import get_pool
from services.reply_linking import build_parent_days, parent_zone


async def timeline(owner, days=7, selected_date=None, parent_id=None, page=1, page_size=None):
    try:
        chosen = date.fromisoformat(selected_date) if selected_date else None
    except ValueError:
        raise HTTPException(422, 'Choose a valid date (YYYY-MM-DD).')
    pool = get_pool()
    parents = await pool.fetch('SELECT * FROM parents WHERE user_id=$1 AND deleted_at IS NULL ORDER BY created_at', owner)
    if parent_id:
        parents = [p for p in parents if str(p['id']) == str(parent_id)]
        if not parents:
            raise HTTPException(404, 'Parent not found.')
    result = []
    for raw in parents:
        parent = dict(raw)
        zone = parent_zone(parent.get('timezone'))
        end_day = (chosen or datetime.now(zone).date()) + timedelta(days=1)
        start_day = chosen or end_day - timedelta(days=days)
        start = datetime.combine(start_day, time.min, zone).astimezone(timezone.utc)
        end = datetime.combine(end_day, time.min, zone).astimezone(timezone.utc)
        async with pool.acquire() as conn:
            logs = [dict(r) for r in await conn.fetch('''SELECT l.* FROM message_logs l WHERE parent_id=$1
                AND (created_at >= $2 AND created_at < $3 OR sid IN
                    (SELECT context_id FROM parent_replies WHERE parent_id=$1 AND created_at >= $2 AND created_at < $3)
                    OR id IN (SELECT message_log_id FROM parent_replies WHERE parent_id=$1 AND association_source='explicit' AND created_at >= $2 AND created_at < $3))
                ORDER BY created_at''', parent['id'], start, end)]
            replies = [dict(r) for r in await conn.fetch('''SELECT * FROM parent_replies WHERE parent_id=$1
                AND (created_at >= $2 AND created_at < $3 OR context_id=ANY($4::text[])
                     OR (association_source='explicit' AND message_log_id=ANY($5::uuid[]))) ORDER BY created_at''',
                parent['id'], start, end, [l['sid'] for l in logs if l.get('sid')], [l['id'] for l in logs])]
            if replies:
                outcomes = await conn.fetch('''SELECT reply_id,recipient_kind,recipient_id,status,email_status,audio_status,detail
                    FROM reply_notifications WHERE reply_id=ANY($1::uuid[]) ORDER BY created_at''', [r['id'] for r in replies])
                for r in replies:
                    r['notifications'] = [{k: str(v) if k in ('recipient_id', 'reply_id') else v for k, v in dict(n).items()} for n in outcomes if n['reply_id'] == r['id']]
        parent_days = build_parent_days(parent, logs, replies)
        parent_days = [d for d in parent_days if start_day.isoformat() <= d['day_key'] < end_day.isoformat()]
        total_days = len(parent_days)
        if page_size:
            # Newest day first, then slice. Only applied when the caller asks for
            # pagination, so the default response shape/order is unchanged.
            paged = sorted(parent_days, key=lambda d: d['day_key'], reverse=True)
            parent_days = paged[(page - 1) * page_size: page * page_size]
        entry = {'parent_id': str(parent['id']), 'name': parent.get('preferred_name') or parent['name'],
                 'relationship': parent['relationship'], 'timezone': str(zone), 'days': parent_days}
        if page_size:
            entry.update({'page': page, 'page_size': page_size, 'total_days': total_days,
                          'has_more': page * page_size < total_days})
        result.append(entry)
    events = await pool.fetch("SELECT id,parent_id,body,created_at FROM emergency_events WHERE user_id=$1 AND status='open' ORDER BY created_at DESC LIMIT 20", owner)
    return {'parents': result, 'alerts': [{'kind': 'emergency', 'event_id': str(e['id']), 'parent_id': str(e['parent_id']), 'body': e['body'], 'created_at': e['created_at'].isoformat()} for e in events]}