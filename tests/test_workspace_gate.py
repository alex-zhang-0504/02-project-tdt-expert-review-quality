import asyncio
import unittest

from tdt_scoring.workspace import WorkspaceGate


class FakeWorkspace:
    def authorize(self, request):
        return {'employee_id': '0001', 'role': 'admin', 'personal_scope': False}


class WorkspaceGateLockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.slow, self.release = '', asyncio.Event()

        async def app(scope, receive, send):
            if scope['path'] == self.slow:
                await self.release.wait()
        self.gate = WorkspaceGate(app, FakeWorkspace())

    async def call(self, path):
        scope = {'type': 'http', 'method': 'POST', 'path': path, 'query_string': b'', 'root_path': '',
                 'headers': [(b'host', b'127.0.0.1:8865')], 'scheme': 'http',
                 'server': ('127.0.0.1', 8865), 'client': ('127.0.0.1', 1)}

        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}

        async def send(message):
            pass
        await self.gate(scope, receive, send)

    async def test_waiting_for_external_service_does_not_block_saves(self):
        for slow in ('/api/feishu/auth/complete', '/api/experiment/test', '/api/experiment/preview'):
            with self.subTest(slow=slow):
                self.slow = slow
                self.release.clear()
                pending = asyncio.create_task(self.call(slow))
                await asyncio.sleep(0)
                await asyncio.wait_for(self.call('/api/subjective/review'), 1)
                self.release.set()
                await pending

    async def test_ordinary_writes_remain_serialized(self):
        self.slow = '/api/workspace/tasks'
        first = asyncio.create_task(self.call(self.slow))
        await asyncio.sleep(0)
        second = asyncio.create_task(self.call('/api/subjective/review'))
        await asyncio.sleep(0.05)
        self.assertFalse(second.done())
        self.release.set()
        await asyncio.gather(first, second)
