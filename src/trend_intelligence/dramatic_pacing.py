"""New-draft pacing gate. Timing is structural evidence, never acting approval.

Kept outside historical screenplay parsers so archived stories remain readable.
"""
from __future__ import annotations

import math

POLICY_VERSION = 'dramatic-pacing/2026-09-11'


def audit_pacing(story, kind):
    if kind not in ('short', 'long'):
        raise ValueError('unknown screenplay kind')
    totals = dict.fromkeys(('setup', 'conflict', 'escalation', 'turn', 'resolution', 'closure'), 0.0)
    for shot in story['version']['shots']:
        seconds = shot['duration_seconds']
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('invalid shot duration')
        if shot['beat'] not in totals:
            raise ValueError('unknown beat')
        totals[shot['beat']] += seconds
    total = sum(totals.values())
    if total <= 0:
        raise ValueError('empty timeline')
    pressure = sum(totals[key] for key in ('conflict', 'escalation', 'turn'))
    ending = totals['resolution'] + totals['closure']
    # Editorial budgets for this project's conflict dramas, not universal rules.
    setup_limit, pressure_minimum, ending_limit = (5, 30, 10) if kind == 'short' else (20, 117, 36)
    issues = []
    if totals['setup'] > setup_limit:
        issues.append(f'setup {totals["setup"]:g}s exceeds {setup_limit}s')
    if pressure < pressure_minimum:
        issues.append(f'conflict/escalation/turn {pressure:g}s below {pressure_minimum}s')
    if ending > ending_limit:
        issues.append(f'resolution/closure {ending:g}s exceeds {ending_limit}s')
    return {'policy_version': POLICY_VERSION, 'total_seconds': total,
            'beat_seconds': totals, 'pressure_seconds': pressure,
            'pressure_share': pressure / total, 'ending_seconds': ending,
            'issues': issues, 'semantic_review_required': True}


def require_new_draft_pacing(story, kind):
    report = audit_pacing(story, kind)
    if report['issues']:
        raise ValueError('dramatic pacing: ' + '; '.join(report['issues']))
    return report


def require_delivery_fields(production):
    """Check coverage only; the independent reviewer must judge actual meaning."""
    required = ('触发：', '情绪：', '语速：', '语气：', '重音：', '停顿：', '余波：')
    for shot in production['shots']:
        text = shot.get('emotion_and_performance', '')
        for index, field in enumerate(required):
            if text.count(field) != 1:
                raise ValueError(f'{shot["shot_id"]}: delivery requires exactly one {field}')
            start = text.index(field) + len(field)
            end = text.index(required[index + 1]) if index + 1 < len(required) else len(text)
            if end < start or not text[start:end].strip('；; \n'):
                raise ValueError(f'{shot["shot_id"]}: empty or unordered delivery {field}')
