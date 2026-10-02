"""Validated, per-assessment scoring snapshot."""
import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[2] / 'config/scoring-policy-v0.1.json'

STAGE_PERCENTAGES = {
    'all': {'TDR1': 40, 'TDR2': 20, 'TDR3': 40},
    'first_third': {'TDR1': 50, 'TDR3': 50},
    'with_second': {'TDR1_or_TDR3': 65, 'TDR2': 35},
}


def effective_policy(receipt):
    """Adapt legacy active snapshots without rewriting persisted assessments."""
    if 'stage_percentages' in receipt['parameters']:
        return receipt
    result = deepcopy(receipt)
    p = result['parameters']
    old = p.pop('stage_weights')
    groups = deepcopy(STAGE_PERCENTAGES)
    for key, stages in (('all', ('TDR1', 'TDR2', 'TDR3')), ('first_third', ('TDR1', 'TDR3'))):
        total = sum(old[s] for s in stages)
        values = [round(old[s] * 100 / total, 2) for s in stages[:-1]]
        groups[key] = dict(zip(stages, [*values, round(100 - sum(values), 2)]))
    p['stage_percentages'] = groups
    result['source_sha256'] = receipt['sha256']
    result['sha256'] = sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()
    return result


def applicable_percentages(policy, stages):
    result = dict.fromkeys(('TDR1', 'TDR2', 'TDR3'), 0)
    if len(stages) == 1:
        result[stages[0]] = 100
    elif len(stages) == 3:
        result.update(policy['stage_percentages']['all'])
    elif len(stages) == 2:
        if 'TDR2' not in stages:
            result.update(policy['stage_percentages']['first_third'])
        else:
            group = policy['stage_percentages']['with_second']
            result['TDR2'] = group['TDR2']
            result[next(s for s in stages if s != 'TDR2')] = group['TDR1_or_TDR3']
    return result


def parse_policy(raw):
    try:
        data = json.loads(raw)
        from .subjective import DIMENSIONS
        if not (data['version'] == '0.1'): raise ValueError()
        if 'stage_percentages' in data:
            if 'stage_weights' in data: raise ValueError()
            groups = data['stage_percentages']
            if not isinstance(groups, dict) or set(groups) != set(STAGE_PERCENTAGES): raise ValueError()
            for key, expected in STAGE_PERCENTAGES.items():
                group = groups[key]
                if not isinstance(group, dict) or set(group) != set(expected): raise ValueError()
                if not all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 100 for v in group.values()): raise ValueError()
                if not math.isclose(sum(group.values()), 100, rel_tol=0, abs_tol=1e-8): raise ValueError()
        else:
            if set(data['stage_weights']) != {'TDR1', 'TDR2', 'TDR3'}: raise ValueError()
            if not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in data['stage_weights'].values()): raise ValueError()
        if not (set(data['components']) == {'attendance', 'signoff', 'opinion'}): raise ValueError()
        if not (set(data['subjective']) == {d['id'] for d in DIMENSIONS}): raise ValueError()
        for d in DIMENSIONS:
            if not (set(data['subjective'][d['id']]) == {o['id'] for o in d['options']}): raise ValueError()
        numbers = [*data['components'].values(),
                   *data['participation']['tier_scores'], data['opinion_threshold'],
                   data['excess_opinion_points'], data['solution_points'], data['total_cap'],
                   *(v for opts in data['subjective'].values() for v in opts.values())]
        if not (all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in numbers)): raise ValueError()
        if not (data['opinion_threshold'] > 0 and data['total_cap'] > 0): raise ValueError()
        if not (len(data['participation']['tier_scores']) == 3): raise ValueError()
        if not (data['participation']['tier_scores'] == sorted(data['participation']['tier_scores'], reverse=True)): raise ValueError()
        if not (type(data['participation']['minimum_sessions']) is int and data['participation']['minimum_sessions'] >= 1): raise ValueError()
        if not (type(data['precision']) is int and 0 <= data['precision'] <= 4): raise ValueError()
        for opts in data['subjective'].values():
            if not (opts['high'] >= opts.get('medium', opts['low']) >= opts['low']): raise ValueError()
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        raise ValueError('评分参数未读取或参数无效，考核已阻止') from None
    return effective_policy({'parameters': data, 'version': data['version'], 'sha256': sha256(raw).hexdigest(),
            'file': 'config/' + POLICY_PATH.name, 'loaded_at': datetime.now(timezone.utc).isoformat()})


def load_policy(questionnaire=None):
    try:
        from .questionnaire import load
        data = json.loads(POLICY_PATH.read_bytes())
        questionnaire = questionnaire or load()
        data['subjective'] = questionnaire['parameters']['scores']
        result = parse_policy(json.dumps(data, ensure_ascii=False, sort_keys=True).encode())
        result['sha256'] = sha256((result['sha256'] + questionnaire['sha256']).encode()).hexdigest()
        result['questionnaire_hash'] = questionnaire['sha256']
        return result
    except OSError:
        raise ValueError('评分参数未读取或参数无效，考核已阻止') from None


def snapshot(analysis=None):
    return effective_policy(analysis.assessment['policy']) if analysis and analysis.assessment.get('confirmed') else load_policy()
