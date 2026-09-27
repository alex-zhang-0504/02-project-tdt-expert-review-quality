"""Trusted local identities, persisted questionnaires and administrator workflow."""
from copy import deepcopy
import asyncio
from hashlib import sha256
from io import BytesIO

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .assessment import tasks, manager_task, require_selected
from .score_statistics import build_statistics, build_statistics_workbook
from .scoring import refresh
from .storage import now
from .subjective import save_review
from .submission import EXCEL_MEDIA_TYPE
from .export_names import review_export_disposition

COOKIE = 'tdt_workspace_user'


class Workspace:
    def __init__(self, service, store):
        self.service, self.store = service, store
        self.restores = {}

    def authorize(self, request, admin=False):
        user = self.store.user(request.cookies.get(COOKIE, ''))
        if not user:
            raise HTTPException(401, '请先选择姓名和工号登录')
        if admin and user['role'] != 'admin':
            raise HTTPException(403, '此操作仅限管理员')
        return user

    def freeze_accounts(self, analysis):
        owners = tasks(analysis)['managers']
        bindings = self.store.bindings()
        mapping = {}
        for manager in owners:
            owner = manager['manager_id']
            employee = owner[6:] if owner.startswith('local:') else bindings.get(owner)
            if not employee or not self.store.user(employee):
                raise ValueError('请先把每份报告的项目经理关联到姓名与工号：' + manager['name'])
            mapping[owner] = employee
        analysis.assessment['manager_accounts'] = mapping
        analysis.assessment['manager_names'] = {eid: self.store.user(eid)['name'] for eid in mapping.values()}
        analysis.assessment['created_at'] = now()

    def task_list(self, analysis, user):
        data = tasks(analysis)
        mids = {m['manager_id'] for m in data['managers'] if user['role'] == 'admin' or m['manager_id'] == user['employee_id']}
        return {**data, 'managers': [m for m in data['managers'] if m['manager_id'] in mids],
                'reviews': {mid: value for mid, value in analysis.manager_reviews.items() if mid in mids},
                'exclusions': analysis.assessment.get('exclusions', {}) if user['role'] == 'admin' else {}}

    def visible(self, analysis, user):
        if user['role'] == 'admin':
            return analysis
        require_selected(analysis)
        manager = next((m for m in tasks(analysis)['managers'] if m['manager_id'] == user['employee_id']), None)
        if not manager:
            raise HTTPException(403, '此考核没有分配给你的问卷')
        result = deepcopy(analysis)
        result.experts = [e for e in result.experts if e.expert_name in manager['experts']]
        for expert in result.experts:
            expert.sessions = [s for s in expert.sessions if s.project_code in manager['experts'][expert.expert_name]]
        refresh(result.experts)
        result.reports, result.sessions, result.issues, result.subjective_reviews = [], [], [], {}
        result.batch_summary = None
        result.assessment = {key: deepcopy(analysis.assessment[key]) for key in ('confirmed', 'included', 'policy', 'questionnaire', 'finalized') if key in analysis.assessment}
        result.assessment['included'] = list(manager['experts'])
        result.manager_reviews = {user['employee_id']: deepcopy(analysis.manager_reviews.get(user['employee_id'], {}))}
        return result

    def review(self, payload, user):
        with self.service.edit_analysis(payload.analysis_id) as analysis:
            require_selected(analysis)
            if user['role'] != 'admin' and payload.manager_id != user['employee_id']:
                raise HTTPException(403, '只能填写分配给本人的问卷')
            previous = analysis.manager_reviews.get(payload.manager_id, {}).get(payload.expert_name, {})
            if analysis.assessment.get('finalized') or (previous.get('locked_by_admin') and user['role'] != 'admin'):
                raise HTTPException(409, '问卷已锁定，请联系管理员退回后再填写')
            if payload.expected_revision != previous.get('revision', 0):
                raise HTTPException(409, '问卷已被其他页面更新，本次未保存。请先保留当前输入，再重新打开问卷核对')
            record = save_review(analysis, payload)
            record['locked_by_admin'] = bool(previous.get('locked_by_admin') or (user['role'] == 'admin' and payload.manager_id != user['employee_id']))
            self.audit(analysis, payload.manager_id, payload.expert_name, user, '管理员调整' if payload.manager_id != user['employee_id'] else '填写问卷', previous, record)
            return record

    @staticmethod
    def audit(analysis, mid, expert, user, action, previous, record):
        entries = analysis.assessment.setdefault('review_history', {}).setdefault(mid, {}).setdefault(expert, [])
        entries.append({'at': now(), 'actor': dict(user), 'action': action, 'before': deepcopy(previous), 'after': deepcopy(record)})

    def summary(self, analysis, user):
        confirmed = analysis.assessment.get('confirmed', False)
        managers = self.task_list(analysis, user)['managers'] if confirmed else []
        for manager in managers:
            reviews = analysis.manager_reviews.get(manager['manager_id'], {})
            manager['completed'] = sum(reviews.get(name, {}).get('status') == '已完成' for name in manager['experts'])
            manager['expected'] = len(manager['experts'])
        return {'id': analysis.analysis_id, 'name': analysis.source_name, 'created_at': analysis.assessment.get('created_at', ''),
                'confirmed': confirmed, 'finalized': bool(analysis.assessment.get('finalized')), 'managers': managers}


