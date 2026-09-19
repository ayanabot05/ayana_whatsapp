"""Admin-only live sanity suite.

Lets an operator smoke-test the two flows that historically silently broke
without waiting for real parents to reply:
  1. Welcome opener to a parent AND the account owner (child) — verifies the
     phone-format fix and welcome_deliveries idempotency.
  2. Fake parent inbound reply — creates a parent_reply row and runs the
     notification pipeline so the child either receives the free-form text
     (if window open) or the ayana_parent_reply_{lang} template (if closed).

Every action is scoped to a parent the admin explicitly picks and audit-logged.
"""
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_admin
from database import get_pool
from services import notifications
from services.welcomes import welcome_parent_and_child

router = APIRouter(prefix='/api/admin/sanity', tags=['Admin sanity suite'])


class WelcomeInput(BaseModel):
    parent_id: uuid.UUID


class FakeReplyInput(BaseModel):
    parent_id: uuid.UUID
    body: str = Field(min_length=1, max_length=600, default='[sanity] Amma is fine, ate lunch 💛')


async def _load_parent_and_owner(parent_id: uuid.UUID):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            'SELECT * FROM parents WHERE id=$1 AND deleted_at IS NULL', parent_id,
        )
        if not parent:
            raise HTTPException(404, 'Parent not found or deleted.')
        owner = await conn.fetchrow(
            'SELECT * FROM users WHERE id=$1 AND deleted_at IS NULL', parent['user_id'],
        )
        if not owner:
            raise HTTPException(404, 'Owner not found for this parent.')
    return dict(parent), dict(owner)


@router.post('/welcome')
async def sanity_welcome(payload: WelcomeInput, admin: dict = Depends(get_current_admin)):
    """Send the approved ayana_opener template to parent + child NOW.

    Uses the real welcome_deliveries idempotency table, so calling twice for
    the same (parent, child_phone) is a no-op. Change the child's phone first
    if you need a fresh welcome to a new number.
    """
    parent, owner = await _load_parent_and_owner(payload.parent_id)
    await welcome_parent_and_child(parent, owner, require_activation=False)
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO audit_logs(user_id,action,meta) VALUES($1,'sanity_welcome',$2::jsonb)",
            admin['id'], json.dumps({'parent_id': str(parent['id']), 'owner_id': str(owner['id'])}),
        )
        rows = await conn.fetch(
            "SELECT event_key,phone,status,detail,updated_at FROM welcome_deliveries "
            "WHERE event_key IN ($1,$2) ORDER BY event_key",
            f"parent:{parent['id']}",
            f"child:{owner['id']}:{__import__('hashlib').sha256(owner['phone'].encode()).hexdigest()[:16]}",
        )
    return {
        'ok': True,
        'parent': {'id': str(parent['id']), 'name': parent.get('preferred_name') or parent['name'], 'phone': parent['phone']},
        'child': {'id': str(owner['id']), 'name': owner['name'], 'phone': owner['phone']},
        'deliveries': [
            {'event_key': r['event_key'], 'phone': r['phone'], 'status': r['status'],
             'detail': r['detail'], 'updated_at': r['updated_at'].isoformat() if r['updated_at'] else None}
            for r in rows
        ],
    }


@router.post('/fake-reply')
async def sanity_fake_reply(payload: FakeReplyInput, admin: dict = Depends(get_current_admin)):
    """Inject a synthetic parent inbound reply and run the notification pipeline.

    Effect: creates a parent_replies row (as if the parent messaged), enqueues
    reply_notifications for every care-circle recipient, and immediately drains
    them so the WhatsApp send (template or free-form) happens in-request.
    """
    parent, owner = await _load_parent_and_owner(payload.parent_id)
    now = datetime.now(timezone.utc)
    async with get_pool().acquire() as conn, conn.transaction():
        # Pick the most recent outbound so the reply "belongs" to a real
        # check-in. If none exists, seed a lightweight message_log so the
        # reply has a category to display.
        outbound = await conn.fetchrow(
            "SELECT id, category FROM message_logs WHERE parent_id=$1 "
            "AND msg_type IN ('checkin','reminder') ORDER BY created_at DESC LIMIT 1",
            parent['id'],
        )
        if not outbound:
            log_id = await conn.fetchval(
                "INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,body,created_at) "
                "VALUES($1,$2,$3,'mood','checkin','sent','[sanity opener]',$4) RETURNING id",
                owner['id'], parent['id'], now.strftime('%Y-%m-%d'), now,
            )
            category = 'mood'
        else:
            log_id, category = outbound['id'], outbound['category']

        reply_row = await conn.fetchrow(
            """
            INSERT INTO parent_replies(user_id,parent_id,message_log_id,body,is_voice,created_at,intent)
            VALUES($1,$2,$3,$4,false,$5,'sanity:text')
            RETURNING *
            """,
            owner['id'], parent['id'], log_id, payload.body, now,
        )
        await notifications.enqueue_reply(conn, reply_row)
        await conn.execute(
            "INSERT INTO audit_logs(user_id,action,meta) VALUES($1,'sanity_fake_reply',$2::jsonb)",
            admin['id'], json.dumps({'parent_id': str(parent['id']), 'reply_id': str(reply_row['id'])}),
        )

    # Drain outside the transaction — deliver acquires its own connection.
    await notifications.drain_notifications()

    async with get_pool().acquire() as conn:
        deliveries = await conn.fetch(
            "SELECT recipient_kind,to_phone,status,sid,detail,error_code,email_status,updated_at "
            "FROM reply_notifications WHERE reply_id=$1 ORDER BY created_at",
            reply_row['id'],
        )
    return {
        'ok': True,
        'reply_id': str(reply_row['id']),
        'parent': {'id': str(parent['id']), 'name': parent.get('preferred_name') or parent['name']},
        'category': category,
        'body': payload.body,
        'deliveries': [
            {
                'recipient_kind': d['recipient_kind'],
                'to_phone': d['to_phone'],
                'status': d['status'],
                'sid': d['sid'],
                'detail': d['detail'],
                'error_code': d['error_code'],
                'email_status': d['email_status'],
                'updated_at': d['updated_at'].isoformat() if d['updated_at'] else None,
            }
            for d in deliveries
        ],
    }


@router.get('/parents')
async def sanity_list_parents(admin: dict = Depends(get_current_admin)):
    """Compact parent list for the admin UI's picker."""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.id, p.name, p.preferred_name, p.phone, p.language,
                   u.email AS owner_email, u.name AS owner_name, u.phone AS owner_phone
            FROM parents p JOIN users u ON u.id=p.user_id
            WHERE p.deleted_at IS NULL AND u.deleted_at IS NULL
            ORDER BY p.created_at DESC LIMIT 200
            """
        )
    return {
        'items': [
            {
                'id': str(r['id']),
                'name': r['preferred_name'] or r['name'],
                'phone': r['phone'],
                'language': r['language'],
                'owner_email': r['owner_email'],
                'owner_name': r['owner_name'],
                'owner_phone': r['owner_phone'],
            }
            for r in rows
        ]
    }
