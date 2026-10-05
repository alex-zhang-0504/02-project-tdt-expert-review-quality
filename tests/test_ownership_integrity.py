from copy import deepcopy
import unittest

from tdt_scoring.assessment import tasks
from tdt_scoring.ownership import resolve_owners, snapshot_errors
from tdt_scoring.service import ScoringService
from tdt_scoring.storage import WorkspaceStore
from tdt_scoring.score_statistics import build_statistics
from tests import test_workspace


class OwnershipIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.h = test_workspace.WorkspaceTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def cloud(self):
        a = self.h.analysis
        for row in [*a.reports, *a.sessions]:
            local = row.manager_identity['owner_id']
            row.manager_identity.update(owner_id=local.replace('local:', 'ou_'), source_token='virtual')
        a.assessment['manager_accounts'] = {'ou_a': 'a', 'ou_b': 'b'}
        return a

    def test_old_binding_cannot_override_unique_source_name(self):
        a = self.cloud()
        users = self.h.store.users()
        before = deepcopy(a)
        mapping, errors = resolve_owners(a, users, {'ou_a': '0001'})
        self.assertNotIn('ou_a', mapping)
        self.assertIn('历史归属', errors[0]['reason'])
        self.assertEqual(before, a)

    def test_frozen_bad_binding_blocks_tasks_and_personal_data(self):
        a = self.cloud()
        a.assessment['manager_accounts']['ou_a'] = '0001'
        a.assessment['manager_names']['0001'] = '虚拟管理员'
        self.assertTrue(snapshot_errors(a))
        self.assertEqual([], tasks(a)['managers'])
        self.assertTrue(tasks(a)['unresolved_reports'])
        self.assertEqual(set(), self.h.workspace.owned_sessions(a, self.h.manager))

    def test_admin_is_a_participant_and_fills_own_questionnaire_only_in_personal_view(self):
        a = self.h.analysis
        for row in [*a.reports, *a.sessions]:
            if row.manager_identity['owner_id'] == 'local:a':
                row.manager_identity.update(owner_id='local:0001', name='虚拟管理员')
        a.assessment.update(manager_accounts={'local:0001':'0001','local:b':'b'},
                            manager_names={'0001':'虚拟管理员','b':'虚拟经理乙'},
                            task_users=self.h.store.users())
        self.assertIn('0001', [m['manager_id'] for m in tasks(a)['managers']])
        code, result = self.h.save(self.h.payload(mid='0001'), user='0001')
        self.assertEqual(403, code, result)
        self.assertIn('我的考评', result['detail'])
        self.assertNotIn('0001', a.manager_reviews)
        code, result = self.h.request('/api/subjective/review', self.h.payload(mid='0001'), 'POST', '0001', personal=True)
        self.assertEqual(200, code, result)
        self.assertFalse(a.manager_reviews['0001'][self.h.name]['locked_by_admin'])
        self.assertEqual('填写问卷', a.assessment['review_history']['0001'][self.h.name][-1]['action'])

    def test_external_binding_api_rejects_cross_name_and_unknown_source(self):
        self.cloud()
        for owner, employee in [('ou_a','0001'), ('ou_unknown','a')]:
            code, _ = self.h.request('/api/workspace/bindings', {
                'analysis_id':self.h.id, 'owner_id':owner, 'employee_id':employee}, 'POST')
            self.assertEqual(400, code)
        self.assertFalse(self.h.store.bindings())

    def test_conflicting_source_copies_block_resolution(self):
        a = self.cloud()
        a.sessions[0].manager_identity['name'] = '虚拟经理乙'
        mapping, errors = resolve_owners(a, self.h.store.users())
        self.assertTrue(errors)
        self.assertNotIn('ou_a', mapping)

    def test_conflict_survives_restart_and_cannot_save_or_complete(self):
        a = self.cloud()
        before = deepcopy(a.sessions)
        objective = [r['objective_total'] for r in build_statistics(a)['rows']]
        a.assessment['manager_accounts']['ou_a'] = '0001'
        a.assessment['manager_names']['0001'] = '虚拟管理员'
        self.h.service.persist(a)
        restored = ScoringService(store=WorkspaceStore(self.h.temp.name)).get_analysis(a.analysis_id)
        self.assertTrue(snapshot_errors(restored))
        self.assertFalse(self.h.workspace.manager_matches(restored)['mapping'] == {})
        self.assertTrue(self.h.workspace.manager_matches(restored)['errors'])
        code, _ = self.h.request('/api/subjective/review', self.h.payload(mid='0001'), 'POST', '0001', personal=True)
        self.assertEqual(400, code)
        self.assertEqual(before, restored.sessions)
        stats = build_statistics(restored)
        self.assertEqual(objective, [r['objective_total'] for r in stats['rows']])
        self.assertTrue(all(r['total'] is None for r in stats['rows']))

    def test_storage_cannot_bind_mismatched_or_reassign_existing_owner(self):
        store = self.h.store
        with self.assertRaisesRegex(ValueError, '姓名与账号不一致'):
            store.bind('ou_a', '0001', owner_name='虚拟经理甲')
        self.assertFalse(store.bindings())
        store.bind('ou_a', 'a', owner_name='虚拟经理甲')
        with self.assertRaisesRegex(ValueError, '历史归属冲突'):
            store.bind('ou_a', 'b', owner_name='虚拟经理乙')
        self.assertEqual({'ou_a':'a'}, store.bindings())

    def test_different_owner_ids_in_report_and_sessions_are_rejected(self):
        a = self.cloud()
        a.sessions[0].manager_identity.update(owner_id='ou_other', name='虚拟经理乙')
        self.assertTrue(snapshot_errors(a))
        self.assertTrue(resolve_owners(a, self.h.store.users())[1])

    def test_admin_only_roster_creates_task(self):
        from tdt_scoring.task_workflow import create_task_router
        self.h.app.include_router(create_task_router(self.h.workspace, self.h.encode, lambda:False))
        code, result = self.h.request('/api/workspace/tasks', {
            'year':'2030', 'period':'年度', 'accounts':{'version':1,'users':[self.h.admin]}}, 'POST')
        self.assertEqual(200, code, result)

    def test_corrupt_completed_snapshot_is_not_presented_as_valid_history(self):
        from tdt_scoring.task_workflow import create_task_router
        self.h.app.include_router(create_task_router(self.h.workspace, self.h.encode, lambda:False))
        a = self.cloud()
        a.assessment['manager_accounts']['ou_a'] = '0001'
        a.assessment['manager_names']['0001'] = '虚拟管理员'
        a.assessment.update(completed=True, completion={'statistics':{'rows':[]}})
        self.assertEqual(400, self.h.request('/api/workspace/tasks/'+a.analysis_id+'/history')[0])

    def test_valid_frozen_identity_survives_global_rename(self):
        a = self.cloud()
        self.assertEqual([], snapshot_errors(a))
        user = self.h.store.user('a')
        self.h.store.update_user('a', {**user, 'name':'虚拟改名'}, user)
        self.assertEqual([], snapshot_errors(a))
        self.assertEqual(2, len(tasks(a)['managers']))
