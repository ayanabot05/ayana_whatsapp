"""Authenticated reply detail and audio endpoints for deep-linked notifications."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Response
from auth import get_current_user, serialize
from database import get_pool
from services.notifications import reply_details
from services.reply_media import load_audio

router = APIRouter(prefix='/api/replies', tags=['Replies'])


async def authorized_reply(reply_id, user):
    async with get_pool().acquire() as conn:
        reply = await reply_details(conn,reply_id)
    owner_id = user.get('household_owner_id') or user['id']
    if not reply or str(reply['user_id']) != str(owner_id):
        raise HTTPException(404,'Reply not found.')
    return reply


@router.get('/{reply_id}')
async def get_reply(reply_id: UUID, user=Depends(get_current_user)):
    reply = await authorized_reply(reply_id,user)
    public = {key:reply.get(key) for key in ('id','parent_id','parent_name','prompt','display_time','local_date','body','transcription','stt_confidence','is_voice','created_at','read_at')}
    notifications = await get_pool().fetch('SELECT status,email_status,audio_status,detail FROM reply_notifications WHERE reply_id=$1 AND recipient_kind=$2 AND recipient_id=$3',reply_id,'user',user['id'])
    return {**serialize(public),'notifications':[dict(n) for n in notifications]}


@router.get('/{reply_id}/audio')
async def get_reply_audio(reply_id: UUID, user=Depends(get_current_user)):
    reply = await authorized_reply(reply_id,user)
    if not reply['is_voice']:
        raise HTTPException(404,'This reply has no voice note.')
    try:
        audio, content_type = await load_audio(reply)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503,'The recording could not be loaded. Please try again shortly.')
    return Response(content=audio,media_type=content_type,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})