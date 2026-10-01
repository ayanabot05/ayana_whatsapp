"""Read-only delivery diagnostics. Never prints credentials or message bodies."""
import asyncio
import json
import os
import argparse
from pathlib import Path
import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / 'backend' / '.env')

async def main(email=None):
    url = os.environ.get('SUPABASE_DB_URL') or os.environ.get('DATABASE_URL')
    try:
        conn = await asyncpg.connect(url, statement_cache_size=0, timeout=20)
        async with conn.transaction(readonly=True):
            if email:
                users = await conn.fetch("SELECT id,right(phone,4) AS phone_last4,to_jsonb(u)->>'email_verified_at' AS email_verified_at,to_jsonb(u)->>'phone_changed_at' AS phone_changed_at,to_jsonb(u)->>'contact_version' AS contact_version,to_jsonb(u)->>'deleted_at' AS deleted_at FROM users u WHERE lower(email)=lower($1)", email)
                print('requested_account', json.dumps([dict(r) for r in users], default=str))
                for user in users:
                    for label, sql in [
                        ('account_welcomes', 'SELECT event_key,status,detail,attempts,right(phone,4) AS phone_last4,updated_at FROM welcome_deliveries WHERE recipient_id=$1'),
                        ('account_notifications', 'SELECT status,error_code,detail,attempts,right(to_phone,4) AS phone_last4,updated_at FROM reply_notifications WHERE recipient_id=$1 ORDER BY created_at DESC LIMIT 15'),
                        ('account_parents', 'SELECT id,language,timezone,created_at,deleted_at FROM parents WHERE user_id=$1'),
                    ]:
                        try:
                            async with conn.transaction():
                                print(label, json.dumps([dict(r) for r in await conn.fetch(sql, user['id'])], default=str))
                        except Exception as exc:
                            print(label, type(exc).__name__, str(exc).splitlines()[0])
            for label, sql in [
                ('notifications', "SELECT status,error_code,count(*) AS count,max(created_at) AS latest FROM reply_notifications GROUP BY status,error_code ORDER BY count(*) DESC"),
                ('welcomes', "SELECT status,count(*) AS count,max(updated_at) AS latest FROM welcome_deliveries GROUP BY status"),
                ('recent_provider_failures', "SELECT payload->>'status' AS status,payload->'errors' AS errors,count(*) AS count FROM provider_receipts WHERE received_at>now()-interval '7 days' AND payload->>'status'='failed' GROUP BY 1,2"),
                ('changed_contacts', "SELECT id,right(phone,4) AS phone_last4,phone_changed_at FROM users WHERE deleted_at IS NULL AND phone_changed_at IS NOT NULL ORDER BY phone_changed_at DESC LIMIT 10"),
                ('activity', "SELECT (SELECT max(created_at) FROM parent_replies) AS latest_reply,(SELECT max(created_at) FROM message_logs) AS latest_send,(SELECT count(*) FROM inbound_events WHERE status='pending') AS pending_inbound"),
            ]:
                try:
                    async with conn.transaction():
                        print(label, json.dumps([dict(r) for r in await conn.fetch(sql)], default=str))
                except Exception as exc:
                    print(label, type(exc).__name__)
        await conn.close()
    except Exception as exc:
        print('database_connection', type(exc).__name__)
    token = os.environ.get('META_WA_ACCESS_TOKEN')
    account = os.environ.get('META_WA_BUSINESS_ACCOUNT_ID')
    if token and account:
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.get(f"https://graph.facebook.com/{os.environ.get('META_WA_GRAPH_VERSION','v22.0')}/{account}/message_templates", headers={'Authorization':f'Bearer {token}'}, params={'fields':'name,status,category,language,components','limit':100})
                data = response.json()
                rows = data.get('data', [])
                while data.get('paging', {}).get('next'):
                    after = data['paging']['cursors']['after']
                    response = await client.get(f"https://graph.facebook.com/{os.environ.get('META_WA_GRAPH_VERSION','v22.0')}/{account}/message_templates", headers={'Authorization':f'Bearer {token}'}, params={'fields':'name,status,category,language,components','limit':100,'after':after})
                    response.raise_for_status()
                    data = response.json()
                    rows.extend(data.get('data', []))
                if rows:
                    (Path(__file__).resolve().parents[1] / 'backend' / 'approved_templates.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
                print('meta_templates', len(rows), 'catalog refreshed')
        except Exception as exc:
            print('meta_connection', type(exc).__name__)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--email')
    asyncio.run(main(parser.parse_args().email))
