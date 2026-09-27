"""Local workspace storage. JSON snapshots are data, never executable objects."""
from dataclasses import asdict, fields, is_dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
import json
import os
from hashlib import sha256
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
from threading import RLock
from typing import get_args, get_origin, get_type_hints

from .models import WorkbookAnalysis


def workspace_directory():
    return Path(os.environ.get('TDT_WORKSPACE_DIR') or Path(__file__).resolve().parents[2] / 'var' / 'multi-user').resolve()


def workspace_id():
    return sha256(os.path.normcase(str(workspace_directory())).encode()).hexdigest()[:16]


def now():
    return datetime.now(timezone.utc).isoformat()


@lru_cache
def hints(cls):
    return get_type_hints(cls)


def decode(cls, value):
    if value is None:
        return None
    if is_dataclass(cls):
        return cls(**{f.name: decode(hints(cls)[f.name], value[f.name]) for f in fields(cls) if f.name in value})
    origin, args = get_origin(cls), get_args(cls)
    if origin is list:
        return [decode(args[0], item) for item in value]
    if origin is dict:
        return {key: decode(args[1], item) for key, item in value.items()}
    if cls is date:
        return date.fromisoformat(value)
    if type(None) in args:
        return decode(next(t for t in args if t is not type(None)), value)
    return value


