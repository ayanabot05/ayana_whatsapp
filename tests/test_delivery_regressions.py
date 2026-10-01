"""Offline regression tests. No server startup, database connection or real sends."""
import os
import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

os.environ.update(SUPABASE_DB_URL='postgresql://test:test@127.0.0.1:1/ayana_test_local',
                  DATABASE_URL='postgresql://test:test@127.0.0.1:1/ayana_test_local',
                  WHATSAPP_ENABLED='false', FRONTEND_URL='https://example.test')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from services.template_registry import build
from services.reply_linking import linked_replies, build_parent_days
from services.notification_transport import send_update
import whatsapp


class TemplateTests(unittest.TestCase):
    def test_text_template_has_no_invented_buttons(self):
        for lang in ('en', 'te', 'hi'):
            payload, body = build(f'ayana_parent_reply_{lang}', lang, ['Amma', 'lunch', 'Yes', '1 PM'], 'ayana:reply:123')
            self.assertEqual([c['type'] for c in payload['components']], ['body'])
            self.assertIn('Yes', body)

    def test_voice_uses_actual_name_and_index(self):
        # Historical approved catalog fixture: live approval may change while
        # a replacement template is under review. Do not require live approval
        # for this payload-shape regression.
        import json
        snapshot = json.loads((Path(__file__).resolve().parents[1] / 'docs/meta_template_snapshot.json').read_text(encoding='utf-8'))
        with patch('services.template_registry.catalog', return_value=snapshot):
            self._assert_voice_shape()

    def _assert_voice_shape(self):
        for lang in ('en', 'te', 'hi'):
            payload, _ = build(f'ayana_parent_voice_{lang}', lang, ['Amma', 'lunch', '1 PM'], 'ayana:voice:123')
            self.assertEqual(payload['components'][1]['index'], '0')
            self.assertEqual(payload['components'][1]['parameters'][0]['payload'], 'ayana:voice:123')
            if lang == 'hi':
                self.assertEqual(payload['name'], '_ayana_parent_voice_hi')

    def test_registered_language_not_name_suffix(self):
        self.assertEqual(build('ayana_office_return_en', 'en', ['Amma'])[0]['language']['code'], 'en_IN')
        self.assertEqual(build('ayana_office_return_te', 'te', ['Amma'])[0]['language']['code'], 'en')

    def test_missing_or_wrong_shape_is_configuration_error(self):
        with self.assertRaises(ValueError):
            build('not_approved', 'en', [])
        with self.assertRaises(ValueError):
            build('ayana_parent_reply_en', 'en', ['Amma'])

    def test_international_phone_normalization(self):
        for source, expected in [('+1 (202) 555-0123','12025550123'),('+44 7700 900123','447700900123'),
                                 ('+971 50 123 4567','971501234567'),('+61 412 345 678','61412345678'),
                                 ('+31 6 12345678','31612345678'),('+91 98765 43210','919876543210')]:
            self.assertEqual(whatsapp._meta_phone(source), expected)


class ReplyTests(unittest.TestCase):
    def test_evening_reply_keeps_morning_context(self):
        logs = [dict(id='morning', parent_id='p', sid='wam-morning', category='breakfast', msg_type='checkin', status='sent', created_at=datetime(2026,9,29,8,tzinfo=timezone.utc)),
                dict(id='evening', parent_id='p', sid='wam-evening', category='dinner', msg_type='checkin', status='sent', created_at=datetime(2026,9,29,20,tzinfo=timezone.utc))]
        reply = dict(id='r', parent_id='p', context_id='wam-morning', body='Yes', created_at=datetime(2026,9,29,20,5,tzinfo=timezone.utc))
        linked, general = linked_replies(logs, [reply])
        self.assertEqual(list(linked), ['morning'])
        self.assertEqual(general, [])
        days = build_parent_days({'timezone':'UTC'}, logs, [reply])
        self.assertTrue(days[0]['messages'][0]['replied'])
        self.assertFalse(days[0]['messages'][1]['replied'])
        reply['context_id'] = None
        linked, general = linked_replies(logs, [reply])
        self.assertEqual(linked, {})
        self.assertEqual(len(general), 1)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_child_window_sends_template(self):
        reply = dict(id='r',parent_id='p',parent_name='Amma',prompt='lunch',display_time='1 PM',body='Yes',is_voice=False)
        with patch('services.notification_transport.whatsapp_enabled', return_value=True), patch('services.notification_transport.post_meta', new_callable=AsyncMock, return_value={'status':'sent','sid':'wam'}) as send:
            result = await send_update('+12025550123', reply, False)
            self.assertEqual(result['status'], 'sent')
            self.assertEqual(send.call_args.args[0]['type'], 'template')

    async def test_stale_child_window_immediately_uses_template(self):
        reply = dict(id='r',parent_id='p',parent_name='Amma',prompt='lunch',display_time='1 PM',body='Yes',is_voice=False)
        with patch('services.notification_transport.whatsapp_enabled', return_value=True), patch('services.notification_transport.post_meta', new_callable=AsyncMock, side_effect=[{'status':'failed','error_code':131047},{'status':'sent','sid':'wam'}]) as send:
            result = await send_update('+12025550123', reply, True)
            self.assertEqual(result['status'], 'sent')
            self.assertEqual([c.args[0]['type'] for c in send.call_args_list], ['text','template'])

    async def test_uncertain_child_submission_is_not_duplicated(self):
        reply = dict(id='r',parent_id='p',parent_name='Amma',prompt='lunch',display_time='1 PM',body='Yes',is_voice=False)
        with patch('services.notification_transport.whatsapp_enabled', return_value=True), patch('services.notification_transport.post_meta', new_callable=AsyncMock, return_value={'status':'uncertain'}) as send:
            await send_update('+12025550123', reply, True)
            self.assertEqual(send.call_count, 1)

    async def test_parent_window_rejection_falls_back_once(self):
        parent = dict(id='p',phone='+919876543210',name='Amma',language='en')
        pool = AsyncMock()
        with patch('whatsapp.is_session_open', new_callable=AsyncMock, return_value=True), patch('whatsapp.render_slot_body_async', new_callable=AsyncMock, return_value='How are you?'), patch('whatsapp.render_slot_buttons', return_value=[]), patch('whatsapp._send_quick_reply', new_callable=AsyncMock, return_value={'status':'failed','error_code':131047}), patch('whatsapp.get_pool', return_value=pool), patch('whatsapp._send_content_template_with_retry', new_callable=AsyncMock, return_value={'status':'sent','sid':'wam'}) as template, patch('whatsapp.mark_opener_sent', new_callable=AsyncMock):
            result = await whatsapp.send_dynamic_checkin(parent, 'goodnight', 1, 3)
            self.assertEqual(result['status'], 'sent')
            template.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
