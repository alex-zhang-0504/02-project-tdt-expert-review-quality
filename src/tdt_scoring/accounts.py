"""The editable JSON account directory; SQLite holds only its backup snapshot."""
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory


def validate(data, *, require_admin=True):
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('users'), list):
        raise ValueError('账号配置须包含version为1及users数组')
    users, seen, owners, names = [], set(), set(), set()
    for user in data['users']:
        required = {'employee_id', 'name', 'role', 'enabled'}
        if not isinstance(user, dict) or not required <= set(user) or set(user) - required - {'owner_ids'}:
            raise ValueError('账号须包含employee_id、name、role、enabled，可设置owner_ids数组')
        eid, name = user['employee_id'], user['name']
        if not isinstance(eid, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', eid):
            raise ValueError('工号须为1至64位字母、数字、点、短横线或下划线，保留前导零')
        if eid in seen:
            raise ValueError('该工号已有账号，请使用已有账号')
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or user['role'] not in ('manager', 'admin'):
            raise ValueError('请填写有效姓名和角色')
        if type(user['enabled']) is not bool:
            raise ValueError('enabled须为true或false')
        if user['enabled']:
            if name.strip() in names:
                raise ValueError('启用账号的姓名不能重复，请核对配置')
            names.add(name.strip())
        ids = user.get('owner_ids', [])
        if not isinstance(ids, list) or any(not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', owner) for owner in ids):
            raise ValueError('owner_ids须为ID字符串数组，仅允许字母、数字、下划线和短横线')
        if len(set(ids)) != len(ids) or owners.intersection(ids):
            raise ValueError('同一owner ID只能归属一个账号，配置中不能重复')
        owners.update(ids)
        seen.add(eid)
        users.append({**user, 'name': name.strip(), 'owner_ids': ids})
    if require_admin and users and not any(u['enabled'] and u['role'] == 'admin' for u in users):
        raise ValueError('不能删除或停用最后一个管理员账号，也不能将其改为技术项目经理')
    return users


def parse(raw):
    try:
        return validate(json.loads(raw.decode('utf-8-sig')))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('accounts.json格式错误，请修正JSON后刷新；未覆盖文件') from exc


def import_directory(data, current, *, task=False):
    """Accept a three-field manager roster, preserving internal account metadata.

    task=True imports one task's roster: people absent or disabled there keep their
    account state, so other tasks' rosters and logins are unaffected; only people
    enabled in this roster are enabled for login. Account deactivation stays in the
    account directory itself.
    """
    imported, merged = _merge_directory(data, current)
    if task:
        previous = {u['employee_id']: u['enabled'] for u in current}
        wanted = {u['employee_id'] for u in imported if u['enabled']}
        merged = validate({'version': 1, 'users': [
            dict(u, enabled=previous[u['employee_id']] or u['employee_id'] in wanted) if u['employee_id'] in previous else u
            for u in merged]})
    return imported, merged


def _merge_directory(data, current):
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('users'), list):
        raise ValueError('技术项目经理配置须包含version为1及users数组')
    simple = all(isinstance(u, dict) and set(u) == {'name', 'employee_id', 'enabled'} for u in data['users'])
    if not simple:
        imported = validate(data)
        merged = {u['employee_id']: u for u in current}
        for row in merged.values():
            if row['role'] == 'manager':
                row = dict(row)
                row['enabled'] = False
                merged[row['employee_id']] = row
        for user in imported:
            old = merged.get(user['employee_id'])
            if old:
                user['owner_ids'] = list(dict.fromkeys(old.get('owner_ids', []) + user['owner_ids']))
            merged[user['employee_id']] = user
        return imported, validate({'version': 1, 'users': list(merged.values())})
    by_id = {u['employee_id']: u for u in current}
    imported = validate({'version': 1, 'users': [{**row, 'role': 'manager'} for row in data['users']]}, require_admin=False)
    names = set()
    for row in imported:
        row['owner_ids'] = by_id.get(row['employee_id'], {}).get('owner_ids', [])
        if row['enabled']:
            name = row['name']
            if name in names:
                raise ValueError('启用的技术项目经理姓名不能重复，请核对配置')
            names.add(name)
    merged = {u['employee_id']: dict(u) for u in current}
    for user in merged.values():
        if user['role'] == 'manager':
            user['enabled'] = False
    for row in imported:
        old = merged.get(row['employee_id'])
        merged[row['employee_id']] = {**row, 'role': old['role'], 'enabled': old['enabled']} if old and old['role'] == 'admin' else row
    return [dict(row, role=merged[row['employee_id']]['role']) for row in imported], validate({'version': 1, 'users': list(merged.values())})


def content(users):
    return (json.dumps({'version': 1, 'users': users}, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def replace(path, raw, expected):
    """Atomic file replacement after checking the bytes read by this operation."""
    path = Path(path)
    with TemporaryDirectory(prefix='accounts-write-', dir=path.parent) as directory:
        staged = Path(directory) / 'accounts.json'
        with staged.open('wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        current = path.read_bytes() if path.exists() else None
        if current != expected:
            raise ValueError('账号配置已在另一端修改，本次未覆盖；请刷新后核对')
        os.replace(staged, path)
    if path.read_bytes() != raw:
        raise ValueError('账号配置写后核验不一致，请刷新核对，不要重复提交')