def serialize(analysis):
    return json.dumps(asdict(analysis), ensure_ascii=False, default=lambda v: v.isoformat(), allow_nan=False)


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class WorkspaceStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'assessment.sqlite3'
        self._ready = False
        self._lock = RLock()

    def connect(self):
        with self._lock:
            return self._connect()

    def _connect(self):
        if not self._ready:
            self.directory.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path, timeout=15, factory=Connection) as db:
                if db.execute('PRAGMA user_version').fetchone()[0] not in (0, 1):
                    raise ValueError('本机数据库版本不兼容，未修改数据')
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS users(employee_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS bindings(owner_id TEXT PRIMARY KEY, employee_id TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS analyses(id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL);
                    PRAGMA user_version=1;
                ''')
            self._ready = True
        backup = self.directory / 'backups' / ('daily-' + date.today().isoformat() + '.sqlite3')
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path, factory=Connection) as source, sqlite3.connect(backup, factory=Connection) as target:
                source.backup(target)
        db = sqlite3.connect(self.path, timeout=15, factory=Connection)
        db.row_factory = sqlite3.Row
        return db

    def users(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM users ORDER BY employee_id')]

    def user(self, employee_id):
        return next((u for u in self.users() if u['employee_id'] == employee_id), None)

    def add_user(self, employee_id, name, role='manager', first=False):
        if not isinstance(employee_id, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', employee_id):
            raise ValueError('工号须为1至64位字母、数字、点、短横线或下划线，保留前导零')
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or role not in ('manager', 'admin'):
            raise ValueError('请填写有效姓名和角色')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if first and db.execute('SELECT count(*) FROM users').fetchone()[0]:
                raise ValueError('管理员已建立，请选择已有身份进入')
            if db.execute('SELECT 1 FROM users WHERE employee_id=?', (employee_id,)).fetchone():
                raise ValueError('该工号已有账号，请使用已有账号')
            db.execute('INSERT INTO users VALUES(?,?,?)', (employee_id, name.strip(), role))
        return self.user(employee_id)

    def delete_user(self, employee_id, actor_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            actor = db.execute('SELECT role FROM users WHERE employee_id=?', (actor_id,)).fetchone()
            if not actor or actor['role'] != 'admin':
                raise ValueError('此操作仅限管理员')
            user = db.execute('SELECT role FROM users WHERE employee_id=?', (employee_id,)).fetchone()
            if not user:
                raise ValueError('账号不存在或已删除，请刷新账号列表')
            if user['role'] == 'admin' and db.execute("SELECT count(*) FROM users WHERE role='admin'").fetchone()[0] <= 1:
                raise ValueError('不能删除最后一个管理员账号')
            if employee_id == actor_id:
                raise ValueError('不能删除当前登录账号，请切换其他管理员后操作')
            if db.execute('SELECT 1 FROM bindings WHERE employee_id=?', (employee_id,)).fetchone():
                raise ValueError('账号已关联飞书报告，请先重新绑定报告归属后再删除')
            for row in db.execute('SELECT payload FROM analyses'):
                analysis = json.loads(row['payload'])
                assessment = analysis.get('assessment', {})
                history = assessment.get('review_history', {})
                actors = [entry.get('actor', {}).get('employee_id')
                          for experts in history.values() for entries in experts.values() for entry in entries]
                actors.extend(entry.get('actor', {}).get('employee_id') for entry in assessment.get('finalization_history', []))
                owners = [(report.get('manager_identity') or {}).get('owner_id') for report in analysis.get('reports', [])]
                if (employee_id in assessment.get('manager_accounts', {}).values()
                        or employee_id in analysis.get('manager_reviews', {}) or employee_id in history
                        or employee_id in actors or 'local:' + employee_id in owners):
                    raise ValueError('账号已关联报告、考核或问卷历史，不能删除；已有数据保持不变')
            db.execute('DELETE FROM users WHERE employee_id=?', (employee_id,))

    def bind(self, owner_id, employee_id):
        if not self.user(employee_id) or not isinstance(owner_id, str) or not owner_id:
            raise ValueError('请选择已建立的经理账号及有效报告身份')
        with self.connect() as db:
            db.execute('INSERT INTO bindings VALUES(?,?) ON CONFLICT(owner_id) DO UPDATE SET employee_id=excluded.employee_id', (owner_id, employee_id))

    def bindings(self):
        with self.connect() as db:
            return dict(db.execute('SELECT owner_id,employee_id FROM bindings'))

    def load_all(self):
        if not self.path.exists():
            return []
        with self.connect() as db:
            return [(decode(WorkbookAnalysis, json.loads(r['payload'])), r['revision']) for r in db.execute('SELECT * FROM analyses ORDER BY updated_at ASC')]

    def save(self, analysis, revision):
        payload = serialize(analysis)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM analyses WHERE id=?', (analysis.analysis_id,)).fetchone()
            if (row['revision'] if row else 0) != revision:
                raise ValueError('考核已在另一服务中更新，请重新启动当前服务后重试；本次修改未保存')
            db.execute('INSERT INTO analyses VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at,revision=excluded.revision',
                       (analysis.analysis_id, payload, now(), revision + 1))
        return revision + 1

    def backup(self):
        with TemporaryDirectory(prefix='tdt-backup-') as directory:
            path = Path(directory) / 'backup.sqlite3'
            with self.connect() as source, sqlite3.connect(path, factory=Connection) as target:
                source.backup(target)
            return path.read_bytes()

    def inspect_backup(self, content):
        if len(content) > 100 * 1024 * 1024 or not content.startswith(b'SQLite format 3\x00'):
            raise ValueError('请选择不超过100MB的本系统数据库备份')
        try:
            with TemporaryDirectory(prefix='tdt-restore-') as directory:
                path = Path(directory) / 'backup.sqlite3'
                path.write_bytes(content)
                with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, factory=Connection) as db:
                    if db.execute('PRAGMA user_version').fetchone()[0] != 1 or db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('备份版本不兼容或完整性检查失败')
                    users = db.execute('SELECT employee_id,name,role FROM users').fetchall()
                    bindings = db.execute('SELECT owner_id,employee_id FROM bindings').fetchall()
                    analyses = db.execute('SELECT id,payload,updated_at,revision FROM analyses').fetchall()
                    if not any(u[2] == 'admin' for u in users):
                        raise ValueError('备份中缺少管理员')
                    for row in analyses:
                        analysis = decode(WorkbookAnalysis, json.loads(row[1]))
                        if row[0] != analysis.analysis_id:
                            raise ValueError('备份考核标识不一致')
                    return users, bindings, analyses
        except (sqlite3.Error, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError('备份结构无效，未修改当前数据') from exc

    def restore(self, content):
        users, bindings, analyses = self.inspect_backup(content)
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup_path = self.directory / 'backups' / ('before-restore-' + stamp + '.sqlite3')
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_bytes(self.backup())
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            revision = max([r[3] for r in analyses] + [db.execute('SELECT COALESCE(MAX(revision),0) FROM analyses').fetchone()[0]]) + 1
            for table in ('users', 'bindings', 'analyses'):
                db.execute('DELETE FROM ' + table)
            db.executemany('INSERT INTO users VALUES(?,?,?)', users)
            db.executemany('INSERT INTO bindings VALUES(?,?)', bindings)
            db.executemany('INSERT INTO analyses VALUES(?,?,?,?)', [(r[0], r[1], r[2], revision) for r in analyses])
        return backup_path.name
