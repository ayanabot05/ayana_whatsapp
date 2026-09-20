"""Provider boundary for ordinary child updates. No out-of-window free-text fallback."""
import os
import httpx
from urllib.parse import urlencode
from whatsapp import _creds, _messages_url, _meta_phone, whatsapp_enabled
from email_sender import _esc, email_enabled


async def send_update(phone, reply, session_open, language='en'):
    if not whatsapp_enabled():
        return {'status': 'disabled', 'detail': 'WhatsApp sending is disabled.'}
    name, prompt, stamp = reply['parent_name'], reply['prompt'], reply['display_time']
    url = reply_url(reply)
    body = reply.get('body') or '[voice note]'
    preview = body if len(body) <= 3300 else body[:3300] + '\n[Full reply in Check-ins]'
    text = f"AYANA: {name} replied · {prompt}\n\n{preview}\n\n{stamp}\n{url}"
    if session_open:
        return await post_meta({'messaging_product':'whatsapp','to':phone,'type':'text','text':{'body':text}})
    # ayana_parent_reply_{en,te,hi} and ayana_parent_voice_{en,te,hi} are
    # approved with a static Website button and a Quick-reply button, so we
    # always try the template when the recipient's window is closed. Opt out
    # only when Meta has explicitly disabled the templates upstream.
    if os.environ.get('WA_CHILD_REPLY_TEMPLATES_ENABLED', 'true').lower() == 'false':
        return {'status': 'awaiting_template', 'detail': 'Child reply templates are disabled by configuration.'}
    lang = language if language in ('en', 'te', 'hi') else 'en'
    kind = 'voice' if reply['is_voice'] else 'reply'
    params = [name, prompt, stamp] if kind == 'voice' else [name, prompt, body[:600], stamp]
    components = [{'type':'body','parameters':[{'type':'text','text':' '.join(str(v).split())} for v in params]}]
    components.append({'type':'button','sub_type':'quick_reply','index':'1','parameters':[{'type':'payload','payload':f"ayana:{kind}:{reply['id']}"}]})
    # Enable only if Meta's approved URL button uses /replies/{{1}}.
    if os.environ.get('WA_REPLY_DYNAMIC_URLS', '').lower() == 'true':
        components.append({'type':'button','sub_type':'url','index':'0','parameters':[{'type':'text','text':str(reply['id'])}]})
    token, phone_id = _creds()
    payload = {'messaging_product':'whatsapp','to':phone,'type':'template','template':{'name':f'ayana_parent_{kind}_{lang}','language':{'code':lang},'components':components}}
    return await post_meta(payload, token, phone_id)


async def post_meta(payload, token=None, phone_id=None):
    token, phone_id = (token, phone_id) if token and phone_id else _creds()
    if not whatsapp_enabled() or not token or not phone_id:
        return {'status':'disabled', 'detail':'WhatsApp credentials are not configured.'}
    try:
        payload = {**payload, 'to': _meta_phone(payload['to'])}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(_messages_url(phone_id), headers={'Authorization':f'Bearer {token}'}, json=payload)
        data = response.json()
        if response.is_success and data.get('messages'):
            return {'status':'sent', 'sid':data['messages'][0]['id']}
        error = data.get('error') or {}
        return {'status':'failed','error_code':error.get('code'),'detail':error.get('message','WhatsApp rejected the request.')}
    except (httpx.TimeoutException, httpx.NetworkError):
        # Acceptance is uncertain: automatic retries could duplicate a delivered message.
        return {'status':'uncertain','detail':'Provider response unavailable; inspect receipts before retrying.'}


async def send_update_email(recipient, reply, notification_id):
    if not recipient.get('email_verified_at'):
        return {'status':'unverified_email'}
    if not email_enabled() or not os.environ.get('RESEND_API_KEY') or not os.environ.get('EMAIL_FROM'):
        return {'status':'disabled'}
    link = reply_url(reply)
    html = f"<p>{_esc(reply['parent_name'])} sent a care reply.</p><p><a href=\"{_esc(link)}\">Open the reply in your AYANA account</a></p>"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post('https://api.resend.com/emails', headers={'Authorization':f"Bearer {os.environ['RESEND_API_KEY']}",'Idempotency-Key':f'notification-{notification_id}'}, json={'from':os.environ['EMAIL_FROM'],'to':[recipient['email']],'subject':'Your parent replied on AYANA','html':html})
        return {'status':'sent','id':response.json().get('id')} if response.is_success else {'status':'failed'}
    except httpx.HTTPError:
        return {'status':'failed'}


def reply_url(reply):
    if not reply.get('parent_id'):
        # Compatibility for old persisted jobs: the authenticated redirect
        # resolves the parent/date; do not block notification delivery.
        return os.environ['FRONTEND_URL'].rstrip('/') + '/replies/' + str(reply['id'])
    query = {'tab': 'checkins', 'parent': str(reply['parent_id']), 'reply': str(reply['id'])}
    if reply.get('local_date'):
        query['date'] = reply['local_date']
    return os.environ['FRONTEND_URL'].rstrip('/') + '/dashboard?' + urlencode(query)