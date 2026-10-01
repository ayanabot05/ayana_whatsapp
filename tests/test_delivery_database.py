"""Real PostgreSQL tests against the isolated port-55439 local test cluster."""
import asyncio
import json
import os
import sys
import unittest
import uuid
from contextlib import contextmanager
from copy import deepcopy
import httpx
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

os.environ.update(PYTHON_DOTENV_DISABLED='1', APP_ENV='test', WHATSAPP_ENABLED='false',
    SCHEDULER_ENABLED='false', EMAIL_ENABLED='false', PAYMENTS_ENABLED='false', SENTRY_DSN='',
    SUPABASE_DB_URL='postgresql://ayana_test@127.0.0.1:55439/ayana_delivery_local',
    DATABASE_URL='postgresql://ayana_test@127.0.0.1:55439/ayana_delivery_local',
    REDIS_URL='', JWT_SECRET='local-delivery-regression-only', FRONTEND_URL='https://example.test',
    DB_MIN_POOL_SIZE='2', DB_MAX_POOL_SIZE='8')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import database
import scheduler
from services import care_followups, notifications, welcomes
from services.migrations import apply_care_migration
from services.schedule_source import event_key
from services.checkin_timeline import timeline


@contextmanager
def mock_meta_http():
    """Mock only HTTP; real scheduler, templates, outboxes and DB still execute."""
    packets = []

    def response(url, **kwargs):
        if not str(url).startswith('https://graph.facebook.com/'):
            raise AssertionError(f'Unexpected outbound HTTP destination: {url}')
        sid = 'wamid.test.' + uuid.uuid4().hex
        packets.append({'sid': sid, 'payload': deepcopy(kwargs['json'])})
        return httpx.Response(200, json={'messages': [{'id': sid}]}, request=httpx.Request('POST', url))

    async def async_response(_client, url, **kwargs):
        return response(url, **kwargs)

    with patch.dict(os.environ, {'WHATSAPP_ENABLED':'true','META_WA_ACCESS_TOKEN':'test-only-token',
            'META_WA_PHONE_NUMBER_ID':'test-only-id','WA_CHILD_REPLY_TEMPLATES_ENABLED':'true'}), \
            patch('httpx.post', side_effect=response), patch('httpx.AsyncClient.post',new=async_response), \
            patch('services.notifications.send_update_email',new_callable=AsyncMock) as email:
        yield packets, email


class DeliveryDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def close_both_windows(self):
        old = datetime.now(timezone.utc) - timedelta(hours=49)
        await self.pool.execute('INSERT INTO wa_sessions(parent_id,last_inbound_at,session_open) VALUES($1,$2,false) ON CONFLICT(parent_id) DO UPDATE SET last_inbound_at=$2,session_open=false',self.parent['id'],old)
        await self.pool.execute('INSERT INTO recipient_sessions(phone,last_inbound_at) VALUES($1,$2) ON CONFLICT(phone) DO UPDATE SET last_inbound_at=$2',self.owner['phone'],old)
        return old

    async def test_case1_both_silent_over_24h_still_send_daily_approved_templates(self):
        import whatsapp
        old = await self.close_both_windows()
        await self.schedule([{'time':'20:00','category':'dinner'}])
        with mock_meta_http() as (packets, email):
            for day in range(31):
                due = self.now + timedelta(days=day)
                await scheduler._deliver_parent(self.parent,due)
                await scheduler._deliver_parent(self.parent,due+timedelta(minutes=3))
                self.assertFalse(await whatsapp.is_session_open(self.parent['id']))
                self.assertFalse(await notifications.window_open(self.pool,self.owner['phone']))
            self.assertEqual(len(packets),31, 'One scheduled send per day despite no inbound replies')
            for packet in packets:
                payload = packet['payload']
                self.assertEqual(payload['to'],self.parent['phone'].lstrip('+'))
                self.assertEqual(payload['type'],'template')
                self.assertEqual(payload['template']['name'],'ayana_meal_en')
            email.assert_not_awaited()
        self.assertEqual(await self.pool.fetchval('SELECT last_inbound_at FROM wa_sessions WHERE parent_id=$1',self.parent['id']),old)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM reply_notifications WHERE recipient_id=$1',self.owner['id']),0,
                         'No parent reply means no invented child reply notification')

    async def test_case2_welcomes_parent_message_reply_and_child_delivery_outside_window(self):
        from routes.webhook import _process_meta_payload
        from services import receipts
        from monthly_report import _daily_details
        await self.close_both_windows()
        await self.pool.execute("INSERT INTO consent_logs(user_id,consent_type,agreed,text) VALUES($1,'child',true,'Test consent')", self.owner['id'])
        await self.schedule([{'time':'20:00','category':'lunch'}])
        from services.template_registry import catalog
        fixture = [{**r, 'status': 'APPROVED'} for r in json.loads((Path(__file__).resolve().parents[1] / 'docs/supplied_warning_welcome_templates.json').read_text(encoding='utf-8'))]
        with patch('services.template_registry.catalog', return_value=catalog() + fixture), mock_meta_http() as (packets, email):
            await welcomes.welcome_parent_and_child(self.parent,dict(self.owner),True)
            self.assertEqual(len(packets),2)
            self.assertEqual({p['payload']['to'] for p in packets},{self.parent['phone'].lstrip('+'),self.owner['phone'].lstrip('+')})
            for packet in packets:
                self.assertEqual(packet['payload']['type'],'template')
                is_child = packet['payload']['to'] == self.owner['phone'].lstrip('+')
                self.assertEqual(packet['payload']['template']['name'], 'ayana_child_welcome_en' if is_child else 'ayana_opener_en')
                self.assertEqual(len(packet['payload']['template']['components'][0]['parameters']), 1 if is_child else 2)
                await receipts.ingest({'id':packet['sid'],'status':'delivered'})
            # Re-entering activation must not repeat either welcome.
            await welcomes.welcome_parent_and_child(self.parent,dict(self.owner),True)
            self.assertEqual(len(packets),2)
            await scheduler._deliver_parent(self.parent,self.now)
            outbound = packets[-1]
            self.assertEqual(outbound['payload']['template']['name'],'ayana_meal_en')
            log = await self.pool.fetchrow('SELECT * FROM message_logs WHERE sid=$1',outbound['sid'])
            self.assertIsNotNone(log)
            await receipts.ingest({'id':outbound['sid'],'status':'delivered'})
            message = {'id':'wamid.reply.'+uuid.uuid4().hex,'from':self.parent['phone'].lstrip('+'),
                'timestamp':str(int(datetime.now(timezone.utc).timestamp())), 'type':'button',
                'context':{'id':outbound['sid']}, 'button':{'text':'Yes','payload':''}}
            webhook = {'entry':[{'changes':[{'value':{'messages':[message]}}]}]}
            await _process_meta_payload(webhook)
            await _process_meta_payload(webhook)
            child_updates = [p for p in packets if p['payload']['to']==self.owner['phone'].lstrip('+')
                and p['payload'].get('template',{}).get('name')=='ayana_parent_reply_en']
            self.assertEqual(len(child_updates),1, 'A retried inbound webhook must not duplicate the child update')
            child = child_updates[0]
            self.assertEqual(child['payload']['type'],'template')
            params = child['payload']['template']['components'][0]['parameters']
            self.assertEqual([p['text'] for p in params[:3]],['Amma','lunch','Yes'])
            self.assertFalse(await notifications.window_open(self.pool,self.owner['phone']),
                             'Parent reply must not open the child window')
            notification = await self.pool.fetchrow('SELECT * FROM reply_notifications WHERE sid=$1',child['sid'])
            self.assertEqual(notification['status'],'accepted')
            await receipts.ingest({'id':child['sid'],'status':'delivered'})
            self.assertEqual(await self.pool.fetchval('SELECT status FROM reply_notifications WHERE id=$1',notification['id']),'delivered')
            reply = await self.pool.fetchrow('SELECT * FROM parent_replies WHERE wam_id=$1',message['id'])
            self.assertEqual(reply['message_log_id'],log['id'])
            data = await timeline(self.owner['id'],period=self.now.strftime('%Y-%m'))
            displayed = next(m for d in data['parents'][0]['days'] for m in d['messages'] if m['id']==str(log['id']))
            self.assertEqual(displayed['reply']['body'],params[2]['text'])
            self.assertEqual(displayed['delivery_status'],'delivered')
            start = self.now.replace(day=1).date().isoformat()
            end = ((self.now.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)).date().isoformat()
            async with self.pool.acquire() as conn:
                report = await _daily_details(conn,self.parent['id'],start,end,'UTC')
            self.assertEqual(report['summary'],data['parents'][0]['summary'])
            email.assert_not_awaited()

    async def test_scheduler_preserves_shopping_location(self):
        await self.close_both_windows()
        await self.schedule([{'time':'20:00','category':'shopping_return','location_label':'Dmart'}])
        with mock_meta_http() as (packets, _):
            await scheduler._deliver_parent(self.parent, self.now)
        self.assertEqual(len(packets), 1)
        template = packets[0]['payload']['template']
        self.assertEqual(template['name'], 'ayana_shopping_return_en')
        self.assertEqual(template['components'][0]['parameters'][1]['text'], 'Dmart')

    async def test_full_month_schedule_with_submitted_templates_approved(self):
        from services.template_registry import catalog
        await self.close_both_windows()
        await self.schedule([
            {'time':'08:00','category':'morning_wish'},
            {'time':'13:00','category':'lunch'},
            {'time':'16:00','category':'walk_check'},
            {'time':'18:00','category':'outing_return','weekdays':[2]},
            {'time':'20:00','category':'goodnight'},
        ])
        fixture = [{**row, 'status':'APPROVED'} for row in json.loads((Path(__file__).resolve().parents[1] / 'docs/daily_template_drafts.json').read_text(encoding='utf-8'))]
        expected = []
        with patch('services.template_registry.catalog', return_value=catalog()+fixture), mock_meta_http() as (packets, _):
            for day in range(1,32):
                for hour, template in ((8,'morning_wish'),(13,'meal'),(16,'walk_check'),(18,'outing_return'),(20,'goodnight')):
                    due = (self.now+timedelta(days=day)).replace(hour=hour)
                    await scheduler._deliver_parent(self.parent,due)
                    await scheduler._deliver_parent(self.parent,due+timedelta(minutes=3))
                    if hour!=18 or due.weekday()==2:
                        expected.append(f'ayana_{template}_en')
        self.assertEqual([p['payload']['template']['name'] for p in packets], expected)

    async def test_midday_and_evening_warnings_are_once_per_recipient(self):
        import escalation
        from services.template_registry import catalog
        fixture = [{**r, 'status':'APPROVED'} for r in json.loads((Path(__file__).resolve().parents[1] / 'docs/supplied_warning_welcome_templates.json').read_text(encoding='utf-8'))]
        morning = self.now.replace(hour=8)
        await self.pool.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,delivery_status,created_at,delivered_at) VALUES($1,$2,$3,'breakfast','checkin','sent','delivered',$4,$4)",self.owner['id'],self.parent['id'],morning.date().isoformat(),morning)
        with patch('services.template_registry.catalog', return_value=catalog()+fixture), mock_meta_http() as (packets, _):
            for hour in (14,14,22,22):
                with patch('escalation.local_now', return_value=self.now.replace(hour=hour)):
                    await escalation._watch_parent(self.parent)
        self.assertEqual([p['payload']['template']['name'] for p in packets],
                         ['ayana_first_warn_parent_en','ayana_first_warn_child_en','ayana_main_warn_child_en'])
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM message_logs WHERE parent_id=$1 AND category='reengagement'",self.parent['id']),1)

    async def test_rejected_midday_nudge_does_not_claim_it_was_sent_to_child(self):
        import escalation
        morning = self.now.replace(hour=8)
        await self.pool.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,delivery_status,created_at,delivered_at) VALUES($1,$2,$3,'breakfast','checkin','sent','delivered',$4,$4)",self.owner['id'],self.parent['id'],morning.date().isoformat(),morning)
        with patch('escalation.local_now', return_value=self.now.replace(hour=14)), \
                patch('escalation._send_claimed', AsyncMock(return_value={'status':'failed'})), \
                patch('escalation._notify_family_warning', AsyncMock()) as child:
            await escalation._watch_parent(self.parent)
            child.assert_not_awaited()

    async def test_parent_reply_suppresses_no_reply_warnings(self):
        import escalation
        morning = self.now.replace(hour=8)
        await self.pool.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,delivery_status,created_at,delivered_at) VALUES($1,$2,$3,'breakfast','checkin','sent','delivered',$4,$4)",self.owner['id'],self.parent['id'],morning.date().isoformat(),morning)
        await self.pool.execute("INSERT INTO parent_replies(parent_id,body,created_at) VALUES($1,'Yes',$2)",self.parent['id'],morning+timedelta(minutes=5))
        with patch('escalation.local_now', return_value=self.now.replace(hour=14)), \
                patch('escalation._send_claimed', AsyncMock()) as send:
            await escalation._watch_parent(self.parent)
            send.assert_not_awaited()

    async def test_missing_walk_template_is_logged_and_next_day_is_independent(self):
        await self.close_both_windows()
        await self.schedule([{'time':'20:00','category':'walk_check'}])
        with mock_meta_http() as (packets, _):
            for day in range(2):
                await scheduler._deliver_parent(self.parent, self.now + timedelta(days=day))
        self.assertEqual(packets, [])
        logs = await self.pool.fetch('SELECT status,detail FROM message_logs WHERE parent_id=$1', self.parent['id'])
        self.assertEqual(len(logs), 2)
        for log in logs:
            self.assertEqual(log['status'], 'configuration_error')
            self.assertIn('ayana_walk_check_en', log['detail'])

    async def asyncSetUp(self):
        await database.init_db()
        self.pool = database.get_pool()
        from server import _run_startup_migrations
        await _run_startup_migrations()
        await apply_care_migration()
        self.owner = await self.pool.fetchrow("INSERT INTO users(name,email,phone,password_hash,email_verified_at) VALUES('Test owner',$1,'+12025550123','unused',now()) RETURNING *", f'{uuid.uuid4()}@example.test')
        self.now = datetime.now(timezone.utc).replace(hour=20,minute=0,second=0,microsecond=0)
        self.parent = dict(await self.pool.fetchrow("INSERT INTO parents(user_id,name,relationship,phone,timezone,created_at,activity_window_start,activity_window_end) VALUES($1,'Amma','mother','+919876543210','UTC',$2,NULL,NULL) RETURNING *", self.owner['id'], self.now-timedelta(days=1)))
        await self.pool.execute("INSERT INTO activation_state(user_id,whatsapp_activated,activated_at) VALUES($1,true,$2)", self.owner['id'], self.now-timedelta(minutes=10))
        self.entitlement = patch('services.billing_access.access', new_callable=AsyncMock, return_value={'allowed':True,'plan':'raksha'})
        self.entitlement.start()

    async def asyncTearDown(self):
        self.entitlement.stop()
        await self.pool.execute('DELETE FROM users WHERE id=$1', self.owner['id'])
        await database.close_db()

    async def schedule(self, items, since=None):
        return await self.pool.fetchrow("INSERT INTO schedules(user_id,parent_id,messages,created_at,effective_from) VALUES($1,$2,$3::jsonb,$4,$4) RETURNING *", self.owner['id'], self.parent['id'], json.dumps(items), since or self.now-timedelta(minutes=10))

    async def test_activation_and_repeated_ticks_do_not_backfill_or_duplicate(self):
        await self.schedule([{'time':'08:00','category':'morning_wish'}, {'time':'19:45','category':'lunch'}, {'time':'20:00','category':'goodnight'}])
        with patch('scheduler.send_dynamic_checkin', new_callable=AsyncMock, return_value={'status':'sent','sid':str(uuid.uuid4()),'body':'Good night'}) as send:
            await scheduler._deliver_parent(self.parent, self.now)
            await scheduler._deliver_parent(self.parent, self.now+timedelta(minutes=3))
            await scheduler._deliver_parent(self.parent, self.now+timedelta(minutes=15))
            send.assert_awaited_once()
            self.assertEqual(send.call_args.args[1], 'goodnight')
        logs = await self.pool.fetch('SELECT * FROM message_logs WHERE parent_id=$1', self.parent['id'])
        self.assertEqual(len(logs), 1)
        claim = await self.pool.fetchrow('SELECT * FROM care_send_claims WHERE parent_id=$1', self.parent['id'])
        self.assertEqual(claim['sid'], logs[0]['sid'])
        self.assertEqual(logs[0]['body'], 'Good night')

    async def test_concurrent_ticks_claim_only_once(self):
        await self.schedule([{'time':'20:00','category':'office_return'}])
        with patch('scheduler.send_dynamic_checkin', new_callable=AsyncMock, return_value={'status':'sent','sid':str(uuid.uuid4())}) as send:
            await asyncio.gather(scheduler._deliver_parent(self.parent,self.now), scheduler._deliver_parent(self.parent,self.now))
            send.assert_awaited_once()

    async def test_saved_schedule_never_sends_an_earlier_slot(self):
        await self.schedule([{'time':'20:00','category':'goodnight'}], self.now+timedelta(minutes=5))
        with patch('scheduler.send_dynamic_checkin', new_callable=AsyncMock) as send:
            await scheduler._deliver_parent(self.parent, self.now+timedelta(minutes=6))
            send.assert_not_called()

    async def test_uncertain_submission_does_not_flood_on_repeated_ticks(self):
        await self.schedule([{'time':'20:00','category':'goodnight'}])
        with patch('scheduler.send_dynamic_checkin',new_callable=AsyncMock,return_value={'status':'uncertain'}) as send:
            for minute in range(31):
                await scheduler._deliver_parent(self.parent,self.now+timedelta(minutes=minute))
            send.assert_awaited_once()

    async def test_rejected_submission_retries_are_bounded(self):
        await self.schedule([{'time':'20:00','category':'goodnight'}])
        with patch('scheduler.send_dynamic_checkin',new_callable=AsyncMock,return_value={'status':'failed','error_code':131000}) as send:
            for minute in range(31):
                await scheduler._deliver_parent(self.parent,self.now+timedelta(minutes=minute))
            self.assertEqual(send.await_count,3)

    async def test_delete_foreign_parent_cannot_disable_its_schedule(self):
        from fastapi import BackgroundTasks, HTTPException
        from routes.parents import delete_parent
        schedule = await self.schedule([{'time':'20:00','category':'goodnight'}])
        with self.assertRaises(HTTPException) as error:
            await delete_parent(str(self.parent['id']),BackgroundTasks(),user={'id':uuid.uuid4()})
        self.assertEqual(error.exception.status_code,404)
        self.assertIsNone(await self.pool.fetchval('SELECT deleted_at FROM parents WHERE id=$1',self.parent['id']))
        self.assertTrue(await self.pool.fetchval('SELECT active FROM schedules WHERE id=$1',schedule['id']))

    async def test_reading_timeline_never_removes_parent(self):
        for _ in range(3):
            result = await timeline(self.owner['id'])
            self.assertEqual(result['parents'][0]['parent_id'],str(self.parent['id']))
        self.assertIsNone(await self.pool.fetchval('SELECT deleted_at FROM parents WHERE id=$1',self.parent['id']))

    async def test_followups_only_once_for_medicine_and_safety(self):
        now = datetime.now(timezone.utc)
        items = [{'time':'08:00','category':c} for c in ('medicine','office_return','morning_wish','tea_check')]
        await self.schedule(items, now-timedelta(days=1))
        from services.schedule_source import load_schedule
        async with self.pool.acquire() as conn:
            _, expanded = await load_schedule(conn, self.parent, now)
        for item in expanded:
            key = event_key(self.parent['id'], now.date().isoformat(), item)
            await self.pool.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,delivery_status,created_at,delivered_at,event_key,sid,body) VALUES($1,$2,$3,$4,$5,'sent','delivered',$6,$6,$7,$8,'Original prompt')", self.owner['id'], self.parent['id'], now.date().isoformat(), item['category'], item['type'], now-timedelta(hours=2), key, str(uuid.uuid4()))
        with patch('services.care_followups.whatsapp_enabled', return_value=True), patch('services.care_followups.send_dynamic_checkin', new_callable=AsyncMock, side_effect=lambda *a,**kw: {'status':'sent','sid':str(uuid.uuid4())}) as send:
            for _ in range(4):
                await care_followups.drain()
                # Advance only the send-gap observation; claims remain intact.
                await self.pool.execute("UPDATE message_logs SET created_at=now()-interval '3 minutes' WHERE parent_id=$1 AND msg_type='followup'", self.parent['id'])
            self.assertEqual(send.await_count, 2)
            self.assertEqual({c.args[1] for c in send.call_args_list}, {'medicine','office_return'})

    async def test_exact_late_reply_and_month_summary(self):
        sid = str(uuid.uuid4())
        original = await self.pool.fetchrow("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,sid,created_at) VALUES($1,$2,$3,'medicine','reminder','sent',$4,$5) RETURNING *", self.owner['id'],self.parent['id'],self.now.date().isoformat(),sid,self.now-timedelta(hours=12))
        await self.pool.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,created_at) VALUES($1,$2,$3,'goodnight','checkin','sent',$4)", self.owner['id'],self.parent['id'],self.now.date().isoformat(),self.now)
        reply = await self.pool.fetchrow("INSERT INTO parent_replies(user_id,parent_id,from_phone,body,button_payload,intent,context_id,created_at) VALUES($1,$2,'+919876543210','Taken','template_button','done:medicine',$3,$4) RETURNING *", self.owner['id'],self.parent['id'],sid,self.now+timedelta(minutes=1))
        result = await timeline(self.owner['id'], period=self.now.strftime('%Y-%m'))
        data = result['parents'][0]
        self.assertEqual(data['summary']['replied'],1)
        self.assertEqual(data['summary']['medicine_taken'],1)
        self.assertEqual(data['days'][0]['messages'][0]['reply']['id'],str(reply['id']))
        self.assertFalse(data['days'][0]['messages'][1]['replied'])
        details = await notifications.reply_details(self.pool, reply['id'])
        self.assertEqual(details['prompt'],'medicine')
        self.assertEqual(details['body'],'Taken')

    async def test_changed_contact_has_a_new_single_welcome(self):
        owner = dict(self.owner)
        await welcomes.queue_child(owner)
        owner['contact_version'] = 1
        owner['phone'] = '+919876543211'
        await welcomes.queue_child(owner)
        await welcomes.queue_child(owner)
        rows = await self.pool.fetch('SELECT phone FROM welcome_deliveries WHERE recipient_id=$1', self.owner['id'])
        self.assertEqual(len(rows),2)
        self.assertIn(owner['phone'],[r['phone'] for r in rows])

    async def test_verified_child_welcome_uses_transaction_and_template_once(self):
        await self.pool.execute("INSERT INTO consent_logs(user_id,consent_type,agreed,text) VALUES($1,'child',true,'Test consent')", self.owner['id'])
        async with self.pool.acquire() as conn, conn.transaction():
            key = await welcomes.queue_child(dict(self.owner), 'Amma', conn=conn)
        with patch('services.welcomes.whatsapp_enabled',return_value=True), patch('services.welcomes._send_content_template_with_retry',new_callable=AsyncMock,return_value={'status':'sent','sid':str(uuid.uuid4())}) as send:
            first = await welcomes.deliver(key)
            await welcomes.deliver(key)
            send.assert_awaited_once()
            self.assertEqual(first['status'],'accepted')
            self.assertEqual(send.call_args.args[:4],(self.owner['phone'],'ayana_child_welcome_en','en',{'1':'Test'}))

    async def test_missing_welcome_recovery_requires_latest_consent_and_never_replays(self):
        await welcomes.recover_missing_child_welcomes()
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM welcome_deliveries WHERE recipient_id=$1',self.owner['id']),0)
        await self.pool.execute("INSERT INTO consent_logs(user_id,consent_type,agreed,text) VALUES($1,'child',true,'Test consent')", self.owner['id'])
        await welcomes.recover_missing_child_welcomes()
        await welcomes.recover_missing_child_welcomes()
        rows = await self.pool.fetch('SELECT * FROM welcome_deliveries WHERE recipient_id=$1',self.owner['id'])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['payload']['checking_for'],'Amma')
        await self.pool.execute("UPDATE welcome_deliveries SET status='uncertain' WHERE event_key=$1",rows[0]['event_key'])
        await welcomes.recover_missing_child_welcomes()
        self.assertEqual(await self.pool.fetchval('SELECT status FROM welcome_deliveries WHERE event_key=$1',rows[0]['event_key']),'uncertain')

    async def test_webhook_retry_forwards_once_and_records_same_reply(self):
        from routes.webhook import _record_reply
        sid, wam = str(uuid.uuid4()), str(uuid.uuid4())
        await self.pool.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,sid,created_at) VALUES($1,$2,$3,'lunch','checkin','sent',$4,now()-interval '5 hours')", self.owner['id'],self.parent['id'],datetime.now(timezone.utc).date().isoformat(),sid)
        with patch('services.notifications.send_update', new_callable=AsyncMock, return_value={'status':'sent','sid':str(uuid.uuid4())}) as send:
            first = await _record_reply(self.parent['phone'], 'Yes', parent=self.parent, button_payload='template_button', wam_id=wam, context_id=sid)
            duplicate = await _record_reply(self.parent['phone'], 'Yes', parent=self.parent, button_payload='template_button', wam_id=wam, context_id=sid)
            send.assert_awaited_once()
            self.assertTrue(duplicate['duplicate'])
            self.assertEqual(send.call_args.args[0],self.owner['phone'])
            self.assertFalse(send.call_args.args[2])
            self.assertEqual(send.call_args.args[1]['body'],first['body'])
            self.assertEqual(send.call_args.args[1]['prompt'],'lunch')
        self.assertEqual(await self.pool.fetchval('SELECT status FROM reply_notifications WHERE reply_id=$1',first['id']),'accepted')

    async def test_monthly_export_and_dashboard_use_same_counts(self):
        from monthly_report import _daily_details
        now = datetime.now(timezone.utc)
        await self.pool.execute("INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,delivery_status,created_at) VALUES($1,$2,$3,'medicine','followup','sent','delivered',$4)",self.owner['id'],self.parent['id'],now.date().isoformat(),now)
        dashboard = await timeline(self.owner['id'],period=now.strftime('%Y-%m'))
        start = now.replace(day=1).date().isoformat()
        end = ((now.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)).date().isoformat()
        async with self.pool.acquire() as conn:
            report = await _daily_details(conn,self.parent['id'],start,end,'UTC')
        self.assertEqual(report['summary'],dashboard['parents'][0]['summary'])


if __name__ == '__main__':
    unittest.main()
