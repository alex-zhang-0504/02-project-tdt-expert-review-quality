"""Test suite for the scoring system.

Importing this package first points the workspace and administrator credential at a
temporary folder, so tests never read or write var/multi-user, the real account file
or var/scoring-admin.json. Test modules that import tdt_scoring.api must `import tests`
before any business module.
"""
import atexit
import os
from pathlib import Path
import shutil
import tempfile

_ISOLATED = Path(tempfile.mkdtemp(prefix='tdt-tests-'))
atexit.register(shutil.rmtree, _ISOLATED, ignore_errors=True)
os.environ['TDT_WORKSPACE_DIR'] = str(_ISOLATED / 'workspace')

from tdt_scoring import policy_admin  # noqa: E402

policy_admin.ADMIN_PATH = _ISOLATED / 'scoring-admin.json'
