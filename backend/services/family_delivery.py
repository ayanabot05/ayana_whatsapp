"""Durable report and delivery-alert notifications, with current recipient checks."""
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from database import get_pool
from email_sender import _esc, email_enabled
from services import family_access
from services.notification_transport import post_meta
from services.notifications import window_open, RETRYABLE_CODES
from services.template_registry import build
from whatsapp import whatsapp_enabled

logger = logging.getLogger(__name__)


async def enqueue(conn, parent, kind, identity, payload):
    for recipient_kind, person in await family_access.recipients(conn, parent['user_id']):
        key = f"{kind}:{parent['id']}:{identity}:{recipient_kind}:{person['id']}"
        await conn.execute('''INSERT INTO family_notifications
            (event_key,user_id,parent_id,kind,recipient_kind,recipient_id,payload)
            VALUES($1,$2,$3,$4,$5,$6,$7::jsonb) ON CONFLICT DO NOTHING''',
            key,parent['user_id'],parent['id'],kind,recipient_kind,person['id'],json.dumps(payload))


def content(job, language='en'):
    data = json.loads(job['payload']) if isinstance(job['payload'],str) else job['payload']
    params = {'tab':'reports' if job['kind']=='report' else 'checkins','parent':str(job['parent_id'])}
    params['period' if job['kind']=='report' else 'date'] = data['period'] if job['kind']=='report' else data['day']
    url = os.environ.get('FRONTEND_URL','').rstrip('/') + '/dashboard?' + urlencode(params)
    if job['kind']=='voice_summary':
        from services.voice_summaries import LABELS
        label,caution = LABELS.get(language,LABELS['en'])
        summary = data.get('summary','Summary pending')
        body = f"{data['name']} · {data['prompt']} · {data['stamp']}\n\n{label}:\n{summary}\n\n{caution}"
        url += '&reply=' + data['reply_id']
        return body,url,'ayana_parent_voice_summary',[data['name'],data['prompt'],data['stamp'],summary]
    if job['kind']=='report':
        body = f"{data['name']}'s AYANA monthly report for {data['period']} is ready. View it in your dashboard."
        return body, url, 'ayana_monthly_report_pdf', [data['name'],data['period']]
    body = f"AYANA could not confirm delivery of {data['count']} scheduled messages to {data['name']} on {data['day']}. Please check their phone or contact them directly. This is a delivery problem, not a confirmed missed reply."
    return body, url, 'ayana_delivery_issue', [data['name'],str(data['count']),data['day']]


async def send(job, person, opened):
    if job['kind']=='report':
        from services.report_delivery import send as send_pdf
        return await send_pdf(job,person,opened)
    language = person.get('language') if person.get('language') in ('en','te','hi') else 'en'
    if job['kind']=='voice_summary':
        from services.voice_summaries import get_summary
        data = json.loads(job['payload']) if isinstance(job['payload'],str) else dict(job['payload'])
        summary = await get_summary(data['reply_id'],language)
        if not summary:
            return {'status':'retry','detail':'Summary unavailable; original recording remains available.'}
        job = {**dict(job),'payload':{**data,'summary':summary}}
    body, url, template, values = content(job,language)
    if opened:
        result = await post_meta({'messaging_product':'whatsapp','to':person['phone'],'type':'text','text':{'body':body+'\n'+url}})
        if result.get('error_code') != 131047:
            return result
    try:
        payload, _ = build(f'{template}_{language}', language, values)
    except ValueError as exc:
        return {'status':'configuration_error','detail':str(exc)}
    return await post_meta({'messaging_product':'whatsapp','to':person['phone'],'type':'template','template':payload})


async def deliver(key):
    if not whatsapp_enabled():
        await get_pool().execute("UPDATE family_notifications SET status='disabled' WHERE event_key=$1 AND status IN ('pending','retry','awaiting_template')",key)
        return
    pool = get_pool()
    job = await pool.fetchrow("""UPDATE family_notifications SET status='sending',attempts=attempts+1,updated_at=now()
        WHERE event_key=$1 AND status IN ('pending','retry','awaiting_template','disabled')
        AND attempts<8 AND next_attempt_at<=now() RETURNING *""",key)
    if not job:
        return
    try:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','recipient:'+str(job['recipient_id']))
            person = await family_access.recipient(conn,job['user_id'],job['recipient_kind'],job['recipient_id'])
            parent = await conn.fetchrow('SELECT * FROM parents WHERE id=$1 AND deleted_at IS NULL',job['parent_id'])
            if not person or not parent:
                state, result = 'cancelled', {}
            elif job['created_at'] < datetime.now(timezone.utc)-timedelta(days=7 if job['kind']=='report' else 1):
                state, result = 'expired', {}
            else:
                opened = await window_open(conn,person['phone'],person.get('phone_changed_at'))
                result = await send(job,person,opened)
                state = result.get('status','failed')
                if state=='sent':
                    state='accepted'
                elif result.get('error_code') in RETRYABLE_CODES | {131047} and job['attempts']<8:
                    state='retry'
                if result.get('error_code')==131047:
                    await conn.execute('DELETE FROM recipient_sessions WHERE phone=$1',person['phone'])
            await conn.execute("""UPDATE family_notifications SET status=$2,sid=$3,to_phone=$4,detail=$5,
                next_attempt_at=now()+interval '15 minutes',updated_at=now() WHERE event_key=$1""",
                key,state,result.get('sid'),person['phone'] if person else None,result.get('detail'))
    except Exception:
        logger.exception('Family notification submission interrupted: %s', key)
        await pool.execute("UPDATE family_notifications SET status='uncertain',detail='Submission interrupted; reconcile provider receipts before resending.',updated_at=now() WHERE event_key=$1",key)


