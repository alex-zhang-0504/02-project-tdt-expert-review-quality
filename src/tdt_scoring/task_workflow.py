"""Task lifecycle layered on the existing main assessment and scoring modules."""
from copy import deepcopy
from hashlib import sha256
import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from . import accounts, questionnaire, scoring_policy
from .models import WorkbookAnalysis
from .policy_admin import atomic_write, file_lock
from .score_statistics import build_statistics
from .storage import now


def started(analysis):
    return bool(analysis.assessment.get('started') or any(
        r.get('ratings') for reviews in analysis.manager_reviews.values() for r in reviews.values()) or any(
        item.get('after', {}).get('ratings') for reviews in analysis.assessment.get('review_history', {}).values()
        for history in reviews.values() for item in history))


def result_state(analysis):
    if not analysis.assessment.get('confirmed'):
        return None, False
    data = build_statistics(analysis)
    return data, bool(data['rows']) and all(r['total'] is not None for r in data['rows'])


def policy_receipt(analysis, scope):
    if scope not in ('objective', 'subjective'):
        raise ValueError('未知参数范围')
    path = questionnaire.POLICY_PATH if scope == 'subjective' else scoring_policy.POLICY_PATH
    receipt = deepcopy(analysis.assessment.get('questionnaire' if scope == 'subjective' else 'policy') or
                       (questionnaire.load() if scope == 'subjective' else scoring_policy.load_policy()))
    if scope == 'subjective':
        receipt['parameters']['evidence'] = questionnaire.evidence_rules(receipt['parameters'])
    history = [{'at': h['at'], 'actor': h['actor']['name'], 'before': h['before']['sha256'], 'after': h['after']['sha256']}
               for h in analysis.assessment.get('parameter_history', []) if h['scope'] == scope]
    return {**receipt, 'history': history, 'file_hash': sha256(path.read_bytes()).hexdigest(),
            'task_revision': analysis.assessment.get('parameter_revision', 0), 'content_locked': started(analysis)}


