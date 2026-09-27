import asyncio
from copy import deepcopy
from dataclasses import asdict
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, urlencode

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from openpyxl import load_workbook

from tdt_scoring.assessment import confirm_roster, tasks
from tdt_scoring.assessment_api import create_router
from tdt_scoring.service import ScoringService
from tdt_scoring.storage import WorkspaceStore
from tdt_scoring.subjective import ReviewInput, DIMENSIONS
from tdt_scoring.workspace import Workspace, WorkspaceGate, create_workspace_router, COOKIE, AUTH_COOKIE
from tests.test_assessment import sample


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = WorkspaceStore(self.temp.name)
        self.service = ScoringService(store=self.store)
        self.workspace = Workspace(self.service, self.store)
        self.workspace.sessions['unit-admin-session'] = '0001'
        self.admin = self.store.add_user('0001', '虚拟管理员', 'admin', first=True)
        self.manager = self.store.add_user('a', '虚拟经理甲')
        self.other = self.store.add_user('b', '虚拟经理乙')
        self.analysis = sample()
        self.id = self.analysis.analysis_id
        self.name = self.analysis.experts[0].expert_name
        confirm_roster(self.analysis, [self.name], '虚拟考核')
        self.workspace.freeze_accounts(self.analysis)
        self.service._analyses[self.id] = self.analysis
        self.service.persist(self.analysis)
        self.busy = False
        self.app = FastAPI()
        self.app.add_middleware(WorkspaceGate, workspace=self.workspace)
        self.app.include_router(create_router(self.service, self.encode, self.workspace))
        self.app.include_router(create_workspace_router(self.workspace, self.encode, lambda: self.busy))

        @self.app.exception_handler(ValueError)
        async def invalid(request, exc):
            return JSONResponse({'detail': str(exc)}, status_code=400)

        @self.app.post('/api/subjective/review')
        def review(payload: ReviewInput, request: Request):
            return self.workspace.review(payload, self.workspace.authorize(request))

        @self.app.get('/api/statistics/scores')
        def admin_scores():
            return {'secret': True}

    @staticmethod
    def encode(analysis):
        return jsonable_encoder(asdict(analysis))

    def request(self, path, data=None, method='GET', user='0001'):
        self.workspace.sessions['unit-admin-session-' + user] = user
        async def run():
            url = urlsplit(path)
            body = data if isinstance(data, bytes) else json.dumps(data).encode()
            scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
                     'http_version': '1.1', 'method': method, 'scheme': 'http', 'path': url.path,
                     'query_string': url.query.encode(), 'headers': [(b'host', b'127.0.0.1:8872'),
                     (b'cookie', f'{COOKIE}={user}; {AUTH_COOKIE}=unit-admin-session-{user}'.encode()), (b'content-type', b'application/json')],
                     'client': ('127.0.0.1', 12345), 'server': ('127.0.0.1', 8872), 'root_path': ''}
            messages = []
            async def receive():
                return {'type': 'http.request', 'body': body, 'more_body': False}
            async def send(message):
                messages.append(message)
            await self.app(scope, receive, send)
            output = b''.join(m.get('body', b'') for m in messages)
            try: output = json.loads(output)
            except (UnicodeDecodeError, json.JSONDecodeError): pass
            return messages[0]['status'], output
        return asyncio.run(run())

    def payload(self, mid='a', revision=0):
        ratings = {d['id']: {'option': 'high'} for d in DIMENSIONS}
        ratings['contribution'] = {'option': 'low'}
        return dict(analysis_id=self.id, manager_id=mid, evaluator=self.store.user(mid)['name'],
                    expert_name=self.name, ratings=ratings, expected_revision=revision)

    def save(self, data=None, user='a'):
        return self.request('/api/subjective/review', data or self.payload(), 'POST', user)

    def test_delete_unused_account_persists_and_revokes_identity(self):
        self.store.add_user('0010', '虚拟待删经理')
        before = self.store.load_all()
        path = '/api/workspace/users/0010'
        self.assertEqual(403, self.request(path, method='DELETE', user='a')[0])
        self.assertEqual(401, self.request(path, method='DELETE', user='')[0])
        self.busy = True
        self.assertEqual(409, self.request(path, method='DELETE')[0])
        self.busy = False
        self.assertEqual(200, self.request(path, method='DELETE')[0])
        self.assertIsNone(WorkspaceStore(self.temp.name).user('0010'))
        self.assertNotIn('0010', [u['employee_id'] for u in self.request('/api/workspace/session')[1]['users']])
        self.assertEqual(400, self.request('/api/workspace/login', {'employee_id': '0010'}, 'POST')[0])
        self.assertEqual(401, self.request('/api/workspace/analyses', user='0010')[0])
        self.assertEqual(400, self.request(path, method='DELETE')[0])
        self.assertEqual(before, self.store.load_all())

    def edit_accounts_file(self, change):
        data = json.loads(self.store.accounts_path.read_text(encoding='utf-8'))
        change(data['users'])
        self.store.accounts_path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def test_account_file_and_api_sync_in_both_directions(self):
        code, added = self.request('/api/workspace/users', dict(employee_id='0010', name='虚拟新增经理'), 'POST')
        self.assertEqual(200, code)
        disk = json.loads(self.store.accounts_path.read_text(encoding='utf-8'))
        self.assertIn(added, disk['users'])
        self.edit_accounts_file(lambda users: users.append(dict(employee_id='0020', name='虚拟文件经理', role='manager', enabled=True)))
        self.assertIn('0020', [u['employee_id'] for u in self.request('/api/workspace/session')[1]['users']])
        self.edit_accounts_file(lambda users: users[-1].update(name='虚拟文件修改', role='admin'))
        self.assertEqual(200, self.request('/api/statistics/scores', user='0020')[0])
        expected = self.store.user('0020')
        code, updated = self.request('/api/workspace/users/0020', {**expected, 'name': '虚拟页面修改', 'expected': expected}, 'PUT')
        self.assertEqual(200, code)
        self.assertEqual('虚拟页面修改', WorkspaceStore(self.temp.name).user('0020')['name'])
        self.assertIn(updated, json.loads(self.store.accounts_path.read_text(encoding='utf-8'))['users'])

    def test_fixed_owner_ids_match_without_name_inference_and_freeze(self):
        with self.service.edit_analysis(self.id) as analysis:
            analysis.assessment = {}
            for report in [*analysis.reports, *analysis.sessions]:
                report.manager_identity = dict(owner_id='ou_virtual', name='虚拟经理甲', status='resolved', source_token='virtual-token')
        matches = self.request('/api/workspace/manager-matches?analysis_id='+self.id)[1]
        self.assertEqual(1, len(matches['errors']))
        self.assertEqual(2, len(matches['errors'][0]['reports']))
        self.assertFalse(self.store.bindings())  # Same name never establishes a mapping.
        self.assertEqual(403, self.request('/api/workspace/manager-matches?analysis_id='+self.id, user='a')[0])
        self.assertEqual(200, self.request('/api/workspace/bindings', dict(owner_id='ou_virtual', employee_id='a'), 'POST')[0])
        self.assertIn('ou_virtual', self.store.user('a')['owner_ids'])
        self.assertFalse(self.request('/api/workspace/manager-matches?analysis_id='+self.id)[1]['errors'])
        self.assertEqual({'ou_virtual': 'a'}, WorkspaceStore(self.temp.name).bindings())
        self.assertEqual(200, self.request('/api/assessment/roster', {'analysis_id':self.id, 'names':[self.name], 'confirm':True}, 'POST')[0])
        frozen = deepcopy(self.analysis.assessment['manager_accounts'])
        self.store.bind('ou_virtual', 'b')
        self.assertEqual(frozen, self.analysis.assessment['manager_accounts'])

    def test_owner_disabled_or_missing_blocks_confirmation_and_ids_are_unique(self):
        with self.service.edit_analysis(self.id) as analysis:
            analysis.assessment = {}
            for report in [*analysis.reports, *analysis.sessions]:
                report.manager_identity = dict(owner_id='ou_virtual', name='虚拟经理甲', status='resolved', source_token='virtual-token')
        self.store.bind('ou_virtual','a')
        user = self.store.user('a')
        self.store.update_user('a', {**user, 'enabled':False}, user)
        matches = self.workspace.manager_matches(self.analysis)
        self.assertEqual('账号已停用', matches['errors'][0]['reason'])
        self.assertEqual(400, self.request('/api/assessment/roster', {'analysis_id':self.id,'names':[self.name],'confirm':True},'POST')[0])
        user = self.store.user('b')
        with self.assertRaisesRegex(ValueError,'只能归属一个'):
            self.store.update_user('b',{**user,'owner_ids':['ou_virtual']}, user)
        self.assertIsNone(self.store.user('a'))
        self.assertEqual([], self.store.user('b')['owner_ids'])
        with self.service.edit_analysis(self.id) as analysis:
            for report in analysis.reports:
                report.source_type='feishu_sheet'
                report.manager_identity={}
        matches=self.workspace.manager_matches(self.analysis)
        self.assertTrue(all(not e['can_assign'] for e in matches['errors']))

    def test_account_conflict_disabling_and_history_retention(self):
        self.save()
        before = self.store.load_all()
        expected = self.store.user('a')
        self.edit_accounts_file(lambda users: next(u for u in users if u['employee_id']=='a').update(name='虚拟文件改名'))
        data = {**expected, 'name': '虚拟过时修改', 'expected': expected}
        self.assertIn('另一端修改', self.request('/api/workspace/users/a', data, 'PUT')[1]['detail'])
        expected = self.store.user('a')
        data = {**expected, 'enabled': False, 'expected': expected}
        self.assertEqual(403, self.request('/api/workspace/users/a', data, 'PUT', user='b')[0])
        self.assertEqual(200, self.request('/api/workspace/users/a', data, 'PUT')[0])
        self.assertEqual(401, self.request('/api/workspace/analyses', user='a')[0])
        self.assertNotIn('a', [u['employee_id'] for u in self.request('/api/workspace/session', user='')[1]['users']])
        self.assertIn('a', [u['employee_id'] for u in self.request('/api/workspace/session')[1]['users']])
        self.assertEqual(before, self.store.load_all())
        self.edit_accounts_file(lambda users: next(u for u in users if u['employee_id']=='a').update(enabled=True))
        self.assertEqual(200, self.request('/api/workspace/analyses', user='a')[0])

    def test_invalid_account_file_and_last_admin_are_rejected(self):
        original = self.store.accounts_path.read_bytes()
        expected = self.store.user('0001')
        for changes in ({'enabled': False}, {'role': 'manager'}, {'employee_id': 'new'}):
            self.assertEqual(400, self.request('/api/workspace/users/0001', {**expected, **changes, 'expected': expected}, 'PUT')[0])
            self.assertEqual(original, self.store.accounts_path.read_bytes())
        for change in (lambda users: users.append(dict(users[0])),
                       lambda users: users[0].update(enabled=False),
                       lambda users: users[0].update(role='unknown'),
                       lambda users: users.remove(next(u for u in users if u['employee_id']=='a'))):
            self.edit_accounts_file(change)
            self.assertEqual(400, self.request('/api/workspace/session')[0])
            self.store.accounts_path.write_bytes(original)
        self.store.accounts_path.write_text('{broken', encoding='utf-8')
        self.assertIn('格式错误', self.request('/api/workspace/session')[1]['detail'])
        self.assertIn('格式错误', self.request('/api/workspace/analyses')[1]['detail'])
        self.store.accounts_path.write_bytes(original)
        with patch('tdt_scoring.accounts.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError): self.store.update_user('0001', {**expected, 'name':'虚拟失败修改'}, expected)
        self.assertEqual(original, self.store.accounts_path.read_bytes())

    def test_backup_preserves_disabled_accounts_and_external_changes(self):
        self.edit_accounts_file(lambda users: next(u for u in users if u['employee_id']=='a').update(enabled=False, name='虚拟停用经理'))
        backup = self.store.backup()
        self.edit_accounts_file(lambda users: next(u for u in users if u['employee_id']=='a').update(enabled=True))
        self.store.restore(backup)
        self.assertIsNone(self.store.user('a'))
        record = next(u for u in WorkspaceStore(self.temp.name).users(include_disabled=True) if u['employee_id']=='a')
        self.assertEqual('虚拟停用经理', record['name'])

    def test_delete_protects_current_and_last_admin(self):
        path = '/api/workspace/users/0001'
        self.assertIn('最后一个管理员', self.request(path, method='DELETE')[1]['detail'])
        self.store.add_user('0002', '虚拟备用管理员', 'admin')
        self.assertIn('当前登录', self.request(path, method='DELETE')[1]['detail'])
        self.assertEqual(200, self.request('/api/workspace/users/0002', method='DELETE')[0])
        self.assertIsNotNone(self.store.user('0001'))

    def test_delete_rejects_report_bindings_and_frozen_tasks_without_changing_data(self):
        self.save()
        before = self.store.load_all()
        self.assertIn('考核或问卷历史', self.request('/api/workspace/users/a', method='DELETE')[1]['detail'])
        self.assertEqual(before, self.store.load_all())
        self.store.add_user('unused', '虚拟绑定经理')
        self.store.bind('owner-unused', 'unused')
        self.assertIn('飞书报告', self.request('/api/workspace/users/unused', method='DELETE')[1]['detail'])
        self.store.bind('owner-unused', 'b')
        self.assertEqual(200, self.request('/api/workspace/users/unused', method='DELETE')[0])
        # Draft local report references also prevent dangling manager identities.
        with self.service.edit_analysis(self.id) as analysis:
            analysis.assessment = {}
            analysis.manager_reviews = {}
        self.assertIn('关联报告', self.request('/api/workspace/users/a', method='DELETE')[1]['detail'])

    def test_delete_keeps_administrator_audit_identity(self):
        self.store.add_user('0002', '虚拟调整管理员', 'admin')
        self.save(user='0002')
        self.assertEqual(400, self.request('/api/workspace/users/0002', method='DELETE')[0])
        self.assertIsNotNone(self.store.user('0002'))
        self.assertEqual('0002', self.analysis.assessment['review_history']['a'][self.name][0]['actor']['employee_id'])

    def test_identity_gate_and_scoped_reads_and_writes(self):
        self.assertEqual(401, self.request('/api/workspace/analyses', user='')[0])
        self.assertEqual(403, self.request('/api/statistics/scores', user='a')[0])
        self.assertEqual(403, self.save(user='b')[0])
        self.assertEqual(200, self.save()[0])
        data = self.request('/api/assessment/tasks?analysis_id='+self.id, user='a')[1]
        self.assertEqual(['a'], [m['manager_id'] for m in data['managers']])
        self.assertEqual(['a'], list(data['reviews']))
        view = self.request('/api/workspace/analyses/'+self.id, user='a')[1]
        self.assertEqual([], view['reports'])
        self.assertEqual([], view['sessions'])
        self.assertEqual(['a'], list(view['manager_reviews']))
        allowed = tasks(self.analysis)['managers'][0]['experts'][self.name]
        self.assertTrue(all(s['project_code'] in allowed for e in view['experts'] for s in e['sessions']))
        query = urlencode(dict(analysis_id=self.id, manager_id='b', expert_name=self.name))
        self.assertEqual(403, self.request('/api/workspace/history?'+query, user='a')[0])

    def test_admin_adjustment_lock_return_audit_and_stale_revision(self):
        self.assertEqual(200, self.save()[0])
        self.assertEqual(409, self.save()[0])
        change = self.payload(revision=1)
        change['ratings']['preparation'] = {'option': 'medium'}
        code, record = self.save(change, user='0001')
        self.assertEqual(200, code)
        self.assertTrue(record['locked_by_admin'])
        self.assertEqual(409, self.save(self.payload(revision=2))[0])
        data = dict(analysis_id=self.id, manager_id='a', expert_name=self.name, expected_revision=2)
        self.assertEqual(200, self.request('/api/workspace/return', data, 'POST')[0])
        self.assertEqual(200, self.save(self.payload(revision=3))[0])
        history = self.analysis.assessment['review_history']['a'][self.name]
        self.assertEqual(4, len(history))
        self.assertEqual('high', history[1]['before']['ratings']['preparation']['option'])
        self.assertEqual('medium', history[1]['after']['ratings']['preparation']['option'])

    def test_summary_counts_valid_answers_instead_of_selected_cards(self):
        payload = self.payload()
        payload['ratings']['contribution'] = {'option': 'high'}
        self.assertEqual(200, self.save(payload)[0])
        summary = self.workspace.summary(self.analysis, self.manager)
        manager = summary['managers'][0]
        self.assertEqual(0, manager['completed'])
        self.assertEqual({'status': '待补依据或原因', 'answered': 5, 'selected': 6}, manager['reviews'][self.name])
        self.assertTrue(manager['started'])
        self.assertEqual(200, self.save(self.payload(revision=1))[0])
        self.assertEqual(1, self.workspace.summary(self.analysis, self.manager)['managers'][0]['completed'])

    def test_disk_failure_rolls_back_and_restart_restores_dates_and_audit(self):
        with patch.object(self.store, 'save', side_effect=OSError('virtual disk failure')):
            with self.assertRaises(OSError): self.workspace.review(ReviewInput(**self.payload()), self.manager)
        self.assertEqual({}, self.analysis.manager_reviews)
        self.save()
        restarted = ScoringService(store=WorkspaceStore(self.temp.name)).get_analysis(self.id)
        self.assertEqual(asdict(self.analysis), asdict(restarted))
        stale = ScoringService(store=WorkspaceStore(self.temp.name))
        self.save(self.payload(revision=1))
        with self.assertRaisesRegex(ValueError, '另一服务'):
            with stale.edit_analysis(self.id) as analysis: analysis.source_name = 'stale'
        self.assertNotEqual('stale', stale.get_analysis(self.id).source_name)

    def test_finalize_requires_valid_results_and_freezes_then_reopens(self):
        data = {'analysis_id': self.id}
        self.assertEqual(400, self.request('/api/workspace/finalize', data, 'POST')[0])
        for mid in ('a', 'b'):
            payload = self.payload(mid)
            payload['ratings']['preparation'] = {'option': 'unable', 'reason': '虚拟无法观察'}
            self.assertEqual(200, self.save(payload, mid)[0])
        self.assertEqual(400, self.request('/api/workspace/finalize', data, 'POST')[0])
        self.save(self.payload(revision=1))
        self.assertEqual(200, self.request('/api/workspace/finalize', data, 'POST')[0])
        self.assertEqual(409, self.save(self.payload(revision=2))[0])
        code, output = self.request('/api/workspace/export?analysis_id='+self.id)
        self.assertEqual(200, code)
        book = load_workbook(BytesIO(output))
        self.assertTrue(any(row[0]=='结果状态' and '正式' in row[1] for row in book['配置及范围'].values))
        self.assertEqual(200, self.request('/api/workspace/finalize', {**data, 'reopen': True}, 'POST')[0])
        self.assertEqual(200, self.save(self.payload(revision=2))[0])

    def test_backup_preview_restore_and_invalid_input_leave_data_unchanged(self):
        self.save()
        code, backup = self.request('/api/workspace/backup')
        self.assertEqual(200, code)
        self.assertEqual(400, self.request('/api/workspace/restore-preview', b'bad', 'POST')[0])
        _, preview = self.request('/api/workspace/restore-preview', backup, 'POST')
        self.assertEqual(1, preview['analyses'])
        self.store.add_user('c', '虚拟经理丙')
        self.busy = True
        confirmation = {'digest': preview['digest'], 'confirmed': True}
        self.assertEqual(409, self.request('/api/workspace/restore', confirmation, 'POST')[0])
        self.busy = False
        self.assertEqual(200, self.request('/api/workspace/restore', confirmation, 'POST')[0])
        self.assertIsNone(self.store.user('c'))
        restored = self.service.get_analysis(self.id)
        self.assertEqual(1, restored.manager_reviews['a'][self.name]['revision'])
        self.assertTrue(list((Path(self.temp.name)/'backups').glob('before-restore-*.sqlite3')))

    def test_unbound_roster_rolls_back_and_multiple_owner_ids_count_once(self):
        a = deepcopy(self.analysis)
        a.assessment = {}
        a.manager_reviews = {}
        a.analysis_id = 'virtual-unbound'
        for session in a.sessions:
            session.manager_identity['owner_id'] = 'owner-'+session.project_code
        self.service._analyses[a.analysis_id] = a
        self.service.persist(a)
        payload = {'analysis_id': a.analysis_id, 'names': [self.name], 'confirm': True}
        self.assertEqual(400, self.request('/api/assessment/roster', payload, 'POST')[0])
        self.assertFalse(a.assessment)
        for session in a.sessions:
            self.store.bind(session.manager_identity['owner_id'], 'a')
        self.assertEqual(200, self.request('/api/assessment/roster', payload, 'POST')[0])
        self.assertEqual(1, len(tasks(a)['managers']))
        self.assertEqual('a', tasks(a)['managers'][0]['manager_id'])

    def test_employee_ids_preserve_zeros_and_bootstrap_is_one_time(self):
        self.assertEqual('0001', self.store.user('0001')['employee_id'])
        for employee_id in ('0001', 1, '', '../abc'):
            with self.assertRaises(ValueError): self.store.add_user(employee_id, '虚拟经理')
        with self.assertRaises(ValueError): self.store.add_user('002', '虚拟管理员二', 'admin', first=True)

    def test_batch_intermediate_parse_does_not_create_saved_assessment(self):
        from tests.workbook_factory import build_v04_workbook
        before = len(self.store.load_all())
        analysis = self.service.import_local_bytes(build_v04_workbook([{'stage': 'TDR1'}]), 'virtual.xlsx', retain=False)
        self.assertEqual(before, len(self.store.load_all()))
        self.assertNotIn(analysis.analysis_id, self.service._analyses)


if __name__ == '__main__':
    unittest.main()
