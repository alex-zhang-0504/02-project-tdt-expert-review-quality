import time
import unittest
from threading import Event
from unittest.mock import patch

from fastapi import FastAPI

from tdt_scoring.experiment import create_experiment_router, ERROR_MESSAGES
from tdt_scoring.models import OpinionFact
from tdt_scoring.scoring import refresh
from tdt_scoring.service import ScoringService
from tdt_scoring.submission import build_dimension_one_workbook
from tests.test_experiment import LocalClient, simulated_call
from tests.workbook_factory import build_v04_workbook


class AIJobTests(unittest.TestCase):
    def setUp(self):
        self.service = ScoringService()
        self.analysis = self.service.import_local_bytes(build_v04_workbook([
            {"stage": "TDR1", "opinion": "建议增加屏蔽罩。"}]), "虚拟报告.xlsx")
        session = next(s for e in self.analysis.experts for s in e.sessions if s.opinions)
        for e in self.analysis.experts:
            for s in e.sessions:
                s.opinions = []
        self.opinions = [OpinionFact(str(i), f"建议调整参数{i}。", [], []) for i in range(13)]
        session.opinions = self.opinions
        refresh(self.analysis.experts)
        self.calls = []
        self.behavior = simulated_call
        def caller(key, model, opinions):
            if opinions[0].opinion_id != 'connection-test':
                self.calls.append(opinions[0].opinion_id)
            return self.behavior(key, model, opinions)
        app = FastAPI()
        app.include_router(create_experiment_router(self.service, caller))
        self.client = LocalClient(app)
        self.headers = {'X-Experiment-Request': '1'}
        result = self.post('settings', {'api_key': 'fake-test-key-only', 'model': 'deepseek-flash'})
        self.headers['X-Experiment-Session'] = result.json()['session']

    def post(self, path, body=None):
        return self.client.post('/api/experiment/' + path, headers=self.headers, json=body)

    def start(self):
        return self.post('jobs', {'analysis_id': self.analysis.analysis_id, 'confirmed': True})

    def finish(self, job):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = self.post('jobs/' + job).json()
            if result['status'] != 'running':
                return result
            time.sleep(.02)
        self.fail('任务未结束')

    def test_unverified_and_unconfirmed_rejected(self):
        self.assertEqual(409, self.start().status_code)
        self.assertEqual(400, self.post('jobs', {'analysis_id': self.analysis.analysis_id}).status_code)
        self.assertEqual([], self.calls)

    def test_missing_policy_blocks_job_before_model_call(self):
        self.post('test')
        with patch('tdt_scoring.ai_jobs.load_policy', side_effect=ValueError('未读取判定配置：文件不存在，分析已阻止。')):
            self.assertEqual(422,self.start().status_code)
        self.assertEqual([],self.calls)

    def test_changed_policy_requires_new_confirmation(self):
        self.post('test')
        response=self.post('jobs',{'analysis_id':self.analysis.analysis_id,'confirmed':True,'policy_hash':'old-hash'})
        self.assertEqual(409,response.status_code)
        self.assertEqual([],self.calls)

    def test_all_thirteen_written_once_and_no_repeat(self):
        self.post('test')
        job = self.start().json()['id']
        result = self.finish(job)
        self.assertEqual(('completed', 13, 0, 0), (result['status'], result['completed'], result['failed'], result['remaining']))
        self.assertEqual([str(i) for i in range(13)], self.calls)
        self.assertTrue(all(o.rule_version.startswith('countermeasure-policy-v0.1/sha256:') and o.rule_version.endswith('/deepseek-flash') for o in self.opinions))
        self.assertEqual(0, sum(e.overall['solutions'] for e in self.analysis.experts))
        self.assertEqual(13, sum(e.overall['suspected'] for e in self.analysis.experts))
        self.assertEqual(409, self.start().status_code)
        self.assertNotIn('fake-test-key-only', str(result))

    def test_invalid_item_does_not_block_others_and_retry_only_pending(self):
        self.post('test')
        def invalid(key, model, opinions):
            if opinions[0].opinion_id == '5':
                return {'wrong-id': {'status': 'yes', 'excerpt': 'invented', 'reason': 'secret'}}
            return simulated_call(key, model, opinions)
        self.behavior = invalid
        result = self.finish(self.start().json()['id'])
        self.assertEqual(('partial', 12, 1), (result['status'], result['completed'], result['failed']))
        self.assertEqual('pending', self.opinions[5].ai_status)
        self.assertNotIn('secret', self.opinions[5].reason)
        self.service.select_solution(self.analysis.analysis_id, '0', False)
        self.calls.clear(); self.behavior = simulated_call
        result = self.finish(self.start().json()['id'])
        self.assertEqual(['5'], self.calls)
        self.assertEqual(1, result['completed'])
        self.assertFalse(self.opinions[0].included)

    def test_duplicate_task_cancel_and_session_isolation(self):
        self.post('test')
        entered, release = Event(), Event()
        def blocked(*args):
            entered.set(); release.wait(5)
            return simulated_call(*args)
        self.behavior = blocked
        try:
            job = self.start().json()['id']
            self.assertTrue(entered.wait(2))
            self.assertEqual(job, self.start().json()['id'])
            stranger = self.client.post('/api/experiment/jobs/' + job, headers={'X-Experiment-Request': '1'})
            self.assertEqual(404, stranger.status_code)
            self.post('jobs/' + job + '/cancel')
        finally:
            release.set()
        result = self.finish(job)
        self.assertEqual(('cancelled', 0, 13), (result['status'], result['completed'], result['remaining']))
        self.assertEqual(['0'], self.calls)

    def test_auth_failure_stops_requests_without_marking_no(self):
        self.post('test')
        def denied(*args):
            raise ValueError(ERROR_MESSAGES[401])
        self.behavior = denied
        result = self.finish(self.start().json()['id'])
        self.assertEqual(('partial', 1, 12), (result['status'], result['failed'], result['remaining']))
        self.assertEqual(['0'], self.calls)
        self.assertTrue(all(o.ai_status == 'pending' for o in self.opinions))

    def test_active_task_survives_idle_expiry_and_disable_discards_response(self):
        self.post('test')
        entered, release = Event(), Event()
        def blocked(*args):
            entered.set(); release.wait(5)
            return simulated_call(*args)
        self.behavior = blocked
        try:
            job = self.start().json()['id']
            self.assertTrue(entered.wait(2))
            with patch('tdt_scoring.experiment.monotonic', return_value=float('inf')):
                self.assertEqual(job, self.start().json()['id'])
            self.post('disable')
        finally:
            release.set()
        result = self.finish(job)
        self.assertEqual('cancelled', result['status'])
        self.assertEqual(0, result['completed'])

    def test_transient_failure_retries_without_duplicate_count(self):
        self.post('test')
        def transient(key, model, opinions):
            if len(self.calls) == 1:
                raise ValueError(ERROR_MESSAGES[503])
            return simulated_call(key, model, opinions)
        self.behavior = transient
        result = self.finish(self.start().json()['id'])
        self.assertEqual(('completed', 13, 0), (result['status'], result['completed'], result['failed']))
        self.assertEqual(['0', '0', '1'], self.calls[:3])

    def test_definite_results_manual_override_and_reset(self):
        self.post('test')
        self.behavior = lambda key, model, opinions: {o.opinion_id: {'status': 'no', 'excerpt': '', 'reason': '只有问题'} for o in opinions}
        self.finish(self.start().json()['id'])
        self.service.select_solution(self.analysis.analysis_id, '0', True)
        self.assertEqual(1, sum(e.overall['solutions'] for e in self.analysis.experts))
        self.service.select_solution(self.analysis.analysis_id, '0', None)
        self.assertEqual(0, sum(e.overall['solutions'] for e in self.analysis.experts))
        self.assertIsNone(self.opinions[0].audit[-1]['to'])

    def test_real_fact_ids_and_model_version_export_roundtrip(self):
        self.analysis = self.service.import_local_bytes(build_v04_workbook([
            {'stage': 'TDR1', 'opinion': '建议增加屏蔽罩。'}]), '虚拟报告.xlsx')
        self.post('test'); self.finish(self.start().json()['id'])
        opinion = next(o for e in self.analysis.experts for s in e.sessions for o in s.opinions)
        self.service.select_solution(self.analysis.analysis_id, opinion.opinion_id, False)
        self.service.select_solution(self.analysis.analysis_id, opinion.opinion_id, None)
        content = build_dimension_one_workbook(self.analysis, package_kind='manager_submission', batch_id='2026',
            manager_id='PM01', manager_name='虚拟项目经理', product_version='v0.6', build_id='test')
        merged = self.service.merge_dimension_one_submissions([(content, 'submit.xlsx')], expected_manager_count=1)
        restored = next(o for e in merged.experts for s in e.sessions for o in s.opinions)
        self.assertEqual(opinion.rule_version, restored.rule_version)
        self.assertEqual(opinion.audit, restored.audit)
