"""Trusted local identities, persisted questionnaires and administrator workflow."""
from copy import deepcopy
import asyncio
import secrets
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
AUTH_COOKIE = 'tdt_workspace_auth'


class Workspace:
    def __init__(self, service, store):
        self.service, self.store = service, store
        self.restores = {}
        self.sessions = {}
        from .policy_admin import credential_version
        self.credential_version = credential_version()

    def sync_admin_sessions(self):
        from .policy_admin import credential_version
        current = credential_version()
        if current != self.credential_version:
            self.sessions.clear()
            self.credential_version = current

    def authorize(self, request, admin=False):
        self.sync_admin_sessions()
        user = self.store.user(request.cookies.get(COOKIE, ''))
        if not user:
            raise HTTPException(401, '请先选择姓名和工号登录')
        if user['role'] == 'admin' and self.sessions.get(request.cookies.get(AUTH_COOKIE, '')) != user['employee_id']:
            raise HTTPException(401, '请使用管理员密码登录')
        if admin and user['role'] != 'admin':
            raise HTTPException(403, '此操作仅限管理员')
        return user

    def freeze_accounts(self, analysis):
        match = self.manager_matches(analysis)
        if match['errors']:
            raise ValueError('项目经理匹配尚有异常，请先在文件扫描区域下方确认处理')
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
        analysis.assessment.setdefault('created_at', now())

    def manager_matches(self, analysis):
        users = self.store.users(include_disabled=True)
        by_id = {u['employee_id']: u for u in users}
        by_owner = {owner: u for u in users for owner in u['owner_ids']}
        roster = analysis.assessment.get('task_users')
        eligible = {u['employee_id'] for u in roster if u['enabled']} if roster is not None else set(by_id)
        candidates = [u for u in users if u['enabled'] and u['employee_id'] in eligible]
        errors = {}
        if not analysis.assessment.get('manager_accounts'):
            for report in analysis.reports:
                identity = report.manager_identity or {}
                owner = identity.get('owner_id', '')
                local = report.source_type == 'local_excel' and not identity.get('source_token')
                user = by_id.get(owner[6:]) if local and owner.startswith('local:') else by_owner.get(owner)
                if not user and not local and owner and identity.get('status') == 'resolved':
                    matches = [u for u in candidates if u['name'] == identity.get('name', '').strip()]
                    if len(matches) == 1:
                        user = matches[0]
                        self.store.bind(owner, user['employee_id'])
                        by_owner[owner] = user
                if user and user['enabled'] and user['employee_id'] in eligible and identity.get('status') == 'resolved':
                    continue
                key = owner if owner else report.source_name
                reason = '账号已停用' if user and not user['enabled'] else '项目经理不在本任务启用名单中' if user and user['employee_id'] not in eligible else '原文件所有者姓名未唯一匹配启用的项目经理，请确认归属' if owner and not local else '本地报告尚未指定项目经理' if local else '未读取到有效的原文件所有者ID，请重新扫描'
                entry = errors.setdefault(key, {'owner_id': owner, 'name': identity.get('name', ''),
                    'reason': reason, 'local': local, 'can_assign': local or bool(owner), 'reports': []})
                entry['reports'].append(report.source_name)
        return {'errors': list(errors.values()), 'users': candidates}

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
            if record.get('ratings'):
                analysis.assessment.setdefault('started', {}).setdefault(payload.manager_id, now())
            record['locked_by_admin'] = bool(previous.get('locked_by_admin') or (user['role'] == 'admin' and payload.manager_id != user['employee_id']))
            self.audit(analysis, payload.manager_id, payload.expert_name, user, '管理员调整' if payload.manager_id != user['employee_id'] else '填写问卷', previous, record)
            return record

    @staticmethod
    def audit(analysis, mid, expert, user, action, previous, record):
        entries = analysis.assessment.setdefault('review_history', {}).setdefault(mid, {}).setdefault(expert, [])
        entries.append({'at': now(), 'actor': dict(user), 'action': action, 'before': deepcopy(previous), 'after': deepcopy(record)})

    def summary(self, analysis, user):
        from .questionnaire import snapshot as questionnaire_snapshot
        from .score_statistics import questionnaire_score
        confirmed = analysis.assessment.get('confirmed', False)
        managers = self.task_list(analysis, user)['managers'] if confirmed else []
        for manager in managers:
            reviews = analysis.manager_reviews.get(manager['manager_id'], {})
            manager['completed'] = sum(reviews.get(name, {}).get('status') == '已完成' for name in manager['experts'])
            manager['expected'] = len(manager['experts'])
        from .task_workflow import result_state
        statistics, ready = result_state(analysis) if confirmed else (None, False)
        for manager in managers:
            reviews = analysis.manager_reviews.get(manager['manager_id'], {})
            manager['started'] = bool(analysis.assessment.get('started', {}).get(manager['manager_id']) or any(r.get('ratings') for r in reviews.values()))
            manager['reviews'] = {}
            for name in manager['experts']:
                record = reviews.get(name, {})
                items, _ = questionnaire_score(record, analysis.assessment['policy']['parameters'], questionnaire_snapshot(analysis))
                answered = sum(item['responded'] for item in items)
                selected = len(record.get('ratings', {}))
                manager['reviews'][name] = {'status': '已完成' if answered == 6 else '待补依据或原因' if selected > answered else '待评价',
                    'answered': answered, 'selected': selected}
            manager['completed'] = sum(r['answered'] == 6 for r in manager['reviews'].values())
        return {'id': analysis.analysis_id, 'name': analysis.source_name, 'created_at': analysis.assessment.get('created_at', ''),
                'confirmed': confirmed, 'finalized': bool(analysis.assessment.get('finalized')), 'managers': managers,
                'completed': bool(analysis.assessment.get('completed')), 'report_count': len(analysis.reports),
                'expert_count': len(analysis.assessment.get('included', [])), 'can_complete': ready,
                'objective_complete': bool(statistics and statistics['rows']) and all(r['objective_with_rewards'] is not None for r in statistics['rows'])}


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
            public = {('GET', '/api/health'), ('GET', '/api/workspace/session'), ('POST', '/api/workspace/bootstrap'), ('POST', '/api/workspace/login'), ('POST', '/api/workspace/password')}
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
        workspace.sync_admin_sessions()
        response = JSONResponse({'user': user})
        response.set_cookie(COOKIE, user['employee_id'], httponly=True, samesite='strict')
        token = secrets.token_urlsafe(32)
        workspace.sessions[token] = user['employee_id']
        response.set_cookie(AUTH_COOKIE, token, httponly=True, samesite='strict')
        return response

    @router.get('/session')
    def session(request: Request):
        workspace.sync_admin_sessions()
        users = store.users(include_disabled=True)
        user = next((u for u in users if u['employee_id'] == request.cookies.get(COOKIE, '') and u['enabled']), None)
        if user and user['role'] == 'admin' and workspace.sessions.get(request.cookies.get(AUTH_COOKIE, '')) != user['employee_id']:
            user = None
        from . import policy_admin
        return {'user': user, 'users': users if user and user['role'] == 'admin' else [u for u in users if u['enabled']],
                'accounts_file': str(store.accounts_path), 'password_configured': policy_admin.ADMIN_PATH.exists()}

    @router.post('/bootstrap')
    async def bootstrap(request: Request):
        data = await request.json()
        from .policy_admin import workspace_password
        if store.users(include_disabled=True):
            raise ValueError('已有账号，请登录')
        from .accounts import validate
        validate({'version': 1, 'users': [{'employee_id': data.get('employee_id'), 'name': data.get('name'),
            'role': 'admin', 'enabled': True, 'owner_ids': []}]})
        workspace_password(data)
        return logged_in(store.add_user(data.get('employee_id'), data.get('name'), 'admin', first=True))

    @router.post('/login')
    async def login(request: Request):
        data = await request.json()
        user = store.user(data.get('employee_id'))
        if not user:
            raise HTTPException(400, '请选择已登记的姓名与工号')
        if user['role'] == 'admin':
            from .policy_admin import workspace_password
            workspace_password(data)
        return logged_in(user)

    @router.post('/logout')
    def logout(request: Request):
        response = JSONResponse({'ok': True})
        workspace.sessions.pop(request.cookies.get(AUTH_COOKIE, ''), None)
        response.delete_cookie(COOKIE)
        response.delete_cookie(AUTH_COOKIE)
        return response

    @router.post('/password')
    async def change_password(request: Request):
        current = store.user(request.cookies.get(COOKIE, ''))
        if current and current['role'] != 'admin':
            raise HTTPException(403, '请退出登录后使用原管理员密码修改')
        if request.headers.get('origin') not in (None, str(request.base_url).rstrip('/')):
            raise HTTPException(403, '拒绝跨站密码请求')
        from .policy_admin import workspace_password
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(400, '密码请求格式错误')
        workspace_password(data, change=True)
        workspace.sync_admin_sessions()
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE)
        response.delete_cookie(AUTH_COOKIE)
        return response

    @router.post('/users')
    async def users(request: Request):
        user = workspace.authorize(request, admin=True)
        data = await request.json()
        return store.add_user(data.get('employee_id'), data.get('name'), data.get('role', 'manager'), actor_id=user['employee_id'], owner_ids=data.get('owner_ids'))

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

    @router.get('/manager-matches')
    def manager_matches(analysis_id: str, request: Request):
        workspace.authorize(request, admin=True)
        with service._fact_lock:
            return workspace.manager_matches(service.get_analysis(analysis_id))

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
                if analysis.assessment.get('deleted') or analysis.assessment.get('attached_to'):
                    continue
                if not analysis.assessment.get('confirmed') and user['role'] != 'admin':
                    continue
                row = workspace.summary(analysis, user)
                if user['role'] == 'admin' or row['managers']:
                    result.append(row)
            return sorted(result, key=lambda r: r['created_at'], reverse=True)

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
