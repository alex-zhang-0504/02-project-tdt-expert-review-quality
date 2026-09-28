"""Isolated real UI acceptance with virtual reports and separate credentials/config."""
import json
import asyncio
import os
from pathlib import Path
import sys

import uvicorn
from openpyxl import Workbook
from tdt_scoring import scoring_policy, questionnaire, policy_admin
from tests.workbook_factory import build_v04_workbook

folder = Path(sys.argv[2]).resolve()
folder.mkdir(parents=True, exist_ok=True)
os.environ['TDT_WORKSPACE_DIR'] = str(folder / 'workspace')
for module, filename in [(scoring_policy, 'scoring-policy-v0.1.json'), (questionnaire, 'subjective-policy-v0.1.json')]:
    path = folder / filename
    if not path.exists(): path.write_bytes(module.POLICY_PATH.read_bytes())
    module.POLICY_PATH = path
policy_admin.ADMIN_PATH = folder / 'admin.json'
users = [{'employee_id': eid, 'name': name, 'role': role, 'enabled': True, 'owner_ids': []} for eid, name, role in
         [('0001', '虚拟管理员', 'admin'), ('1001', '虚拟项目经理甲', 'manager'), ('1002', '虚拟项目经理乙', 'manager')]]
(folder / 'accounts-import.json').write_text(json.dumps({'version':1,'users':users}, ensure_ascii=False, indent=2), encoding='utf-8')
for suffix, code in [('a','B260001'), ('b','B260002')]:
    (folder / ('report-'+suffix+'.xlsx')).write_bytes(build_v04_workbook([
        {'stage':'TDR1','problems':[]}], project='虚拟项目-'+code))
wb = Workbook(); wb.active.append(['姓名']); wb.active.append(['虚拟专家甲']); wb.save(folder / 'roster.xlsx')
from tdt_scoring.api import app
if os.environ.get('TDT_UI_DELAY_REVIEWS') == '1':
    @app.middleware('http')
    async def delay_review_response(request, call_next):
        response = await call_next(request)
        if request.method == 'POST' and request.url.path == '/api/subjective/review':
            await asyncio.sleep(2)
        return response
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]))
