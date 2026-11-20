"""Hash-bound, explicitly sampled AV observations for new research requests.

These are model observations, not verified psychological states or causality.
"""
import hashlib
import json
import re
from pathlib import Path

DEFAULT_INDEX = Path(__file__).resolve().parents[2] / 'data/source_emotion/index.json'


def delivery_projection(text):
    """Conservative excerpt filter, NOT a semantic review or truth detector.

Do not feed the small AV model's invented quotations or case summaries to the
writer. Raw responses stay bound in the local audit artifact.
"""
    text = re.sub(r'“[^”]*”|「[^」]*」|"[^"]*"', '', text)
    clauses = re.split(r'[。！？，\n]', text)
    selected = [clause.strip() for clause in clauses
                if re.search(r'语气|语速|节奏|情绪|急切|愤怒|表情|动作|手势|末尾|停顿|重音', clause)
                and not re.search(r'案件|法律|工伤|法院|赔偿|合同|法庭|审判|西装|背景|穿着', clause)]
    return '。'.join(selected) or '没有可单独引用的表达观察，待复核。'


def source_emotion(source_id, source_sha256, *, index_path=None):
    missing = {'status': 'not_analyzed', 'reason': 'No matching original-audio emotion observation'}
    index_path = Path(index_path) if index_path is not None else DEFAULT_INDEX
    if not index_path.is_file():
        return missing
    try:
        index = json.loads(index_path.read_text(encoding='utf-8'))
        entry = index['sources'].get(source_id)
        if not entry or entry['source_video_sha256'] != source_sha256:
            return missing
        raw = Path(entry['artifact_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['artifact_sha256']:
            raise ValueError('emotion artifact hash changed')
        report = json.loads(raw)
        if (report['schema'] != 'source_emotion_analysis/v1'
                or report['source_id'] != source_id
                or report['source_video_sha256'] != source_sha256
                or report['status'] != 'model_observed_unverified'):
            raise ValueError('emotion artifact identity/status mismatch')
        if not report['windows']:
            raise ValueError('no observed windows')
        for window in report['windows']:
            for field in ('observation_path', 'sample_path'):
                data = Path(window[field]).read_bytes()
                if hashlib.sha256(data).hexdigest() != window[field.replace('_path', '_sha256')]:
                    raise ValueError('emotion underlying evidence changed')
        transcript_raw = Path(report['transcript_path']).read_bytes()
        if hashlib.sha256(transcript_raw).hexdigest() != report['transcript_sha256']:
            raise ValueError('emotion transcript changed')
        return {key: report[key] for key in ('schema', 'status', 'coverage',
            'source_duration_seconds', 'limitations', 'asr_density')} | {
                'artifact_sha256': entry['artifact_sha256'],
                'unresolved_windows': report.get('unresolved_windows', []),
                'windows': [{key: value for key, value in window.items()
                             if key in ('source_start', 'source_end', 'observation', 'observation_scope')}
                            for window in report['windows']]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {'status': 'unavailable', 'reason': str(exc)}
