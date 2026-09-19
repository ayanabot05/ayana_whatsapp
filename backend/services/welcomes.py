"""Reuse approved openers, once per recipient, with observable delivery state."""
import hashlib
from database import get_pool
from whatsapp import _send_content_template_with_retry, whatsapp_enabled


async def send_once(key,phone,name,checking_for,language):
    won = await get_pool().fetchval("INSERT INTO welcome_deliveries(event_key,phone) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING event_key",key,phone)
    if not won:
        return dict(await get_pool().fetchrow('SELECT * FROM welcome_deliveries WHERE event_key=$1',key))
    if not whatsapp_enabled():
        result = {'status':'disabled','detail':'WhatsApp sending is disabled.'}
    else:
        result = await _send_content_template_with_retry(phone,f'ayana_opener_{language}',language,{'1':name,'2':checking_for},'opener')
    state = 'accepted' if result.get('status')=='sent' else result.get('status','failed')
    await get_pool().execute('UPDATE welcome_deliveries SET status=$2,sid=$3,detail=$4,updated_at=now() WHERE event_key=$1',key,state,result.get('sid'),result.get('detail'))
    return {'status':state,'detail':result.get('detail')}


def _safe_lang(value):
    return value if value in ('en','te','hi') else 'en'


async def welcome_parent_and_child(parent,owner,require_activation=False):
    if require_activation and not await get_pool().fetchval('SELECT whatsapp_activated FROM activation_state WHERE user_id=$1',parent['user_id']):
        return
    if parent.get('opted_out_at'):
        return
    parent_lang = _safe_lang(parent.get('language'))
    owner_lang = _safe_lang(owner.get('language') or owner.get('preferred_language'))
    pname = parent.get('preferred_name') or parent['name']
    cname = owner['name'].split()[0]
    phone_hash = hashlib.sha256(owner['phone'].encode()).hexdigest()[:16]
    await send_once(f"parent:{parent['id']}",parent['phone'],pname,cname,parent_lang)
    await send_once(f"child:{owner['id']}:{phone_hash}",owner['phone'],cname,pname,owner_lang)