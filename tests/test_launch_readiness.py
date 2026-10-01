"""Integration checks against the isolated local cluster, never live customers."""
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import test_delivery_database as fixture
mock_meta_http=fixture.mock_meta_http
from services import family_access, family_delivery, monthly_jobs, delivery_watch, welcomes, notifications, receipts


class LaunchTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.DeliveryDatabaseTests.asyncSetUp
    asyncTearDown=fixture.DeliveryDatabaseTests.asyncTearDown
    schedule=fixture.DeliveryDatabaseTests.schedule

    async def sibling(self):
        return dict(await self.pool.fetchrow("INSERT INTO care_circle_siblings(owner_id,name,phone,language,verified,email,email_verified_at) VALUES($1,'Sibling','+12025550124','en',true,$2,now()) RETURNING *",self.owner['id'],f'{uuid.uuid4()}@example.test'))

    async def report_jobs(self):
        async with self.pool.acquire() as conn:
            await family_delivery.enqueue(conn,self.parent,'report','2026-09',{'name':'Amma','period':'2026-09'})
        return await self.pool.fetch('SELECT * FROM family_notifications WHERE parent_id=$1 ORDER BY recipient_kind',self.parent['id'])

    async def test_report_queue_deduplicates_and_receipts_track_delivery(self):
        await self.sibling()
        from monthly_report import generate_monthly_report
        with patch('monthly_report.storage_enabled',return_value=False):
            await generate_monthly_report(self.owner['id'],self.parent['id'],'raksha',2026,9)
        jobs=await self.report_jobs()
        await self.report_jobs()
        self.assertEqual(len(jobs),2)
        from services.template_registry import catalog
        templates = catalog()+[{**r,'status':'APPROVED'} for r in json.loads((Path(__file__).resolve().parents[1]/'docs/monthly_pdf_templates.json').read_text(encoding='utf-8'))]
        with patch('services.template_registry.catalog',return_value=templates), patch('services.report_delivery.upload_pdf',AsyncMock(return_value='pdf-test')), mock_meta_http() as (packets,_):
            for job in jobs:
                await family_delivery.deliver(job['event_key'])
                await family_delivery.deliver(job['event_key'])
            self.assertEqual(len(packets),2)
            self.assertTrue(all(p['payload']['template']['name']=='ayana_monthly_report_pdf_en' for p in packets))
            await receipts.ingest({'id':packets[0]['sid'],'status':'delivered'})
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM family_notifications WHERE parent_id=$1 AND status='delivered'",self.parent['id']),1)

    async def test_downgrade_stops_queued_sibling_report_and_reply(self):
        sibling=await self.sibling()
        jobs=await self.report_jobs()
        reply=dict(await self.pool.fetchrow("INSERT INTO parent_replies(parent_id,user_id,body) VALUES($1,$2,'Yes') RETURNING *",self.parent['id'],self.owner['id']))
        async with self.pool.acquire() as conn:
            await notifications.enqueue_reply(conn,reply)
        pending=await self.pool.fetch('SELECT * FROM reply_notifications WHERE reply_id=$1',reply['id'])
        with patch('services.billing_access.access',AsyncMock(return_value={'allowed':True,'plan':'nitya'})), mock_meta_http() as (packets,_):
            for job in jobs:
                await family_delivery.deliver(job['event_key'])
            for job in pending:
                await notifications.deliver(job['id'])
        self.assertTrue(packets)
        self.assertTrue(all(p['payload']['to']==self.owner['phone'].lstrip('+') for p in packets))
        self.assertEqual(await self.pool.fetchval('SELECT status FROM family_notifications WHERE recipient_id=$1',sibling['id']),'cancelled')
        self.assertEqual(await self.pool.fetchval('SELECT status FROM reply_notifications WHERE recipient_id=$1',sibling['id']),'cancelled')

    async def test_downgrade_blocks_linked_household_data_access(self):
        from auth import enforce_family_access
        from fastapi import HTTPException
        from starlette.requests import Request
        member=dict(await self.pool.fetchrow("INSERT INTO users(name,email,phone,password_hash,household_owner_id) VALUES('Member',$1,'+12025550128','test-only',$2) RETURNING *",f'{uuid.uuid4()}@example.test',self.owner['id']))
        try:
            request=Request({'type':'http','method':'GET','path':'/api/parents','headers':[]})
            await enforce_family_access(member,request)
            with patch('services.billing_access.access',AsyncMock(return_value={'allowed':True,'plan':'nitya'})):
                with self.assertRaises(HTTPException) as error:
                    await enforce_family_access(member,request)
                self.assertEqual(error.exception.status_code,403)
                await enforce_family_access(member,Request({'type':'http','method':'GET','path':'/api/auth/me','headers':[]}))
        finally:
            await self.pool.execute('DELETE FROM users WHERE id=$1',member['id'])

    async def test_current_number_used_and_uncertain_never_replayed(self):
        job=(await self.report_jobs())[0]
        await self.pool.execute("UPDATE users SET phone='+12025550129',phone_changed_at=now() WHERE id=$1",self.owner['id'])
        with patch('services.family_delivery.whatsapp_enabled',return_value=True), patch('services.family_delivery.send',AsyncMock(return_value={'status':'uncertain'})) as send:
            await family_delivery.deliver(job['event_key'])
            await family_delivery.deliver(job['event_key'])
            send.assert_awaited_once()
            self.assertEqual(send.call_args.args[1]['phone'],'+12025550129')
        self.assertEqual(await self.pool.fetchval('SELECT status FROM family_notifications WHERE event_key=$1',job['event_key']),'uncertain')

    async def test_report_retries_transient_failure(self):
        job=(await self.report_jobs())[0]
        with patch('services.family_delivery.whatsapp_enabled',return_value=True), patch('services.family_delivery.send',AsyncMock(side_effect=[{'status':'failed','error_code':131000},{'status':'sent','sid':'report-'+uuid.uuid4().hex}])) as send:
            await family_delivery.deliver(job['event_key'])
            self.assertEqual(await self.pool.fetchval('SELECT status FROM family_notifications WHERE event_key=$1',job['event_key']),'retry')
            await self.pool.execute('UPDATE family_notifications SET next_attempt_at=now() WHERE event_key=$1',job['event_key'])
            await family_delivery.deliver(job['event_key'])
            self.assertEqual(send.await_count,2)

    async def test_actual_report_generation_persists_and_queues_once(self):
        from monthly_report import generate_monthly_report
        with patch('monthly_report.storage_enabled',return_value=False):
            for _ in range(2):
                report=await generate_monthly_report(self.owner['id'],self.parent['id'],'raksha',2026,9,notify=True)
        self.assertEqual(report['period'],'2026-09')
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM monthly_reports WHERE parent_id=$1',self.parent['id']),1)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM family_notifications WHERE parent_id=$1',self.parent['id']),1)

    async def test_email_fallback_is_verified_and_deduplicated(self):
        import httpx
        job=(await self.report_jobs())[0]
        post=AsyncMock(return_value=httpx.Response(200,json={'id':'test-mail'}))
        with patch('services.family_delivery.email_enabled',return_value=True), patch.dict('os.environ',{'RESEND_API_KEY':'test-only','EMAIL_FROM':'test@example.test'}), patch('httpx.AsyncClient.post',post):
            await family_delivery.email_fallback(job)
            await family_delivery.email_fallback(job)
        post.assert_awaited_once()
        self.assertEqual(post.call_args.kwargs['json']['to'],[self.owner['email']])
        self.assertEqual(await self.pool.fetchval('SELECT email_status FROM family_notifications WHERE event_key=$1',job['event_key']),'sent')

    async def test_missing_template_recovery_does_not_delay_email(self):
        job=(await self.report_jobs())[0]
        await self.pool.execute("UPDATE family_notifications SET status='configuration_error',updated_at=now()-interval '1 hour',next_attempt_at=now() WHERE event_key=$1",job['event_key'])
        with patch('services.report_delivery.document_template',side_effect=ValueError('Not approved')), patch('services.family_delivery.email_fallback',AsyncMock()) as email:
            await family_delivery.drain()
        email.assert_awaited_once()
        self.assertEqual(email.call_args.args[0]['event_key'],job['event_key'])

    async def test_monthly_job_catches_up_and_generates_only_once(self):
        now=datetime.now(timezone.utc)
        first=now.replace(day=1,hour=9,minute=0,second=0,microsecond=0)
        await self.pool.execute('UPDATE parents SET created_at=$2 WHERE id=$1',self.parent['id'],first-timedelta(days=45))
        async def generated(owner,parent,plan,year,month,notify):
            async with self.pool.acquire() as conn:
                from monthly_report import _notify_report_ready
                await _notify_report_ready(conn,owner,parent,f'{year:04d}-{month:02d}',True)
        with patch('monthly_report.generate_monthly_report',AsyncMock(side_effect=generated)) as generate:
            await monthly_jobs.drain(first-timedelta(minutes=1))
            generate.assert_not_awaited()
            await monthly_jobs.drain(first+timedelta(days=2))
            await monthly_jobs.drain(first+timedelta(days=3))
            generate.assert_awaited_once()
        self.assertEqual(await self.pool.fetchval('SELECT status FROM monthly_report_jobs WHERE parent_id=$1',self.parent['id']),'complete')
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM family_notifications WHERE parent_id=$1',self.parent['id']),1)

    async def test_delivery_failure_alert_deduplicates_slots_and_days(self):
        now=self.now
        await self.schedule([{'category':'lunch','time':'13:00'}])
        for key in ('a','a','b'):
            await self.pool.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,event_key,created_at) VALUES($1,$2,$3,'lunch','checkin','failed',$4,$5)",self.owner['id'],self.parent['id'],now.date().isoformat(),f'{self.parent["id"]}:{key}',now-timedelta(hours=2))
        await delivery_watch.drain(now)
        await delivery_watch.drain(now)
        self.assertEqual(await self.pool.fetchval('SELECT failures FROM parent_delivery_alerts WHERE parent_id=$1',self.parent['id']),2)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM family_notifications WHERE parent_id=$1 AND kind='delivery_alert'",self.parent['id']),1)
        from services.checkin_timeline import timeline
        result=await timeline(self.owner['id'])
        self.assertEqual(len(result['delivery_alerts']),1)

    async def test_successful_retry_resolves_delivery_failure(self):
        await self.schedule([{'category':'lunch','time':'13:00'}])
        for key,state in (('a','failed'),('a','delivered'),('b','failed')):
            await self.pool.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,delivery_status,event_key,created_at) VALUES($1,$2,$3,'lunch','checkin','sent',$4,$5,$6)",self.owner['id'],self.parent['id'],self.now.date().isoformat(),state,f'{self.parent["id"]}:{key}',self.now-timedelta(hours=2))
        await delivery_watch.drain(self.now)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM parent_delivery_alerts WHERE parent_id=$1',self.parent['id']),0)

    async def test_welcome_recovers_only_after_approval_without_replaying_accepted(self):
        await self.pool.execute("INSERT INTO consent_logs(user_id,consent_type,agreed,text) VALUES($1,'child',true,'Test')",self.owner['id'])
        key=await welcomes.queue_child(dict(self.owner))
        await self.pool.execute("UPDATE welcome_deliveries SET status='configuration_error',attempts=4 WHERE event_key=$1",key)
        from services.template_registry import catalog
        fixture=[{**r,'status':'APPROVED'} for r in json.loads((Path(__file__).resolve().parents[1]/'docs/supplied_warning_welcome_templates.json').read_text(encoding='utf-8'))]
        with patch('services.template_registry.catalog',return_value=[]):
            await welcomes.recover_template_configuration()
            self.assertEqual(await self.pool.fetchval('SELECT status FROM welcome_deliveries WHERE event_key=$1',key),'configuration_error')
        with patch('services.template_registry.catalog',return_value=catalog()+fixture), mock_meta_http() as (packets,_):
            await self.pool.execute('UPDATE welcome_deliveries SET next_attempt_at=now() WHERE event_key=$1',key)
            await welcomes.recover_template_configuration()
            await welcomes.deliver(key)
            await welcomes.recover_template_configuration()
            await welcomes.deliver(key)
            self.assertEqual(len(packets),1)

    async def test_need_help_creates_emergency_event_once(self):
        from routes.webhook import _record_reply
        sid='prompt-'+uuid.uuid4().hex
        await self.pool.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,sid) VALUES($1,$2,$3,'health_check','activity','sent',$4)",self.owner['id'],self.parent['id'],self.now.date().isoformat(),sid)
        wam='reply-'+uuid.uuid4().hex
        with patch('services.notifications.drain_notifications',AsyncMock()):
            reply=await _record_reply(self.parent['phone'],'Need help 🆘',parent=self.parent,button_payload='template_button',context_id=sid,wam_id=wam)
            await _record_reply(self.parent['phone'],'Need help 🆘',parent=self.parent,button_payload='template_button',context_id=sid,wam_id=wam)
        self.assertEqual(reply['intent'],'emergency:help')
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM emergency_events WHERE parent_id=$1',self.parent['id']),1)


if __name__=='__main__':
    unittest.main()