class WorkspaceGate:
    """All existing business routes are administrator-only unless explicitly scoped."""
    def __init__(self, app, workspace):
        self.app, self.workspace = app, workspace
        self.write_lock = asyncio.Lock()

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope['method'] not in ('GET', 'HEAD', 'OPTIONS'):
            async with self.write_lock:
                return await self.handle(scope, receive, send)
        return await self.handle(scope, receive, send)

    async def handle(self, scope, receive, send):
        if scope['type'] == 'http':
            path, method = scope['path'], scope['method']
            public = {('GET', '/api/health'), ('GET', '/api/workspace/session'), ('POST', '/api/workspace/bootstrap'), ('POST', '/api/workspace/login')}
            if path.startswith('/api/') and (method, path) not in public:
                request = Request(scope)
                try:
                    user = self.workspace.authorize(request)
                    if not path.startswith('/api/workspace/') and path not in ('/api/subjective/catalog', '/api/subjective/review', '/api/assessment/tasks') and user['role'] != 'admin':
                        raise HTTPException(403, '此操作仅限管理员')
                    if path in ('/api/assessment/task-import', '/api/assessment/exclude-task'):
                        raise HTTPException(409, '本机多人版请直接编辑问卷，保留修改记录')
                    if path == '/api/subjective/catalog' and user['role'] != 'admin':
                        self.workspace.visible(self.workspace.service.get_analysis(request.query_params.get('analysis_id', '')), user)
                except (HTTPException, ValueError, KeyError) as exc:
                    response = JSONResponse({'detail': exc.detail if isinstance(exc, HTTPException) else str(exc) if isinstance(exc, ValueError) else '考核不存在或没有可访问的问卷'}, status_code=exc.status_code if isinstance(exc, HTTPException) else 400 if isinstance(exc, ValueError) else 404)
                    return await response(scope, receive, send)
        await self.app(scope, receive, send)


