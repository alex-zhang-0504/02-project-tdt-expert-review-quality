import tests  # noqa: F401  须先于业务模块导入，隔离真实运行数据
from pathlib import Path
import unittest


class RuntimeIsolationTests(unittest.TestCase):
    def test_api_import_never_uses_real_runtime_data(self):
        import tdt_scoring.api as api
        from tdt_scoring import policy_admin
        root = Path(__file__).resolve().parents[1]
        self.assertNotEqual((root / 'var' / 'multi-user').resolve(), api.workspace_store.directory.resolve())
        self.assertNotEqual((root / 'config' / 'project-managers.json').resolve(), api.workspace_store.accounts_path.resolve())
        self.assertNotEqual((root / 'var' / 'scoring-admin.json').resolve(), policy_admin.ADMIN_PATH.resolve())
