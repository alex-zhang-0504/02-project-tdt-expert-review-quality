"""Validated questionnaire content and per-assessment snapshots."""
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[2] / 'config/subjective-policy-v0.1.json'
IDS = ('preparation', 'judgment', 'guidance', 'verification', 'collaboration', 'contribution')


def parse(raw):
    try:
        data = json.loads(raw)
        if set(data) != {'version','instructions','unable','contribution_prompt','dimensions','scores'}: raise ValueError()
        def text(value):
            if not isinstance(value, str) or not value.strip() or len(value) > 2000: raise ValueError()
        for key in ('version','instructions','contribution_prompt'): text(data[key])
        if not data['version'].isascii() or not data['version'].isdigit() or len(data['version']) > 8: raise ValueError()
        if set(data['unable']) != {'title','description','reason_prompt'}: raise ValueError()
        for value in data['unable'].values(): text(value)
        if [d['id'] for d in data['dimensions']] != list(IDS): raise ValueError()
        if set(data['scores']) != set(IDS): raise ValueError()
        for d in data['dimensions']:
            if set(d) != {'id','title','prompt','boundary','options'}: raise ValueError()
            for key in ('title','prompt','boundary'): text(d[key])
            codes = ['high','low'] if d['id']=='contribution' else ['high','medium','low']
            if [o['id'] for o in d['options']] != codes: raise ValueError()
            titles = []
            for o in d['options']:
                if set(o) != {'id','title','description'}: raise ValueError()
                text(o['title']); text(o['description']); titles.append(o['title'])
            if len(set(titles + [data['unable']['title']])) != len(titles)+1: raise ValueError()
            scores = data['scores'][d['id']]
            if set(scores) != set(codes): raise ValueError()
            values = [scores[c] for c in codes]
            if any(type(v) not in (int,float) or not math.isfinite(v) or not 0 <= v <= 100 for v in values): raise ValueError()
            if values != sorted(values, reverse=True): raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError('主观参数无效，请检查六题结构、文案与档位分值') from None
    return {'parameters': data, 'sha256': sha256(raw).hexdigest(), 'version': data['version'], 'file': 'config/'+POLICY_PATH.name}


def load():
    return parse(POLICY_PATH.read_bytes())


def snapshot(analysis=None):
    saved = analysis.assessment.get('questionnaire') if analysis else None
    return deepcopy(saved or load())


def dimensions(analysis=None, receipt=None):
    data = (receipt or snapshot(analysis))['parameters']
    result = deepcopy(data['dimensions'])
    for d in result:
        d['unable_title'] = data['unable']['title']
        for o in d['options']: o['score'] = data['scores'][d['id']][o['id']]
    return result


def append_snapshot(sheet, analysis):
    receipt = snapshot(analysis)
    sheet.append(['问卷版本', receipt['version']])
    sheet.append(['问卷指纹', receipt['sha256']])
    for key, value in receipt['parameters'].items():
        if key == 'dimensions':
            for dimension in value:
                sheet.append(['问卷题目/'+dimension['id'], json.dumps(dimension, ensure_ascii=False)])
        else:
            sheet.append(['问卷/'+key, json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value])