def create_workspace_router(workspace, encode, busy):
    router = APIRouter(prefix='/api/workspace')
    store, service = workspace.store, workspace.service

    def logged_in(user):
        response = JSONResponse({'user': user})
        response.set_cookie(COOKIE, user['employee_id'], httponly=True, samesite='strict')
        return response

    @router.get('/session')
    def session(request: Request):
        users = store.users(include_disabled=True)
        user = next((u for u in users if u['employee_id'] == request.cookies.get(COOKIE, '') and u['enabled']), None)
        return {'user': user, 'users': users if user and user['role'] == 'admin' else [u for u in users if u['enabled']],
                'accounts_file': str(store.accounts_path)}

    @router.post('/bootstrap')
    async def bootstrap(request: Request):
        data = await request.json()
        return logged_in(store.add_user(data.get('employee_id'), data.get('name'), 'admin', first=True))

    @router.post('/login')
    async def login(request: Request):
        user = store.user((await request.json()).get('employee_id'))
        if not user:
            raise HTTPException(400, '请选择已登记的姓名与工号')
        return logged_in(user)

    @router.post('/logout')
    def logout():
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE)
        return response

    @router.post('/users')
    async def users(request: Request):
        user = workspace.authorize(request, admin=True)
        data = await request.json()
        return store.add_user(data.get('employee_id'), data.get('name'), data.get('role', 'manager'), actor_id=user['employee_id'])

    @router.delete('/users/{employee_id}')
    def delete_user(employee_id: str, request: Request):
        user = workspace.authorize(request, admin=True)
        with service._fact_lock:
            if busy():
                raise HTTPException(409, '请等待报告读取和AI分析结束后再删除账号')
            store.delete_user(employee_id, user['employee_id'])
            workspace.restores.pop(employee_id, None)
        return {'ok': True}

    @router.put('/users/{employee_id}')
    async def update_user(employee_id: str, request: Request):
        user = workspace.authorize(request, admin=True)
        data = await request.json()
        return store.update_user(employee_id, data, data.get('expected'), actor_id=user['employee_id'])

    @router.get('/bindings')
    def bindings(request: Request):
        workspace.authorize(request, admin=True)
        return store.bindings()

    @router.post('/bindings')
    async def bind(request: Request):
        workspace.authorize(request, admin=True)
        data = await request.json()
        store.bind(data.get('owner_id'), data.get('employee_id'))
        return {'ok': True}

    @router.get('/analyses')
    def analyses(request: Request):
        user = workspace.authorize(request)
        with service._fact_lock:
            result = []
            for analysis in reversed(list(service._analyses.values())):
                if not analysis.assessment.get('confirmed') and user['role'] != 'admin':
                    continue
                row = workspace.summary(analysis, user)
                if user['role'] == 'admin' or row['managers']:
                    result.append(row)
            return result

    @router.get('/analyses/{analysis_id}')
    def analysis_detail(analysis_id: str, request: Request):
        with service._fact_lock:
            return encode(workspace.visible(service.get_analysis(analysis_id), workspace.authorize(request)))

    @router.get('/history')
    def history(analysis_id: str, manager_id: str, expert_name: str, request: Request):
        user = workspace.authorize(request)
        if user['role'] != 'admin' and manager_id != user['employee_id']:
            raise HTTPException(403, '只能查看本人问卷记录')
        with service._fact_lock:
            analysis = service.get_analysis(analysis_id)
            manager_task(analysis, manager_id, expert_name)
            return analysis.assessment.get('review_history', {}).get(manager_id, {}).get(expert_name, [])

    @router.post('/return')
    async def return_review(request: Request):
        user = workspace.authorize(request, admin=True)
        data = await request.json()
        with service.edit_analysis(data['analysis_id']) as analysis:
            if analysis.assessment.get('finalized'):
                raise HTTPException(409, '请先重新开放本次主观评价')
            manager_task(analysis, data['manager_id'], data['expert_name'])
            record = analysis.manager_reviews.get(data['manager_id'], {}).get(data['expert_name'])
            if not record or not record.get('locked_by_admin'):
                raise ValueError('此问卷没有待退回的管理员调整')
            if data.get('expected_revision') != record['revision']:
                raise HTTPException(409, '问卷已更新，请重新打开后再退回')
            previous = deepcopy(record)
            record.update(locked_by_admin=False, revision=record['revision'] + 1, updated_at=now())
            workspace.audit(analysis, data['manager_id'], data['expert_name'], user, '退回经理', previous, record)
            return record

    @router.post('/finalize')
    async def finalize(request: Request):
        user = workspace.authorize(request, admin=True)
        data = await request.json()
        with service.edit_analysis(data['analysis_id']) as analysis:
            require_selected(analysis)
            if data.get('reopen') is True:
                analysis.assessment['finalized'] = False
                analysis.assessment.setdefault('finalization_history', []).append({'at': now(), 'actor': user, 'action': '重新开放'})
            else:
                rows = build_statistics(analysis)['rows']
                if not rows or not all(r['subjective_progress']['final'] for r in rows):
                    raise ValueError('仍有未回应任务或无有效评价的题目，不能确认最终结果')
                analysis.assessment['finalized'] = True
                analysis.assessment.setdefault('finalization_history', []).append({'at': now(), 'actor': user, 'action': '确认最终结果', 'rows': deepcopy(rows)})
            return {'finalized': analysis.assessment['finalized']}

    @router.get('/export')
    def export(analysis_id: str, request: Request):
        workspace.authorize(request, admin=True)
        with service._fact_lock:
            analysis = service.get_analysis(analysis_id)
            require_selected(analysis)
            content = build_statistics_workbook(analysis, False, 'subjective')
            label = '主观评价正式结果' if analysis.assessment.get('finalized') else '主观评价过程结果'
        return StreamingResponse(BytesIO(content), media_type=EXCEL_MEDIA_TYPE, headers={'Content-Disposition': review_export_disposition(label, 'subjective.xlsx')})

    @router.get('/backup')
    def backup(request: Request):
        workspace.authorize(request, admin=True)
        return StreamingResponse(BytesIO(store.backup()), media_type='application/octet-stream', headers={'Content-Disposition': 'attachment; filename="tdt-workspace.sqlite3"'})

    @router.post('/restore-preview')
    async def restore_preview(request: Request):
        user = workspace.authorize(request, admin=True)
        content = await request.body()
        users, _, analyses = store.inspect_backup(content)
        digest = sha256(content).hexdigest()
        workspace.restores[user['employee_id']] = (digest, content)
        return {'digest': digest, 'users': len(users), 'analyses': len(analyses)}

    @router.post('/restore')
    async def restore(request: Request):
        user = workspace.authorize(request, admin=True)
        data = await request.json()
        pending = workspace.restores.get(user['employee_id'])
        if not pending or pending[0] != data.get('digest') or data.get('confirmed') is not True:
            raise ValueError('请先预览备份并明确确认恢复')
        with service._fact_lock:
            if busy():
                raise HTTPException(409, '请等待报告读取和AI分析结束后再恢复')
            previous = store.restore(pending[1])
            loaded = store.load_all()
            service._analyses = {a.analysis_id: a for a, _ in loaded}
            service._revisions = {a.analysis_id: revision for a, revision in loaded}
            workspace.restores.clear()
        response = JSONResponse({'ok': True, 'before_restore_backup': previous})
        response.delete_cookie(COOKIE)
        return response

    return router
