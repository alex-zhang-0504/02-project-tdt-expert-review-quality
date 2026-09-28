import asyncio
from http.cookies import SimpleCookie
import json
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from tdt_scoring import policy_admin
from tdt_scoring.service import ScoringService
from tdt_scoring.storage import WorkspaceStore
from tdt_scoring.workspace import Workspace, WorkspaceGate, create_workspace_router


class PasswordChangeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        p = patch.object(policy_admin, 'ADMIN_PATH', Path(folder.name) / 'admin.json')
        p.start(); self.addCleanup(p.stop)
        policy_admin._login_failures.clear()
        self.addCleanup(policy_admin._login_failures.clear)
        self.store = WorkspaceStore(Path(folder.name) / 'workspace')
        self.workspace = Workspace(ScoringService(store=self.store), self.store)
        self.app = FastAPI()
        self.app.add_middleware(WorkspaceGate, workspace=self.workspace)
        self.app.include_router(create_workspace_router(self.workspace, lambda a: {}, lambda: False))
        self.app.include_router(policy_admin.create_policy_admin_router())
        self.cookies = {}
        self.old, self.new = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
        self.assertEqual(200, self.request('/api/workspace/bootstrap', {
            'name': '虚拟管理员', 'employee_id': '0001', 'password': self.old, 'confirmation': self.old})[0])

    def request(self, path, data=None, method='POST', cookies=None, headers=None):
        async def run():
            h = {'host': '127.0.0.1:8899', 'content-type': 'application/json',
                 'cookie': '; '.join(k+'='+v for k,v in (self.cookies if cookies is None else cookies).items()), **(headers or {})}
            scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'}, 'http_version': '1.1',
                     'method': method, 'scheme': 'http', 'path': path, 'query_string': b'', 'root_path': '',
                     'headers': [(k.encode(), v.encode()) for k,v in h.items()],
                     'client': ('127.0.0.1', 12345), 'server': ('127.0.0.1', 8899)}
            sent = []
            async def receive(): return {'type': 'http.request', 'body': json.dumps(data).encode(), 'more_body': False}
            async def send(message): sent.append(message)
            await self.app(scope, receive, send)
            for name,value in sent[0].get('headers', []):
                if name == b'set-cookie':
                    parsed = SimpleCookie(); parsed.load(value.decode())
                    self.cookies.update({k: v.value for k,v in parsed.items()})
            return sent[0]['status'], json.loads(b''.join(m.get('body', b'') for m in sent))
        return asyncio.run(run())

    def payload(self):
        return {'password': self.old, 'new_password': self.new, 'confirmation': self.new}

    def test_change_revokes_sessions_and_policy_unlock_and_persists(self):
        stale = dict(self.cookies)
        status, result = self.request('/api/assessment/admin/unlock', {'password': self.old}, headers={'x-policy-request': '1'})
        self.assertEqual(200, status)
        token = result['token']
        before = self.store.accounts_path.read_bytes()
        self.assertEqual(200, self.request('/api/workspace/password', self.payload())[0])
        self.assertEqual(before, self.store.accounts_path.read_bytes())
        self.assertIsNone(self.request('/api/workspace/session', method='GET', cookies=stale)[1]['user'])
        self.assertEqual(401, self.request('/api/workspace/analyses', method='GET', cookies=stale)[0])
        self.assertEqual(403, self.request('/api/workspace/login', {'employee_id': '0001', 'password': self.old})[0])
        self.assertEqual(200, self.request('/api/workspace/login', {'employee_id': '0001', 'password': self.new})[0])
        self.assertEqual(401, self.request('/api/assessment/admin/policy/objective', {}, method='PUT',
            headers={'x-policy-request': '1', 'x-policy-session': token})[0])
        self.assertNotIn(self.new.encode(), policy_admin.ADMIN_PATH.read_bytes())
        policy_admin.workspace_password({'password': self.new})

    def test_invalid_changes_leave_credential_and_session_unchanged(self):
        original = policy_admin.ADMIN_PATH.read_bytes()
        for payload, status in [({**self.payload(), 'password': secrets.token_urlsafe(16)}, 403),
                                ({**self.payload(), 'confirmation': 'different'}, 400),
                                ({**self.payload(), 'new_password': 'short', 'confirmation': 'short'}, 400),
                                ({'password': self.old, 'new_password': self.old, 'confirmation': self.old}, 400)]:
            self.assertEqual(status, self.request('/api/workspace/password', payload)[0])
            self.assertEqual(original, policy_admin.ADMIN_PATH.read_bytes())
        self.assertEqual(403, self.request('/api/workspace/password', self.payload(), headers={'origin': 'https://foreign.test'})[0])
        with patch.object(policy_admin, 'atomic_write', side_effect=OSError):
            self.assertEqual(500, self.request('/api/workspace/password', self.payload())[0])
        self.assertEqual(original, policy_admin.ADMIN_PATH.read_bytes())
        self.assertEqual(200, self.request('/api/workspace/analyses', method='GET')[0])
        self.store.add_user('1001', '虚拟项目经理')
        self.assertEqual(403, self.request('/api/workspace/password', self.payload(), cookies={'tdt_workspace_user': '1001'})[0])

    def test_login_page_change_requires_existing_password_without_session(self):
        original = policy_admin.ADMIN_PATH.read_bytes()
        wrong = {**self.payload(), 'password': secrets.token_urlsafe(16)}
        self.assertEqual(403, self.request('/api/workspace/password', wrong, cookies={})[0])
        self.assertEqual(original, policy_admin.ADMIN_PATH.read_bytes())
        self.assertEqual(403, self.request('/api/workspace/password', self.payload(), cookies={},
            headers={'origin': 'https://foreign.test'})[0])
        self.assertEqual(200, self.request('/api/workspace/password', self.payload(), cookies={})[0])
        self.assertIsNone(self.request('/api/workspace/session', method='GET')[1]['user'])
        self.assertEqual(200, self.request('/api/workspace/login', {'employee_id': '0001', 'password': self.new})[0])


if __name__ == '__main__':
    unittest.main()
