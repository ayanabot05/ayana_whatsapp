"""Staff permissions and environment-driven password rotation, without network."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['DATABASE_URL'] = 'postgresql://ayana_test@127.0.0.1:55439/ayana_delivery_local'
os.environ['SUPABASE_DB_URL'] = os.environ['DATABASE_URL']
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fastapi import HTTPException
from starlette.requests import Request
import auth


class Connection:
    def __init__(self, rows=()):
        self.fetchrow = AsyncMock(side_effect=list(rows))
        self.execute = AsyncMock()
    def acquire(self): return self
    def transaction(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass


class StaffTests(unittest.IsolatedAsyncioTestCase):
    def test_support_only_reads_delivery_and_own_session(self):
        for method, path in [('GET','/api/admin/delivery-status'), ('GET','/api/auth/me'), ('POST','/api/auth/logout')]:
            auth.enforce_support_access({'role':'support'}, Request({'type':'http','method':method,'path':path,'headers':[]}))
        for method, path in [('GET','/api/admin/users'), ('GET','/api/dashboard/bootstrap'),
                ('DELETE','/api/parents/example'), ('POST','/api/admin/delivery-status')]:
            with self.assertRaises(HTTPException) as caught:
                auth.enforce_support_access({'role':'support'}, Request({'type':'http','method':method,'path':path,'headers':[]}))
            self.assertEqual(caught.exception.status_code,403)

    async def test_regular_user_cannot_access_worker_endpoint(self):
        with patch.object(auth,'get_current_user', AsyncMock(return_value={'role':'user'})):
            with self.assertRaises(HTTPException):
                await auth.get_delivery_viewer(None)

    async def test_staff_seed_hashes_env_passwords_and_separates_roles(self):
        conn = Connection([None,None])
        with patch.dict(os.environ, {'ADMIN_EMAIL':'admin@example.test', 'ADMIN_PASSWORD':'test-admin-only',
                'EMPLOYEE_EMAIL':'worker@example.test','EMPLOYEE_PASSWORD':'test-worker-only'}), patch.object(auth,'get_pool',return_value=conn):
            await auth.seed_admin()
        calls = conn.execute.call_args_list
        self.assertEqual(len(calls),2)
        for call, password, role in zip(calls, ['test-admin-only','test-worker-only'], ['admin','support']):
            args = call.args
            self.assertNotEqual(args[4],password)
            self.assertTrue(auth.verify_password(password,args[4]))
            self.assertEqual(args[5],role)

    async def test_env_rotation_revokes_old_sessions_and_second_start_does_not(self):
        old = {'password_hash': auth.hash_password('old-test-password'), 'role':'admin','deleted_at':None}
        conn = Connection([old])
        settings = {'ADMIN_EMAIL':'admin@example.test','ADMIN_PASSWORD':'new-test-password', 'EMPLOYEE_EMAIL':'','EMPLOYEE_PASSWORD':''}
        with patch.dict(os.environ,settings), patch.object(auth,'get_pool',return_value=conn):
            await auth.seed_admin()
            self.assertIn('auth_version=auth_version+1',conn.execute.call_args.args[0])
            saved = conn.execute.call_args.args[1]
            self.assertTrue(auth.verify_password(settings['ADMIN_PASSWORD'],saved))
            conn.execute.reset_mock()
            conn.fetchrow.side_effect = [{**old,'password_hash':saved}]
            await auth.seed_admin()
            conn.execute.assert_not_called()

    async def test_worker_cannot_be_admin_email(self):
        with patch.dict(os.environ, {'ADMIN_EMAIL':'same@example.test','ADMIN_PASSWORD':'test-password',
                'EMPLOYEE_EMAIL':'same@example.test','EMPLOYEE_PASSWORD':'test-password'}):
            with self.assertRaises(ValueError):
                await auth.seed_admin()


if __name__ == '__main__':
    unittest.main()
