"""Local administrator authorization and atomic scoring-policy updates."""
from contextlib import contextmanager
from hashlib import pbkdf2_hmac
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
from threading import Lock
from time import monotonic

from fastapi import APIRouter, HTTPException, Request

from . import scoring_policy

ADMIN_PATH = Path(__file__).resolve().parents[2] / 'var' / 'scoring-admin.json'
TTL = 600
ITERATIONS = 600_000


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
        now = monotonic()
        for old in list(sessions):
            if sessions[old] <= now:
                del sessions[old]
        if token not in sessions:
            raise HTTPException(401, '管理员授权已失效，请重新解锁')

    async def body(request):
        guard(request)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16384:
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
            sessions[token] = monotonic() + TTL
            return {'token': token, 'expires_in': TTL}

    @router.post('/lock')
    def relock(request: Request):
        guard(request)
        with lock:
            sessions.pop(request.headers.get('x-policy-session', ''), None)
        return {'locked': True}

    @router.put('/policy')
    async def update(request: Request):
        data = await body(request)
        with lock, file_lock(ADMIN_PATH.with_suffix('.lock')):
            authorize(request)
            try:
                raw = json.dumps(data.get('parameters'), ensure_ascii=False, indent=2, allow_nan=False).encode() + b'\n'
                receipt = scoring_policy.parse_policy(raw)
                previous = scoring_policy.load_policy()
            except (ValueError, TypeError):
                raise HTTPException(400, '评分参数无效，请核对数值、档位顺序与权重') from None
            if data.get('previous_hash') != previous['sha256']:
                raise HTTPException(409, '配置已被其他窗口修改，请重新打开配置后编辑')
            try:
                atomic_write(scoring_policy.POLICY_PATH, raw)
                persisted = scoring_policy.load_policy()
                if persisted['sha256'] != receipt['sha256']:
                    raise ValueError()
            except (OSError, ValueError):
                raise HTTPException(500, '配置写入或写后核验失败，请重新读取确认，未宣告保存成功') from None
            return persisted

    return router
