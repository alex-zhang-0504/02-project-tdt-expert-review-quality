"""Local workspace storage. JSON snapshots are data, never executable objects."""
from dataclasses import asdict, fields, is_dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
import json
import os
import re
from hashlib import sha256
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import RLock
from typing import get_args, get_origin, get_type_hints

from .models import WorkbookAnalysis
from . import accounts


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
        self.accounts_path = self.directory / 'accounts.json'
        root = Path(__file__).resolve().parents[2]
        if self.directory.resolve() == (root / 'var' / 'multi-user').resolve():
            self.accounts_path = root / 'config' / 'project-managers.json'
        self._ready = False
        self._lock = RLock()

    def connect(self):
        with self._lock:
            return self._connect()

    def _connect(self):
        if not self._ready:
            self.directory.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path, timeout=15, factory=Connection) as db:
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, 1, 2):
                    raise ValueError('本机数据库版本不兼容，未修改数据')
                if version == 1:
                    backup = self.directory / 'backups' / ('before-accounts-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    with sqlite3.connect(backup, factory=Connection) as target:
                        db.backup(target)
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS users(employee_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS bindings(owner_id TEXT PRIMARY KEY, employee_id TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS analyses(id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL);
                    CREATE TABLE IF NOT EXISTS account_config(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
                    PRAGMA user_version=2;
                ''')
            self._ready = True
        backup = self.directory / 'backups' / ('daily-' + date.today().isoformat() + '.sqlite3')
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix='daily-', dir=backup.parent) as staged:
                candidate = Path(staged) / backup.name
                with sqlite3.connect(self.path, factory=Connection) as source, sqlite3.connect(candidate, factory=Connection) as target:
                    source.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('自动备份校验失败，保留上一份备份')
                os.replace(candidate, backup)
        with sqlite3.connect(f'{backup.as_uri()}?mode=ro', uri=True, factory=Connection) as checked:
            valid = checked.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        if valid:
            for old in backup.parent.iterdir():
                if old != backup and re.fullmatch(r'daily-\d{4}-\d{2}-\d{2}\.sqlite3', old.name) and old.is_file() and not old.is_symlink():
                    old.unlink()
        db = sqlite3.connect(self.path, timeout=15, factory=Connection)
        db.row_factory = sqlite3.Row
        return db

    def _snapshot_accounts(self, db, users):
        db.execute('INSERT INTO account_config VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                   (accounts.content(users).decode('utf-8'),))
        db.execute('DELETE FROM users')
        db.executemany('INSERT INTO users VALUES(?,?,?)', [(u['employee_id'], u['name'], u['role']) for u in users])
        db.execute('DELETE FROM bindings')
        db.executemany('INSERT INTO bindings VALUES(?,?)', [(owner, u['employee_id']) for u in users for owner in u.get('owner_ids', [])])

    def _accounts(self, db):
        snapshot = db.execute('SELECT payload FROM account_config WHERE id=1').fetchone()
        previous = accounts.parse(snapshot['payload'].encode('utf-8')) if snapshot else [
            {**dict(row), 'enabled': True} for row in db.execute('SELECT * FROM users ORDER BY employee_id')]
        if not self.accounts_path.exists():
            if snapshot:
                raise ValueError(f'{self.accounts_path.name}缺失，请恢复账号配置文件；不会自动恢复旧账号')
            accounts.replace(self.accounts_path, accounts.content(previous), None)
        raw = self.accounts_path.read_bytes()
        try:
            document = json.loads(raw.decode('utf-8-sig'))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('账号配置格式错误，请修正JSON后刷新；未覆盖文件') from exc
        if document.get('users') and all('role' not in u for u in document['users']):
            # One-time conversion of the old import-only roster, retaining stable bindings.
            legacy = self.directory / 'accounts.json'
            current = accounts.parse(legacy.read_bytes()) if legacy != self.accounts_path and legacy.exists() else previous
            _, users = accounts.import_directory(document, current)
            accounts.replace(self.accounts_path, accounts.content(users), raw)
            raw = self.accounts_path.read_bytes()
            document = json.loads(raw)
        users = accounts.parse(raw)
        migrate = {u['employee_id'] for u in document['users'] if 'owner_ids' not in u}
        if migrate:
            for user in users:
                if user['employee_id'] in migrate:
                    user['owner_ids'] = [r[0] for r in db.execute('SELECT owner_id FROM bindings WHERE employee_id=?', (user['employee_id'],))]
            users = accounts.validate({'version': 1, 'users': users})
            replacement = accounts.content(users)
            accounts.replace(self.accounts_path, replacement, raw)
            raw = replacement
        if previous and not users:
            raise ValueError('不能删除最后一个管理员账号')
        for user in previous:
            if not any(u['employee_id'] == user['employee_id'] for u in users):
                self._check_user_references(db, user['employee_id'])
        if users != previous or not snapshot:
            self._snapshot_accounts(db, users)
        return users, raw

    def users(self, include_disabled=False):
        with self._lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            users, _ = self._accounts(db)
        return [u for u in users if include_disabled or u['enabled']]

    def user(self, employee_id):
        return next((u for u in self.users() if u['employee_id'] == employee_id), None)

    @staticmethod
    def _require_admin(users, actor_id):
        if not any(u['employee_id'] == actor_id and u['enabled'] and u['role'] == 'admin' for u in users):
            raise ValueError('当前账号已停用或不再是管理员，请重新选择身份')

    def add_user(self, employee_id, name, role='manager', first=False, actor_id=None, owner_ids=None):
        with self._lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            users, raw = self._accounts(db)
            if actor_id is not None:
                self._require_admin(users, actor_id)
            if first and users:
                raise ValueError('管理员已建立，请选择已有身份进入')
            users = accounts.validate({'version': 1, 'users': [*users, dict(employee_id=employee_id, name=name, role=role, enabled=True, owner_ids=owner_ids or [])]})
            self._snapshot_accounts(db, users)
            accounts.replace(self.accounts_path, accounts.content(users), raw)
        return self.user(employee_id)

    def update_user(self, employee_id, data, expected, actor_id=None):
        with self._lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            users, raw = self._accounts(db)
            if actor_id is not None:
                self._require_admin(users, actor_id)
            previous = next((u for u in users if u['employee_id'] == employee_id), None)
            if not previous or previous != expected:
                raise ValueError('账号已在另一端修改，本次未覆盖；请刷新账号列表后重新编辑')
            if data.get('employee_id', employee_id) != employee_id:
                raise ValueError('工号是稳定标识，不可修改；请新增账号并停用旧账号')
            updated = dict(employee_id=employee_id, name=data.get('name'), role=data.get('role'), enabled=data.get('enabled'), owner_ids=data.get('owner_ids', previous['owner_ids']))
            users = accounts.validate({'version': 1, 'users': [updated if u['employee_id'] == employee_id else u for u in users]})
            self._snapshot_accounts(db, users)
            accounts.replace(self.accounts_path, accounts.content(users), raw)
        return next(u for u in users if u['employee_id'] == employee_id)

    def delete_user(self, employee_id, actor_id):
        with self._lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            users, raw = self._accounts(db)
            actor = next((u for u in users if u['employee_id'] == actor_id), None)
            if not actor or not actor['enabled'] or actor['role'] != 'admin':
                raise ValueError('此操作仅限管理员')
            user = next((u for u in users if u['employee_id'] == employee_id), None)
            if not user:
                raise ValueError('账号不存在或已删除，请刷新账号列表')
            if user['role'] == 'admin' and user['enabled'] and sum(u['role'] == 'admin' and u['enabled'] for u in users) <= 1:
                raise ValueError('不能删除最后一个管理员账号')
            if employee_id == actor_id:
                raise ValueError('不能删除当前登录账号，请切换其他管理员后操作')
            self._check_user_references(db, employee_id)
            users = [u for u in users if u['employee_id'] != employee_id]
            self._snapshot_accounts(db, users)
            accounts.replace(self.accounts_path, accounts.content(users), raw)

    def _check_user_references(self, db, employee_id):
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

    def bind(self, owner_id, employee_id, *, owner_name):
        with self._lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            users, raw = self._accounts(db)
            if not any(u['employee_id'] == employee_id and u['enabled'] for u in users) or not owner_id:
                raise ValueError('请选择已启用的经理账号及有效报告身份')
            matches = [u for u in users if u['enabled'] and u['name'] == owner_name.strip()]
            if len(matches) != 1 or matches[0]['employee_id'] != employee_id:
                raise ValueError('报告所有者姓名与账号不一致，禁止绑定')
            if any(owner_id in u['owner_ids'] and u['employee_id'] != employee_id for u in users):
                raise ValueError('历史归属冲突，禁止直接覆盖')
            for user in users:
                user['owner_ids'] = [owner for owner in user['owner_ids'] if owner != owner_id]
                if user['employee_id'] == employee_id:
                    user['owner_ids'].append(owner_id)
            users = accounts.validate({'version': 1, 'users': users})
            self._snapshot_accounts(db, users)
            accounts.replace(self.accounts_path, accounts.content(users), raw)

    def bindings(self):
        return {owner: user['employee_id'] for user in self.users(include_disabled=True) for owner in user['owner_ids']}

    def load_all(self):
        if not self.path.exists():
            return []
        with self.connect() as db:
            self.write_corrections(db)
            return [(decode(WorkbookAnalysis, json.loads(r['payload'])), r['revision']) for r in db.execute('SELECT * FROM analyses ORDER BY updated_at ASC')]

    def save(self, analysis, revision, connection=None):
        payload = serialize(analysis)
        if connection is not None:
            return self._save(connection, analysis.analysis_id, payload, revision)
        path = self.directory / 'countermeasure-corrections.jsonl'
        with self._lock:
            before = path.read_bytes() if path.exists() else None
            try:
                with self.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    updated = self._save(db, analysis.analysis_id, payload, revision)
                    self.write_corrections(db)
                return updated
            except Exception:
                if before is not None and path.exists() and path.read_bytes() != before:
                    accounts.replace(path, before, path.read_bytes())
                elif before is None and path.exists():
                    accounts.replace(path, b'', path.read_bytes())
                raise

    def write_corrections(self, db):
        from .corrections import learning_records
        path = self.directory / 'countermeasure-corrections.jsonl'
        rows = learning_records(r[0] for r in db.execute('SELECT payload FROM analyses ORDER BY id'))
        raw = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode('utf-8')
        before = path.read_bytes() if path.exists() else None
        if raw != before:
            accounts.replace(path, raw, before)

    @staticmethod
    def _save(db, analysis_id, payload, revision):
        row = db.execute('SELECT revision FROM analyses WHERE id=?', (analysis_id,)).fetchone()
        if (row['revision'] if row else 0) != revision:
            raise ValueError('考核已在另一服务中更新，请重新启动当前服务后重试；本次修改未保存')
        db.execute('INSERT INTO analyses VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at,revision=excluded.revision',
                   (analysis_id, payload, now(), revision + 1))
        return revision + 1

    def backup(self):
        self.users(include_disabled=True)
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
                    version = db.execute('PRAGMA user_version').fetchone()[0]
                    if version not in (1, 2) or db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('备份版本不兼容或完整性检查失败')
                    users = [dict(employee_id=r[0], name=r[1], role=r[2], enabled=True)
                             for r in db.execute('SELECT employee_id,name,role FROM users')]
                    legacy_ids = {u['employee_id'] for u in users}
                    if version == 2:
                        snapshot = db.execute('SELECT payload FROM account_config WHERE id=1').fetchone()
                        if snapshot:
                            legacy_ids = {u['employee_id'] for u in json.loads(snapshot[0])['users'] if 'owner_ids' not in u}
                            users = accounts.parse(snapshot[0].encode('utf-8'))
                    bindings = db.execute('SELECT owner_id,employee_id FROM bindings').fetchall()
                    for user in users:
                        if user['employee_id'] in legacy_ids:
                            user['owner_ids'] = [r[0] for r in bindings if r[1] == user['employee_id']]
                    users = accounts.validate({'version': 1, 'users': users})
                    analyses = db.execute('SELECT id,payload,updated_at,revision FROM analyses').fetchall()
                    if not any(u['enabled'] and u['role'] == 'admin' for u in users):
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
        with self._lock:
            previous = self.accounts_path.read_bytes()
            replacement = accounts.content(users)
            replaced = False
            try:
                with self.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    revision = max([r[3] for r in analyses] + [db.execute('SELECT COALESCE(MAX(revision),0) FROM analyses').fetchone()[0]]) + 1
                    for table in ('bindings', 'analyses'):
                        db.execute('DELETE FROM ' + table)
                    self._snapshot_accounts(db, users)
                    db.executemany('INSERT INTO analyses VALUES(?,?,?,?)', [(r[0], r[1], r[2], revision) for r in analyses])
                    accounts.replace(self.accounts_path, replacement, previous)
                    replaced = True
            except Exception:
                if replaced:
                    accounts.replace(self.accounts_path, previous, replacement)
                raise
        return backup_path.name
