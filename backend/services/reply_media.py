"""Private, bounded voice retrieval. Never expose Meta authorization to clients."""
import asyncio
import json
import logging
import httpx
from fastapi import HTTPException
from database import get_pool
import storage
from whatsapp import resolve_meta_media_url, meta_auth_header

logger = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 5 * 1024 * 1024


async def load_audio(reply):
    if reply.get('media_storage_path') and storage.is_enabled():
        return await asyncio.to_thread(storage.get_object, reply['media_storage_path'])
    raw = reply.get('raw_payload') or {}
    raw = json.loads(raw) if isinstance(raw, str) else raw
    media_id = reply.get('media_id') or (raw.get('audio') or {}).get('id')
    if not media_id:
        raise HTTPException(410, 'This older recording is unavailable. Its original media ID was not saved.')
    url = await resolve_meta_media_url(media_id)
    if not url:
        raise HTTPException(410, 'This recording is no longer available from WhatsApp.')
    async with httpx.AsyncClient(timeout=20) as client:
        async with client.stream('GET', url, headers=meta_auth_header()) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_AUDIO_BYTES:
                    raise HTTPException(413, 'This recording exceeds the supported 5 MB playback size.')
            content_type = response.headers.get('content-type', 'audio/ogg').split(';')[0]
            if not content_type.startswith('audio/') and content_type != 'application/ogg':
                raise HTTPException(415, 'The recording is not a supported audio file.')
    return bytes(data), content_type


async def archive_audio(reply):
    if not reply.get('is_voice') or reply.get('media_storage_path') or not storage.is_enabled():
        return
    try:
        data, content_type = await load_audio(reply)
        path = f"voice/{reply['user_id']}/{reply['id']}.audio"
        await asyncio.to_thread(storage.put_object, path, data, content_type)
        await get_pool().execute('UPDATE parent_replies SET media_storage_path=$2,media_content_type=$3 WHERE id=$1', reply['id'], path, content_type)
    except Exception as exc:
        logger.warning('Voice archive pending for reply %s (%s)', reply['id'], type(exc).__name__)