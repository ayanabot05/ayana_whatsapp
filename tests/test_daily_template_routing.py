"""Offline message-content checks. No real WhatsApp or database calls."""
import os
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.update(PYTHON_DOTENV_DISABLED='1', WHATSAPP_ENABLED='false',
                  DATABASE_URL='postgresql://test:test@127.0.0.1:1/test',
                  SUPABASE_DB_URL='postgresql://test:test@127.0.0.1:1/test')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import httpx
import whatsapp
from templates_data import get_template_sid_key


class DailyRoutingTests(unittest.IsolatedAsyncioTestCase):
    parent = dict(id='p', phone='+919876543210', name='Amma', language='en')

    async def test_pending_templates_are_never_treated_as_approved(self):
        from services.template_registry import definition
        with patch('services.template_registry.catalog', return_value=[{
            'name':'ayana_morning_wish_en', 'status':'PENDING', 'language':'en'}]):
            with self.assertRaises(ValueError):
                definition('ayana_morning_wish_en', 'en')

    async def test_catalog_reload_after_sync(self):
        import tempfile
        from types import SimpleNamespace
        from services import template_registry
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'approved_templates.json'
            path.write_text('[]', encoding='utf-8')
            with patch('services.template_registry.Path', return_value=SimpleNamespace(parents=[None, Path(directory)])):
                self.assertEqual(template_registry.catalog(), [])
                temporary = path.with_suffix('.tmp')
                temporary.write_text('[{"name":"new-template"}]', encoding='utf-8')
                temporary.replace(path)
                self.assertEqual(template_registry.catalog(), [{'name':'new-template'}])

    async def test_warning_names_and_parameter_counts(self):
        definitions = json.loads((Path(__file__).resolve().parents[1] / 'docs/supplied_warning_welcome_templates.json').read_text(encoding='utf-8'))
        # Explicit hypothetical catalog, not a claim about live Meta approval.
        with patch('services.template_registry.catalog', return_value=[{**row, 'status':'APPROVED'} for row in definitions]):
            for lang in ('en', 'te', 'hi'):
                for kind, sender, extra in (
                    ('first_warn_child', whatsapp.send_first_warning_to_child, []),
                    ('main_warn_child', whatsapp.send_main_warning_to_child, [4]),
                    ('first_warn_parent', whatsapp.send_first_warning_to_parent, []),
                ):
                    result = await sender(self.parent['phone'], lang, 'Amma', *extra)
                    self.assertEqual(result['template_name'], f'ayana_{kind}_{lang}')
                    self.assertEqual(result['vars'], {'1':'Amma', '2':'4'} if extra else {'1':'Amma'})

    async def test_dedicated_payloads_when_matching_templates_are_approved(self):
        # Hypothetical approval fixture only; production catalog remains unchanged.
        drafts = json.loads((Path(__file__).resolve().parents[1] / 'docs/daily_template_drafts.json').read_text(encoding='utf-8'))
        approved = [{**row, 'status': 'APPROVED'} for row in drafts]
        response = httpx.Response(200, json={'messages': [{'id': 'wam-test'}]},
                                  request=httpx.Request('POST', 'https://example.test'))
        with patch('services.template_registry.catalog', return_value=approved), \
                patch('whatsapp.whatsapp_enabled', return_value=True), \
                patch('whatsapp._creds', return_value=('test-token', 'test-id')), \
                patch('whatsapp.is_session_open', AsyncMock(return_value=False)), \
                patch('whatsapp.mark_opener_sent', AsyncMock()), \
                patch('whatsapp.httpx.post', return_value=response) as post:
            for row in approved:
                category = row['name'][6:].rsplit('_', 1)[0]
                result = await whatsapp.send_dynamic_checkin(
                    {**self.parent, 'language': row['language'], 'child_name':'Naveen'}, category, 1, 3)
                self.assertEqual(result['status'], 'sent')
                self.assertEqual(result['body'], row['components'][0]['text'].replace('{{1}}', 'Amma').replace('{{2}}', 'Naveen'))
                self.assertEqual(post.call_args.kwargs['json']['template']['name'], row['name'])

    async def test_submitted_button_titles_keep_category_and_unwell_meaning(self):
        from services.button_intents import exact_button_intent
        for category, title, expected in (
            ('walk_check', 'Walked 🚶', 'done:walk_check'),
            ('walk_check', 'నడిచాను 🚶', 'done:walk_check'),
            ('tea_check', 'पी ली ☕', 'done:tea_check'),
            ('water', 'Will drink now', 'pending:water'),
            ('bp_check', 'Feeling unwell 😟', 'feeling:not_well'),
            ('sugar_check', 'చెక్ చేశాను ✅', 'done:sugar_check'),
            ('health_check', 'मदद चाहिए 🆘', 'emergency:help'),
            ('afternoon_checkin', 'Resting 😴', 'feeling:okay'),
            ('goodnight', 'Not feeling well 😟', 'feeling:not_well'),
        ):
            self.assertEqual(exact_button_intent({'category':category}, '', title), expected)
        self.assertEqual(exact_button_intent(None, '', 'Walked 🚶'), 'text')

    async def test_love_note_uses_owner_name(self):
        pool = AsyncMock()
        pool.fetchval.return_value = 'Naveen'
        with patch('whatsapp.get_pool', return_value=pool), \
                patch('whatsapp.is_session_open', AsyncMock(return_value=False)), \
                patch('whatsapp._send_content_template_with_retry', AsyncMock(return_value={'status':'sent'})) as send, \
                patch('whatsapp.mark_opener_sent', AsyncMock()):
            await whatsapp.send_dynamic_checkin({**self.parent, 'user_id':'owner'}, 'love_note', 1, 3)
            self.assertEqual(send.call_args.args[3], {'1':'Amma','2':'Naveen'})

    async def test_monthly_notifier_sends_once_without_upload_or_document(self):
        import monthly_report
        conn = AsyncMock()
        conn.fetchrow.return_value = dict(id='p',user_id='owner',preferred_name='Amma', name='Mother', language='en')
        with patch('services.family_delivery.enqueue', AsyncMock()) as send, \
                patch('whatsapp.upload_media_to_whatsapp', AsyncMock()) as upload, \
                patch('whatsapp.upload_media_and_send_document', AsyncMock()) as document:
            await monthly_report._notify_report_ready(conn, 'owner', 'p', '2026-09', False, pdf_bytes=b'pdf')
            send.assert_awaited_once_with(conn,conn.fetchrow.return_value,'report','2026-09',{'name':'Amma','period':'2026-09'})
            upload.assert_not_awaited()
            document.assert_not_awaited()

    async def test_missing_daily_approvals_never_send_unrelated_content(self):
        for category in ('morning_wish', 'walk_check', 'tea_check', 'water',
                         'bp_check', 'sugar_check', 'health_check',
                         'afternoon_checkin', 'goodnight', 'love_note'):
            with self.subTest(category=category), \
                    patch('whatsapp.is_session_open', AsyncMock(return_value=False)), \
                    patch('whatsapp.httpx.post') as post:
                result = await whatsapp.send_dynamic_checkin(self.parent, category, 1, 3)
                self.assertEqual(result['status'], 'configuration_error')
                self.assertIn(f'ayana_{category}_en', result['detail'])
                post.assert_not_called()

    async def test_approved_meals_and_mood_still_send(self):
        for category, template in [('breakfast', 'meal'), ('lunch', 'meal'),
                                   ('dinner', 'meal'), ('how_feeling', 'mood')]:
            self.assertEqual(get_template_sid_key(category), template)
            with patch('whatsapp.is_session_open', AsyncMock(return_value=False)), \
                    patch('whatsapp.mark_opener_sent', AsyncMock()):
                result = await whatsapp.send_dynamic_checkin(self.parent, category, 1, 3)
                self.assertEqual(result['status'], 'simulated')
                self.assertEqual(result['template_name'], f'ayana_{template}_en')

    async def test_open_window_keeps_daily_conversation(self):
        with patch('whatsapp.is_session_open', AsyncMock(return_value=True)), \
                patch('whatsapp._send_quick_reply', AsyncMock(return_value={'status': 'sent'})) as send:
            await whatsapp.send_dynamic_checkin(self.parent, 'walk_check', 1, 3)
            self.assertIn('walk', send.call_args.args[1])
            self.assertNotIn('eaten', send.call_args.args[1])

    async def test_shopping_label_both_windows_and_window_rejection(self):
        for language in ('en', 'te', 'hi'):
            parent = {**self.parent, 'language': language}
            with patch('whatsapp.is_session_open', AsyncMock(return_value=False)):
                result = await whatsapp.send_dynamic_checkin(parent, 'shopping_return', 1, 3,
                                                             medicine_name='DO NOT USE', location_label='Dmart')
                self.assertEqual(result['vars'], {'1': 'Amma', '2': 'Dmart'})
            with patch('whatsapp.is_session_open', AsyncMock(return_value=True)), \
                    patch('whatsapp._send_quick_reply', AsyncMock(return_value={'status': 'failed', 'error_code': 131047})) as send, \
                    patch('whatsapp.get_pool', return_value=AsyncMock()):
                result = await whatsapp.send_dynamic_checkin(parent, 'shopping_return', 1, 3, location_label='Dmart')
                self.assertIn('Dmart', send.call_args.args[1])
                self.assertEqual(result['vars']['2'], 'Dmart')

    async def test_report_payload_matches_text_header_even_with_pdf_arguments(self):
        for lang in ('en', 'te', 'hi'):
            response = httpx.Response(200, json={'messages': [{'id': 'wam-test'}]},
                                      request=httpx.Request('POST', 'https://example.test'))
            with patch('whatsapp.whatsapp_enabled', return_value=True), \
                    patch('whatsapp._creds', return_value=('test-token', 'test-id')), \
                    patch('whatsapp.httpx.post', return_value=response) as post:
                result = await whatsapp.send_report_ready_with_pdf_template(
                    self.parent['phone'], lang, 'Amma', pdf_url='https://example.test/report.pdf')
                self.assertEqual(result['status'], 'sent')
                self.assertFalse(result['pdf_attached'])
                self.assertEqual(result['report_delivery'], 'dashboard')
                post.assert_called_once()
                template = post.call_args.kwargs['json']['template']
                self.assertEqual(template['name'], f'ayana_report_ready_{lang}')
                self.assertEqual([c['type'] for c in template['components']], ['body'])


if __name__ == '__main__':
    unittest.main()
