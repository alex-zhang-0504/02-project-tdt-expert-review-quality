"""Isolated browser acceptance server; never changes the project's live policy/password."""
from hashlib import pbkdf2_hmac
import json
from pathlib import Path
import secrets
import sys
import tempfile

import uvicorn
from openpyxl import Workbook
from tdt_scoring import scoring_policy, policy_admin
from tests.workbook_factory import build_v04_workbook

reuse = len(sys.argv) > 2
folder = Path(sys.argv[2]) if reuse else Path(tempfile.mkdtemp(prefix='tdt-policy-ui-'))
raw = scoring_policy.POLICY_PATH.read_bytes()
scoring_policy.POLICY_PATH = folder / 'scoring-policy-v0.1.json'
policy_admin.ADMIN_PATH = folder / 'admin.json'
if not reuse:
    scoring_policy.POLICY_PATH.write_bytes(raw)
    salt = secrets.token_bytes(32)
    # Synthetic local test credential only, not an application default.
    policy_admin.ADMIN_PATH.write_text(json.dumps({'salt':salt.hex(), 'hash':pbkdf2_hmac(
        'sha256', b'virtual-test-password', salt, policy_admin.ITERATIONS).hex()}), encoding='utf-8')
(folder/'report.xlsx').write_bytes(build_v04_workbook([{'stage':'TDR1','problems':[
    {'number':'1','reviewer':'','description':'虚拟测试问题','must_fix':'是','level':'一般','feedback':'','status':'open'}]}]))
book=Workbook();book.active.append(['姓名']);book.active.append(['虚拟专家甲']);book.active.append(['虚拟专家乙'])
book.save(folder/'roster.xlsx')
print(str(folder), flush=True)
from tdt_scoring.api import app
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]))
