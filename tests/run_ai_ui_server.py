"""Browser acceptance with virtual reports and a simulated model; no external API calls."""
from pathlib import Path
import sys
import tempfile
import time

import uvicorn
from tdt_scoring import experiment
from tests.workbook_factory import build_v04_workbook

calls = []
def simulated_model(key, model, opinions):
    if opinions[0].opinion_id != 'connection-test':
        calls.append(opinions[0].opinion_id)
        time.sleep(3)
    return {o.opinion_id: {'status':'suspected', 'excerpt':o.text, 'reason':'虚拟验证：待人工确认闭环要求'} for o in opinions}

original = experiment.create_experiment_router
experiment.create_experiment_router = lambda service, encode=None: original(service, caller=simulated_model, encode=encode)
from tdt_scoring.api import app

@app.get('/_test/calls')
def observed_calls():
    return {'calls':calls}

folder = Path(tempfile.mkdtemp(prefix='tdt-ai-ui-'))
(folder / 'report.xlsx').write_bytes(build_v04_workbook([{'stage':'TDR1', 'opinion':'\n'.join(f'{i}. 建议完成虚拟验证动作{i}。' for i in range(1,9))}]))
print(folder, flush=True)
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]))
