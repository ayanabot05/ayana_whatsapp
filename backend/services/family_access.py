"""Resolve current family recipients and plan allowances at delivery time."""
from pricing import plan_limits
from services import billing_access
import json


def recipient_language(person):
    prefs = person.get('preferences') or {}
    prefs = json.loads(prefs) if isinstance(prefs,str) else prefs
    language = person.get('language') or prefs.get('notification_language') or 'en'
    return language if language in ('en','te','hi') else 'en'


def normalized(person):
    result = dict(person)
    result['language'] = recipient_language(result)
    return result


async def recipients(conn, owner_id):
    owner = await conn.fetchrow('SELECT * FROM users WHERE id=$1 AND deleted_at IS NULL', owner_id)
    if not owner:
        return []
    result = [('user', normalized(owner))]
    entitlement = await billing_access.access(conn, owner_id)
    limit = plan_limits(entitlement['plan']).get('family_members', 0) if entitlement['allowed'] else 0
    if not limit:
        return result
    users = await conn.fetch('SELECT * FROM users WHERE household_owner_id=$1 AND deleted_at IS NULL ORDER BY created_at,id', owner_id)
    siblings = await conn.fetch('SELECT * FROM care_circle_siblings WHERE owner_id=$1 AND verified ORDER BY created_at,id', owner_id)
    family = [('user', dict(r)) for r in users] + [('sibling', dict(r)) for r in siblings]
    family.sort(key=lambda pair: (pair[1]['created_at'], str(pair[1]['id'])))
    seen = {owner['phone']}
    for kind, person in family:
        if person['phone'] in seen:
            continue
        seen.add(person['phone'])
        result.append((kind, normalized(person)))
        if len(result)-1 >= limit:
            break
    return result


async def recipient(conn, owner_id, kind, recipient_id):
    return next((person for k, person in await recipients(conn, owner_id)
                 if k == kind and person['id'] == recipient_id), None)
