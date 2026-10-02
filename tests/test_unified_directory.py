import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tdt_scoring import accounts
from tdt_scoring.storage import WorkspaceStore


class UnifiedDirectoryTests(unittest.TestCase):
    def test_shipped_example_is_valid_and_does_not_replace_existing_admin(self):
        path = Path(__file__).resolve().parents[1] / 'config/project-managers.example.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        current = [{'name': '虚拟首任管理员', 'employee_id': 'bootstrap-admin',
                    'role': 'admin', 'enabled': True, 'owner_ids': []}]
        imported, merged = accounts.import_directory(data, current)
        self.assertTrue(any(u['role'] == 'manager' and u['enabled'] for u in imported))
        self.assertTrue(any(u['employee_id'] == 'bootstrap-admin' and u['enabled'] for u in merged))
        self.assertTrue(all(u['employee_id'].startswith('00') for u in imported))

    def test_default_import_source_migrates_once_and_preserves_internal_bindings(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config/project-managers.json'
            config.parent.mkdir()
            workspace = root / 'var/multi-user'
            legacy = WorkspaceStore(workspace)
            legacy.add_user('001', '虚拟管理员', 'admin', first=True)
            legacy.add_user('002', '虚拟技术项目经理', owner_ids=['owner_virtual'])
            config.write_text(json.dumps({'version': 1, 'users': [{'name': '虚拟技术项目经理', 'employee_id': '002', 'enabled': True}]}), encoding='utf-8')
            with patch('tdt_scoring.storage.__file__', str(root / 'src/tdt_scoring/storage.py')):
                store = WorkspaceStore(workspace)
            users = store.users(True)
            self.assertEqual(config.resolve(), store.accounts_path.resolve())
            self.assertEqual(['owner_virtual'], next(u for u in users if u['employee_id'] == '002')['owner_ids'])
            self.assertTrue(any(u['role'] == 'admin' for u in users))
            raw = config.read_bytes()
            self.assertEqual(users, store.users(True))
            self.assertEqual(raw, config.read_bytes())
            changed = accounts.parse(raw)
            next(u for u in changed if u['employee_id'] == '002')['enabled'] = False
            accounts.replace(config, accounts.content(changed), raw)
            self.assertIsNone(store.user('002'))
            self.assertTrue(legacy.user('002'), '旧文件只验证为独立存档，不能再影响统一配置')

    def test_full_import_changes_roles_but_preserves_owner_binding(self):
        current = [{'name': '虚拟管理员', 'employee_id': '001', 'enabled': True, 'role': 'admin', 'owner_ids': []},
                   {'name': '虚拟技术项目经理', 'employee_id': '002', 'enabled': True, 'role': 'manager', 'owner_ids': ['owner_virtual']}]
        revised = [dict(u, owner_ids=[], role='admin') for u in current]
        imported, merged = accounts.import_directory({'version': 1, 'users': revised}, current)
        self.assertEqual('admin', imported[1]['role'])
        self.assertEqual(['owner_virtual'], merged[1]['owner_ids'])
        self.assertEqual('manager', current[1]['role'])
