"""One stable medicine occurrence per send. Invalid capacity never drops care."""
import hashlib
from fastapi import HTTPException
from pricing import plan_limits

SYNC_SOURCE = 'medicine_sync'


def medicine_identity(medicine):
    return medicine.get('id') or hashlib.sha256((medicine['name'] + '|' + (medicine.get('dose') or '')).encode()).hexdigest()[:24]


def sync_medicine_reminders(medicine_list, existing_messages, plan_id, recovery_mode=False):
    manual = [m for m in existing_messages if m.get('source') != SYNC_SOURCE]
    synced = []
    for med in medicine_list:
        if med.get('is_recovery') and not recovery_mode:
            continue
        for clock in sorted(set(med.get('reminder_times') or ([med['reminder_time']] if med.get('reminder_time') else []))):
            # Old medicine-only slots at this time are replaced, not double-counted.
            manual = [m for m in manual if not (m.get('category') == 'medicine' and m.get('time') == clock and not m.get('custom_text'))]
            synced.append({'time': clock, 'category': 'medicine', 'type': 'reminder',
                           'medicine_id': medicine_identity(med), 'source': SYNC_SOURCE,
                           'weekdays': list(range(7))})
    limits = plan_limits(plan_id)
    maximum = limits['reminders'] + (limits.get('recovery_extra_reminders', 0) if recovery_mode and limits.get('recovery_mode') else 0)
    if len(synced) + sum(m.get('category') == 'medicine' for m in manual) > maximum:
        raise HTTPException(422, f'This schedule needs more than {maximum} medicine reminders per day. Nothing was saved or dropped.')
    return {'messages': manual + synced, 'synced_times': [m['time'] for m in synced], 'dropped': []}