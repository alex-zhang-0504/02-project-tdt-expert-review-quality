import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from tdt_scoring import scoring_policy, policy_admin
from tests.test_assessment import sample
from tdt_scoring.assessment import confirm_roster


class PolicyAdminTests(unittest.TestCase):
    def setUp(self):
        raw = scoring_policy.POLICY_PATH.read_bytes()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.policy = self.path / 'scoring-policy-v0.1.json'
        self.policy.write_bytes(raw)
        for target, value in [('tdt_scoring.scoring_policy.POLICY_PATH', self.policy),
                              ('tdt_scoring.policy_admin.ADMIN_PATH', self.path / 'admin.json')]:
            p = patch(target, value); p.start(); self.addCleanup(p.stop)
        self.app = self.new_app()
        self.password = 'virtual-test-password'
        self.token = ''

    def new_app(self):
        app = FastAPI(); app.include_router(policy_admin.create_policy_admin_router())
        return app

    def request(self, path, data=None, method='POST', headers=None, client='127.0.0.1'):
        async def run():
            h = {'host':'127.0.0.1:8895','x-policy-request':'1','x-policy-session':self.token,
                 'content-type':'application/json', **(headers or {})}
            scope = {'type':'http','http_version':'1.1','method':method,'scheme':'http',
                     'path':'/api/assessment/admin/'+path,'raw_path':b'', 'query_string':b'',
                     'headers':[(k.encode(),v.encode()) for k,v in h.items()],
                     'client':(client,12345),'server':('127.0.0.1',8895),'root_path':''}
            sent=[]
            async def receive(): return {'type':'http.request','body':json.dumps(data).encode(),'more_body':False}
            async def send(message): sent.append(message)
            await self.app(scope,receive,send)
            return sent[0]['status'],json.loads(b''.join(m.get('body',b'') for m in sent[1:]))
        return asyncio.run(run())

    def setup_admin(self):
        code, body = self.request('unlock',{'setup':True,'password':self.password,'confirmation':self.password})
        self.assertEqual(code,200)
        self.token=body['token']

    def update(self, parameters=None, previous=None):
        receipt=scoring_policy.load_policy()
        return self.request('policy',{'parameters':parameters or receipt['parameters'],
                            'previous_hash':previous or receipt['sha256']},method='PUT')

    def test_readonly_auth_origin_and_save_relocks_without_expiry(self):
        self.assertEqual(self.request('status',method='GET')[1], {'configured':False})
        self.assertEqual(self.update()[0],401)
        self.assertEqual(self.request('status',method='GET',headers={'origin':'https://foreign.test'})[0],403)
        self.assertEqual(self.request('status',method='GET',headers={'host':'foreign.test'})[0],403)
        self.assertEqual(self.request('status',method='GET',client='192.0.2.1')[0],403)
        self.assertEqual(self.request('status',method='GET',headers={'x-policy-request':''})[0],403)
        self.setup_admin()
        with patch('tdt_scoring.policy_admin.monotonic',return_value=10**20):
            self.assertEqual(self.update()[0],200)
        self.assertEqual(self.update()[0],401)

    def test_password_hash_persistence_and_relock(self):
        self.setup_admin()
        self.assertNotIn(self.password,(self.path/'admin.json').read_text())
        self.assertEqual(self.request('unlock',{'setup':True,'password':self.password,'confirmation':self.password})[0],409)
        self.app=self.new_app()
        self.assertEqual(self.update()[0],401)
        self.assertEqual(self.request('unlock',{'password':'invalid-password'})[0],403)
        code, result=self.request('unlock',{'password':self.password})
        self.assertEqual(code,200);self.token=result['token']
        self.assertEqual(self.update()[0],200)
        self.request('lock')
        self.assertEqual(self.update()[0],401)

    def test_parameter_validation_conflict_and_write_failure(self):
        self.setup_admin()
        original=scoring_policy.load_policy()
        invalid=deepcopy(original['parameters']);invalid['stage_weights']['TDR1']=0
        self.assertEqual(self.update(invalid)[0],400)
        self.assertEqual(self.update(previous='stale')[0],409)
        self.assertEqual(scoring_policy.load_policy()['sha256'],original['sha256'])
        with patch('tdt_scoring.policy_admin.atomic_write',side_effect=OSError('virtual denied')):
            self.assertEqual(self.update()[0],500)
        self.assertEqual(scoring_policy.load_policy()['sha256'],original['sha256'])

    def test_persisted_policy_and_existing_snapshot(self):
        analysis=sample()
        confirm_roster(analysis,[analysis.experts[0].expert_name],'virtual')
        original=deepcopy(analysis.assessment['policy'])
        self.setup_admin()
        new=deepcopy(original['parameters']);new['solution_points']=3
        code, result=self.update(new)
        self.assertEqual(code,200)
        self.assertEqual(result['sha256'],scoring_policy.load_policy()['sha256'])
        self.app=self.new_app()
        self.assertEqual(scoring_policy.load_policy()['parameters']['solution_points'],3)
        self.assertEqual(scoring_policy.snapshot(analysis),original)
        self.assertEqual(self.update(new,previous=original['sha256'])[0],401)

    def test_concurrent_writer_and_failed_attempt_limit(self):
        self.setup_admin()
        with policy_admin.file_lock(policy_admin.ADMIN_PATH.with_suffix('.lock')):
            self.assertEqual(self.update()[0],409)
        for _ in range(5):
            self.assertEqual(self.request('unlock',{'password':'wrong-password'})[0],403)
        self.assertEqual(self.request('unlock',{'password':self.password})[0],429)


if __name__=='__main__': unittest.main()
