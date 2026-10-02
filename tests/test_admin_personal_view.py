from copy import deepcopy
from dataclasses import asdict
import unittest

from tests import test_workspace
from tdt_scoring.models import OpinionFact
from tdt_scoring.score_statistics import build_statistics
from tdt_scoring.service import ScoringService


class AdminPersonalViewTests(unittest.TestCase):
    def setUp(self):
        self.h = test_workspace.WorkspaceTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        a = self.h.analysis
        for row in [*a.reports, *a.sessions]:
            if row.manager_identity['owner_id'] == 'local:a':
                row.manager_identity.update(owner_id='local:0001', name='虚拟管理员')
        a.assessment.update(manager_accounts={'local:0001': '0001', 'local:b': 'b'},
                            manager_names={'0001': '虚拟管理员', 'b': '虚拟经理乙'},
                            task_users=self.h.store.users())
        for e in a.experts:
            for s in e.sessions:
                s.opinions = [OpinionFact(e.expert_name + s.source_name + s.review_id,
                                         '虚拟对策', [], [], ai_status='suspected')]
        self.h.service.persist(a)

    def test_personal_reads_are_scoped_without_changing_role_or_full_data(self):
        h = self.h
        before = deepcopy(asdict(h.analysis))
        path = '/api/workspace/analyses/' + h.id
        code, data = h.request(path, personal=True)
        self.assertEqual(200, code)
        self.assertTrue(data['assessment']['personal_scope'])
        self.assertEqual({'a.xlsx'}, {s['source_name'] for e in data['experts'] for s in e['sessions']})
        code, catalog = h.request('/api/assessment/tasks?analysis_id=' + h.id, personal=True)
        self.assertEqual(['0001'], [m['manager_id'] for m in catalog['managers']])
        self.assertEqual(403, h.request('/api/statistics/scores', personal=True)[0])
        self.assertEqual(403, h.request('/api/workspace/users', {'employee_id': 'x', 'name': '虚拟新增'}, 'POST', personal=True)[0])
        self.assertEqual(200, h.request('/api/statistics/scores')[0])
        self.assertEqual('admin', h.store.user('0001')['role'])
        self.assertEqual(before, asdict(h.analysis))
        self.assertEqual(2, len(h.request(path)[1]['reports']))

    def test_personal_decision_changes_original_and_full_score_but_rejects_foreign(self):
        h = self.h
        before = deepcopy(build_statistics(h.analysis)['rows'])
        expert = next(e for e in h.analysis.experts if e.expert_name == h.name)
        own = next(o for s in expert.sessions if s.source_name == 'a.xlsx' for o in s.opinions)
        other = next(o for s in expert.sessions if s.source_name == 'b.xlsx' for o in s.opinions)
        payload = {'analysis_id': h.id, 'opinion_id': other.opinion_id, 'included': True}
        self.assertEqual(403, h.request('/api/workspace/solution-selection', payload, 'POST', personal=True)[0])
        self.assertIsNone(other.included)
        payload['opinion_id'] = own.opinion_id
        code, result = h.request('/api/workspace/solution-selection', payload, 'POST', personal=True)
        self.assertEqual(200, code)
        self.assertTrue(result['assessment']['personal_scope'])
        self.assertTrue(own.included)
        after = build_statistics(h.analysis)['rows']
        self.assertNotEqual(before, after)
        loaded = ScoringService(store=h.store).get_analysis(h.id)
        self.assertEqual(after, build_statistics(loaded)['rows'])
        self.assertEqual(2, len(loaded.reports))

    def test_personal_questionnaire_rejects_other_and_preserves_admin_actor(self):
        h = self.h
        self.assertEqual(403, h.request('/api/subjective/review', h.payload(mid='b'), 'POST', personal=True)[0])
        code, result = h.request('/api/subjective/review', h.payload(mid='0001'), 'POST', personal=True)
        self.assertEqual(200, code, result)
        record = h.analysis.manager_reviews['0001'][h.name]
        self.assertFalse(record['locked_by_admin'])
        self.assertEqual('admin', h.analysis.assessment['review_history']['0001'][h.name][-1]['actor']['role'])

    def test_normal_manager_cannot_gain_admin_scope(self):
        h = self.h
        self.assertEqual(403, h.request('/api/statistics/scores', user='b')[0])
        self.assertTrue(h.request('/api/workspace/analyses/' + h.id, user='b')[1]['assessment']['personal_scope'])

    def test_entry_eligibility_uses_own_reports_not_admin_role(self):
        h = self.h
        self.assertEqual(1, h.request('/api/workspace/analyses')[1][0]['personal_report_count'])
        h.store.add_user('0002', '虚拟无报告管理员', 'admin')
        self.assertEqual(0, h.request('/api/workspace/analyses', user='0002')[1][0]['personal_report_count'])
        self.assertEqual([], h.request('/api/workspace/analyses', user='0002', personal=True)[1])
        self.assertEqual(403, h.request('/api/workspace/analyses/' + h.id, user='0002', personal=True)[0])
