"""Verifiable source-media readiness and descriptive expression comparisons.

Sampling scores are retrieval priorities, never model contribution weights.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import median

from .sample_gate import LIKE_KINDS, VIEW_KINDS, MIN_VIDEOS


EXPRESSION_MODES = frozenset({'prop_demonstration', 'conflict_drama', 'direct_explanation',
    'question_answer', 'case_reenactment', 'screen_demonstration', 'text_cards',
    'interview', 'mixed', 'unknown'})


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _artifact(reasons, label, path, digest, verify):
    if not path or not isinstance(digest, str) or len(digest) != 64:
        reasons.append(f'{label}缺少文件及哈希证据')
        return
    if verify:
        try:
            if file_sha256(path) != digest:
                reasons.append(f'{label}内容已变化，须重新分析')
        except (OSError, ValueError):
            reasons.append(f'{label}文件不可读取')


def media_readiness(analysis, *, verify_artifacts=True):
    """Check stored observations and their artifacts, not the truth of model claims."""
    reasons = []
    if analysis.status != 'completed' or analysis.media_access_mode != 'local_media_authorized':
        reasons.append('尚未完成原视频音画分析，标题元数据不能代替')
    media = analysis.media_evidence or {}
    expression = analysis.expression_analysis or {}
    if media.get('schema') != 'local_media_evidence/v1':
        reasons.append('缺少可追溯的媒体证据')
    duration = media.get('duration_seconds')
    valid_duration = _finite(duration) and duration > 0
    if not valid_duration:
        reasons.append('缺少原视频实际时长')
    _artifact(reasons, '原视频', media.get('source_video_path'),
              media.get('source_video_sha256'), verify_artifacts)
    visual = media.get('visual') or {}
    audio = media.get('audio') or {}
    if visual.get('status') != 'completed':
        reasons.append('关键帧理解未完成')
    times = visual.get('sample_times_seconds') or []
    if (not times or any(not _finite(t) for t in times) or times != sorted(set(times))
            or visual.get('analyzed_frame_count') != len(times)
            or visual.get('total_sampled_frame_count') != len(times)):
        reasons.append('抽帧时间或实际分析覆盖记录不完整')
    elif valid_duration:
        # Long clips can be sampled sparsely; that limitation remains explicit.
        if (times[0] > 1.0 or times[0] < 0 or times[-1] > duration + .2
                or times[-1] < duration - min(3.0, duration / 2)
                or len(times) < min(4, max(1, math.ceil(duration)))):
            reasons.append('关键帧未覆盖全片首尾')
    _artifact(reasons, '视觉分析', visual.get('artifact_path'), visual.get('artifact_sha256'), verify_artifacts)
    if visual.get('artifact_path'):
        try:
            from .content_analysis.artifacts import require_no_semantic_rejection
            require_no_semantic_rejection(visual['artifact_path'])
        except (OSError, ValueError, TypeError) as exc:
            reasons.append(f'来源语义复核已拒绝或记录不可核验：{exc}')
    _artifact(reasons, '抽帧清单', visual.get('frame_manifest_path'), visual.get('frame_manifest_sha256'), verify_artifacts)
    manifest = None
    if verify_artifacts and visual.get('frame_manifest_path'):
        try:
            manifest = json.loads(Path(visual['frame_manifest_path']).read_text(encoding='utf-8'))
            frames = manifest.get('frames') or []
            if (manifest.get('schema') != 'local_video_frame_manifest/v2'
                    or manifest.get('source_video_sha256') != media.get('source_video_sha256')
                    or [f.get('time_seconds') for f in frames] != times):
                reasons.append('抽帧清单与当前原片或采样时间不匹配')
            for frame in frames:
                _artifact(reasons, f'视频帧 {frame.get("id", "")}', frame.get('path'),
                          frame.get('sha256'), True)
        except (OSError, ValueError, TypeError, AttributeError):
            reasons.append('抽帧清单不可解析')
    if audio.get('status') not in {'transcribed', 'verified_no_speech'}:
        reasons.append('音轨转写或无语音核查未完成')
    if audio.get('status') == 'verified_no_speech' and not audio.get('status_reason'):
        reasons.append('无语音结论缺少检测依据')
    _artifact(reasons, '音频分析', audio.get('artifact_path'), audio.get('artifact_sha256'), verify_artifacts)
    if audio.get('audio_path') or audio.get('status') == 'transcribed':
        _artifact(reasons, '原视频音轨', audio.get('audio_path'), audio.get('audio_sha256'), verify_artifacts)
    if valid_duration and (not _finite(audio.get('coverage_start_seconds'))
            or not _finite(audio.get('coverage_end_seconds'))
            or not 0 <= audio['coverage_start_seconds'] <= audio['coverage_end_seconds'] <= duration + .25
            or audio['coverage_start_seconds'] > .1 or audio['coverage_end_seconds'] < duration - .25):
        reasons.append('音轨未覆盖全片')
    if verify_artifacts and manifest is not None and visual.get('artifact_path') and audio.get('artifact_path'):
        try:
            # Import at call time: content_analysis also uses this readiness check.
            from .content_analysis.artifacts import read_json, verify_expression_evidence
            visual_payload = read_json(visual['artifact_path'])
            transcript_payload = read_json(audio['artifact_path'])
            if visual_payload.get('answer', {}).get('expression_analysis') != expression:
                reasons.append('入库表达分析与视觉分析原始工件不一致')
            verify_expression_evidence(expression, manifest, transcript_payload,
                                       visual_batches=visual_payload.get('batches') or [],
                                       observation_review=visual_payload.get('observation_review'))
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
            reasons.append(f'表达证据与实际帧或转写不匹配：{exc}')
    if expression.get('schema') != 'video_expression_analysis/v1':
        reasons.append('缺少逐视频核心表达与表达方式分析')
    evidence = expression.get('evidence') or []
    ids = set()
    channels = set()
    for item in evidence:
        if not isinstance(item, dict):
            reasons.append('表达证据格式错误')
            continue
        start, end = item.get('start_seconds'), item.get('end_seconds')
        if (not item.get('id') or item['id'] in ids or not item.get('text')
                or item.get('channel') not in {'visual', 'asr'}
                or not _finite(start) or not _finite(end) or start < 0 or end < start
                or (valid_duration and end > duration + .25)):
            reasons.append('表达证据缺少唯一ID、内容或有效时间戳')
        ids.add(item.get('id'))
        channels.add(item.get('channel'))
    if 'visual' not in channels or (audio.get('status') == 'transcribed' and 'asr' not in channels):
        reasons.append('核心表达缺少画面或语音时间证据')

    channel_by_id = {e.get('id'): e.get('channel') for e in evidence if isinstance(e, dict)}

    def backed(claim, channel=None):
        return (isinstance(claim, dict) and bool(claim.get('text'))
                and isinstance(claim.get('evidence_ids'), list) and bool(claim['evidence_ids'])
                and all(isinstance(eid, str) for eid in claim['evidence_ids'])
                and set(claim['evidence_ids']).issubset(ids)
                and (channel is None or any(channel_by_id.get(eid) == channel for eid in claim['evidence_ids'])))

    if not backed(expression.get('core_message')):
        reasons.append('核心表达未绑定可核对证据')
    modes = expression.get('expression_modes') or []
    if not modes or any(not isinstance(m, dict) or m.get('mode') not in EXPRESSION_MODES - {'unknown'}
            or not m.get('evidence_ids') or not set(m['evidence_ids']).issubset(ids) for m in modes):
        reasons.append('表达方式未知或没有证据支撑')
    for key in ('visual_expression', 'audio_expression'):
        claims = expression.get(key) or []
        if key == 'audio_expression' and audio.get('status') == 'verified_no_speech':
            continue
        required_channel = 'visual' if key == 'visual_expression' else 'asr'
        if not claims or any(not backed(c, required_channel) for c in claims):
            reasons.append(f'{key}缺少表达方式及证据')
    conflict = expression.get('conflict') or {}
    if conflict.get('status') not in {'observed', 'not_observed', 'unknown'}:
        reasons.append('人物冲突未区分已观察、未见或未知')
    if conflict.get('status') == 'observed':
        for key in ('trigger', 'opposition'):
            if not backed(conflict.get(key)):
                reasons.append('人物冲突的触发及阻碍缺少证据')
    return {'ready': not reasons, 'item_id': analysis.item_id, 'video_id': analysis.video_id,
        'analysis_id': analysis.analysis_id, 'reasons': list(dict.fromkeys(reasons)),
        'visual_status': visual.get('status', 'missing'), 'audio_status': audio.get('status', 'missing'),
        'artifact_hashes_verified': verify_artifacts and not reasons,
        'interpretation_status': 'automatic_candidate_requires_independent_review',
        'scope': '抽样画面理解及全音轨转写；不代表已核实原片声线、语气和口型。'}


def batch_media_readiness(analyses, *, required_count=MIN_VIDEOS, expected_item_ids=None, verify_artifacts=True):
    unique = {a.video_id: a for a in analyses}
    results = [media_readiness(a, verify_artifacts=verify_artifacts) for a in unique.values()]
    media_owners = {}
    for analysis, result in zip(unique.values(), results):
        digest = analysis.media_evidence.get('source_video_sha256')
        if result['ready'] and digest:
            if digest in media_owners:
                result['ready'] = False
                result['reasons'].append(f'与 {media_owners[digest]} 使用同一原片，不能按不同来源重复计数')
            else:
                media_owners[digest] = analysis.item_id
    missing = [r for r in results if not r['ready']]
    present = {a.item_id for a in unique.values()}
    for item_id in sorted(set(expected_item_ids or ()) - present):
        missing.append({'item_id': item_id, 'video_id': '', 'reasons': ['尚无本条视频的分析结果']})
    ready_count = sum(r['ready'] for r in results)
    return {'schema': 'source_media_gate/v1', 'ready': ready_count >= required_count and not missing,
        'analyzed_count': len(results), 'ready_count': ready_count, 'required_count': required_count,
        'missing': missing, 'artifacts_checked': verify_artifacts,
        'message': f'原视频音画表达分析 {ready_count}/{max(required_count, len(results), len(set(expected_item_ids or ())))}；不足时停在待分析，不调用编剧。'}


class SourceMediaGateError(ValueError):
    def __init__(self, result):
        self.result = result
        super().__init__(result['message'])


def require_source_media(analyses):
    result = batch_media_readiness(analyses)
    if not result['ready']:
        raise SourceMediaGateError(result)
    return result


def build_expression_patterns(cohort):
    """Compare observed modes within the selected cohort from one batch.

    Likes and views stay in separate groups. Ties are never broken into invented
    high/low differences. This is descriptive association, not a causal effect.
    """
    groups, mode_sources = defaultdict(list), defaultdict(list)
    for candidate in cohort:
        observation, analysis = candidate.observation, candidate.analysis
        if not media_readiness(analysis, verify_artifacts=False)['ready']:
            continue
        kind = 'likes' if observation.metric_kind in LIKE_KINDS else 'views' if observation.metric_kind in VIEW_KINDS else 'unknown'
        value = observation.metric_value
        if kind == 'unknown' or type(value) is not int or value < 0:
            continue
        modes = {m['mode'] for m in analysis.expression_analysis.get('expression_modes', [])}
        row = {'source_id': observation.item_id, 'metric': value, 'modes': modes,
               'relevance': candidate.relevance}
        groups[kind].append(row)
        for mode in modes:
            mode_sources[mode].append(row)
    patterns = []
    for mode, supports in sorted(mode_sources.items()):
        comparisons = []
        for kind, rows in sorted(groups.items()):
            ordered = sorted(r['metric'] for r in rows)
            threshold = ordered[max(0, len(rows) - math.ceil(len(rows) * .25))]
            high = [r for r in rows if r['metric'] >= threshold]
            comparison = [r for r in rows if r['metric'] < threshold]
            with_mode = [r for r in rows if mode in r['modes']]
            without_mode = [r for r in rows if mode not in r['modes']]
            comparisons.append({'metric_kind': kind, 'high_group_threshold': threshold,
                'high_group_support': sum(mode in r['modes'] for r in high), 'high_group_size': len(high),
                'comparison_group_support': sum(mode in r['modes'] for r in comparison),
                'comparison_group_size': len(comparison),
                'median_metric_with_mode': median(r['metric'] for r in with_mode) if with_mode else None,
                'median_metric_without_mode': median(r['metric'] for r in without_mode) if without_mode else None,
                'high_source_item_ids': [r['source_id'] for r in high if mode in r['modes']],
                'comparison_source_item_ids': [r['source_id'] for r in comparison if mode in r['modes']],
                'contrast_available': bool(high and comparison and with_mode and without_mode)})
        patterns.append({'mode': mode, 'support_video_count': len(supports),
            'source_item_ids': [r['source_id'] for r in supports],
            'average_account_relevance': round(sum(r['relevance'] for r in supports)/len(supports), 2),
            'metric_groups': comparisons})
    return {'schema': 'observed_expression_patterns/v1', 'patterns': patterns,
        'comparison_method': '所选来源集合内按同种明确指标的上四分位（含并列）与其余样本比较',
        'interpretation': '表达方式与高点赞/播放的样本关联；不证明其导致高表现，不推断完播或转化。',
        'creative_contribution_percent': None,
        'account_adaptation': '结合账号受众、服务范围和禁止旁白要求选用有证据的表达方式；不要默认改成知识问答。'}
