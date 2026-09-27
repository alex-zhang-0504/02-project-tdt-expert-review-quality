from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tdt_scoring import accounts
from tdt_scoring.storage import Connection, WorkspaceStore


class AccountMigrationTests(unittest.TestCase):
    def test_legacy_migration_backup_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(directory)
            with sqlite3.connect(store.path, factory=Connection) as db:
                db.executescript('''
                    CREATE TABLE users(employee_id TEXT PRIMARY KEY,name TEXT,role TEXT);
                    CREATE TABLE bindings(owner_id TEXT PRIMARY KEY,employee_id TEXT);
                    CREATE TABLE analyses(id TEXT PRIMARY KEY,payload TEXT,updated_at TEXT,revision INTEGER);
                    PRAGMA user_version=1;
                ''')
                db.execute('INSERT INTO users VALUES(?,?,?)', ('0001', '虚拟旧管理员', 'admin'))
                db.execute('INSERT INTO users VALUES(?,?,?)', ('0010', '虚拟旧经理', 'manager'))
            legacy = store.path.read_bytes()
            self.assertEqual(['0001', '0010'], [u['employee_id'] for u in store.users()])
            self.assertTrue(store.accounts_path.exists())
            self.assertEqual(1, len(list((Path(directory)/'backups').glob('before-accounts-*.sqlite3'))))
            with sqlite3.connect(store.path, factory=Connection) as db:
                self.assertEqual(2, db.execute('PRAGMA user_version').fetchone()[0])
            expected = store.user('0010')
            store.update_user('0010', {**expected, 'enabled':False}, expected)
            store.restore(legacy)
            self.assertTrue(store.user('0010')['enabled'])
            self.assertEqual('虚拟旧经理', store.user('0010')['name'])
            store.accounts_path.rename(Path(directory)/'missing-accounts.json')
            with self.assertRaisesRegex(ValueError, '缺失'):
                WorkspaceStore(directory).users()

    def test_file_changed_during_write_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'accounts.json'
            path.write_bytes(b'new contents')
            with self.assertRaisesRegex(ValueError, '另一端修改'):
                accounts.replace(path, b'outdated replacement', b'old contents')
            self.assertEqual(b'new contents', path.read_bytes())

    def test_database_snapshot_failure_does_not_change_file(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(directory)
            store.add_user('0001', '虚拟管理员', 'admin', first=True)
            original = store.accounts_path.read_bytes()
            with patch.object(store, '_snapshot_accounts', side_effect=sqlite3.OperationalError('disk failure')):
                with self.assertRaises(sqlite3.OperationalError): store.add_user('0010','虚拟经理')
            self.assertEqual(original, store.accounts_path.read_bytes())