async def email_fallback(job):
    pool=get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','recipient:'+str(job['recipient_id']))
        person=await family_access.recipient(conn,job['user_id'],job['recipient_kind'],job['recipient_id'])
        parent=await conn.fetchval('SELECT 1 FROM parents WHERE id=$1 AND deleted_at IS NULL',job['parent_id'])
        if not person or not parent:
            await conn.execute("UPDATE family_notifications SET email_status='cancelled' WHERE event_key=$1",job['event_key'])
            return
        prefs=person.get('preferences') or {}
        prefs=json.loads(prefs) if isinstance(prefs,str) else prefs
        if not person.get('email_verified_at') or not person.get('email') or prefs.get('email_notifications') is False:
            await conn.execute("UPDATE family_notifications SET email_status='disabled' WHERE event_key=$1",job['event_key'])
            return
        if not email_enabled() or not os.environ.get('RESEND_API_KEY') or not os.environ.get('EMAIL_FROM'):
            return
        claimed=await pool.fetchval("""UPDATE family_notifications SET email_status='sending',email_attempts=email_attempts+1,
            updated_at=now() WHERE event_key=$1 AND coalesce(email_status,'') IN ('','retry') AND email_attempts<4 RETURNING event_key""",job['event_key'])
        if not claimed:
            return
        body,url,_,_=content(job)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response=await client.post('https://api.resend.com/emails',headers={
                    'Authorization':'Bearer '+os.environ['RESEND_API_KEY'],
                    'Idempotency-Key':'family-'+hashlib.sha256(job['event_key'].encode()).hexdigest()},json={
                    'from':os.environ['EMAIL_FROM'],'to':[person['email']],
                    'subject':'AYANA monthly report' if job['kind']=='report' else 'AYANA message delivery needs attention',
                    'html':f'<p>{_esc(body)}</p><p><a href="{_esc(url)}">Open AYANA</a></p>'})
            state='sent' if response.is_success else 'retry'
        except httpx.HTTPError:
            state='uncertain'
        await conn.execute("UPDATE family_notifications SET email_status=$2,next_attempt_at=now()+interval '15 minutes',updated_at=now() WHERE event_key=$1",job['event_key'],state)


async def persist_receipt(status):
    sid,state=status.get('id'),status.get('status')
    if not sid or state not in ('sent','delivered','read','failed'):
        return
    error=(status.get('errors') or [{}])[0]
    new='accepted' if state=='sent' else state
    if state=='failed' and error.get('code') in RETRYABLE_CODES | {131047}:
        new='retry'
    await get_pool().execute("""UPDATE family_notifications SET status=$2,detail=$3,
        next_attempt_at=now()+interval '15 minutes',updated_at=now()
        WHERE sid=$1 AND status<>'read' AND (status<>'delivered' OR $2='read')""",sid,new,error.get('title'))
    if error.get('code')==131047:
        await get_pool().execute('DELETE FROM recipient_sessions WHERE phone IN (SELECT to_phone FROM family_notifications WHERE sid=$1)',sid)


async def drain():
    pool=get_pool()
    await pool.execute("UPDATE family_notifications SET status='uncertain' WHERE status='sending' AND updated_at<now()-interval '5 minutes'")
    await pool.execute("UPDATE family_notifications SET email_status='uncertain' WHERE email_status='sending' AND updated_at<now()-interval '5 minutes'")
    # Missing approvals do not consume attempts. Requeue only once a valid
    # template exists, without replaying anything Meta may already have accepted.
    await pool.execute("""UPDATE family_notifications SET status='expired'
        WHERE status IN ('pending','retry','configuration_error','disabled')
        AND created_at<now()-CASE WHEN kind='report' THEN interval '7 days' ELSE interval '1 day' END""")
    for job in await pool.fetch("SELECT * FROM family_notifications WHERE status='configuration_error' AND updated_at<=now()-interval '5 minutes' ORDER BY updated_at LIMIT 100"):
        async with pool.acquire() as conn:
            person=await family_access.recipient(conn,job['user_id'],job['recipient_kind'],job['recipient_id'])
            opened=bool(person and await window_open(conn,person['phone'],person.get('phone_changed_at')))
        if not person:
            await pool.execute("UPDATE family_notifications SET status='cancelled' WHERE event_key=$1",job['event_key'])
            continue
        _,_,name,values=content(job)
        lang=person.get('language') if person.get('language') in ('en','te','hi') else 'en'
        try:
            if opened:
                pass
            elif job['kind']=='report':
                from services.report_delivery import document_template
                document_template(lang,values[0],values[1],{'id':'validation-only'})
            else:
                build(f'{name}_{lang}',lang,values)
        except ValueError:
            await pool.execute("UPDATE family_notifications SET updated_at=now() WHERE event_key=$1 AND status='configuration_error'",job['event_key'])
            continue
        await pool.execute("UPDATE family_notifications SET status='pending',attempts=0,next_attempt_at=now() WHERE event_key=$1 AND status='configuration_error'",job['event_key'])
    for job in await pool.fetch("SELECT event_key FROM family_notifications WHERE status IN ('pending','retry','awaiting_template','disabled') AND attempts<8 AND next_attempt_at<=now() ORDER BY created_at LIMIT 30"):
        await deliver(job['event_key'])
    for job in await pool.fetch("""SELECT * FROM family_notifications WHERE (status IN ('failed','configuration_error','uncertain','disabled','retry')
        OR (status='accepted' AND updated_at<now()-interval '6 hours'))
        AND kind<>'voice_summary' AND coalesce(email_status,'') IN ('','retry') AND email_attempts<4 AND next_attempt_at<=now()
        AND created_at>now()-CASE WHEN kind='report' THEN interval '7 days' ELSE interval '24 hours' END ORDER BY created_at LIMIT 30"""):
        await email_fallback(job)
