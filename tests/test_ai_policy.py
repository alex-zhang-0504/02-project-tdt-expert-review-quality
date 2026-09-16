import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from tdt_scoring.ai_policy import load_policy, using_policy, policy_prompt
from tdt_scoring.experiment import call_deepseek, create_experiment_router
from tdt_scoring.models import OpinionFact
from tdt_scoring.service import ScoringService
from tests.test_experiment import LocalClient


class PolicyTests(unittest.TestCase):
    def test_snapshot_and_confirmed_cases_only(self):
        policy=load_policy()
        policy['data']['examples'].append(dict(id='draft',text='UNCONFIRMED_CASE',context='待讨论',expected='yes',reason='待讨论',confirmed=False))
        policy['data']['rules'].append('SNAPSHOT_RULE')
        opinion=OpinionFact('x','建议增加屏蔽罩。',[],[])
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'results':[{'id':'x','status':'yes','excerpt':opinion.text,'reason':'措施'}]})}}]}).encode()
        with patch('tdt_scoring.experiment.build_opener') as opener, using_policy(policy), patch('tdt_scoring.experiment.load_policy',side_effect=AssertionError('不应在同批次重读')):
            opener.return_value.open.return_value=response
            call_deepseek('fake-test-key','deepseek-flash',[opinion])
            payload=json.loads(opener.return_value.open.call_args.args[0].data)
            self.assertIn('SNAPSHOT_RULE',payload['messages'][0]['content'])
            self.assertNotIn('UNCONFIRMED_CASE',payload['messages'][0]['content'])

    def test_missing_invalid_and_changed_file_receipts(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'policy.json'
            with patch('tdt_scoring.ai_policy.POLICY_PATH',path):
                with self.assertRaisesRegex(ValueError,'文件不存在'): load_policy()
                path.write_text('{bad',encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'校验失败'): load_policy()
            source=load_policy()['data']
            with patch('tdt_scoring.ai_policy.POLICY_PATH',path):
                path.write_text(json.dumps(source),encoding='utf-8')
                first=load_policy()
                source['rules'].append('新增规则')
                path.write_text(json.dumps(source),encoding='utf-8')
                second=load_policy()
                self.assertNotEqual(first['receipt']['sha256'],second['receipt']['sha256'])
                self.assertNotIn('新增规则',policy_prompt(first))

    def test_visible_failure_receipt_and_no_network_fallback(self):
        app=FastAPI()
        app.include_router(create_experiment_router(ScoringService()))
        client=LocalClient(app)
        with patch('tdt_scoring.ai_policy.POLICY_PATH',Path('missing-policy-for-test.json')), patch('tdt_scoring.experiment.build_opener') as opener:
            result=client.post('/api/experiment/policy',headers={'X-Experiment-Request':'1'})
            self.assertEqual(422,result.status_code)
            self.assertFalse(result.json()['loaded'])
            with self.assertRaises(ValueError): call_deepseek('fake-test-key','deepseek-flash',[])
            opener.assert_not_called()
