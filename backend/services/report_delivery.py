"""Send the persisted monthly report as an actual PDF attachment."""
import asyncio
import json
import httpx
from database import get_pool
from services.notification_transport import post_meta
from services.template_registry import build, definition
from whatsapp import _creds, _GRAPH_VERSION


def document_template(language, name, period, document):
    template_name = f'ayana_monthly_report_pdf_{language}'
    row = definition(template_name,language)
    header = next((c for c in row['components'] if c['type']=='HEADER'),{})
    if header.get('format') != 'DOCUMENT':
        raise ValueError('Monthly PDF template requires an approved DOCUMENT header')
    payload,_ = build(template_name,language,[name,period])
    payload['components'].insert(0,{'type':'header','parameters':[{'type':'document','document':document}]})
    return payload


async def upload_pdf(data, filename):
    token,phone_id = _creds()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f'https://graph.facebook.com/{_GRAPH_VERSION}/{phone_id}/media',
            headers={'Authorization':f'Bearer {token}'}, data={'messaging_product':'whatsapp'},
            files={'file':(filename,data,'application/pdf')})
    response.raise_for_status()
    return response.json()['id']


async def send(job, person, opened):
    data = json.loads(job['payload']) if isinstance(job['payload'],str) else job['payload']
    lang = person.get('language') if person.get('language') in ('en','te','hi') else 'en'
    filename = f"AYANA-{data['period']}.pdf"
    if not opened:
        try:
            document_template(lang,data['name'],data['period'],{'id':'validation-only','filename':filename})
        except ValueError as exc:
            return {'status':'configuration_error','detail':str(exc)}
    report = await get_pool().fetchrow('SELECT * FROM monthly_reports WHERE user_id=$1 AND parent_id=$2 AND period=$3',job['user_id'],job['parent_id'],data['period'])
    if not report:
        return {'status':'retry','detail':'Monthly report is not available yet.'}
    from monthly_report import _generate_pdf_bytes
    report = dict(report)
    details = json.loads(report['details']) if isinstance(report['details'],str) else report['details']
    pdf = await asyncio.to_thread(_generate_pdf_bytes,report,details or {})
    if not pdf:
        return {'status':'retry','detail':'PDF generation unavailable.'}
    try:
        media_id = await upload_pdf(pdf,filename)
    except (httpx.HTTPError,ValueError,KeyError):
        # Retrying an upload cannot duplicate a recipient message.
        return {'status':'retry','detail':'PDF upload unavailable.'}
    document = {'id':media_id,'filename':filename}
    if opened:
        result = await post_meta({'messaging_product':'whatsapp','to':person['phone'],'type':'document','document':document})
        if result.get('error_code') != 131047:
            return result
    try:
        payload = document_template(lang,data['name'],data['period'],document)
    except ValueError as exc:
        return {'status':'configuration_error','detail':str(exc)}
    return await post_meta({'messaging_product':'whatsapp','to':person['phone'],'type':'template','template':payload})
