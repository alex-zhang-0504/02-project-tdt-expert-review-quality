"""Validated, per-assessment scoring snapshot."""
import json
import math
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[2] / 'config/scoring-policy-v0.1.json'


def load_policy():
    try:
        raw = POLICY_PATH.read_bytes()
        data = json.loads(raw)
        from .subjective import DIMENSIONS
        if not (data['version'] == '0.1'): raise ValueError()
        if not (set(data['stage_weights']) == {'TDR1', 'TDR2', 'TDR3'}): raise ValueError()
        if not (set(data['components']) == {'attendance', 'signoff', 'opinion'}): raise ValueError()
        if not (set(data['subjective']) == {d['id'] for d in DIMENSIONS}): raise ValueError()
        for d in DIMENSIONS:
            if not (set(data['subjective'][d['id']]) == {o['id'] for o in d['options']}): raise ValueError()
        numbers = [*data['stage_weights'].values(), *data['components'].values(),
                   *data['participation']['tier_scores'], data['opinion_threshold'],
                   data['excess_opinion_points'], data['solution_points'], data['total_cap'],
                   *(v for opts in data['subjective'].values() for v in opts.values())]
        if not (all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in numbers)): raise ValueError()
        if not (all(v > 0 for v in data['stage_weights'].values())): raise ValueError()
        if not (data['opinion_threshold'] > 0 and data['total_cap'] > 0): raise ValueError()
        if not (len(data['participation']['tier_scores']) == 3): raise ValueError()
        if not (data['participation']['tier_scores'] == sorted(data['participation']['tier_scores'], reverse=True)): raise ValueError()
        if not (type(data['participation']['minimum_sessions']) is int and data['participation']['minimum_sessions'] >= 1): raise ValueError()
        if not (type(data['precision']) is int and 0 <= data['precision'] <= 4): raise ValueError()
        for opts in data['subjective'].values():
            if not (opts['high'] >= opts.get('medium', opts['low']) >= opts['low']): raise ValueError()
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        raise ValueError('评分配置未读取或参数无效，考核已阻止') from None
    return {'parameters': data, 'version': data['version'], 'sha256': sha256(raw).hexdigest(),
            'file': 'config/' + POLICY_PATH.name, 'loaded_at': datetime.now(timezone.utc).isoformat()}


def snapshot(analysis=None):
    return analysis.assessment['policy'] if analysis and analysis.assessment.get('confirmed') else load_policy()
