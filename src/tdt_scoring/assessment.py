"""Roster intersection and stable manager/reviewer assignment."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import re

from openpyxl import load_workbook
from .excel_reader import normalize_person_name
from .scoring_policy import load_policy


def require_selected(analysis):
    if not analysis.assessment.get('confirmed'):
        raise ValueError('请先在读取评审表模块确认考核名单')


def selected_experts(analysis):
    names = analysis.assessment.get('included')
    return [e for e in analysis.experts if names is None or e.expert_name in names]


def roster_from_excel(content):
    try:
        wb = load_workbook(BytesIO(content), read_only=True, data_only=True)
        rows = list(wb.active.values)
        headers = ('评审人', '评审人姓名', '姓名')
        for i, row in enumerate(rows[:20]):
            column = next((j for j, v in enumerate(row) if str(v).strip() in headers), None)
            if column is not None:
                return [str(r[column]).strip() for r in rows[i+1:] if len(r) > column and r[column] is not None]
        raise ValueError('名单需包含「姓名」「评审人」或「评审人姓名」列')
    except (OSError, KeyError, TypeError):
        raise ValueError('无法读取考核名单Excel') from None


def match_roster(analysis, names):
    if isinstance(names, str):
        names = [names]
    parts = [part for value in names for part in re.split(r'[\s、,，.。;；]+', str(value)) if part]
    normalized = list(dict.fromkeys(normalize_person_name(n) for n in parts))
    normalized = [n for n in normalized if n]
    available = {normalize_person_name(e.expert_name): e.expert_name for e in analysis.experts}
    included = [available[n] for n in normalized if n in available]
    return {'requested': normalized, 'included': included,
            'unmatched': [n for n in normalized if n not in available],
            'excluded': [e.expert_name for e in analysis.experts if e.expert_name not in included]}


def confirm_roster(analysis, names, batch_id, policy_hash=None):
    from .subjective import require_analysis
    require_analysis(analysis)
    if analysis.assessment.get('confirmed'):
        raise ValueError('本批次名单已固定；调整名单请重新导入报告建立新批次')
    if not batch_id.strip():
        raise ValueError('请填写考核批次编号')
    result = match_roster(analysis, names)
    if not result['included']:
        raise ValueError('名单与报告没有交集，不能开始考核')
    from .questionnaire import load as load_questionnaire
    questionnaire = load_questionnaire()
    policy = load_policy(questionnaire)
    if policy_hash is not None and policy_hash != policy['sha256']:
        raise ValueError('评分参数已变化，请重新读取评分参数后再进入')
    result.update(confirmed=True, batch_id=batch_id.strip(), policy=policy, questionnaire=questionnaire, exclusions={})
    result['roster_hash'] = sha256(json.dumps(sorted(result['included']), ensure_ascii=False).encode()).hexdigest()
    analysis.assessment = result
    unresolved = tasks(analysis)['unresolved_reports']
    if unresolved:
        analysis.assessment = {}
        raise ValueError('请先识别或明确指定这些报告的项目经理：' + '；'.join(unresolved))
    return result


def assign_local_manager(analysis, source_name, manager_id, name):
    if analysis.assessment.get('confirmed'):
        raise ValueError('名单已确认，经理归属已固定；请建立新批次后调整')
    if not manager_id.strip() or not name.strip():
        raise ValueError('本地报告需明确填写经理编号及姓名')
    if any(s.source_name != source_name and s.manager_identity.get('owner_id') == 'local:' + manager_id.strip()
           and s.manager_identity.get('name') != name.strip() for s in analysis.sessions):
        raise ValueError('同一经理编号对应的姓名不一致，请核对后指定')
    sessions = [s for s in analysis.sessions if s.source_name == source_name]
    reports = [r for r in analysis.reports if r.source_name == source_name]
    if not sessions or any(r.source_type.startswith('feishu') for r in reports) or any(s.manager_identity.get('source_token') for s in sessions):
        raise ValueError('只能指定本地报告的经理，飞书报告须使用原文件所有者')
    identity = {'owner_id': 'local:' + manager_id.strip(), 'name': name.strip(), 'status': 'resolved', 'source': 'explicit_assignment'}
    for s in sessions:
        s.manager_identity, s.project_manager = deepcopy(identity), name.strip()
    for r in analysis.reports:
        if r.source_name == source_name:
            r.manager_identity = deepcopy(identity)


def tasks(analysis):
    require_selected(analysis)
    result = {}
    unresolved = set()
    for expert in selected_experts(analysis):
        # Actual project intersection, not merely being on an invitation list.
        projects = {s.project_code for s in expert.sessions if s.attended}
        for report in analysis.sessions:
            if report.project_code not in projects:
                continue
            identity = report.manager_identity
            if identity.get('status') != 'resolved' or not identity.get('owner_id'):
                unresolved.add(report.source_name)
                continue
            mid = identity['owner_id']
            manager = result.setdefault(mid, {'manager_id': mid, 'name': identity['name'], 'experts': {}})
            manager['experts'].setdefault(expert.expert_name, set()).add(report.project_code)
    for manager in result.values():
        manager['experts'] = {n: sorted(codes) for n, codes in manager['experts'].items()}
    return {'managers': list(result.values()), 'unresolved_reports': sorted(unresolved)}


def manager_task(analysis, manager_id, expert_name):
    catalog = tasks(analysis)
    if catalog['unresolved_reports']:
        raise ValueError('仍有报告的项目经理待识别，请在名单确认前完成经理指定或重新导入')
    manager = next((m for m in catalog['managers'] if m['manager_id'] == manager_id), None)
    if not manager or expert_name not in manager['experts']:
        raise ValueError('该经理与评审人没有实际项目交集，不能评价')
    return manager


def exclude_task(analysis, manager_id, expert_name, reason):
    manager_task(analysis, manager_id, expert_name)
    key = json.dumps([manager_id, expert_name], ensure_ascii=False)
    if reason.strip():
        analysis.assessment['exclusions'][key] = reason.strip()
    else:
        analysis.assessment['exclusions'].pop(key, None)


def is_excluded(analysis, manager_id, expert_name):
    return analysis.assessment.get('exclusions', {}).get(json.dumps([manager_id, expert_name], ensure_ascii=False), '')
