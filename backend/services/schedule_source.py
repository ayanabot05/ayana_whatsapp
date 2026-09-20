"""Compatibility boundary: the dashboard's saved schedule wins when present.

Never merge two parallel configurations: doing so resurrects deleted reminders.
Granular-only households remain supported without any destructive backfill.
"""
import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from templates_data import category_type


def as_list(value):
    return json.loads(value) if isinstance(value,str) else (value or [])


def eligible(parent, local, schedule=None, check_hours=True):
    if parent.get('deleted_at') or parent.get('opted_out_at'):
        return False
    if schedule and (not schedule.get('active') or schedule.get('deleted_at')):
        return False
    today, clock = local.strftime('%Y-%m-%d'), local.strftime('%H:%M')
    if parent.get('vacation_start') and parent.get('vacation_end') and parent['vacation_start'] <= today <= parent['vacation_end']:
        return False
    start, end = parent.get('activity_window_start'), parent.get('activity_window_end')
    if check_hours and start and end:
        return start <= clock <= end if start <= end else clock >= start or clock <= end
    return True


def local_now(parent, now=None):
    # Invalid stored timezones should be visible, not silently send at a wrong time.
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(parent['timezone']))


def event_key(parent_id, day, item):
    identity = f"{item['category']}|{item['time']}|{item.get('medicine_id') or item.get('medicine_name','')}"
    return f"{parent_id}:{day}:{hashlib.sha256(identity.encode()).hexdigest()[:24]}"


async def load_schedule(conn,parent, now=None, day_filter=True):
    legacy = await conn.fetchrow('SELECT * FROM schedules WHERE parent_id=$1 ORDER BY created_at DESC LIMIT 1', parent['id'])
    items = []
    if legacy is not None:
        legacy = dict(legacy)
        if legacy.get('deleted_at') or not legacy['active']:
            return legacy, []
        local = local_now(parent, now)
        if legacy.get('recovery_mode') and legacy.get('recovery_until') and str(legacy['recovery_until'])[:10] < local.date().isoformat():
            legacy['recovery_mode'] = False
            remaining = [m for m in as_list(legacy['messages']) if not m.get('is_recovery')]
            await conn.execute('UPDATE schedules SET recovery_mode=false,recovery_until=NULL,messages=$2::jsonb WHERE id=$1', legacy['id'], json.dumps(remaining))
            legacy['messages'] = remaining
        for item in as_list(legacy['messages']):
            if not item.get('active', True) or (day_filter and local.weekday() not in item.get('weekdays', list(range(7)))):
                continue
            if item.get('is_recovery') and not legacy.get('recovery_mode'):
                continue
            item = {**item,'type':category_type(item['category'])}
            if item['category']=='medicine':
                from medicine_sync import medicine_identity
                from services.medicine_content import medicine_description
                medicines = [m for m in as_list(parent.get('medicine_list')) if (medicine_identity(m) == item['medicine_id'] if item.get('medicine_id') else item['time'] in (m.get('reminder_times') or [m.get('reminder_time')]))]
                if medicines:
                    for med in medicines:
                        items.append({**item, 'medicine_id': medicine_identity(med), 'medicine_name': medicine_description(med, parent.get('language', 'en'))})
                elif item.get('source') != 'medicine_sync':
                    items.append({**item, 'medicine_name': item.get('custom_text') or 'your prescribed medicine'})
            else:
                items.append(item)
    else:
        for table in ('parent_checkins','parent_health_reminders','parent_routines'):
            rows = await conn.fetch(f'SELECT category,time FROM {table} WHERE parent_id=$1 AND is_active',parent['id'])
            items.extend({'category':r['category'],'time':str(r['time'])[:5],'type':category_type(r['category'])} for r in rows)
        for med in await conn.fetch('SELECT * FROM medicines WHERE parent_id=$1 AND is_active',parent['id']):
            from services.medicine_content import medicine_description
            items.extend({'category':'medicine','time':t,'type':'reminder','medicine_id':str(med['id']),'medicine_name':medicine_description(dict(med),parent.get('language','en'))} for t in as_list(med['reminder_times']))
    unique = {(event_key(parent['id'],'',item), tuple(item.get('weekdays', range(7)))):item for item in items}
    return legacy, sorted(unique.values(),key=lambda item:(item['time'],item['category']))