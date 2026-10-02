"""Validate report provenance before resolving any account or questionnaire scope."""


def owner_groups(analysis):
    groups, sources = {}, {}
    for row in [*analysis.reports, *analysis.sessions]:
        identity = row.manager_identity or {}
        owner = identity.get('owner_id', '')
        sources.setdefault(row.source_name, set()).add(owner)
        entry = groups.setdefault(owner or row.source_name, {
            'owner_id': owner, 'names': set(), 'reports': set(), 'resolved': True,
            'local': (owner.startswith('local:') or getattr(row, 'source_type', '') == 'local_excel')
                     and not identity.get('source_token')})
        entry['names'].add(identity.get('name', '').strip())
        entry['reports'].add(row.source_name)
        entry['resolved'] &= identity.get('status') == 'resolved' and bool(owner)
    for group in groups.values():
        if any(len(sources[source]) != 1 for source in group['reports']):
            group['resolved'] = False
    return list(groups.values())


def resolve_owners(analysis, users, bindings=None):
    """Names select accounts; prior owner bindings may only veto a conflict."""
    mapping, errors = {}, []
    bindings = bindings or {}
    for group in owner_groups(analysis):
        owner, names = group['owner_id'], group['names']
        name = next(iter(names)) if len(names) == 1 else ''
        matches = [u for u in users if u['enabled'] and u['name'].strip() == name]
        reason = ''
        if not group['resolved'] or not name:
            reason = '报告所有者身份缺失或同一所有者姓名不一致，请重新核对来源'
        elif len(matches) != 1:
            reason = '原文件所有者姓名未唯一匹配本任务启用名单，请核对人员配置'
        elif group['local'] and owner != 'local:' + matches[0]['employee_id']:
            reason = '本地报告编号与姓名不一致，请重新指定'
        elif owner in bindings and bindings[owner] != matches[0]['employee_id']:
            reason = '历史归属与报告所有者姓名冲突，已阻止分配，请核对后修正历史归属'
        if reason:
            errors.append({'owner_id': owner, 'name': name, 'reason': reason,
                           'local': group['local'], 'can_assign': group['local'],
                           'reports': sorted(group['reports'])})
        else:
            mapping[owner] = matches[0]['employee_id']
    return mapping, errors


def snapshot_errors(analysis):
    """Frozen names, not a mutable global directory, validate historical ownership."""
    mapping = analysis.assessment.get('manager_accounts')
    if mapping is None:
        return []
    names = analysis.assessment.get('manager_names', {})
    errors = set()
    for group in owner_groups(analysis):
        owner = group['owner_id']
        if not group['resolved']:
            errors.update(group['reports'])
        if owner not in mapping:
            continue  # Older snapshots only included owners with reviewer intersections.
        if (not group['resolved'] or len(group['names']) != 1
                or not names.get(mapping[owner]) or group['names'] != {names[mapping[owner]]}
                or (group['local'] and owner != 'local:' + mapping[owner])):
            errors.update(group['reports'])
    return sorted(errors)
