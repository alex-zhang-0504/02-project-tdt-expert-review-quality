"""Read original-file ownership; never infer a manager from editor metadata."""
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from subprocess import TimeoutExpired

POLICY_PATH = Path(__file__).resolve().parents[2] / 'config' / 'report-owner-policy-v0.1.json'


def request(arguments):
    from .sources.feishu_document import FeishuDocumentSource as Source
    try:
        response = Source._run_cli(arguments, timeout=60)
        payload = Source._payload(response)
        if response.returncode or payload.get('ok') is False:
            return {}, Source._error_message(response)
        data = payload.get('data')
        return (data, '') if isinstance(data, dict) else ({}, '飞书身份信息返回格式异常')
    except (RuntimeError, OSError, TimeoutExpired):
        return {}, '飞书身份信息读取失败或超时，请检查连接后重扫'


def load_policy():
    try:
        raw = POLICY_PATH.read_bytes()
        policy = json.loads(raw)
        required = {'feishu_manager_source': 'original_file.owner_id',
                    'owner_is_project_manager': True, 'identity_type': 'open_id',
                    'resolve_shortcuts': True, 'fallback_to_creator_or_editor': False,
                    'missing_owner': 'unresolved', 'local_excel': 'explicit_assignment'}
        if not isinstance(policy, dict) or policy.get('version') != '0.1':
            raise ValueError()
        if any(policy.get(k) != v or type(policy.get(k)) is not type(v) for k, v in required.items()):
            raise ValueError()
        return {'version': policy['version'], 'sha256': sha256(raw).hexdigest(),
                'file': 'config/' + POLICY_PATH.name,
                'loaded_at': datetime.now(timezone.utc).isoformat()}
    except (OSError, ValueError, TypeError):
        raise ValueError('技术项目经理识别配置未读取或内容无效，未识别技术项目经理') from None


def read_owners(tokens):
    tokens = list(dict.fromkeys(t for t in tokens if t))
    result = {t: {'source_token': t, 'owner_id': '', 'name': '', 'status': 'unresolved',
                  'error': '', 'policy': None} for t in tokens}
    try:
        receipt = load_policy()
    except ValueError as exc:
        for entry in result.values():
            entry['error'] = str(exc)
        return result
    for entry in result.values():
        entry['policy'] = receipt
    for offset in range(0, len(tokens), 200):
        batch = tokens[offset:offset + 200]
        data, error = request(['drive', 'metas', 'batch_query', '--as', 'user',
            '--params', json.dumps({'user_id_type': 'open_id'}), '--data',
            json.dumps({'request_docs': [{'doc_token': t, 'doc_type': 'sheet'} for t in batch]})])
        if error:
            for token in batch:
                result[token]['error'] = error
            continue
        for meta in data.get('metas', []):
            token, owner = meta.get('doc_token'), meta.get('owner_id')
            if token in result and isinstance(owner, str) and owner.startswith('ou_'):
                result[token].update(owner_id=owner, status='name_unresolved')
        for token in batch:
            if not result[token]['owner_id']:
                result[token]['error'] = '未取得原文件owner_id，请检查文件元数据权限'
    owners = list(dict.fromkeys(v['owner_id'] for v in result.values() if v['owner_id']))
    for offset in range(0, len(owners), 30):
        batch = owners[offset:offset + 30]
        data, error = request(['contact', '+search-user', '--as', 'user', '--user-ids',
            ','.join(batch), '--lang', 'zh_cn', '--page-size', '30'])
        users = data.get('users', [])
        names = {u.get('open_id'): u.get('localized_name', '').strip() for u in users if isinstance(u, dict)}
        for entry in result.values():
            if entry['owner_id'] not in batch:
                continue
            name = names.get(entry['owner_id'])
            if name:
                entry.update(name=name, status='resolved', error='')
            else:
                entry['error'] = error or '已取得owner_id，但未取得所有者姓名，请检查通讯录读取权限'
    return result


def read_owner_url(url):
    from .sources.feishu_document import FeishuDocumentSource as Source
    token = Source._spreadsheet_token_from_url(url)
    if not token:
        data, _ = request(['drive', '+inspect', '--as', 'user', '--url', Source.cli_url(url)])
        if data.get('type') == 'sheet':
            token = data.get('token', '')
    if not token:
        return {'source_token': '', 'owner_id': '', 'name': '', 'status': 'unresolved',
                'error': '未能解析原始电子表格身份，未识别技术项目经理', 'policy': None}
    try:
        return read_owners([token])[token]
    except (RuntimeError, OSError, TimeoutExpired) as exc:
        return {'source_token': token, 'owner_id': '', 'name': '', 'status': 'unresolved',
                'error': '技术项目经理读取失败：' + str(exc), 'policy': None}


def apply_owner(sessions, identity):
    for session in sessions:
        session.manager_identity = dict(identity)
        session.project_manager = identity.get('name', '')
