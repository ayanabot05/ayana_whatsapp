"""Atomic onboarding/dashboard save; preserves existing authorization checks."""
from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from auth import get_current_user, validate_csrf_token
from database import atomic_care_save
from models import ParentInput, ScheduleInput
from routes.parents import create_parent, update_parent
from routes.schedules import create_schedule, update_schedule
from services.deps import scope
import json

router = APIRouter(prefix='/api')


class CarePlanInput(BaseModel):
    parent: ParentInput
    schedule: ScheduleInput


async def save(payload, background_tasks, user, parent_id=None):
    async with atomic_care_save() as conn:
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'care-save:' + str(scope(user)))
        if parent_id:
            # Stage the new manual slots before medicine sync, inside the SAME
            # transaction: old slots must not reject an otherwise valid edit.
            await conn.execute('UPDATE schedules SET messages=$3::jsonb WHERE parent_id=$1::uuid AND user_id=$2 AND deleted_at IS NULL', parent_id, scope(user), json.dumps([m.model_dump() for m in payload.schedule.messages]))
        parent = await update_parent(parent_id, payload.parent, user) if parent_id else await create_parent(payload.parent, background_tasks, user)
        pid = parent['id']
        schedule = payload.schedule.model_copy(update={'parent_id': pid})
        previous = await conn.fetchrow('SELECT id FROM schedules WHERE parent_id=$1::uuid AND user_id=$2 AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1', pid, scope(user))
        saved = await update_schedule(str(previous['id']), schedule, user) if previous else await create_schedule(schedule, user)
    # One-sync: care-plan changed -> invalidate this user's cached views.
    try:
        from services import cache
        await cache.bump_version(scope(user))
    except Exception:
        pass
    return {'parent': parent, 'schedule': saved}


@router.post('/care-plans')
async def create(payload: CarePlanInput, background_tasks: BackgroundTasks, user=Depends(get_current_user), _csrf=Depends(validate_csrf_token)):
    return await save(payload, background_tasks, user)


@router.put('/care-plans/{parent_id}')
async def update(parent_id: str, payload: CarePlanInput, background_tasks: BackgroundTasks, user=Depends(get_current_user), _csrf=Depends(validate_csrf_token)):
    return await save(payload, background_tasks, user, parent_id)