def create_task_router(workspace, encode, busy):
    router = APIRouter(prefix='/api/workspace/tasks')
    service, store = workspace.service, workspace.store

    def admin(request):
        return workspace.authorize(request, admin=True)

    @router.post('')
    async def create(request: Request):
        user = admin(request)
        data = await request.json()
        year, period = str(data.get('year', '')), data.get('period')
        if not year.isdigit() or not 2000 <= int(year) <= 2100 or period not in ('年度', '上半年', '下半年'):
            raise ValueError('请选择有效年份与考评周期')
        imported = accounts.validate(data.get('accounts'))
        if not any(u['enabled'] and u['role'] == 'manager' for u in imported):
            raise ValueError('配置至少需要一位启用的项目经理')
        with service._fact_lock:
            if any(a.assessment.get('year') == year and a.assessment.get('period') == period and not a.assessment.get('deleted') for a in service._analyses.values()):
                raise ValueError('该年份与周期已有任务，请从任务卡片打开')
            # Import only additive/identical identities; edits use the existing account directory.
            current = store.users(include_disabled=True)
            merged = {u['employee_id']: u for u in current}
            for u in imported:
                if u['employee_id'] in merged and merged[u['employee_id']] != u:
                    raise ValueError('导入名单与已有账号配置不一致，请先核对账号配置文件')
                merged[u['employee_id']] = u
            users = accounts.validate({'version': 1, 'users': list(merged.values())})
            definition = questionnaire.load()
            a = WorkbookAnalysis(uuid4().hex, 'workspace', year + period + '评审人考核', [], [], [])
            a.assessment = {'year': year, 'period': period, 'created_at': now(), 'created_by': user['employee_id'],
                            'task_users': imported, 'questionnaire': definition, 'policy': scoring_policy.load_policy(definition)}
            with store._lock:
                raw = store.accounts_path.read_bytes()
                replacement = accounts.content(users)
                replaced = False
                try:
                    with store.connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        store._snapshot_accounts(db, users)
                        revision = store.save(a, 0, db)
                        accounts.replace(store.accounts_path, replacement, raw)
                        replaced = True
                except Exception:
                    if replaced:
                        accounts.replace(store.accounts_path, raw, replacement)
                    raise
            service._revisions[a.analysis_id] = revision
            service._analyses[a.analysis_id] = a
            return encode(a)

    @router.post('/{task_id}/reports')
    async def adopt(task_id: str, request: Request):
        admin(request)
        data = await request.json()
        with service.edit_analysis(task_id, persist=False) as target:
            source = service.get_analysis(data['analysis_id'])
            if source.analysis_id == task_id or source.assessment.get('year') or source.assessment.get('confirmed') or source.assessment.get('attached_to') not in (None, task_id):
                raise ValueError('请选择本任务新读取的报告')
            for key in ('source_type', 'sessions', 'experts', 'issues', 'reports', 'batch_summary', 'rule_version', 'ai_message'):
                setattr(target, key, deepcopy(getattr(source, key)))
            target.assessment['confirmed'] = False
            for key in ('manager_accounts', 'manager_names'):
                target.assessment.pop(key, None)
            with service.edit_analysis(source.analysis_id, persist=False):
                source.assessment['attached_to'] = task_id
                with store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    target_revision = store.save(target, service._revisions[task_id], db)
                    source_revision = store.save(source, service._revisions[source.analysis_id], db)
                service._revisions.update({task_id: target_revision, source.analysis_id: source_revision})
            return encode(target)

    @router.post('/{task_id}/scope')
    def invalidate(task_id: str, request: Request):
        admin(request)
        with service.edit_analysis(task_id) as a:
            a.assessment['confirmed'] = False
            return encode(a)

    @router.delete('/{task_id}')
    async def delete(task_id: str, request: Request):
        admin(request)
        data = await request.json()
        if busy():
            raise HTTPException(409, '请等待报告读取及分析结束后再删除任务')
        # Retain durable history in backups; deleted tasks cannot be viewed or edited.
        with service._fact_lock:
            a = service.get_analysis(task_id)
            if data.get('name') != a.source_name or data.get('confirmed') is not True:
                raise ValueError('请核对任务名称并确认删除')
            old = deepcopy(a.assessment)
            a.assessment['deleted'] = True
            try:
                service.persist(a)
            except Exception:
                a.assessment = old
                raise
        return {'ok': True}

    @router.get('/{task_id}/history')
    def history(task_id: str, request: Request):
        admin(request)
        a = service.get_analysis(task_id)
        if not a.assessment.get('completed'):
            raise ValueError('本期考评尚未完成')
        return {'name': a.source_name, **deepcopy(a.assessment['completion'])}

    @router.post('/{task_id}/complete')
    async def complete(task_id: str, request: Request):
        user = admin(request)
        data = await request.json()
        if data.get('confirmed') is not True or busy():
            raise ValueError('请等待操作结束并二次确认完成本期考评')
        with service.edit_analysis(task_id) as a:
            statistics, ready = result_state(a)
            if not ready:
                raise ValueError('客观评价、全部问卷或有效总分尚未完成')
            a.assessment.update(completed=True, finalized=True, completion={
                'at': now(), 'actor': user, 'statistics': deepcopy(statistics),
                'policy': deepcopy(a.assessment['policy']), 'questionnaire': deepcopy(a.assessment['questionnaire'])})
        return {'completed': True}

    @router.get('/{task_id}/policy/{scope}')
    def read_policy(task_id: str, scope: str, request: Request):
        admin(request)
        a = service.get_analysis(task_id)
        if a.assessment.get('completed'):
            raise ValueError('历史任务参数只读')
        return policy_receipt(a, scope)

    @router.put('/{task_id}/policy/{scope}')
    async def save_policy(task_id: str, scope: str, request: Request):
        user = admin(request)
        data = await request.json()
        path = questionnaire.POLICY_PATH if scope == 'subjective' else scoring_policy.POLICY_PATH
        with file_lock(path.with_suffix('.lock')), service.edit_analysis(task_id, persist=False) as a:
            old = policy_receipt(a, scope)
            if data.get('file_hash') != old['file_hash'] or data.get('task_revision') != old['task_revision']:
                raise HTTPException(409, '配置或任务已变化，请重新打开核对')
            params = deepcopy(data.get('parameters'))
            if not isinstance(params, dict):
                raise ValueError('请提交有效评分参数')
            before = deepcopy(a.assessment)
            if scope == 'subjective':
                # Ignore the numerical version when comparing meaning; answers survive numeric changes only.
                semantics = lambda p: {k: v for k, v in p.items() if k not in ('version', 'scores')}
                if started(a) and semantics(params) != semantics(old['parameters']):
                    raise ValueError('已有问卷开始填写，题干、选项含义和依据要求不能再修改')
                params['version'] = str(int(questionnaire.load()['version']) + 1)
                raw = json.dumps(params, ensure_ascii=False, indent=2, allow_nan=False).encode() + b'\n'
                q = questionnaire.parse(raw)
                a.assessment['questionnaire'] = q
                p = deepcopy(a.assessment.get('policy') or scoring_policy.load_policy(q))
                p['parameters']['subjective'] = deepcopy(params['scores'])
                p['questionnaire_hash'] = q['sha256']
                p['sha256'] = sha256(json.dumps(p['parameters'], sort_keys=True).encode() + q['sha256'].encode()).hexdigest()
                a.assessment['policy'] = p
                from .subjective import rating_result
                dims = questionnaire.dimensions(a)
                for reviews in a.manager_reviews.values():
                    for record in reviews.values():
                        if record.get('questionnaire_hash') == old['sha256']:
                            record['questionnaire_hash'] = q['sha256']
                            checks = [rating_result(d, record['ratings'].get(d['id'], {})) for d in dims]
                            record['status'] = '已完成' if all(x['responded'] for x in checks) else '待评价'
                            record['revision'] = record.get('revision', 0) + 1
            elif scope == 'objective':
                keys = {'stage_weights','components','participation','opinion_threshold','excess_opinion_points','solution_points'}
                if not isinstance(params, dict) or set(params) != keys:
                    raise ValueError('客观入口只能修改客观数值参数')
                merged = deepcopy(old['parameters']); merged.update(params)
                a.assessment['policy'] = scoring_policy.parse_policy(json.dumps(merged, allow_nan=False).encode())
                raw = json.dumps({k:v for k,v in merged.items() if k != 'subjective'}, ensure_ascii=False, indent=2).encode() + b'\n'
            else:
                raise ValueError('未知参数范围')
            a.assessment['parameter_revision'] = old['task_revision'] + 1
            a.assessment.setdefault('parameter_history', []).append({'at': now(), 'actor': user, 'scope': scope,
                'before': before['questionnaire' if scope == 'subjective' else 'policy'],
                'after': deepcopy(a.assessment['questionnaire' if scope == 'subjective' else 'policy'])})
            original = path.read_bytes()
            try:
                atomic_write(path, raw)
                if path.read_bytes() != raw:
                    raise OSError('参数写后核验失败')
                # Persist here so a failed database save can restore the previous file as well.
                service.persist(a)
            except Exception:
                atomic_write(path, original)
                raise
            return policy_receipt(a, scope)

    return router
