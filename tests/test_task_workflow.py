from copy import deepcopy
import json
from pathlib import Path
import secrets
import unittest
from unittest.mock import patch

from tests import test_workspace
from tdt_scoring import questionnaire, scoring_policy, policy_admin
from tdt_scoring.task_workflow import create_task_router, policy_receipt, started
from tdt_scoring.service import ScoringService
from tdt_scoring.storage import WorkspaceStore


class TaskWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.h = test_workspace.WorkspaceTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.app = self.h.app
        self.app.include_router(create_task_router(self.h.workspace, self.h.encode, lambda: False))
        self.folder = Path(self.h.temp.name)
        for module, attr, name in [(questionnaire, 'POLICY_PATH', 'subjective.json'), (scoring_policy, 'POLICY_PATH', 'objective.json')]:
            path = self.folder / name
            path.write_bytes(getattr(module, attr).read_bytes())
            p = patch.object(module, attr, path); p.start(); self.addCleanup(p.stop)
        p = patch.object(policy_admin, 'ADMIN_PATH', self.folder / 'admin.json'); p.start(); self.addCleanup(p.stop)
        self.url = '/api/workspace/tasks/' + self.h.id

    def update(self, kind, change):
        code, receipt = self.h.request(self.url + '/policy/' + kind)
        self.assertEqual(200, code)
        params = deepcopy(receipt['parameters'])
        if kind == 'objective':
            params = {k:v for k,v in params.items() if k in {'stage_weights','components','participation','opinion_threshold','excess_opinion_points','solution_points'}}
        change(params)
        return self.h.request(self.url + '/policy/' + kind, {**receipt, 'parameters': params}, 'PUT')

    def fill(self):
        for mid in ('a', 'b'):
            self.assertEqual(200, self.h.save(self.h.payload(mid), '0001')[0])

    def test_independent_config_recompute_preserve_answers_and_restart(self):
        self.fill()
        before = deepcopy(self.h.analysis.manager_reviews)
        original = scoring_policy.POLICY_PATH.read_bytes()
        code, receipt = self.update('subjective', lambda p: p['scores']['preparation'].update(high=9))
        self.assertEqual(200, code, receipt)
        self.assertEqual(original, scoring_policy.POLICY_PATH.read_bytes())
        for mid in ('a', 'b'):
            self.assertEqual(before[mid][self.h.name]['ratings'], self.h.analysis.manager_reviews[mid][self.h.name]['ratings'])
            self.assertEqual(receipt['sha256'], self.h.analysis.manager_reviews[mid][self.h.name]['questionnaire_hash'])
        from tdt_scoring.score_statistics import build_statistics
        self.assertEqual(59, build_statistics(self.h.analysis)['rows'][0]['subjective_total'])
        from io import BytesIO
        from openpyxl import load_workbook
        from tdt_scoring.score_statistics import build_statistics_workbook
        wb = load_workbook(BytesIO(build_statistics_workbook(self.h.analysis, dimension='subjective')), data_only=True)
        self.assertEqual(59, wb['主观打分']['H2'].value)
        q = questionnaire.POLICY_PATH.read_bytes()
        self.assertEqual(200, self.update('objective', lambda p: p.update(solution_points=3))[0])
        self.assertEqual(q, questionnaire.POLICY_PATH.read_bytes())
        restarted = ScoringService(store=WorkspaceStore(self.folder)).get_analysis(self.h.id)
        self.assertEqual(self.h.analysis.manager_reviews, restarted.manager_reviews)
        self.assertEqual(self.h.analysis.assessment['policy'], restarted.assessment['policy'])

    def test_first_save_locks_semantics_even_after_clearing(self):
        self.assertFalse(started(self.h.analysis))
        self.assertEqual(200, self.update('subjective', lambda p: p['dimensions'][0].update(title='虚拟准备要求'))[0])
        self.h.save(user='0001')
        payload = self.h.payload(revision=1); payload['ratings'] = {}
        self.h.save(payload, '0001')
        self.assertTrue(started(self.h.analysis))
        self.assertEqual(400, self.update('subjective', lambda p: p['dimensions'][0].update(title='变更题意'))[0])
        self.assertEqual(400, self.update('subjective', lambda p: p['evidence'].update(preparation=['high']))[0])

    def test_completion_gate_snapshot_and_backend_readonly(self):
        self.assertEqual(400, self.h.request(self.url+'/complete', {'confirmed':True}, 'POST')[0])
        self.fill()
        self.assertEqual(400, self.h.request(self.url+'/complete', {}, 'POST')[0])
        self.assertEqual(200, self.h.request(self.url+'/complete', {'confirmed':True}, 'POST')[0])
        frozen = deepcopy(self.h.analysis.assessment['completion'])
        self.assertEqual(400, self.h.request(self.url+'/scope', {}, 'POST')[0])
        self.assertEqual(400, self.h.request('/api/workspace/finalize', {'analysis_id':self.h.id,'reopen':True}, 'POST')[0])
        self.assertEqual(200, self.h.request(self.url+'/history')[0])
        self.assertEqual(frozen, self.h.analysis.assessment['completion'])
        with self.assertRaises(ValueError):
            with self.h.service.edit_analysis(self.h.id): pass

    def test_failed_database_write_restores_config_and_memory(self):
        old = questionnaire.POLICY_PATH.read_bytes()
        before = deepcopy(self.h.analysis.assessment)
        with patch.object(self.h.store, 'save', side_effect=OSError('virtual disk failure')):
            with self.assertRaises(OSError): self.update('subjective', lambda p: p['scores']['preparation'].update(high=8))
        self.assertEqual(old, questionnaire.POLICY_PATH.read_bytes())
        self.assertEqual(before, self.h.analysis.assessment)

    def test_create_import_new_default_and_delete_confirmation(self):
        config = {'version':1,'users':self.h.store.users(include_disabled=True)}
        data = {'year':'2027','period':'上半年','accounts':config}
        code, a = self.h.request('/api/workspace/tasks', data, 'POST')
        self.assertEqual(200, code, a)
        self.assertEqual(400, self.h.request('/api/workspace/tasks', data, 'POST')[0])
        aid = a['analysis_id']; path = '/api/workspace/tasks/'+aid
        self.assertEqual(400, self.h.request(path, {'confirmed':True,'name':'错误任务'}, 'DELETE')[0])
        self.assertEqual(200, self.h.request(path, {'confirmed':True,'name':a['source_name']}, 'DELETE')[0])
        self.assertNotIn(aid, [r['id'] for r in self.h.request('/api/workspace/analyses')[1]])
        with self.assertRaises(KeyError): self.h.service.get_analysis(aid)

    def test_manager_rejected_and_stale_parameter_write(self):
        self.assertEqual(403, self.h.request(self.url+'/policy/objective', user='a')[0])
        _, old = self.h.request(self.url+'/policy/subjective')
        self.assertEqual(200, self.update('subjective', lambda p: p['scores']['preparation'].update(high=9))[0])
        self.assertEqual(409, self.h.request(self.url+'/policy/subjective', old, 'PUT')[0])

    def test_other_tasks_keep_their_snapshot_and_new_tasks_read_saved_defaults(self):
        data = {'year':'2028','period':'上半年','accounts':{'version':1,'users':self.h.store.users(include_disabled=True)}}
        _, prior = self.h.request('/api/workspace/tasks', data, 'POST')
        self.fill()
        self.assertEqual(200, self.update('subjective', lambda p:p['scores']['preparation'].update(high=9))[0])
        existing = self.h.service.get_analysis(prior['analysis_id'])
        self.assertEqual(prior['assessment']['questionnaire'], existing.assessment['questionnaire'])
        _, fresh = self.h.request('/api/workspace/tasks', {**data,'period':'下半年'}, 'POST')
        self.assertEqual(9, fresh['assessment']['questionnaire']['parameters']['scores']['preparation']['high'])

    def test_failed_create_preserves_accounts_and_does_not_leave_task(self):
        original = self.h.store.accounts_path.read_bytes()
        users = self.h.store.users(include_disabled=True)
        users.append({'employee_id':'virtual-new','name':'虚拟新增项目经理','role':'manager','enabled':True,'owner_ids':[]})
        ids = set(self.h.service._analyses)
        with patch.object(self.h.store, 'save', side_effect=OSError('virtual disk failure')):
            with self.assertRaises(OSError):
                self.h.request('/api/workspace/tasks', {'year':'2028','period':'年度','accounts':{'version':1,'users':users}}, 'POST')
        self.assertEqual(original, self.h.store.accounts_path.read_bytes())
        self.assertEqual(ids, set(self.h.service._analyses))

    def test_reimport_is_atomic_and_preserves_questionnaires_and_policy(self):
        from tests.workbook_factory import build_v04_workbook
        imported = self.h.service.import_local_bytes(build_v04_workbook([{'stage':'TDR2','problems':[]}]), 'virtual-new.xlsx')
        before = deepcopy(self.h.analysis)
        original_save = self.h.store.save
        def failing_save(a, revision, connection=None):
            if a.analysis_id == imported.analysis_id: raise OSError('virtual disk failure')
            return original_save(a, revision, connection)
        with patch.object(self.h.store, 'save', side_effect=failing_save):
            with self.assertRaises(OSError): self.h.request(self.url+'/reports', {'analysis_id':imported.analysis_id}, 'POST')
        self.assertEqual(before, self.h.analysis)
        self.assertNotIn('attached_to', imported.assessment)
        self.assertEqual(200, self.h.request(self.url+'/reports', {'analysis_id':imported.analysis_id}, 'POST')[0])
        self.assertFalse(self.h.analysis.assessment['confirmed'])
        self.assertEqual(before.manager_reviews, self.h.analysis.manager_reviews)
        self.assertEqual(before.assessment['policy'], self.h.analysis.assessment['policy'])
        self.assertNotIn(imported.analysis_id, [r['id'] for r in self.h.request('/api/workspace/analyses')[1]])

    def test_admin_login_requires_password_and_manager_does_not(self):
        self.assertEqual(400, self.h.request('/api/workspace/login', {'employee_id':'0001'}, 'POST')[0])
        self.assertEqual(200, self.h.request('/api/workspace/login', {'employee_id':'a'}, 'POST')[0])
        password = secrets.token_urlsafe(18)
        data = {'employee_id':'0001','password':password,'confirmation':password}
        self.assertEqual(200, self.h.request('/api/workspace/login', data, 'POST')[0])
        self.assertEqual(403, self.h.request('/api/workspace/login', {**data,'password':'wrong-value'}, 'POST')[0])
        self.assertNotIn(password, policy_admin.ADMIN_PATH.read_text())


if __name__ == '__main__':
    unittest.main()
