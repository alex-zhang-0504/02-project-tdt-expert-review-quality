"""Local administrator authorization and atomic scoring-policy updates."""
from contextlib import contextmanager
from hashlib import pbkdf2_hmac, sha256
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
from threading import Lock
from time import monotonic

from fastapi import APIRouter, HTTPException, Request

from . import scoring_policy, questionnaire

ADMIN_PATH = Path(__file__).resolve().parents[2] / 'var' / 'scoring-admin.json'
ITERATIONS = 600_000
_login_failures = []
_login_lock = Lock()


def credential_version():
    return sha256(ADMIN_PATH.read_bytes()).hexdigest() if ADMIN_PATH.exists() else None


def workspace_password(data, *, change=False):
    """Use the existing local administrator credential for workspace login."""
    password = data.get('password')
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise HTTPException(400, '管理员密码长度须为8至128位')
    if change:
        new_password = data.get('new_password')
        if not isinstance(new_password, str) or not 8 <= len(new_password) <= 128:
            raise HTTPException(400, '新密码长度须为8至128位')
        if new_password != data.get('confirmation'):
            raise HTTPException(400, '两次输入的新密码不一致')
        if new_password == password:
            raise HTTPException(400, '新密码不能与原密码相同')
    with _login_lock, file_lock(ADMIN_PATH.with_suffix('.lock')):
        stamp = monotonic()
        _login_failures[:] = [t for t in _login_failures if stamp - t < 60]
        if len(_login_failures) >= 5:
            raise HTTPException(429, '密码尝试过多，请一分钟后重试')
        if not ADMIN_PATH.exists():
            if change:
                raise HTTPException(409, '尚未设置管理员密码，请重新登录')
            if data.get('confirmation') != password:
                raise HTTPException(400, '首次登录请设置密码，两次输入须一致')
            salt = secrets.token_bytes(32)
            atomic_write(ADMIN_PATH, json.dumps({'salt': salt.hex(), 'hash': pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS).hex()}).encode())
        else:
            record = json.loads(ADMIN_PATH.read_bytes())
            digest = pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(record['salt']), ITERATIONS).hex()
            if not hmac.compare_digest(record['hash'], digest):
                _login_failures.append(stamp)
                raise HTTPException(403, '管理员密码不正确')
        if change:
            salt = secrets.token_bytes(32)
            content = json.dumps({'salt': salt.hex(), 'hash': pbkdf2_hmac('sha256', new_password.encode(), salt, ITERATIONS).hex()}).encode()
            try:
                atomic_write(ADMIN_PATH, content)
                if ADMIN_PATH.read_bytes() != content:
                    raise OSError()
            except OSError:
                raise HTTPException(500, '密码保存或核验失败，请重新登录确认') from None
        _login_failures.clear()


