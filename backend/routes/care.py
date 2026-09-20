"""Read-only care readiness, using exactly the scheduler's schedule source."""
from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from auth import get_current_user
from database import get_pool
from services.schedule_source import eligible, load_schedule, local_now

router = APIRouter(prefix='/api/parents',tags=['Care readiness'])


@router.get('/{parent_id}/care-status')
async def care_status(parent_id: UUID,user=Depends(get_current_user)):
    owner = user.get('household_owner_id') or user['id']
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow('SELECT * FROM parents WHERE id=$1 AND user_id=$2 AND deleted_at IS NULL',parent_id,owner)
        if not row:
            raise HTTPException(404,'Parent not found.')
        parent = dict(row)
        schedule, items = await load_schedule(conn,parent,day_filter=False)
        activation = await conn.fetchrow('SELECT * FROM activation_state WHERE user_id=$1',owner)
        welcome = await conn.fetchrow('SELECT status,detail FROM welcome_deliveries WHERE event_key=$1',f'parent:{parent_id}')
        last = await conn.fetchrow('SELECT created_at,delivery_status,category FROM message_logs WHERE parent_id=$1 ORDER BY created_at DESC LIMIT 1',parent_id)
        child_welcome = await conn.fetchrow('SELECT status,detail FROM welcome_deliveries WHERE recipient_id=$1 ORDER BY created_at DESC LIMIT 1',user['id'])
        from services.billing_access import access
        entitlement = await access(conn,owner)
    result = {'timezone':parent['timezone'],'next_at':None,'next_label':None,'welcome':dict(welcome) if welcome else None,'child_welcome':dict(child_welcome) if child_welcome else None,'last_delivery':last['delivery_status'] if last else None}
    if parent.get('opted_out_at'):
        return {**result,'state':'opted_out','message':'Your parent requested STOP. Scheduled care is paused.'}
    if schedule and (not schedule.get('active') or schedule.get('deleted_at')):
        return {**result,'state':'paused','message':'This schedule is paused.'}
    if not activation or not activation['whatsapp_activated']:
        return {**result,'state':'not_activated','message':'Schedule saved. Activate care to begin future check-ins.'}
    if not entitlement['allowed']:
        return {**result,'state':'access_expired','message':'Care access has ended. Review your plan before scheduling resumes.'}
    if not items:
        return {**result,'state':'no_schedule','message':'No reminders are saved for this parent.'}
    try:
        now = local_now(parent)
    except (ValueError, KeyError):
        return {**result,'state':'invalid_timezone','message':'Update this parent’s timezone before care can run.'}
    # This is the next configured slot, not a promise of provider delivery.
    for offset in range(367):
        day = now+timedelta(days=offset)
        for item in items:
            if day.weekday() not in item.get('weekdays', list(range(7))):
                continue
            hour,minute = map(int,item['time'].split(':'))
            candidate = day.replace(hour=hour,minute=minute,second=0,microsecond=0)
            if candidate > max(now,parent['created_at'],activation['activated_at'] or datetime.min.replace(tzinfo=timezone.utc)) and eligible(parent,candidate,schedule):
                return {**result,'state':'scheduled','next_at':candidate.isoformat(),'next_label':candidate.strftime('%d %b, %I:%M %p %Z'),'message':'Next configured check-in'}
    return {**result,'state':'held','message':'No upcoming slot fits the current quiet hours or vacation dates.'}