@contextmanager
def file_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise HTTPException(409, '配置正在被其他窗口修改，请稍后重试') from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '-')
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def create_policy_admin_router():
    router = APIRouter(prefix='/api/assessment/admin')
    sessions, failures = {}, []
    lock = Lock()

    def guard(request):
        if (request.url.hostname not in {'localhost', '127.0.0.1', '::1'}
                or not request.client or request.client.host not in {'127.0.0.1', '::1'}):
            raise HTTPException(403, '评分参数管理仅限本机访问')
        if request.headers.get('x-policy-request') != '1':
            raise HTTPException(403, '请通过评分参数界面操作')
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            raise HTTPException(403, '拒绝跨站配置请求')

    def authorize(request):
        guard(request)
        token = request.headers.get('x-policy-session', '')
        if token not in sessions or sessions[token] != credential_version():
            raise HTTPException(401, '管理员授权已失效，请重新解锁')

    async def body(request):
        guard(request)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536:
                raise HTTPException(413, '配置请求过大')
        try:
            data = json.loads(raw)
            if not isinstance(data, dict): raise ValueError()
            return data
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, '配置请求格式错误') from None

    @router.get('/status')
    def status(request: Request):
        guard(request)
        return {'configured': ADMIN_PATH.exists()}

    @router.post('/unlock')
    async def unlock(request: Request):
        data = await body(request)
        password = data.get('password')
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise HTTPException(400, '管理员密码长度须为8至128位')
        with lock, file_lock(ADMIN_PATH.with_suffix('.lock')):
            now = monotonic()
            failures[:] = [stamp for stamp in failures if now - stamp < 60]
            if len(failures) >= 5:
                raise HTTPException(429, '密码尝试过多，请一分钟后重试')
            if data.get('setup') is True:
                if ADMIN_PATH.exists():
                    raise HTTPException(409, '管理员密码已设置，请使用密码解锁')
                if password != data.get('confirmation'):
                    raise HTTPException(400, '两次输入的密码不一致')
                salt = secrets.token_bytes(32)
                record = {'salt': salt.hex(), 'hash': pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS).hex()}
                try:
                    atomic_write(ADMIN_PATH, json.dumps(record).encode())
                except OSError:
                    raise HTTPException(500, '管理员设置未写入成功，请检查目录权限') from None
            else:
                try:
                    record = json.loads(ADMIN_PATH.read_bytes())
                    digest = pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(record['salt']), ITERATIONS).hex()
                    valid = hmac.compare_digest(record['hash'], digest)
                except (OSError, ValueError, KeyError, TypeError):
                    valid = False
                if not valid:
                    failures.append(now)
                    raise HTTPException(403, '管理员密码不正确或尚未设置')
            failures.clear()
            token = secrets.token_urlsafe(32)
            sessions[token] = credential_version()
            return {'token': token}

    @router.post('/lock')
    def relock(request: Request):
        guard(request)
        with lock:
            sessions.pop(request.headers.get('x-policy-session', ''), None)
        return {'locked': True}

    objective_keys = {'stage_weights', 'components', 'opinion_threshold', 'participation', 'excess_opinion_points', 'solution_points'}

    @router.get('/policy/{scope}')
    def read_policy(scope: str, request: Request):
        guard(request)
        if scope == 'subjective': return questionnaire.load()
        if scope == 'objective': return scoring_policy.load_policy()
        raise HTTPException(400, '未知参数范围')

    @router.put('/policy')
    @router.put('/policy/{scope}')
    async def update(request: Request, scope: str = 'objective'):
        data = await body(request)
        with lock, file_lock(ADMIN_PATH.with_suffix('.lock')):
            authorize(request)
            try:
                parameters = data.get('parameters')
                if not isinstance(parameters, dict): raise ValueError()
                if scope == 'subjective':
                    previous = questionnaire.load()
                    if data.get('previous_hash') != previous['sha256']:
                        raise HTTPException(409, '配置已被其他窗口修改，请重新打开后编辑')
                    if parameters.get('version') != previous['parameters']['version']: raise ValueError()
                    parameters['version'] = str(int(previous['version']) + 1)
                    raw = json.dumps(parameters, ensure_ascii=False, indent=2, allow_nan=False).encode() + b'\n'
                    receipt = questionnaire.parse(raw)
                    path, read = questionnaire.POLICY_PATH, questionnaire.load
                elif scope == 'objective':
                    previous = scoring_policy.load_policy()
                    if data.get('previous_hash') != previous['sha256']:
                        raise HTTPException(409, '配置已被其他窗口修改，请重新打开配置后编辑')
                    merged = dict(previous['parameters'])
                    if set(parameters) == objective_keys:
                        merged.update(parameters)
                    elif set(parameters) == set(merged) and all(parameters[k] == merged[k] for k in set(merged)-objective_keys):
                        merged = parameters
                    else:
                        raise ValueError('客观入口不得修改主观或全局参数')
                    scoring_policy.parse_policy(json.dumps(merged, allow_nan=False).encode())
                    stored = {k: v for k, v in merged.items() if k != 'subjective'}
                    raw = json.dumps(stored, ensure_ascii=False, indent=2, allow_nan=False).encode() + b'\n'
                    receipt = {'sha256': sha256(raw).hexdigest()}
                    path, read = scoring_policy.POLICY_PATH, scoring_policy.load_policy
                else:
                    raise ValueError()
            except (ValueError, TypeError):
                raise HTTPException(400, '参数无效或超出编辑范围，请核对文案、分值及权重') from None
            try:
                atomic_write(path, raw)
                if sha256(path.read_bytes()).hexdigest() != sha256(raw).hexdigest(): raise ValueError()
                persisted = read()
            except (OSError, ValueError):
                raise HTTPException(500, '配置写入或写后核验失败，请重新读取确认，未宣告保存成功') from None
            sessions.pop(request.headers.get('x-policy-session', ''), None)
            return persisted

    return router
