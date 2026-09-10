"""Prompt-based short/long scripts with structural checks before artifact writes."""
from dataclasses import fields
from datetime import datetime, timezone
import hashlib
import copy
import json
import math
import re
from pathlib import Path

PROMPT_PATH = Path(__file__).parent / 'prompts/script_pair.md'
BEAT_ROLES = ('setup', 'conflict', 'escalation', 'turn', 'resolution', 'closure')
VISUAL_FIELDS = ('composition', 'lighting', 'shot_size', 'camera_angle', 'camera_movement',
                 'start_frame', 'end_frame', 'transition')
SHOT_SIZES = ('远景', '全景', '中景', '中近景', '近景', '特写', '大特写')
CAMERA_MOVEMENTS = ('固定', '横移', '跟拍', '摇镜')
NARRATION = r'旁白|解说|内心独白|心声|(?i:voice[ -]?over|narrator|\bVO\b)'
# A reviewed 20-video cohort needs room for complete clause boundaries and long
# narrative endings. These are text-size guards, not semantic acceptance rules.
# Keep every required citation and adjacent ASR; never trim to meet a guard.
SOURCE_PROJECTION_MAX_RECORDS = 384
SOURCE_PROJECTION_MAX_CHARS = 48000
SOURCE_PROJECTION_TOTAL_MAX_CHARS = 260000


class SourceSemanticReviewError(RuntimeError):
    """Unresolved source meaning requires source review, not another authoring attempt."""


def _has_narration(value):
    # A negative production instruction is not a request for narration.
    cleaned = re.sub(r'(?:无|没有|禁止|不要|不加|不使用|不含|不设|不得|不允许)[^，。；;\n]{0,10}(?:' + NARRATION + ')', '', value)
    return bool(re.search(NARRATION, cleaned))


def _shot_visual_issues(shot, *, kind):
    """Describe actual field defects independently; never infer a hidden cut."""
    label = f"{kind} {shot['shot_id']}"
    missing = [key for key in VISUAL_FIELDS if not isinstance(shot.get(key), str) or not shot[key].strip()]
    issues = [f"{label} 缺失摄影/画面字段或字段不是非空文字：{', '.join(missing)}"] if missing else []
    if 'shot_size' not in missing and shot['shot_size'] not in SHOT_SIZES:
        instruction = '；长版每镜须完整填写实际景别，不支持用“同S01/同 S01/同上”继承' if kind == 'long' else ''
        issues.append(f"{label} shot_size={shot['shot_size']!r} 无效；必须选择一个有效值：{'、'.join(SHOT_SIZES)}{instruction}")
    if 'camera_movement' not in missing and shot['camera_movement'] not in CAMERA_MOVEMENTS:
        issues.append(f"{label} camera_movement={shot['camera_movement']!r} 无效；必须选择一个有效值：{'、'.join(CAMERA_MOVEMENTS)}")
    if ('camera_angle' not in missing
            and re.search(r'正反打|切到|切至|切镜|转场|拉近|拉远|变焦', shot['camera_angle'])):
        issues.append(f"{label} camera_angle={shot['camera_angle']!r} 含切镜、转场或变焦指令；该字段只能描述一个机位和角度，切镜应拆为独立分镜")
    return issues


def _validate_shot_production(shot, *, names, kind):
    label = f"{kind} {shot['shot_id']}"
    visual_issues = _shot_visual_issues(shot, kind=kind)
    if visual_issues:
        raise ValueError('；'.join(visual_issues))
    mode = shot.get('dialogue_mode')
    if mode not in ('in_scene', 'device', 'none'):
        raise ValueError(f'{label} 禁止旁白；dialogue_mode 只能为 in_scene、device 或 none')
    speaker, dialogue = shot.get('dialogue_speaker'), shot.get('dialogue')
    if mode == 'none':
        if speaker != '' or dialogue != '':
            raise ValueError(f'{label} 静默镜头的说话人和对白须为空字符串')
    else:
        _text(shot, 'dialogue')
        if speaker not in names or _has_narration(speaker):
            raise ValueError(f'{label} 禁止旁白，说话人必须是已定义的剧情人物')
        if mode == 'in_scene' and speaker not in shot['participants']:
            raise ValueError(f'{label} 场内对白的说话人必须入画；设备传声须明确标记 device')
        if mode == 'device' and not re.search(r'手机|电话|扬声器|免提|外放|录音|对讲机', shot['audio']):
            raise ValueError(f'{label} device 须在 audio 交代场内设备声源，不得作为旁白通道')
    if any(_has_narration(shot[key]) for key in ('audio', 'action', 'emotion_and_performance')):
        raise ValueError(f'{label} 禁止在声音、动作或表演中安排旁白、解说或内心独白')


def _text(row, key):
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'剧本字段 {key} 缺失或为空')
    return value.strip()


def _public_media_evidence(value):
    """Keep verifiable media metadata without exposing local artifact locations to the author."""
    if isinstance(value, dict):
        return {key: _public_media_evidence(item) for key, item in value.items()
                if key != 'path' and not key.endswith('_path')}
    if isinstance(value, list):
        return [_public_media_evidence(item) for item in value]
    return copy.deepcopy(value)


def _full_source_evidence(cohort):
    """Keep the original, verified source records for local audit and validation."""
    def independent_review(analysis):
        # This is a read-only snapshot of a separately bound review, never an
        # upgrade of the model artifact's own candidate/unreviewed status.
        from datetime import timedelta
        from .content_analysis.artifacts import sha256

        unavailable = {'decision': 'not_reviewed', 'reviewed_at': None, 'review_sha256': None,
                       'reason': '没有完整匹配当前来源及分析版本的独立审核',
                       'acoustic_status': 'not_verified',
                       'notice': '历史审核不能替代编剧或LLM审稿重新读取来源证据；ASR和抽帧不证明声线、语气、语速或口型。'}
        try:
            media = analysis.media_evidence
            visual = media.get('visual', {})
            source_hash, artifact_hash = media.get('source_video_sha256'), visual.get('artifact_sha256')
            if (media.get('schema') != 'local_media_evidence/v1' or visual.get('status') != 'completed'
                    or not all(isinstance(h, str) and re.fullmatch(r'[0-9a-f]{64}', h)
                               for h in (source_hash, artifact_hash))):
                return unavailable
            artifact = Path(visual['artifact_path']).resolve()
            source = Path(media['source_video_path']).resolve()
            artifact_bytes = artifact.read_bytes()
            if hashlib.sha256(artifact_bytes).hexdigest() != artifact_hash or sha256(source) != source_hash:
                return unavailable
            qwen = json.loads(artifact_bytes)
            if (qwen.get('schema') != 'local_qwen_frame_analysis/v2'
                    or qwen.get('source_video_sha256') != source_hash
                    or qwen.get('answer', {}).get('expression_analysis') != analysis.expression_analysis):
                return unavailable
            # Do not call require_no_semantic_rejection here: it can write a
            # registry record. Even a malformed existing marker fails closed.
            marker = (Path(__file__).resolve().parents[2] / 'data/video_analysis/semantic_rejections'
                      / f'{artifact_hash}.json')
            if marker.exists():
                return {**unavailable, 'reason': '当前分析SHA已有永久拒绝记录，历史通过记录不可解除拒绝'}
            review_bytes = artifact.with_name('semantic_review.json').read_bytes()
            review = json.loads(review_bytes)
            review_path = review.get('artifact_path')
            if (review.get('schema') != 'source_expression_semantic_review/v1'
                    or review.get('artifact_sha256') != artifact_hash
                    or review.get('source_video_sha256') != source_hash
                    or not isinstance(review_path, str) or not Path(review_path).is_absolute()
                    or Path(review_path).resolve() != artifact
                    or review.get('blocked_for_script_generation') is not False
                    or review.get('decision') not in {'passed', 'passed_with_limits'}):
                return unavailable
            reviewed_at = datetime.fromisoformat(review['reviewed_at'])
            if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
                return unavailable

            def notes(value, count):
                rows = value if isinstance(value, list) else [value] if isinstance(value, str) else []
                selected = []
                shortened = False
                for row in rows[:count]:
                    if isinstance(row, dict):
                        row = row.get('text') or row.get('finding') or row.get('note')
                    if isinstance(row, str) and row.strip():
                        text = row.strip()
                        shortened |= len(text) > 220
                        selected.append(text[:220] + ('…' if len(text) > 220 else ''))
                return selected, len(rows) > count or shortened or len(selected) < min(count, len(rows))

            limits, limited = notes(review.get('limitations') or review.get('review_limits')
                                    or review.get('scope_limitations') or [], 4)
            remarks, notes_limited = notes(review.get('nonblocking_notes') or review.get('findings') or [], 2)
            result = {key: value for key, value in unavailable.items() if key != 'reason'}
            result.update(decision=review['decision'],
                          reviewed_at=reviewed_at.astimezone(timezone(timedelta(hours=8))).isoformat(),
                          review_sha256=hashlib.sha256(review_bytes).hexdigest(),
                          artifact_sha256=artifact_hash, source_video_sha256=source_hash,
                          limits=limits, notes=remarks, summary_is_partial=limited or notes_limited)
            scope = review.get('visual_scope') or review.get('review_scope') or {}
            scope = scope if isinstance(scope, dict) else {}
            for key in ('viewed_count', 'manifest_total_count', 'unviewed_count'):
                if type(scope.get(key)) is int and scope[key] >= 0:
                    result.setdefault('visual_scope', {})[key] = scope[key]
            # The summary deliberately does not certify acoustic checks merely
            # because the source's text/visual semantic review passed.
            acoustic = review.get('acoustic_review')
            acoustic_status = acoustic.get('status') if isinstance(acoustic, dict) else acoustic
            if acoustic_status in ('not_reviewed', 'not_performed'):
                result['acoustic_status'] = 'not_reviewed'
            return result
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return unavailable

    return [{
        'source_id': c.observation.item_id, 'analysis_id': c.analysis.analysis_id,
        'title': c.observation.title, 'hashtags': c.observation.hashtags,
        'metric_kind': c.observation.metric_kind, 'metric_value': c.observation.metric_value,
        'collected_at': c.observation.collected_at, 'published_at': c.observation.published_at,
        'content_summary': c.analysis.content_summary[:1500],
        'media_access_mode': c.analysis.media_access_mode,
        'expression_analysis': copy.deepcopy(c.analysis.expression_analysis),
        'media_evidence': _public_media_evidence(c.analysis.media_evidence),
        'independent_review': independent_review(c.analysis),
    } for c in cohort]


def _claim_evidence_ids(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('evidence', 'evidence_projection'):
                continue
            if key == 'evidence_ids':
                if not isinstance(item, list) or any(not isinstance(eid, str) or not eid for eid in item):
                    raise ValueError('来源主张的 evidence_ids 格式无效')
                yield from item
            else:
                yield from _claim_evidence_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _claim_evidence_ids(item)


def _source_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _reference_source_ids(value, sources=None):
    """Validate an explicit authoring scope without silently deduplicating IDs."""
    if (not isinstance(value, (tuple, list))
            or any(not isinstance(sid, str) or not sid.strip() or sid != sid.strip() for sid in value)):
        raise ValueError('script_reference_source_ids 必须是不含空白的来源ID数组')
    if len(set(value)) != len(value):
        raise ValueError('script_reference_source_ids 不允许重复来源ID')
    if sources is not None:
        unknown = set(value) - {source['source_id'] for source in sources}
        if unknown:
            raise ValueError(f'script_reference_source_ids 含当前完整采样集合中不存在的来源ID：{sorted(unknown)}')
    return tuple(value)


def _source_overview(sources):
    """A comparison index, explicitly distinct from raw cited source evidence."""
    return [{**{key: copy.deepcopy(source.get(key)) for key in (
                 'source_id', 'analysis_id', 'title', 'metric_kind', 'metric_value',
                 'published_at', 'collected_at', 'independent_review')},
             'core_message': copy.deepcopy(source.get('expression_analysis', {}).get('core_message')),
             'expression_modes': copy.deepcopy(source.get('expression_analysis', {}).get('expression_modes', []))}
            for source in sources]


def project_source_evidence(sources, *, reference_usage=()):
    """Send every source's claims with exact cited records and nearby ASR context.

    Bounds are hard failures, not truncation. Full evidence remains in the cohort,
    source analysis artifacts, and the generation trace; it is used for validation.
    """
    if not isinstance(sources, list):
        raise ValueError('source_evidence 必须是来源数组')
    source_ids = [source.get('source_id') for source in sources if isinstance(source, dict)]
    if len(source_ids) != len(sources) or any(not isinstance(sid, str) or not sid for sid in source_ids) or len(set(source_ids)) != len(source_ids):
        raise ValueError('source_evidence 的来源ID缺失或重复')
    extra = {}
    for ref in reference_usage:
        if not isinstance(ref, dict) or ref.get('source_id') not in source_ids:
            raise ValueError('审稿引用来源不在原始来源集合中')
        ids = ref.get('evidence_ids')
        if not isinstance(ids, list) or any(not isinstance(eid, str) or not eid for eid in ids):
            raise ValueError('审稿引用的 evidence_ids 格式无效')
        extra.setdefault(ref['source_id'], set()).update(ids)
    projected = []
    for source in sources:
        sid = source['source_id']
        if 'evidence_projection' in source:
            raise ValueError(f'{sid} 已是编剧证据投影；投影与审稿必须从完整原始来源生成，不能把删减结果冒充完整来源')
        expression = source.get('expression_analysis', {})
        if not isinstance(expression, dict):
            raise ValueError(f'{sid} expression_analysis 格式无效')
        records = expression.get('evidence', [])
        if not isinstance(records, list):
            raise ValueError(f'{sid} 原始 evidence 格式无效')
        by_id = {item.get('id'): item for item in records if isinstance(item, dict)}
        if (len(by_id) != len(records) or any(not isinstance(eid, str) or not eid for eid in by_id)):
            raise ValueError(f'{sid} 原始 evidence ID缺失或重复')
        cited = set(_claim_evidence_ids(expression))
        required = cited | extra.get(sid, set())
        missing = required - set(by_id)
        if missing:
            raise ValueError(f'{sid} 来源主张或剧本引用了不存在的 evidence_ids：{sorted(missing)}')
        def interval(item):
            values = (item.get('start_seconds'), item.get('end_seconds'))
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in values) or values[1] < values[0]:
                raise ValueError(f'{sid} {item.get("id")} 证据时间无效')
            return values
        asr = sorted((item for item in records if item.get('channel') == 'asr'), key=interval)
        positions = {item['id']: index for index, item in enumerate(asr)}
        anchors = {eid for eid in required if eid in positions}
        for eid in required:
            item = by_id[eid]
            start, end = interval(item)
            if item.get('channel') != 'visual' or not asr:
                continue
            overlapping = [row for row in asr if row['start_seconds'] <= end and row['end_seconds'] >= start]
            if overlapping:
                anchors.update(row['id'] for row in overlapping)
            else:
                nearest = min(asr, key=lambda row: max(row['start_seconds']-end, start-row['end_seconds'], 0))
                if max(nearest['start_seconds']-end, start-nearest['end_seconds'], 0) <= 3:
                    anchors.add(nearest['id'])
        selected = required | anchors
        for eid in anchors:
            index = positions[eid]
            for neighbor in (index-1, index+1):
                if 0 <= neighbor < len(asr):
                    left, right = sorted((asr[index], asr[neighbor]), key=interval)
                    if right['start_seconds'] - left['end_seconds'] <= 8:
                        selected.add(asr[neighbor]['id'])
        if len(selected) > SOURCE_PROJECTION_MAX_RECORDS:
            raise SourceSemanticReviewError(f'{sid} 必需证据与紧邻转写共 {len(selected)} 条，超过单源 {SOURCE_PROJECTION_MAX_RECORDS} 条编剧输入预算；须先复核来源主张范围，不能静默删去引用或直接调用模型。')
        row = copy.deepcopy(source)
        row['expression_analysis']['evidence'] = [copy.deepcopy(item) for item in records if item['id'] in selected]
        # Coverage remains explicit; a long per-frame timestamp array is available
        # in the complete local evidence, not duplicated into the writer context.
        visual = row.get('media_evidence', {}).get('visual', {})
        sample_times = visual.pop('sample_times_seconds', None)
        row['evidence_projection'] = {
            'schema': 'script_source_evidence_projection/v1',
            'strategy': 'all_source_claims_exact_citations_and_immediate_asr_context',
            'total_evidence_count': len(records), 'included_evidence_count': len(selected),
            'omitted_evidence_count': len(records)-len(selected),
            'claim_cited_evidence_ids': sorted(cited),
            'script_cited_evidence_ids': sorted(extra.get(sid, set())),
            'context_evidence_ids': sorted(selected-required),
            'full_source_sha256': hashlib.sha256(_source_json(source).encode('utf-8')).hexdigest(),
            'omitted_visual_sample_time_count': len(sample_times) if isinstance(sample_times, list) else 0,
            'notice': '全部候选主张保留，原始引文逐字保留；省略了未被主张或剧本引用且非邻近上下文的证据。此输入不代表原片的全部细节，未显示部分不能推断。完整来源保留在本地分析与审计中。',
        }
        size = len(_source_json(row))
        if size > SOURCE_PROJECTION_MAX_CHARS:
            raise SourceSemanticReviewError(f'{sid} 保留全部主张及必需证据后为 {size} 字符，超过单源 {SOURCE_PROJECTION_MAX_CHARS} 字符预算；须先复核来源分析范围，未截断引文、未调用模型。')
        projected.append(row)
    total = len(_source_json(projected))
    if total > SOURCE_PROJECTION_TOTAL_MAX_CHARS:
        raise SourceSemanticReviewError(f'全部 {len(sources)} 条来源的必需证据为 {total} 字符，超过编剧输入 {SOURCE_PROJECTION_TOTAL_MAX_CHARS} 字符预算；须分阶段复核来源主张，不能丢弃来源或引文。')
    return projected


def build_messages(profile, cohort, overlap, *, short_seconds, long_seconds, editor_feedback='', continuous_short=False,
                   script_reference_source_ids=()):
    from .media_evidence import build_expression_patterns

    prompt = PROMPT_PATH.read_text(encoding='utf-8')
    sources = _full_source_evidence(cohort)
    selected = _reference_source_ids(script_reference_source_ids, sources)
    payload = {
        'short_seconds': short_seconds, 'long_seconds': long_seconds,
        'account_positioning': {'domain': profile.domain_strategy_id,
                                'service_scope': profile.service_scope,
                                'audiences': profile.target_audiences,
                                'domain_config': profile.domain_config},
        'expression_direction': {
            'priority': ['prop_demonstration', 'conflict_drama', 'action_comparison'],
            'requirement': '用实物状态变化、人物目标受阻和行动结果表达核心；问答不作为默认形式，动作不能只是讲知识时翻页点头。',
        },
        'focus': overlap.focus,
        'observed_traits': [{'dimension': t.dimension, 'value': t.value,
                            'evidence_level': t.evidence_level} for t in overlap.traits],
        'source_evidence': project_source_evidence(
            [source for source in sources if source['source_id'] in selected] if selected else sources),
        'expression_patterns': build_expression_patterns(cohort),
        'reference_policy': '采样分数、点赞份额不是创作贡献；只报告逐源证据和实际借鉴到的镜头，不生成参考贡献百分比。',
    }
    if selected:
        payload['source_overview'] = _source_overview(sources)
        payload['script_reference_selection'] = {
            'schema': 'script_reference_selection/v1', 'mode': 'explicit_source_focus',
            'requested_source_ids': list(selected),
            'detailed_source_ids': [row['source_id'] for row in payload['source_evidence']],
            'full_source_count': len(sources), 'overview_source_count': len(sources),
            'full_source_evidence_sha256': hashlib.sha256(_source_json(sources).encode('utf-8')).hexdigest(),
            'notice': '全批次来源仍用于采样门槛和表达对照。source_overview仅为核心、方式、指标及历史审核概览，不是原文证据；本次只从指定详细来源借鉴并填写reference_usage。选中来源保留全部既有投影，不再删引文。审稿必须重新读取实际引用的原文和相邻上下文，历史审核及ID合法不代表内容通过。',
        }
    if continuous_short:
        prompt += ('\n本轮短版使用S01定义的场景级共享制作设置：仅S01完整定义shot_size、camera_angle、lighting，'
                   'S02起这三个字段可以写“同S01”，程序会在校验和审稿前展开为S01原值。'
                   '这项专用规则替代短版重复填写光线和景别的要求；所有镜头camera_movement仍须为“固定”。'
                   '每镜动作、人物站位、构图、道具与对白独立编写，必须在S01固定画幅和光线下成立。长版规则不变。')
        payload['production_constraints'] = {'short_mode':'continuous_fixed_two_person',
            'shared_production': {'source_shot_id': 'S01', 'fields': ['shot_size', 'camera_angle', 'lighting'],
                                  'later_shot_reference': '同S01', 'camera_movement': '固定'},
            'required':'短版每镜participants均包含两个既有角色；S01完整定义场景级固定景别、机位和灯光，后续镜仅复用这三个设置，不重新定义光源或机位；camera_movement逐镜为固定；程序会将每镜start_frame直接绑定到紧邻前镜end_frame，动作必须从该继承状态开始，不得依赖另写的重置姿态；首尾状态只写静态姿态与持物，动作推进写在本镜action；单镜4—15整数秒。所有动作与道具变化仍需在共享制作设置下成立并接受审稿。长版不受此固定机位限制。'}
    payload['editor_feedback'] = editor_feedback
    return [{'role': 'system', 'content': prompt},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]


def validate_continuous_short(data):
    short = data['short']
    names = {c['name'] for c in short['characters']}
    if len(names) != 2:
        raise ValueError('连续双人短版必须保留两个角色')
    first, previous, issues = short['shots'][0], None, []
    for shot in short['shots']:
        sid = shot['shot_id']
        if len(shot['participants']) != 2 or set(shot['participants']) != names:
            issues.append(f'{sid} participants必须包含两个既有角色')
        if shot['camera_movement'] != '固定':
            issues.append(f'{sid} camera_movement必须固定')
        for field in ('shot_size', 'camera_angle', 'lighting'):
            if shot[field] != first[field]:
                issues.append(f'{sid} {field}必须与S01逐字一致，维持同一机位景别和光源')
        if previous and shot['start_frame'].strip() != previous['end_frame'].strip():
            issues.append(f"{sid} start_frame必须逐字承接{previous['shot_id']} end_frame；状态推进放在本镜action，不能跳过拿放动作")
        duration = shot['end_seconds'] - shot['start_seconds']
        if duration != int(duration) or not 4 <= duration <= 15:
            issues.append(f'{sid}时长必须为4—15整数秒')
        previous = shot
    if issues:
        raise ValueError('连续拍摄结构未通过：' + '；'.join(issues))


def bind_continuous_starts(data):
    """Resolve each start to the model-authored previous end, preserving raw prose in the trace."""
    result = copy.deepcopy(data)
    changes = []
    shots = result['short']['shots']
    for previous, current in zip(shots, shots[1:]):
        inherited = previous['end_frame']
        if current['start_frame'] != inherited:
            changes.append({'shot_id':current['shot_id'], 'field':'start_frame',
                'source':f"short.{previous['shot_id']}.end_frame",
                'model_proposed_start':current['start_frame'], 'bound_start':inherited})
            current['start_frame'] = inherited
    return result, changes


def bind_continuous_production(data):
    """Expand S01's scene-level settings without rewriting any story/action field."""
    result = copy.deepcopy(data)
    shots = result['short']['shots']
    if not shots or shots[0].get('shot_id') != 'S01':
        raise ValueError('连续短版共享制作设置必须由S01定义')
    first = shots[0]
    shared_fields = ('shot_size', 'camera_angle', 'lighting')
    settings = {}
    for field in shared_fields:
        _text(first, field)
        value = first[field]
        if re.search(r'同S0?1|沿用S0?1|同上', value, re.IGNORECASE):
            raise ValueError(f'S01 {field}须完整定义，不能引用自身或写同上')
        settings[field] = value
    if settings['shot_size'] not in SHOT_SIZES:
        raise ValueError('S01 shot_size必须是一个有效景别')
    if re.search(r'正反打|切到|切至|切镜|转场|拉近|拉远|变焦', settings['camera_angle']):
        raise ValueError('S01 camera_angle须定义一个固定机位，不得包含切镜或变焦')
    # Moving-camera requests are not wording variants of a fixed setup. Keep
    # the existing strict constraint rather than silently normalizing them.
    if any(shot.get('camera_movement') != '固定' for shot in shots):
        raise ValueError('连续短版camera_movement逐镜必须固定，共享设置不能覆盖运镜请求')
    changes = []
    for shot in shots[1:]:
        for field, inherited in settings.items():
            if field in shot and not isinstance(shot[field], str):
                raise ValueError(f"{shot['shot_id']} {field}必须是文字或省略以复用S01")
            if shot.get(field) != inherited:
                changes.append({'shot_id': shot['shot_id'], 'field': field,
                                'source': f'short.S01.{field}', 'model_proposed': shot.get(field),
                                'bound_value': inherited})
                shot[field] = inherited
    return result, {'schema': 'continuous_short_shared_production/v1', 'scope': 'short',
                    'source_shot_id': 'S01', 'settings': {**settings, 'camera_movement': '固定'},
                    'changes': changes,
                    'review_requirement': '共享设置只确定拍摄条件；仍须检查每镜动作、构图、人物、道具、声音、因果和引用是否成立。'}


def _preflight_shots(data, *, short_seconds, long_seconds):
    """Report independent shot defects together instead of wasting a rewrite per missing field."""
    issues = []
    required = ('scene', 'blocking', 'action', 'emotion_and_performance', 'audio',
                'narrative_purpose', 'continuity', *VISUAL_FIELDS)
    for kind, duration in (('short', short_seconds), ('long', long_seconds)):
        row = data.get(kind)
        if not isinstance(row, dict) or not isinstance(row.get('shots'), list):
            continue
        names = {c.get('name') for c in row.get('characters', []) if isinstance(c, dict)
                 and isinstance(c.get('name'), str)}
        shots = row['shots']
        if any(not isinstance(s, dict) for s in shots):
            continue
        if [s.get('shot_id') for s in shots] != [f'S{i:02d}' for i in range(1, len(shots) + 1)]:
            issues.append(f'{kind} 必须独立从 S01 编号至 S{len(shots):02d}，不可沿用另一版编号；节拍 shot_ids 同步对应')
        total = 0
        cursor = 0.0
        for i, original in enumerate(shots, 1):
            shot = {**original, 'shot_id': f'S{i:02d}'}
            label = f'{kind} S{i:02d}'
            missing = [f for f in required if not isinstance(shot.get(f), str) or not shot[f].strip()]
            other_missing = [f for f in missing if f not in VISUAL_FIELDS]
            if other_missing:
                issues.append(f"{label} 缺失字段：{', '.join(other_missing)}")
            visual_issues = _shot_visual_issues(shot, kind=kind)
            issues.extend(visual_issues)
            if not visual_issues and not any(f in missing for f in ('audio', 'action', 'emotion_and_performance')):
                speaker = shot.get('dialogue_speaker')
                if isinstance(speaker, str):
                    normalized = re.sub(r'[（(][^（）()]*[）)]$', '', speaker).strip()
                    if normalized in names:
                        shot['dialogue_speaker'] = normalized
                try:
                    _validate_shot_production(shot, names=names, kind=kind)
                except (ValueError, KeyError, TypeError) as exc:
                    issues.append(f'{label} {exc}')
            dialogue = shot.get('dialogue')
            start, end = shot.get('start_seconds'), shot.get('end_seconds')
            valid_time = all(type(v) in (int, float) and math.isfinite(v) for v in (start, end))
            if not valid_time:
                issues.append(f'{label} 时间必须是有效数字')
            else:
                if abs(start - cursor) > 0.01:
                    issues.append(f'{label} 时间线不连续：上一镜结束于 {cursor:g} 秒，本镜开始于 {start:g} 秒')
                if not 3 <= end - start <= 20:
                    issues.append(f'{label} 单镜时长 {end-start:g} 秒超出3—20秒范围；当前 {start:g}—{end:g} 秒')
                cursor = end
            if isinstance(dialogue, str):
                total += len(dialogue)
                if all(type(v) in (int, float) and math.isfinite(v) for v in (start, end)) and end > start:
                    if len(dialogue) > (end - start) * 5:
                        issues.append(f'{label} 台词过长：{len(dialogue)} 字 / {end-start:g} 秒，最多 {int((end-start)*5)} 字（含标点）')
        if total > duration * 4:
            issues.append(f'{kind} 全片台词 {total} 字，超过自然语速预算 {duration*4:g} 字')
        if abs(cursor - duration) > 0.01:
            issues.append(f'{kind} 总时长须为 {duration:g} 秒')
        if shots and shots[-1].get('dialogue') != row.get('closing_line'):
            issues.append(f'{kind} closing_line 必须等于本版最后镜头 dialogue，逐字一致')
    if issues:
        raise ValueError('请一次修正以下全部问题：' + '；'.join(issues))


def _shot_references(row, key, valid_ids, label):
    value = row.get(key)
    if (not isinstance(value, list) or not value
            or any(not isinstance(sid, str) or sid not in valid_ids for sid in value)
            or len(value) != len(set(value))):
        raise ValueError(f'{label} {key} 必须引用本版真实且不重复的镜头编号')
    return value


def _validate_expression_trace(row, *, kind, names, source_evidence, script_reference_source_ids=()):
    """Verify trace identifiers; editorial review still judges whether actions carry the story."""
    plan = row.get('expression_plan')
    if not isinstance(plan, dict):
        raise ValueError(f'{kind} 缺少 expression_plan，须先选择有音画证据的表达方式')
    for key in ('presentation_mode', 'account_fit', 'source_pattern_rationale', 'protagonist',
                'goal', 'obstacle', 'stakes'):
        _text(plan, key)
    if plan['protagonist'] not in names:
        raise ValueError(f'{kind} expression_plan.protagonist 必须是本版已定义角色')
    valid_ids = [s['shot_id'] for s in row['shots']]
    chain = plan.get('action_chain')
    if not isinstance(chain, list) or len(chain) < 2 or any(not isinstance(v, dict) for v in chain):
        raise ValueError(f'{kind} action_chain 至少写出两步改变情境的可见行动')
    changes = []
    for step in chain:
        _shot_references(step, 'shot_ids', valid_ids, f'{kind} action_chain')
        _text(step, 'visible_action')
        changes.append(_text(step, 'state_change'))
    if len(set(changes)) != len(changes):
        raise ValueError(f'{kind} action_chain 不可用重复的状态变化假充剧情推进')
    beats = {b['role']: b['shot_ids'] for b in row['story_beats']}
    for field, text_fields, required_ids in (
            ('turn', ('visible_trigger', 'result'), beats['turn']),
            ('ending', ('visible_result', 'core_answer'), [valid_ids[-1]])):
        part = plan.get(field)
        if not isinstance(part, dict):
            raise ValueError(f'{kind} expression_plan 缺少 {field}')
        ids = _shot_references(part, 'shot_ids', valid_ids, f'{kind} {field}')
        if not set(ids).intersection(required_ids):
            raise ValueError(f'{kind} {field} 未落实到实际转折节拍或结尾镜头')
        for key in text_fields:
            _text(part, key)
    usage = row.get('reference_usage')
    if not isinstance(usage, list) or not usage:
        raise ValueError(f'{kind} reference_usage 缺失，必须记录实际借鉴的来源证据与镜头')
    if not isinstance(source_evidence, list) or not source_evidence:
        raise ValueError('缺少可验证的 source_evidence，不能确认剧本引用来源')
    sources = {s['source_id']: s for s in source_evidence if isinstance(s, dict) and s.get('source_id')}
    if len(sources) != len(source_evidence):
        raise ValueError('source_evidence 的 source_id 缺失或重复')
    selected = _reference_source_ids(script_reference_source_ids, source_evidence)
    validated = []
    allowed = {'source_id', 'evidence_ids', 'borrowed_expression', 'adaptation', 'shot_ids'}
    for ref in usage:
        if not isinstance(ref, dict) or set(ref) != allowed:
            raise ValueError(f'{kind} reference_usage 只允许来源、证据、借鉴方式、改编和镜头字段；不得编造贡献占比')
        sid = _text(ref, 'source_id')
        if sid not in sources:
            raise ValueError(f'{kind} 引用了未提供的来源 source_id={sid}')
        if selected and sid not in selected:
            raise ValueError(f'{kind} {sid} 仅有来源概览，未被指定为本次详细参考；不能把概览当作引用原文')
        analysis = sources[sid].get('expression_analysis', {})
        source_items = analysis.get('evidence', [])
        available = {e.get('id'): e for e in source_items
                     if isinstance(e, dict) and e.get('id')}
        if len(available) != len(source_items):
            raise ValueError(f'{kind} {sid} 原始音画证据ID缺失或重复')
        ids = ref.get('evidence_ids')
        if (not isinstance(ids, list) or not ids or any(not isinstance(eid, str) or eid not in available for eid in ids)
                or len(ids) != len(set(ids))):
            raise ValueError(f'{kind} {sid} evidence_ids 必须来自该视频实际音画证据')
        source_duration = sources[sid].get('media_evidence', {}).get('duration_seconds')
        for eid in ids:
            item = available[eid]
            start, end = item.get('start_seconds'), item.get('end_seconds')
            if (item.get('channel') not in ('visual', 'asr') or not isinstance(item.get('text'), str)
                    or not item['text'].strip()
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end))
                    or start < 0 or end < start
                    or (type(source_duration) in (int, float) and end > source_duration + .25)):
                raise ValueError(f'{kind} {sid} {eid} 缺少有效音画证据内容、通道或原视频时间范围')
        _shot_references(ref, 'shot_ids', valid_ids, f'{kind} reference_usage')
        _text(ref, 'borrowed_expression')
        _text(ref, 'adaptation')
        validated.append({**copy.deepcopy(ref), 'analysis_id': sources[sid].get('analysis_id', ''),
                          'source_evidence': [copy.deepcopy(available[eid]) for eid in ids]})
    return {'expression_plan': copy.deepcopy(plan), 'reference_usage': copy.deepcopy(usage),
            'reference_usage_validation': {'status': 'identifiers_verified_content_pending_editorial_review',
                'attribution_method': 'explicit_evidence_to_shot_mapping_not_contribution_percentage',
                'references': validated}}


def parse_pair(raw, *, profile, created_at, short_seconds, long_seconds, generation, source_evidence=None):
    from .pre_video_script import (CharacterSpec, DetailedVideoScript, _build_detailed_shot,
                                   STYLE, NEGATIVE_CONSTRAINTS)

    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        detail = f'（{exc}）' if isinstance(exc, json.JSONDecodeError) else ''
        raise ValueError('模型未返回有效的双剧本 JSON' + detail) from exc
    if not isinstance(data, dict) or set(data) != {'core_message', 'short', 'long'}:
        raise ValueError('必须同时返回一个核心、短版和长版剧本')
    _preflight_shots(data, short_seconds=short_seconds, long_seconds=long_seconds)
    core = _text(data, 'core_message')
    scripts = []
    delivery_issues = []
    for kind, duration in [('short', short_seconds), ('long', long_seconds)]:
        row = data[kind]
        if not isinstance(row, dict):
            raise ValueError(f'{kind} 剧本格式无效')
        text = {key: _text(row, key) for key in (
            'title', 'premise', 'dramatic_question', 'resolution', 'closing_line', 'legal_review_note')}
        ending = text['closing_line']
        if ending.endswith(('？', '?', '…', '...')) or any(word in ending for word in (
            '未完待续', '下集', '下期', '后续揭晓', '关注看后续')):
            raise ValueError('结尾仍悬而未决，需改写为明确收束')
        raw_characters = row.get('characters')
        if not isinstance(raw_characters, list) or not 1 <= len(raw_characters) <= 6:
            raise ValueError('需要 1—6 个明确角色')
        characters = tuple(CharacterSpec(**{f.name: _text(c, f.name) for f in fields(CharacterSpec)})
                           for c in raw_characters if isinstance(c, dict))
        names = {c.name for c in characters}
        if len(names) != len(raw_characters):
            raise ValueError('角色格式无效或姓名重复')
        if any(_has_narration(c.name + '；' + c.identity) for c in characters):
            raise ValueError('禁止定义旁白或解说角色；仅允许情境中的人物')
        continuity = ('全片锁定角色的脸型、发型、服装、配饰和体型。',
                      '物件、空间、视线和动作按时间线衔接，不凭空出现或消失。',
                      '只以剧情人物的动作和场内对白推进；禁止旁白、解说配音和内心独白。',
                      '末镜头完成结果与情绪收束，不为下一集留悬念。')
        raw_shots = row.get('shots')
        low, high = (6, 12) if kind == 'short' else (9, 30)
        if not isinstance(raw_shots, list) or not low <= len(raw_shots) <= high:
            raise ValueError(f'{kind} 需要 {low}—{high} 个镜头')
        shots, cursor = [], 0.0
        for index, shot in enumerate(raw_shots, 1):
            if not isinstance(shot, dict) or shot.get('shot_id') != f'S{index:02d}':
                raise ValueError('镜头编号须从 S01 连续递增')
            for key in ('scene', 'blocking', 'action', 'emotion_and_performance',
                        'audio', 'narrative_purpose', 'continuity'):
                _text(shot, key)
            start, end = shot.get('start_seconds'), shot.get('end_seconds')
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end)):
                raise ValueError('镜头时间必须是有效数字')
            if abs(start - cursor) > 0.01 or not 3 <= end - start <= 20:
                raise ValueError('时间线必须连续，单镜头须为 3—20 秒')
            cursor = end
            participants = shot.get('participants')
            if not isinstance(participants, list) or not participants or any(p not in names for p in participants):
                raise ValueError('镜头中出现未定义角色')
            speaker = shot.get('dialogue_speaker', '')
            if not isinstance(speaker, str):
                raise ValueError('dialogue_speaker 必须是字符串')
            normalized_speaker = re.sub(r'[（(][^（）()]*[）)]$', '', speaker).strip()
            if normalized_speaker in names and normalized_speaker != speaker:
                shot = {**shot, 'dialogue_speaker': normalized_speaker,
                        'audio': shot['audio'] + '；声音表演：' + speaker}
            _validate_shot_production(shot, names=names, kind=kind)
            if len(shot['dialogue']) > (end - start) * 5:
                delivery_issues.append(f"{kind} {shot['shot_id']} 台词过长：{len(shot['dialogue'])} 字 / {end-start:g} 秒，"
                                       f"最多 {int((end-start)*5)} 字（含标点）；请缩短这句：{shot['dialogue']}")
            shots.append(_build_detailed_shot(shot, characters=characters, global_continuity=continuity))
        if abs(cursor - duration) > 0.01:
            raise ValueError(f'{kind} 剧本总时长应为 {duration} 秒')
        if shots[-1].dialogue.strip() != ending:
            delivery_issues.append(f'{kind} 收尾台词必须实际出现在最后一个镜头；closing_line={ending!r}，'
                                   f'末镜 dialogue={shots[-1].dialogue!r}，请改为逐字相同且符合末镜时长的短句')
        spoken_total = sum(len(s.dialogue) for s in shots)
        if spoken_total > duration * 4:
            delivery_issues.append(f'{kind} 全片台词 {spoken_total} 字，超过自然语速预算 {duration*4:g} 字；'
                                   '同时精简各镜头赘述，保留必要的规则边界和结局')
        beats = row.get('story_beats')
        if (not isinstance(beats, list) or any(not isinstance(b, dict) for b in beats)
                or tuple(b.get('role') for b in beats) != BEAT_ROLES):
            raise ValueError('必须具备顺序完整的六段因果结构')
        beat_ids = []
        for beat in beats:
            _text(beat, 'because')
            _text(beat, 'change')
            if not isinstance(beat.get('shot_ids'), list) or not beat['shot_ids']:
                raise ValueError('每段剧情必须落实到镜头')
            beat_ids.extend(beat['shot_ids'])
        if beat_ids != [shot.shot_id for shot in shots]:
            raise ValueError('剧情节拍必须按顺序覆盖每个镜头且不重复')
        expression_trace = _validate_expression_trace(row, kind=kind, names=names, source_evidence=source_evidence,
            script_reference_source_ids=generation.get('script_reference_selection', {}).get('requested_source_ids', ()))
        digest = hashlib.sha256((raw + kind + created_at).encode()).hexdigest()[:24]
        scripts.append(DetailedVideoScript(
            schema='detailed_video_script/v4', script_id=f'detailed-script:{digest}-{kind}',
            account_uuid=profile.account_uuid, domain_strategy_id=profile.domain_strategy_id,
            strategy_version=profile.strategy_version, variant_id=kind, title=text['title'],
            status='draft_pending_legal_review', target_duration_seconds=float(duration),
            aspect_ratio='9:16', style=STYLE, premise=text['premise'], characters=characters,
            shots=tuple(shots), global_continuity=continuity, negative_constraints=NEGATIVE_CONSTRAINTS,
            legal_review_note=text['legal_review_note'], created_at=created_at, format_kind=kind,
            core_message=core, dramatic_question=text['dramatic_question'], resolution=text['resolution'],
            closing_line=ending, story_beats=tuple(beats), generation={**copy.deepcopy(generation), **expression_trace}))
    if delivery_issues:
        raise ValueError('请一次修正以下全部问题：' + '；'.join(delivery_issues))
    if len(scripts[1].shots) < len(scripts[0].shots) + 3:
        raise ValueError('长版需要新增至少三个推进剧情的镜头')
    # Both versions may share the same setup. Actual added story value is
    # reviewed under long_adds_value; identical dialogue expansion still fails.
    if [s.dialogue for s in scripts[0].shots] == [s.dialogue for s in scripts[1].shots[:len(scripts[0].shots)]]:
        raise ValueError('长版不能直接复制短版扩时')
    return tuple(scripts)


REVIEW_CHECKS = ('domain_fit', 'core_clear', 'opening_answered', 'ending_complete',
                 'reasoning_coherent', 'spoken_fit', 'evidence_honest', 'long_adds_value',
                 'no_narration', 'visual_complete', 'shot_continuity',
                 'expression_source_fit', 'action_drives_story', 'conflict_turn_payoff',
                 'source_semantic_fidelity')

CURRENT_SCRIPT_REVIEW_SCHEMA = 'script_editorial_evidence_review/v2'
SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS = 3
SCRIPT_REVIEW_MAX_EVIDENCE_PATCH_ATTEMPTS = 2
SCRIPT_REVIEW_MAX_TOTAL_ATTEMPTS = SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS + SCRIPT_REVIEW_MAX_EVIDENCE_PATCH_ATTEMPTS
REVIEW_RAW_FIELDS = {'checks', 'issues', 'summary', 'candidate_sha256', 'evidence_sha256',
                     'shot_audit', 'result_audit', 'character_audit', 'conflict_audit'}
REVIEW_CROSS_FIELDS = ('dialogue', 'audio', 'emotion_and_performance', 'blocking',
                       'camera_angle', 'composition', 'start_frame', 'end_frame')
REVIEW_CROSS_CHECKS = ('dialogue_action', 'voice_performance', 'spatial')
REVIEW_CONFLICT_GROUPS = {'opening': ('setup',), 'dispute': ('conflict', 'escalation'),
                         'turn': ('turn',), 'ending': ('resolution', 'closure')}


def build_script_review_rows(scripts):
    """One exact review projection for live scripts and saved artifact dictionaries.

    This excludes saved approval flags and recomputes speech budgets. It does not
    validate or grant editorial approval; callers must verify the current report.
    """
    def value(obj, key):
        try:
            return obj[key] if isinstance(obj, dict) else getattr(obj, key)
        except (KeyError, AttributeError) as exc:
            raise ValueError(f'送审稿件缺少实际字段：{key}') from exc

    rows = []
    for script in scripts:
        row = {key: value(script, key) for key in (
            'format_kind', 'target_duration_seconds', 'title', 'core_message', 'dramatic_question',
            'premise', 'resolution', 'closing_line', 'story_beats', 'legal_review_note')}
        generation = value(script, 'generation')
        row.update({key: value(generation, key) for key in ('expression_plan', 'reference_usage')})
        row['characters'] = [{key: value(character, key) for key in
            ('name', 'identity', 'appearance', 'wardrobe', 'performance_arc')}
            for character in value(script, 'characters')]
        row['shots'] = []
        for shot in value(script, 'shots'):
            projected = {key: value(shot, key) for key in (
                'shot_id', 'start_seconds', 'end_seconds', 'scene', 'participants', 'blocking',
                'action', 'dialogue_speaker', 'dialogue', 'dialogue_mode', 'audio',
                'emotion_and_performance', 'continuity', *VISUAL_FIELDS, 'narrative_purpose')}
            start, end = projected['start_seconds'], projected['end_seconds']
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end) or end <= start
                    or not isinstance(projected['dialogue'], str)):
                raise ValueError('实际送审镜头时长或对白无效')
            duration, count = end - start, len(projected['dialogue'])
            projected['spoken_budget'] = {'characters_including_punctuation': count,
                'duration_seconds': duration, 'characters_per_second': round(count / duration, 3)}
            row['shots'].append(projected)
        rows.append(row)
    # Normalize tuple/list representations and detach all saved/live nested data.
    return json.loads(json.dumps(rows, ensure_ascii=False, allow_nan=False))


def _review_structural_facts(script_rows):
    """Recompute the exact structural claims sent to the reviewer from current shots."""
    if (not isinstance(script_rows, list) or len(script_rows) != 2
            or {row.get('format_kind') for row in script_rows if isinstance(row, dict)} != {'short', 'long'}):
        raise ValueError('双稿审稿须提供short和long两个实际版本')
    versions = {row['format_kind']: row for row in script_rows}
    for row in script_rows:
        duration = row.get('target_duration_seconds')
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('实际送审时长无效')
    _preflight_shots(versions, short_seconds=versions['short']['target_duration_seconds'],
                     long_seconds=versions['long']['target_duration_seconds'])
    for row in script_rows:
        characters = row.get('characters')
        if not isinstance(characters, list) or not characters:
            raise ValueError('实际送审版本缺少角色')
        names = {_text(c, 'name') for c in characters}
        if len(names) != len(characters) or any(_has_narration(c['name'] + _text(c, 'identity')) for c in characters):
            raise ValueError('实际送审角色重复或包含旁白角色')
        if not row.get('shots'):
            raise ValueError('实际送审版本缺少镜头')
        for shot in row['shots']:
            _validate_shot_production(shot, names=names, kind=row['format_kind'])
    coverage = {}
    for row in script_rows:
        shots = row['shots']
        characters = []
        for character in row['characters']:
            name = character['name']
            visible = [shot['shot_id'] for shot in shots if name in shot['participants']]
            characters.append({'character_name': name,
                'spoken_shot_ids': [shot['shot_id'] for shot in shots
                                    if shot['dialogue_speaker'] == name and shot['dialogue']],
                'first_last_visible_shot_ids': list(dict.fromkeys(visible[:1] + visible[-1:]))})
        groups = {}
        for group, roles in REVIEW_CONFLICT_GROUPS.items():
            allowed = {shot_id for beat in row['story_beats'] if beat['role'] in roles
                       for shot_id in beat['shot_ids']}
            actual = [shot for shot in shots if shot['shot_id'] in allowed]
            groups[group] = {'allowed_shot_ids': [shot['shot_id'] for shot in actual],
                'required_evidence_fields': ['action'] + (['dialogue'] if any(shot['dialogue'] for shot in actual) else [])}
        coverage[row['format_kind']] = {'shot_ids': [shot['shot_id'] for shot in shots],
            'characters': characters, 'conflict_groups': groups}
    return {
        'closing_line_matches_own_last_dialogue': {
            row['format_kind']: row['closing_line'] == row['shots'][-1]['dialogue'] for row in script_rows},
        'different_closing_lines_between_versions_are_allowed': True,
        'duration_and_spoken_budgets_passed': True,
        'narration_forbidden': True,
        'device_dialogue_requires_defined_character_and_in_scene_source': True,
        'verification': 'recomputed_from_current_review_scripts_not_inherited_approval',
        'required_audit_coverage': coverage,
    }


def script_review_binding(payload):
    """Bind a report to precisely the scripts and evidence actually sent for review."""
    return {'candidate_sha256': hashlib.sha256(_source_json(payload['scripts']).encode('utf-8')).hexdigest(),
            'evidence_sha256': hashlib.sha256(_source_json(payload['evidence']).encode('utf-8')).hexdigest()}


def _validate_review_citation(citation, payload):
    if not isinstance(citation, dict):
        raise ValueError('审稿原文引用格式无效')
    quote = citation.get('quote')
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError('审稿原文引用须为非空文字')
    if 'source_id' in citation:
        if set(citation) != {'source_id', 'evidence_id', 'quote'}:
            raise ValueError('审稿来源引用字段无效')
        source = next((row for row in payload['evidence'].get('source_evidence', [])
                       if row.get('source_id') == citation['source_id']), {})
        original = next((item for item in source.get('expression_analysis', {}).get('evidence', [])
                         if item.get('id') == citation['evidence_id']), {})
        value = original.get('text')
        if not isinstance(value, str) or quote not in value:
            raise ValueError('审稿来源引用不在本次实际提供的source_id/evidence_id原文中')
        return
    if set(citation) != {'script', 'shot_id', 'field', 'quote'}:
        raise ValueError('审稿稿件引用字段无效')
    current = next((row for row in payload['scripts'] if row['format_kind'] == citation['script']), None)
    if current and citation['shot_id'] not in ('', 'overall'):
        current = next((shot for shot in current['shots'] if shot['shot_id'] == citation['shot_id']), None)
    value = current.get(citation['field']) if current else None
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False)
    if not isinstance(value, str) or quote not in value:
        limit = 4000
        missing = current is None or citation['field'] not in current
        detail = {
            'required_match': 'contiguous_excerpt',
            'location': f'{citation["script"]}/{citation["shot_id"] or "overall"}/{citation["field"]}',
            'received_quote': quote[:limit],
            'received_quote_length': len(quote),
            'received_quote_truncated': len(quote) > limit,
            'source_field': value[:limit] if isinstance(value, str) else None,
            'source_field_type': 'missing' if missing else type(value).__name__,
            'source_field_missing': missing,
            'source_field_length': len(value) if isinstance(value, str) else None,
            'source_field_truncated': isinstance(value, str) and len(value) > limit,
            'context_character_limit': limit,
        }
        raise ValueError('审稿引用不在当前稿件对应字段中，须重新核对原文：'
                         'quote必须是该字段中逐字连续存在的原文，不能跳过中间文字、跨段拼接或用省略号代替；'
                         '版本元数据用shot_id空串或overall，末镜实际台词用dialogue；'
                         + json.dumps(detail, ensure_ascii=False))


def _review_quote_matches(quote, original, *, full=False, empty=False, location=''):
    if (not isinstance(quote, str) or not isinstance(original, str)
            or (not quote.strip() and not (empty and original == quote == ''))
            or (quote != original if full else quote not in original)):
        detail = {'location': location, 'required_match': 'full' if full else 'contiguous_excerpt'}
        if isinstance(quote, str) and isinstance(original, str):
            # Give the format-only retry the actual failing field and
            # literal evidence. Never repair the quote or its decision.
            prefix = 0
            while prefix < min(len(quote), len(original)) and quote[prefix] == original[prefix]:
                prefix += 1
            start = max(0, prefix - 48)
            detail.update(first_prefix_difference=prefix,
                          received_context=quote[start:prefix + 80],
                          source_context=original[start:prefix + 80])
        raise ValueError('跨字段审核原文不符或覆盖不完整；不可用摘要、局部声线或机位片段代替全文；'
                         + json.dumps(detail, ensure_ascii=False))


def _review_conflict_coverage_detail(script, group, allowed, required, covered):
    return {'location': f'{script}.conflict_audit.{group}', 'script': script, 'group': group,
            'allowed_shot_ids': sorted(allowed), 'required': sorted(required),
            'covered': sorted(covered), 'missing': sorted(required - covered)}


def _review_conflict_location_detail(script, group, allowed, citation, citation_index):
    return {'location': f'{script}.conflict_audit.{group}',
            'citation_index': citation_index,
            'received': {key: citation[key] for key in ('source_id', 'evidence_id', 'script', 'shot_id', 'field')
                         if key in citation},
            'allowed_shot_ids': sorted(allowed), 'allowed_fields': ['action', 'dialogue'],
            'expected_script': script}


def _review_character_endpoint_detail(script, name, endpoints, performance):
    required = list(endpoints)
    received = list(performance) if isinstance(performance, dict) else []
    return {'location': f'{script}.character.{name}.performance_quotes',
            'script': script, 'character_name': name,
            'required_shot_ids': required, 'received_shot_ids': received,
            'missing': [shot_id for shot_id in required if shot_id not in received],
            'extra': [shot_id for shot_id in received if shot_id not in required],
            'received_type': type(performance).__name__,
            'basis': 'participants_first_and_last_visible_shots_not_spoken_shots',
            'notice': '按participants判断该角色首末入画镜头，不按dialogue_speaker的首末发声镜头；只说明缺项，不代填表演引文。'}


class _EvidenceQuoteErrors(ValueError):
    def __init__(self, targets):
        super().__init__('审核结构与覆盖有效，但已有字符串引文需模型逐字修正')
        self.targets = targets


def validate_script_review_report(report, payload):
    return _validate_script_review_report(report, payload)


def plan_review_evidence_patch(report, payload):
    """Classify quote-only format failure without filling text or granting a pass."""
    try:
        _validate_script_review_report(report, payload, _evidence_errors=[])
    except _EvidenceQuoteErrors as exc:
        return exc.targets
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    return None


def _validate_script_review_report(report, payload, *, _evidence_errors=None):
    """Validate evidence coverage and version binding; never infer meaning from a score."""
    if not isinstance(report, dict) or set(report) != REVIEW_RAW_FIELDS:
        raise ValueError('审稿须完整返回checks/issues/summary、两项SHA、shot_audit/result_audit/character_audit/conflict_audit')
    expected_binding = script_review_binding(payload)
    if any(payload.get(key) != digest or report.get(key) != digest for key, digest in expected_binding.items()):
        raise ValueError('审稿候选或证据SHA不匹配；改稿后旧审核失效')
    if (not isinstance(report['checks'], dict) or set(report['checks']) != set(REVIEW_CHECKS)
            or any(type(value) is not bool for value in report['checks'].values())):
        raise ValueError('审稿检查项缺失或无效')
    if not isinstance(report['issues'], list):
        raise ValueError('审稿问题列表缺失')
    for issue in report['issues']:
        if not isinstance(issue, dict) or not isinstance(issue.get('evidence'), list) or not issue['evidence']:
            raise ValueError('每条审稿问题必须引用当前稿件的字段原文evidence')
        for citation in issue['evidence']:
            _validate_review_citation(citation, payload)
    if (not report['checks']['source_semantic_fidelity']
            and not any('source_id' in citation for issue in report['issues'] for citation in issue['evidence'])):
        raise ValueError('来源语义复核不通过时必须引用实际source_id/evidence_id原文')
    _text(report, 'summary')
    expected_shots = {(row['format_kind'], shot['shot_id']) for row in payload['scripts'] for shot in row['shots']}
    expected_results = {(row['format_kind'], target) for row in payload['scripts'] for target in ('resolution', 'ending')}
    if len(expected_shots) != sum(len(row['shots']) for row in payload['scripts']):
        raise ValueError('送审镜号重复，不能据此确认审核覆盖')

    def audit_rows(key, expected, location_field, row_fields):
        rows, seen = report[key], set()
        if not isinstance(rows, list):
            raise ValueError(f'{key}必须完整列出本次审核范围')
        for row in rows:
            if not isinstance(row, dict) or set(row) != row_fields:
                raise ValueError(f'{key}条目字段不完整或含未定义字段')
            location = (_text(row, 'script'), _text(row, location_field))
            if location not in expected or location in seen:
                raise ValueError(f'{key}含未知或重复的版本/位置')
            seen.add(location)
            if row['decision'] not in ('passed', 'failed'):
                raise ValueError(f'{key}不能用未知或待审判断代替完成审核')
            refs = row['action_evidence']
            if not isinstance(refs, list) or not refs:
                raise ValueError(f'{key}缺少实际动作原文依据，不能仅打勾通过')
            matched_action = False
            for citation in refs:
                _validate_review_citation(citation, payload)
                if ('source_id' not in citation and citation['script'] == location[0]
                        and citation['field'] == 'action'
                        and (location_field != 'shot_id' or citation['shot_id'] == location[1])):
                    matched_action = True
            if not matched_action:
                raise ValueError(f'{key}必须引用本镜或本版实际action，不能以元数据、对白或来源摘要代替已完成动作')
            for field in row_fields - {'script', location_field, 'decision', 'action_evidence',
                                      'cross_field_evidence', 'cross_checks'}:
                _text(row, field)
        if seen != expected:
            raise ValueError(f'{key}漏审了实际版本/镜头/结果：{sorted(expected-seen)}')
        return rows

    shots = audit_rows('shot_audit', expected_shots, 'shot_id',
        {'script', 'shot_id', 'decision', 'action_evidence', 'continuity_note', 'voice_note',
         'cross_field_evidence', 'cross_checks', 'dialogue_action_note'})
    results = audit_rows('result_audit', expected_results, 'target',
        {'script', 'target', 'decision', 'action_evidence', 'explanation'})
    versions = {row['format_kind']: row for row in payload['scripts']}
    shot_lookup = {(row['format_kind'], shot['shot_id']): shot
                   for row in payload['scripts'] for shot in row['shots']}

    def quote_matches(quote, original, *, full=False, empty=False, location='', path=''):
        try:
            _review_quote_matches(quote, original, full=full, empty=empty, location=location)
        except ValueError:
            if _evidence_errors is None or not isinstance(quote, str) or not isinstance(original, str) or not path:
                raise
            _evidence_errors.append({'path': path, 'source_text': original,
                'required_match': 'full' if full else 'contiguous_excerpt', 'empty_allowed': empty})

    for index, row in enumerate(shots):
        actual = shot_lookup[(row['script'], row['shot_id'])]
        quotes, checks = row['cross_field_evidence'], row['cross_checks']
        if not isinstance(quotes, dict) or set(quotes) != set(REVIEW_CROSS_FIELDS):
            raise ValueError('cross_field_evidence必须逐镜覆盖全部指定字段')
        for field, quote in quotes.items():
            quote_matches(quote, actual[field], full=field in ('dialogue', 'audio', 'camera_angle'),
                          empty=field == 'dialogue', location=f"{row['script']}.{row['shot_id']}.{field}",
                          path=f'/shot_audit/{index}/cross_field_evidence/{field}')
        if (not isinstance(checks, dict) or set(checks) != set(REVIEW_CROSS_CHECKS)
                or any(check not in ('passed', 'failed') for check in checks.values())):
            raise ValueError('cross_checks必须明确审核对白动作、声音表演和空间关系，缺审或未知不得通过')

    characters, seen = report['character_audit'], set()
    expected_characters = {(kind, c['name']) for kind, script in versions.items() for c in script['characters']}
    character_fields = {'script', 'character_name', 'decision', 'spoken_shot_ids', 'performance_arc_quote',
                        'dialogue_quotes', 'voice_quote', 'performance_quotes', 'assessment'}
    if not isinstance(characters, list):
        raise ValueError('character_audit必须逐版覆盖全部角色')
    for index, row in enumerate(characters):
        if not isinstance(row, dict) or set(row) != character_fields:
            raise ValueError('character_audit字段不完整或含未知字段')
        location = (_text(row, 'script'), _text(row, 'character_name'))
        if location not in expected_characters or location in seen:
            raise ValueError('character_audit含未知或重复角色')
        seen.add(location)
        if row['decision'] not in ('passed', 'failed'):
            raise ValueError('character_audit缺少明确完成判断')
        script, name = versions[location[0]], location[1]
        character = next(c for c in script['characters'] if c['name'] == name)
        spoken = [shot for shot in script['shots'] if shot['dialogue_speaker'] == name and shot['dialogue']]
        visible = [shot for shot in script['shots'] if name in shot['participants']]
        if row['spoken_shot_ids'] != [shot['shot_id'] for shot in spoken]:
            raise ValueError('character_audit发声镜头须按实际顺序完整覆盖，不能遗漏或借用他人对白')
        expected_dialogue = {shot['shot_id']: shot['dialogue'] for shot in spoken}
        if not isinstance(row['dialogue_quotes'], dict) or set(row['dialogue_quotes']) != set(expected_dialogue):
            raise ValueError('character_audit须逐字覆盖该角色全部实际对白')
        for shot_id, original in expected_dialogue.items():
            quote_matches(row['dialogue_quotes'][shot_id], original, full=True,
                location=f'{location[0]}.character.{name}.dialogue_quotes.{shot_id}',
                path=f'/character_audit/{index}/dialogue_quotes/{shot_id}')
        quote_matches(row['performance_arc_quote'], character['performance_arc'], full=True,
                      location=f'{location[0]}.character.{name}.performance_arc_quote',
                      path=f'/character_audit/{index}/performance_arc_quote')
        quote_matches(row['voice_quote'], spoken[0]['audio'] if spoken else '', full=True, empty=not spoken,
                      location=f'{location[0]}.character.{name}.voice_quote',
                      path=f'/character_audit/{index}/voice_quote')
        endpoints = {shot['shot_id']: shot for shot in (visible[:1] + visible[-1:])}
        performance = row['performance_quotes']
        if not isinstance(performance, dict) or set(performance) != set(endpoints):
            raise ValueError('character_audit须覆盖角色首末入画镜头的实际表演；'
                + json.dumps(_review_character_endpoint_detail(location[0], name, endpoints, performance), ensure_ascii=False))
        for shot_id, quote in performance.items():
            quote_matches(quote, endpoints[shot_id]['emotion_and_performance'],
                          location=f'{location[0]}.character.{name}.performance_quotes.{shot_id}',
                          path=f'/character_audit/{index}/performance_quotes/{shot_id}')
        _text(row, 'assessment')
    if seen != expected_characters:
        raise ValueError('character_audit漏审实际角色')

    conflicts, seen = report['conflict_audit'], set()
    conflict_fields = {'script', 'decision', 'conflict_object', 'disputed_property', 'positions',
                       'turn', 'closure_scope', 'evidence'}
    if not isinstance(conflicts, list):
        raise ValueError('conflict_audit必须覆盖两版争议对象和实际解决范围')
    for row in conflicts:
        if not isinstance(row, dict) or set(row) != conflict_fields:
            raise ValueError('conflict_audit字段不完整或含未知字段')
        kind = _text(row, 'script')
        if kind not in versions or kind in seen:
            raise ValueError('conflict_audit含未知或重复版本')
        seen.add(kind)
        if row['decision'] not in ('passed', 'failed'):
            raise ValueError('conflict_audit缺少明确完成判断')
        for field in conflict_fields - {'script', 'decision', 'evidence'}:
            _text(row, field)
        groups, script = row['evidence'], versions[kind]
        if not isinstance(groups, dict) or set(groups) != set(REVIEW_CONFLICT_GROUPS):
            raise ValueError('conflict_audit证据必须覆盖opening/dispute/turn/ending')
        for group, roles in REVIEW_CONFLICT_GROUPS.items():
            allowed = {shot_id for beat in script['story_beats'] if beat['role'] in roles
                       for shot_id in beat['shot_ids']}
            refs, covered = groups[group], set()
            required = {'action'}
            if any(shot_lookup[(kind, shot_id)]['dialogue'] for shot_id in allowed):
                required.add('dialogue')
            if not isinstance(refs, list) or not refs:
                raise ValueError('conflict_audit各阶段必须引用真实动作和实际对白；'
                    + json.dumps(_review_conflict_coverage_detail(kind, group, allowed, required, covered), ensure_ascii=False))
            for citation_index, citation in enumerate(refs):
                _validate_review_citation(citation, payload)
                if ('source_id' in citation or citation['script'] != kind
                        or citation['shot_id'] not in allowed or citation['field'] not in ('action', 'dialogue')):
                    raise ValueError('conflict_audit不得使用别版、别阶段或元数据代替当前阶段的动作对白；'
                        + json.dumps(_review_conflict_location_detail(kind, group, allowed, citation, citation_index),
                                     ensure_ascii=False))
                covered.add(citation['field'])
            if not required <= covered:
                raise ValueError('conflict_audit漏引当前阶段实际动作或对白；'
                    + json.dumps(_review_conflict_coverage_detail(kind, group, allowed, required, covered), ensure_ascii=False))
    if seen != set(versions):
        raise ValueError('conflict_audit漏审版本')
    if _evidence_errors:
        raise _EvidenceQuoteErrors(_evidence_errors)
    validated = copy.deepcopy(report)
    validated['schema'] = CURRENT_SCRIPT_REVIEW_SCHEMA
    validated['passed'] = (all(report['checks'].values()) and not report['issues']
                           and all(row['decision'] == 'passed' for row in shots + results + characters + conflicts)
                           and all(value == 'passed' for row in shots for value in row['cross_checks'].values()))
    return validated


def validate_saved_script_review_report(report, payload):
    """Recheck a saved report against the current exact review payload, not its saved flag."""
    raw_fields = REVIEW_RAW_FIELDS
    saved_fields = {'schema', 'passed', 'format_attempts', 'prompt_sha256', 'legal_review_status', 'source_review_scope',
                    'format_trace_sha256'}
    if (not isinstance(report, dict) or not raw_fields.issubset(report)
            or set(report) - raw_fields - saved_fields
            or report.get('schema') != CURRENT_SCRIPT_REVIEW_SCHEMA
            or type(report.get('passed')) is not bool):
        raise ValueError('已保存审稿报告schema或字段无效，不能沿用其通过标记')
    validated = validate_script_review_report({key: report[key] for key in raw_fields}, payload)
    if report['passed'] != validated['passed']:
        raise ValueError('已保存审稿通过标记与实际逐镜/结果证据门槛不一致')
    return {**copy.deepcopy(report), **validated}


def _parse_script_review_json(response):
    """Keep malformed/ambiguous model JSON rejected rather than silently repairing it."""
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'审稿JSON包含重复字段：{key}；不能覆盖先前判断')
            result[key] = value
        return result
    return json.loads(response, object_pairs_hook=unique_keys)


def _review_evidence_diagnostics(report, payload, *, limit=16):
    """Read-only, bounded diagnostics using the same strict validators.

    This is only format-retry context, not an alternate acceptance gate. It never
    fills missing evidence or changes the model's text or editorial decisions.
    """
    errors = []
    script_fields = {'script', 'shot_id', 'field', 'quote'}
    source_fields = {'source_id', 'evidence_id', 'quote'}

    def record(path, exc):
        message = str(exc)
        reason, marker, details = message.partition('；{')
        item = {'path': path, 'reason': reason[:350]}
        if marker:
            try:
                detail = json.loads('{' + details)
            except (TypeError, ValueError):
                detail = {}
            for key in ('location', 'required_match', 'first_prefix_difference',
                        'received_context', 'source_context', 'source_field_type', 'source_field_missing'):
                if key in detail:
                    item[key] = detail[key]
            if 'received_quote' in detail and isinstance(detail.get('source_field'), str):
                quote, original = detail['received_quote'], detail['source_field']
                matched_offset = original.find(quote[:32]) if quote else -1
                offset = max(0, matched_offset)
                aligned = original[offset:]
                prefix = 0
                while prefix < min(len(quote), len(aligned)) and quote[prefix] == aligned[prefix]:
                    prefix += 1
                start = max(0, prefix - 48)
                item.update(first_prefix_difference=prefix,
                    source_excerpt_offset=offset, source_difference_offset=offset + prefix,
                    diagnostic_alignment='exact_quote_prefix' if matched_offset >= 0 else 'field_start_fallback',
                    received_context=quote[start:prefix + 80], source_context=aligned[start:prefix + 80],
                    diagnostic_input_truncated=detail['received_quote_truncated'] or detail['source_field_truncated'])
        errors.append(item)

    pending = [('$', report)]
    while pending and len(errors) < limit:
        path, value = pending.pop()
        if isinstance(value, dict):
            if set(value) in (script_fields, source_fields):
                try:
                    _validate_review_citation(value, payload)
                except (TypeError, ValueError, KeyError) as exc:
                    record(path, exc)
            else:
                pending.extend((f'{path}.{key}', child) for key, child in reversed(list(value.items())))
        elif isinstance(value, list):
            pending.extend((f'{path}[{index}]', child) for index, child in reversed(list(enumerate(value))))
    actual_shots = {(script['format_kind'], shot['shot_id']): shot
                    for script in payload['scripts'] for shot in script['shots']}
    rows = report.get('shot_audit', []) if isinstance(report, dict) else []
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        if len(errors) >= limit:
            break
        if not isinstance(row, dict):
            continue
        if not isinstance(row.get('script'), str) or not isinstance(row.get('shot_id'), str):
            continue  # Diagnostics must not replace a malformed-location error.
        actual = actual_shots.get((row.get('script'), row.get('shot_id')))
        quotes = row.get('cross_field_evidence')
        if actual is None or not isinstance(quotes, dict):
            continue
        for field in REVIEW_CROSS_FIELDS:
            if len(errors) >= limit:
                break
            if field not in quotes:
                continue  # The main schema gate reports missing fields.
            try:
                _review_quote_matches(quotes[field], actual[field],
                    full=field in ('dialogue', 'audio', 'camera_angle'), empty=field == 'dialogue',
                    location=f"{row['script']}.{row['shot_id']}.{field}")
            except ValueError as exc:
                record(f'$.shot_audit[{index}].cross_field_evidence.{field}', exc)
    versions = {script['format_kind']: script for script in payload['scripts']}
    characters = report.get('character_audit', []) if isinstance(report, dict) else []
    for index, row in enumerate(characters if isinstance(characters, list) else []):
        if len(errors) >= limit:
            break
        if (not isinstance(row, dict) or not isinstance(row.get('script'), str)
                or not isinstance(row.get('character_name'), str)):
            continue
        kind, name = row['script'], row['character_name']
        if kind not in versions or name not in {c['name'] for c in versions[kind]['characters']}:
            continue
        visible = [shot for shot in versions[kind]['shots'] if name in shot['participants']]
        endpoints = {shot['shot_id']: shot for shot in visible[:1] + visible[-1:]}
        performance = row.get('performance_quotes')
        if not isinstance(performance, dict) or set(performance) != set(endpoints):
            errors.append({'path': f'$.character_audit[{index}].performance_quotes',
                'reason': '角色表演引文镜号未覆盖实际首末入画镜头',
                **_review_character_endpoint_detail(kind, name, endpoints, performance)})
        character = next(c for c in versions[kind]['characters'] if c['name'] == name)
        spoken = [shot for shot in versions[kind]['shots'] if shot['dialogue_speaker'] == name and shot['dialogue']]
        quote_targets = [
            ('performance_arc_quote', row.get('performance_arc_quote'), character['performance_arc'], True, False),
            ('voice_quote', row.get('voice_quote'), spoken[0]['audio'] if spoken else '', True, not spoken)]
        dialogue = row.get('dialogue_quotes')
        if isinstance(dialogue, dict):
            quote_targets.extend((f'dialogue_quotes.{shot["shot_id"]}', dialogue[shot['shot_id']],
                shot['dialogue'], True, False) for shot in spoken if shot['shot_id'] in dialogue)
        if isinstance(performance, dict):
            quote_targets.extend((f'performance_quotes.{shot_id}', performance[shot_id],
                shot['emotion_and_performance'], False, False)
                for shot_id, shot in endpoints.items() if shot_id in performance)
        for field, quote, original, full, empty in quote_targets:
            if len(errors) >= limit:
                break
            try:
                _review_quote_matches(quote, original, full=full, empty=empty,
                    location=f'{kind}.character.{name}.{field}')
            except ValueError as exc:
                record(f'$.character_audit[{index}].{field}', exc)
    conflicts = report.get('conflict_audit', []) if isinstance(report, dict) else []
    for index, row in enumerate(conflicts if isinstance(conflicts, list) else []):
        if len(errors) >= limit:
            break
        if not isinstance(row, dict) or not isinstance(row.get('script'), str):
            continue
        kind, groups = row['script'], row.get('evidence')
        if kind not in versions or not isinstance(groups, dict):
            continue
        for group, roles in REVIEW_CONFLICT_GROUPS.items():
            if len(errors) >= limit:
                break
            allowed = {shot_id for beat in versions[kind]['story_beats'] if beat['role'] in roles
                       for shot_id in beat['shot_ids']}
            required, covered = {'action'}, set()
            if any(actual_shots[(kind, shot_id)]['dialogue'] for shot_id in allowed):
                required.add('dialogue')
            refs = groups.get(group)
            for citation_index, citation in enumerate(refs if isinstance(refs, list) else []):
                if len(errors) >= limit:
                    break
                try:
                    _validate_review_citation(citation, payload)
                except (TypeError, ValueError, KeyError):
                    continue
                if ('source_id' in citation or citation['script'] != kind
                        or citation['shot_id'] not in allowed or citation['field'] not in ('action', 'dialogue')):
                    errors.append({'path': f'$.conflict_audit[{index}].evidence.{group}[{citation_index}]',
                        'reason': '引用身份不属于当前版本、争议阶段或动作对白字段；不代选引文',
                        **_review_conflict_location_detail(kind, group, allowed, citation, citation_index)})
                    continue
                covered.add(citation['field'])
            if not required <= covered and len(errors) < limit:
                errors.append({'path': f'$.conflict_audit[{index}].evidence.{group}',
                    'reason': '缺少当前阶段真实动作或对白引用；只列缺项，不代选或填入引文',
                    **_review_conflict_coverage_detail(kind, group, allowed, required, covered)})
    return errors


def _review_format_feedback(exc, response, *, evidence_diagnostics=None):
    detail = str(exc)
    if isinstance(exc, json.JSONDecodeError):
        context = response[max(0, exc.pos - 100):exc.pos + 100]
        detail += (f'；解析器位置 line={exc.lineno}, column={exc.colno}, char={exc.pos}；'
                   '附近原文以JSON字符串转义展示=' + json.dumps(context, ensure_ascii=False))
    feedback = (f'这是审稿输出格式错误（{detail}），不是剧本错误。'
            '请保持当前请求的candidate_sha256/evidence_sha256，完整返回checks、issues、summary、'
            'shot_audit、result_audit、character_audit、conflict_audit，补齐逐镜跨字段、角色和争议阶段原文证据。'
            '重点检查说明字符串内部未转义的ASCII双引号：说明用中文引号“”；'
            'quote必须保留原文字词，原文ASCII双引号用JSON反斜杠转义。'
            '字段不能重复，不能补括号后裁去判断；保留所有实质失败判断，只修报告格式；禁止改稿或返回changes。')
    if evidence_diagnostics:
        feedback += ('\n同一原报告的只读引文诊断（最多16处，非自动修复；'
                     '未列出不代表已通过；不能跨段拼接或省略原字）：'
                     + json.dumps(evidence_diagnostics, ensure_ascii=False))
    return feedback


class ScriptReviewRetryState:
    """One bounded report/quote-patch chain, shared by live calls and saved replay."""

    def __init__(self, payload, prompt):
        self.payload = payload
        self.full_messages = [{'role': 'system', 'content': prompt},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
        self.messages = copy.deepcopy(self.full_messages)
        self.mode, self.parent, self.parent_attempt, self.targets = 'full_report', None, None, []
        self.report = None
        self.error = None
        self.mode_attempts = {'full_report': 0, 'evidence_patch': 0}

    def assert_can_call(self, attempt):
        if (type(attempt) is not int or attempt != sum(self.mode_attempts.values()) + 1
                or attempt > SCRIPT_REVIEW_MAX_TOTAL_ATTEMPTS or self.report is not None):
            raise ValueError('审稿调用轮次无效或已完成；总调用最多5次')
        limits = {'full_report': SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS,
                  'evidence_patch': SCRIPT_REVIEW_MAX_EVIDENCE_PATCH_ATTEMPTS}
        if self.mode not in limits or self.mode_attempts[self.mode] >= limits[self.mode]:
            raise ValueError(f'审稿{self.mode}调用余额已耗尽；完整报告最多3次，引文补丁最多2次')

    def consume(self, response, attempt):
        self.assert_can_call(attempt)
        self.mode_attempts[self.mode] += 1
        from .review_evidence_patch import (FullReviewRequired, apply_evidence_patch,
            build_evidence_patch_messages, canonical_sha)
        mode, parent, parent_attempt, targets = self.mode, self.parent, self.parent_attempt, self.targets
        record = {'attempt': attempt, 'mode': mode, 'parent_attempt': parent_attempt,
            'parent_report_sha256': canonical_sha(parent) if parent is not None else None,
            'allowed_paths': [target['path'] for target in targets],
            'patch_prompt_sha256': hashlib.sha256(self.messages[0]['content'].encode('utf-8')).hexdigest()
                if mode == 'evidence_patch' else None,
            'effective_report_sha256': None, 'valid': False, 'full_review_required': None}
        effective, force_full = None, None
        try:
            if not response:
                raise ValueError('审稿模型没有返回内容')
            model_value = _parse_script_review_json(response)
            if mode == 'evidence_patch':
                effective = apply_evidence_patch(parent, model_value, targets)
            else:
                effective = model_value
            record['effective_report_sha256'] = canonical_sha(effective)
            self.report = validate_script_review_report(effective, self.payload)
            record['valid'] = True
            self.error = None
        except FullReviewRequired as exc:
            self.error, force_full = exc, str(exc)
            record['full_review_required'] = force_full
        except (TypeError, ValueError) as exc:
            self.error = exc
        if record['valid']:
            return record, effective
        if mode == 'full_report':
            diagnostics = _review_evidence_diagnostics(effective, self.payload) if effective is not None else None
            self.full_messages.extend([{'role': 'assistant', 'content': response},
                {'role': 'user', 'content': _review_format_feedback(self.error, response,
                    evidence_diagnostics=diagnostics)}])
        if force_full:
            self.full_messages.append({'role': 'user', 'content':
                '引文修复模型认为真实引文可能改变原审核结论，不能仅修引文维持既有判断。'
                '请对同一原稿与证据完整重新审核；不得改稿或忽略实质失败。原因：' + force_full
                + '\n需重新核对的父报告（仅作为历史记录，不代表通过）：'
                + json.dumps(parent, ensure_ascii=False)})
            self.mode, self.parent, self.parent_attempt, self.targets = 'full_report', None, None, []
            self.messages = copy.deepcopy(self.full_messages)
        else:
            planned = plan_review_evidence_patch(effective, self.payload) if effective is not None else None
            if planned:
                self.mode, self.parent, self.parent_attempt, self.targets = 'evidence_patch', effective, attempt, planned
                self.messages = build_evidence_patch_messages(effective, self.payload, planned)
            elif mode == 'evidence_patch' and effective is None:
                # Bad patch JSON/mapping does not erase its true parent or open
                # permission to rewrite a decision. Retry the same leaf scope.
                self.messages = build_evidence_patch_messages(parent, self.payload, targets)
                self.messages.extend([{'role': 'assistant', 'content': response},
                    {'role': 'user', 'content': '补丁格式错误：' + str(self.error)
                     + '。仍只返回同一allowed_paths的完整字符串映射；若真实引文动摇判断，返回full_review_required。'}])
            else:
                if mode == 'evidence_patch':
                    self.full_messages.append({'role': 'user', 'content':
                        '局部引文补丁后完整门禁仍发现结构问题，须完整复审；不得修改剧本。'
                        + _review_format_feedback(self.error, response)})
                self.mode, self.parent, self.parent_attempt, self.targets = 'full_report', None, None, []
                self.messages = copy.deepcopy(self.full_messages)
        return record, effective


def review_pair(client, scripts, evidence, *, trace_path=None):
    prompt = PROMPT_PATH.with_name('script_pair_review.md').read_text(encoding='utf-8')
    evidence = copy.deepcopy(evidence)
    evidence['editor_feedback'] = '\n'.join(line for line in evidence.get('editor_feedback', '').splitlines()
                                            if not re.search(r'输出.*(?:JSON|changes)|扁平\s*changes|只输出|数组格式必须', line))
    review_evidence = copy.deepcopy(evidence)
    references = [ref for script in scripts for ref in script.generation['reference_usage']]
    review_sources = evidence.get('source_evidence', [])
    if evidence.get('script_reference_selection'):
        selected = _reference_source_ids(evidence['script_reference_selection']['requested_source_ids'], review_sources)
        actual_ids = {ref['source_id'] for ref in references}
        if not actual_ids or not actual_ids.issubset(selected):
            raise ValueError('审稿的实际引用必须来自本次指定的详细来源，不能使用概览代替原文')
        review_sources = [source for source in review_sources if source['source_id'] in actual_ids]
        review_evidence['review_source_scope'] = {
            'strategy': 'actual_script_references_from_complete_original_sources',
            'detailed_source_ids': [source['source_id'] for source in review_sources],
            'notice': '以下详细来源从完整原始证据重新投影，包含全部候选主张、实际剧本引文和相邻转写；须逐条判断借鉴是否符合原文，不以概览或历史审核代替判断。',
        }
    review_evidence['source_evidence'] = project_source_evidence(review_sources, reference_usage=references)
    payload = {'evidence': review_evidence, 'scripts': build_script_review_rows(scripts),
               'review_contract_schema': CURRENT_SCRIPT_REVIEW_SCHEMA}
    shared = next((s.generation.get('continuous_production') for s in scripts
                   if s.format_kind == 'short'), None)
    if shared:
        payload['continuous_production'] = copy.deepcopy(shared)
    payload['validated_structure'] = _review_structural_facts(payload['scripts'])
    payload.update(script_review_binding(payload))
    from .review_evidence_patch import TRACE_SCHEMA, trace_bytes
    retry = ScriptReviewRetryState(payload, prompt)
    chain = {'schema': TRACE_SCHEMA, **script_review_binding(payload),
             'prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(), 'attempts': []}
    for review_attempt in range(SCRIPT_REVIEW_MAX_TOTAL_ATTEMPTS):
        try:
            retry.assert_can_call(review_attempt + 1)
        except ValueError as exc:
            raise RuntimeError(f'审稿结果格式无效，未完成审稿，未修改剧本：{exc}；{retry.error}') from exc
        messages = retry.messages
        request_raw = trace_bytes(messages)
        if trace_path:
            trace_path.with_name(f'{trace_path.stem}_request_{review_attempt+1}.json').write_bytes(request_raw)
        response = client.chat_completion_tracked(messages,
            caller='pre_video_script_review', temperature=0.1, json_mode=True, use_cache=False)
        response_raw = (response or '').encode('utf-8')
        if trace_path:
            trace_path.with_name(f'{trace_path.stem}_response_{review_attempt+1}.txt').write_bytes(response_raw)
        if not response:
            raise RuntimeError('审稿模型请求失败或未返回可用内容；停止重写，保留草稿，请检查模型连接或超时日志')
        entry, effective = retry.consume(response, review_attempt + 1)
        entry.update(request_sha256=hashlib.sha256(request_raw).hexdigest(),
                     response_sha256=hashlib.sha256(response_raw).hexdigest(), merged_report_sha256=None)
        if entry['mode'] == 'evidence_patch' and effective is not None:
            merged_raw = trace_bytes(effective)
            entry['merged_report_sha256'] = hashlib.sha256(merged_raw).hexdigest()
            if trace_path:
                trace_path.with_name(f'{trace_path.stem}_merged_{review_attempt+1}.json').write_bytes(merged_raw)
        chain['attempts'].append(entry)
        chain_raw = trace_bytes(chain)
        if trace_path:
            trace_path.with_name(f'{trace_path.stem}_attempt_chain.json').write_bytes(chain_raw)
        if entry['valid']:
            report = retry.report
            break
        if review_attempt == SCRIPT_REVIEW_MAX_TOTAL_ATTEMPTS - 1:
            raise RuntimeError(f'审稿结果格式无效，未完成审稿，未修改剧本：{retry.error}') from retry.error
    report['format_attempts'] = review_attempt + 1
    report['format_trace_sha256'] = hashlib.sha256(chain_raw).hexdigest()
    report['prompt_sha256'] = hashlib.sha256(prompt.encode()).hexdigest()
    report['legal_review_status'] = 'pending_human_review'
    if evidence.get('script_reference_selection'):
        report['source_review_scope'] = {
            **review_evidence['review_source_scope'],
            'full_source_evidence_sha256': evidence['script_reference_selection']['full_source_evidence_sha256'],
            'source_evidence_projection': [
                {'source_id': row['source_id'], **row['evidence_projection']}
                for row in review_evidence['source_evidence']],
        }
    return report


def _merge_model_revision(candidate, response):
    """Apply only model-authored field revisions; retain untouched storyboard data verbatim."""
    patch = json.loads(response)
    if isinstance(patch, dict) and 'source_review_required' in patch:
        # Preserve the stop protocol for the normal source-validation stage; never merge it into a script.
        return patch
    if isinstance(patch, dict) and set(patch) == {'changes'}:
        changes = patch['changes']
        if not isinstance(changes, list) or not changes:
            raise ValueError('changes 必须是非空数组')
        patch, seen = {}, set()
        for change in changes:
            if (isinstance(change, dict) and set(change) == {'script', 'field', 'value'}
                    and change['field'] in {'title', 'premise', 'dramatic_question', 'resolution',
                                            'closing_line', 'legal_review_note', 'characters', 'story_beats', 'core_message',
                                            'expression_plan', 'reference_usage'}):
                change = {**change, 'shot_id': ''}
            if not isinstance(change, dict) or set(change) != {'script', 'shot_id', 'field', 'value'}:
                raise ValueError('每项修订必须包含 script、shot_id、field、value')
            kind, shot_id, field = change['script'], change['shot_id'], change['field']
            if any(not isinstance(v, str) for v in (kind, shot_id, field)):
                raise ValueError('修订位置必须是字符串')
            location = (kind, shot_id, field)
            if location in seen:
                raise ValueError('不能重复修订同一字段')
            seen.add(location)
            if kind in ('both', 'short', 'long') and field == 'core_message' and not shot_id:
                if 'core_message' in patch and patch['core_message'] != change['value']:
                    raise ValueError('两个版本的共同核心修订互相冲突')
                patch['core_message'] = change['value']
            elif kind in ('short', 'long'):
                version = patch.setdefault(kind, {})
                if shot_id:
                    if field == 'shot_id':
                        raise ValueError('不能改名镜头')
                    rows = version.setdefault('shots', [])
                    row = next((s for s in rows if s['shot_id'] == shot_id), None)
                    if row is None:
                        row = {'shot_id': shot_id}
                        rows.append(row)
                    row[field] = change['value']
                elif field != 'shots':
                    version[field] = change['value']
                else:
                    raise ValueError('镜头修订必须指定 shot_id')
            else:
                raise ValueError('修订版本无效')
    if not isinstance(patch, dict) or not patch or set(patch) - {'core_message', 'short', 'long'}:
        raise ValueError('定点修订只能包含 core_message、short、long 中需要修改的键')
    merged = copy.deepcopy(candidate)
    for key, value in patch.items():
        if key == 'core_message':
            merged[key] = value
            continue
        if not isinstance(value, dict) or not isinstance(merged.get(key), dict):
            raise ValueError(f'{key} 修订必须是对象')
        for field, update in value.items():
            if field not in {'title', 'premise', 'dramatic_question', 'resolution', 'closing_line',
                              'legal_review_note', 'characters', 'story_beats', 'shots', 'expression_plan', 'reference_usage'}:
                raise ValueError(f'{key} 修订了不存在的字段 {field}')
            if field != 'shots':
                merged[key][field] = update
                continue
            if not isinstance(update, list) or any(not isinstance(s, dict) for s in update):
                raise ValueError('shots 修订须为带 shot_id 的对象数组')
            original = merged[key]['shots']
            by_id = {s['shot_id']: s for s in original}
            used = set()
            for shot_patch in update:
                shot_id = shot_patch.get('shot_id')
                if shot_id not in by_id or shot_id in used:
                    raise ValueError('定点修订只能更新已有镜头，不得增加、重复或改名镜头')
                used.add(shot_id)
                # Missing required fields may be added, but arbitrary new fields are forbidden.
                allowed = {'shot_id', 'start_seconds', 'end_seconds', 'scene', 'participants',
                           'blocking', 'action', 'emotion_and_performance', 'dialogue_mode',
                           'dialogue_speaker', 'dialogue', 'audio', 'narrative_purpose', 'continuity',
                           'camera', *VISUAL_FIELDS}
                if set(shot_patch) - allowed:
                    raise ValueError(f'{shot_id} 修订包含未定义字段')
                by_id[shot_id].update(shot_patch)
    return merged


def _can_patch(data):
    if not isinstance(data, dict) or set(data) != {'core_message', 'short', 'long'}:
        return False
    for kind in ('short', 'long'):
        if not isinstance(data[kind], dict):
            return False
        shots = data[kind].get('shots')
        if not isinstance(shots, list) or not shots or any(not isinstance(s, dict) for s in shots):
            return False
        if [s.get('shot_id') for s in shots] != [f'S{i:02d}' for i in range(1, len(shots)+1)]:
            return False
    return True


def _fit_spoken_timing(data, *, short_seconds, long_seconds):
    """Borrow spare time within an already valid timeline without editing model-authored text."""
    result, adjustments = copy.deepcopy(data), []
    if not _can_patch(data):
        return result, adjustments
    for kind, target in (('short', short_seconds), ('long', long_seconds)):
        shots = result[kind]['shots']
        if any(not isinstance(s.get('dialogue'), str) for s in shots):
            continue
        durations, cursor, valid = [], 0.0, True
        for s in shots:
            start, end = s.get('start_seconds'), s.get('end_seconds')
            if not all(type(v) in (int, float) and math.isfinite(v) for v in (start, end)):
                valid = False
                break
            if abs(start - cursor) > .01 or not 3 <= end-start <= 20:
                valid = False
                break
            durations.append(end-start)
            cursor = end
        minimums = [max(3, math.ceil(len(s['dialogue']) / 5)) for s in shots]
        if (not valid or abs(cursor-target) > .01 or max(minimums) > 20
                or sum(minimums) > target or sum(len(s['dialogue']) for s in shots) > target*4):
            continue
        fitted = [max(d, m) for d, m in zip(durations, minimums)]
        extra = sum(fitted) - target
        if extra <= .01:
            continue
        for i in sorted(range(len(shots)), key=lambda j: fitted[j]-minimums[j], reverse=True):
            amount = min(extra, fitted[i]-minimums[i])
            fitted[i] -= amount
            extra -= amount
        cursor = 0.0
        for s, duration in zip(shots, fitted):
            before = [s['start_seconds'], s['end_seconds']]
            s['start_seconds'], s['end_seconds'] = cursor, cursor+duration
            cursor += duration
            if before != [s['start_seconds'], s['end_seconds']]:
                adjustments.append({'script': kind, 'shot_id': s['shot_id'], 'before': before,
                                    'after': [s['start_seconds'], s['end_seconds']]})
    return result, adjustments


def _normalize_single_participants(data):
    result, changes = copy.deepcopy(data), []
    if not _can_patch(data):
        return result, changes
    for kind in ('short', 'long'):
        characters = result[kind].get('characters')
        if not isinstance(characters, list):
            continue
        names = {c.get('name') for c in characters if isinstance(c, dict) and isinstance(c.get('name'), str)}
        for shot in result[kind]['shots']:
            value = shot.get('participants')
            if isinstance(value, str) and value in names:
                shot['participants'] = [value]
                changes.append({'script':kind, 'shot_id':shot['shot_id'], 'field':'participants',
                                'before':value, 'after':[value]})
    return result, changes


def _revision_messages(messages, candidate, error):
    instruction = (
        '以下是定点改稿任务。两个剧本已经写出，请解决列出的全部问题，同时保持其他内容与字段原文不变。'
        '只返回一个简单 JSON 对象：{"changes":[{"script":"short","shot_id":"S03","field":"dialogue","value":"修改后的台词"}]}。'
        '每项只修改一个字段。script 为 short 或 long；修改标题、resolution、closing_line 等版本字段时 shot_id 为空字符串；'
        '修改共同核心时 script 为 both、shot_id 为空、field 为 core_message。不要嵌套 short/long/shots，也不要复制完整双剧本。'
        '禁止增加、删除或改名镜头。可以调整相邻镜头时间但须保持连续和总时长。'
        '对白修改时同时检查说话人、动作、口型、台词预算及结局；末镜 dialogue 与 closing_line 同步修改。'
        '视觉问题应实际修订 composition、lighting、机位、首尾画面等对应字段；不能只改审稿备注。'
        '表达与冲突问题要同步改对应镜头及 expression_plan；来源改动须同步 reference_usage，不能只写计划而不改画面。'
        'current_pair就是本次输入中完整、可修改的当前稿件对象，按其实际字段修订即可；不需要读取或猜测磁盘draft_1.json、draft_3.json等文件，不能把想象中的文件缺失当作停机原因。'
        'issues_to_fix指出的景别枚举、摄影字段、镜号、时长、时间线、对白和其他作者制作问题属于已经授权的定点修订，应返回changes解决；不需要再次确认能否修改，也不能挂上某个source_id把这些问题改称来源失败。'
        'source_review_required只用于实际来源的关键语义仍无法确定：reason必须说明对应source_id/evidence_ids中的原句或帧观察究竟哪里冲突、否定或条件不清，以及为何已提供的相邻证据仍无法澄清；不能仅重复当前稿件制作错误或笼统说无法修订。'
        '若实际源证据存在无法确定的语义冲突，可仅返回 source_review_required 停止协议，具体结构遵守下方来源复核约束；不得继续改写。'
        '只允许修订剧情数据，不返回解释、补丁代码、命令或 Markdown。'
    )
    # The authoring system's full-pair output schema conflicts with partial edits.
    # Keep creative constraints, but give this stage its own system/output contract.
    boundaries = messages[0]['content'].split('严格返回 JSON 对象')[0].split('\n', 1)[-1]
    evidence = json.loads(messages[1]['content'])
    current_feedback = ''
    if '\n代理对当前稿的新意见：\n' in error:
        error, current_feedback = error.split('\n代理对当前稿的新意见：\n', 1)
    reference = evidence.get('editor_feedback', '')
    verified = re.search(r'已核对资料[\s\S]*?(?=具体要求：)', reference)
    if current_feedback and verified:
        reference = verified.group(0)
    return [{'role': 'system', 'content': '你是中文视频剧本的定点修订编辑。' + instruction
             + '\n本轮以 current_editor_feedback 和 issues_to_fix 为具体修改任务，必须逐项落实。reference_facts 只供事实核对，不是旧稿改写任务。'
             + '\n以下是合并后完整作品应满足的创作约束，不能因此返回完整剧本：\n' + boundaries},
            {'role': 'user', 'content': json.dumps({
                'issues_to_fix': error, 'current_editor_feedback': current_feedback,
                'reference_facts': reference,
                'account_positioning': evidence.get('account_positioning', {}),
                'source_evidence': evidence.get('source_evidence', []),
                'expression_patterns': evidence.get('expression_patterns', {}),
                'expression_direction': evidence.get('expression_direction', {}),
                'reference_policy': evidence.get('reference_policy', ''),
                'observed_traits': evidence.get('observed_traits', []),
                'focus': evidence.get('focus', ''),
                'production_constraints': evidence.get('production_constraints', {}),
                **{key: evidence[key] for key in ('source_overview', 'script_reference_selection') if key in evidence},
                'current_pair': candidate}, ensure_ascii=False)}]


def _check_source_abstention(parsed, evidence):
    if not isinstance(parsed, dict) or 'source_review_required' not in parsed:
        return
    issues = parsed.get('source_review_required')
    if set(parsed) != {'source_review_required'} or not isinstance(issues, list) or not issues:
        raise ValueError('来源复核请求必须仅含非空 source_review_required 数组')
    sources = {s['source_id']: s for s in evidence['source_evidence']}
    for issue in issues:
        if not isinstance(issue, dict) or set(issue) != {'source_id', 'evidence_ids', 'reason'}:
            raise ValueError('来源复核请求须包含 source_id、evidence_ids、reason')
        source = sources.get(_text(issue, 'source_id'))
        if not source:
            raise ValueError('来源复核请求引用了未提供的 source_id')
        actual_ids = {item['id'] for item in source.get('expression_analysis', {}).get('evidence', [])}
        ids = issue.get('evidence_ids')
        if not isinstance(ids, list) or not ids or any(not isinstance(eid, str) or eid not in actual_ids for eid in ids):
            raise ValueError('来源复核请求必须引用本来源实际 evidence_ids')
        _text(issue, 'reason')
    raise SourceSemanticReviewError('来源含义尚待核实，已停止起草和自动改稿：' + json.dumps(issues, ensure_ascii=False))


def generate_script_pair(client, profile, cohort, overlap, *, created_at, short_seconds, long_seconds, trace_dir=None, editor_feedback='', initial_draft_path='', revision_feedback='', initial_revision_path='', baseline_draft_path='', continuous_short=False, review_client=None, review_only=False, script_reference_source_ids=(), staged_screenplay_bundle_path=''):
    staged = bool(staged_screenplay_bundle_path)
    if staged and any((initial_draft_path, baseline_draft_path, initial_revision_path, revision_feedback)):
        raise ValueError('分阶段剧本包不能混用 baseline/resume/revision；失败须返回原阶段修订')
    continuous_short = continuous_short or staged
    if getattr(client, 'provider_name', '') == 'mock' and not staged:
        raise ValueError('请先配置真实编剧模型，不能使用模拟输出生成双剧本')
    reviewer = review_client or client
    if review_only and not staged and (not initial_draft_path or revision_feedback or initial_revision_path or baseline_draft_path):
        raise ValueError('只读复核须使用相同输入的保存草稿，不能混用改稿参数')
    if getattr(reviewer, 'provider_name', '') == 'mock':
        raise ValueError('不能使用模拟模型审稿')
    messages = build_messages(profile, cohort, overlap, short_seconds=short_seconds, long_seconds=long_seconds,
                              editor_feedback=editor_feedback, continuous_short=continuous_short,
                              script_reference_source_ids=script_reference_source_ids)
    evidence = json.loads(messages[1]['content'])
    # Validation and editorial reference lookup use the full verified cohort,
    # never the smaller network payload as a substitute for original records.
    evidence['source_evidence'] = _full_source_evidence(cohort)
    if evidence.get('script_reference_selection'):
        current_hash = hashlib.sha256(_source_json(evidence['source_evidence']).encode('utf-8')).hexdigest()
        if current_hash != evidence['script_reference_selection']['full_source_evidence_sha256']:
            raise ValueError('来源证据或独立审核在构造编剧请求期间发生变化，请重新构造输入；未调用模型')
    if baseline_draft_path and (initial_draft_path or initial_revision_path or not revision_feedback.strip()):
        raise ValueError('跨输入定点修订必须提供具体意见，且不能混用相同输入续审参数')
    if revision_feedback and not (initial_draft_path or baseline_draft_path):
        raise ValueError('新增读稿意见必须对应已有工作流草稿')
    if initial_revision_path and not initial_draft_path:
        raise ValueError('续用模型修订必须指定其对应的保存草稿')
    initial_raw = None
    staged_pair = staged_provenance = None
    if staged:
        from .screenplay_bundle import load_screenplay_bundle
        staged_pair, staged_provenance = load_screenplay_bundle(
            staged_screenplay_bundle_path, evidence=evidence, short_seconds=short_seconds,
            long_seconds=long_seconds, reference_source_ids=script_reference_source_ids)
        initial_raw = json.dumps(staged_pair, ensure_ascii=False)
    baseline_provenance = None
    if baseline_draft_path:
        source = Path(baseline_draft_path).resolve()
        previous_request_path = source.with_name('request.json')
        previous_request = json.loads(previous_request_path.read_text(encoding='utf-8'))
        initial_raw = source.read_text(encoding='utf-8')
        if not _can_patch(json.loads(initial_raw)):
            raise ValueError('跨输入修订需要已有的完整双剧本，不允许退回重新编写')
        if not isinstance(previous_request, list) or len(previous_request) < 2:
            raise ValueError('基线缺少原始工作流请求记录')
        baseline_provenance = {'draft_path': str(source),
            'draft_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'request_sha256': hashlib.sha256(previous_request_path.read_bytes()).hexdigest(),
            'mode': 'new_evidence_targeted_revision_not_same_input_resume'}
    if initial_draft_path:
        source = Path(initial_draft_path).resolve()
        previous_request = json.loads(source.with_name('request.json').read_text(encoding='utf-8'))
        if previous_request != messages:
            raise ValueError('当前输入与保存草稿的输入不一致，请按新输入重新生成')
        initial_raw = source.read_text(encoding='utf-8')
    initial_revision = None
    if initial_revision_path:
        patch_path = Path(initial_revision_path).resolve()
        number = re.fullmatch(r'revision_(\d+)\.json', patch_path.name)
        if patch_path.parent != source.parent or not number:
            raise ValueError('只能续用同一工作流记录中的模型修订')
        call = json.loads(patch_path.with_name(f'call_{number[1]}.json').read_text(encoding='utf-8'))
        if json.loads(call[-1]['content']).get('current_pair') != json.loads(initial_raw):
            raise ValueError('模型修订与指定草稿不匹配')
        initial_revision = patch_path.read_text(encoding='utf-8')
        initial_raw = json.dumps(_merge_model_revision(json.loads(initial_raw), initial_revision), ensure_ascii=False)
    if revision_feedback:
        evidence['editor_feedback'] += '\n\n代理对当前稿的新意见：\n' + revision_feedback
    reviews = []
    candidate = None
    repair_error = ''
    trace = Path(trace_dir) if trace_dir else None
    if trace:
        trace.mkdir(parents=True, exist_ok=False)
        (trace / 'request.json').write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding='utf-8')
        (trace / 'source_evidence.full.json').write_text(
            json.dumps(evidence['source_evidence'], ensure_ascii=False, indent=2), encoding='utf-8')
        if revision_feedback:
            (trace / 'revision_feedback.md').write_text(revision_feedback, encoding='utf-8')
        if baseline_provenance:
            (trace / 'baseline.json').write_text(json.dumps(baseline_provenance, ensure_ascii=False, indent=2), encoding='utf-8')
        if staged_provenance:
            (trace / 'bundle.provenance.json').write_text(
                json.dumps(staged_provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    generation = {'method': 'llm_script_pair', 'prompt_version': '2026-09-10-cross-field-v9',
                  'full_source_evidence_sha256': hashlib.sha256(
                      _source_json(evidence['source_evidence']).encode('utf-8')).hexdigest(),
                  'expression_patterns': evidence.get('expression_patterns', {}),
                  'source_evidence_projection': [
                      {'source_id': row['source_id'], **row['evidence_projection']}
                      for row in json.loads(messages[1]['content'])['source_evidence']],
                  'started_at': created_at,
                  'reused_draft_path': str(initial_draft_path),
                  'reused_revision_path': str(initial_revision_path),
                  'baseline_provenance': baseline_provenance,
                  'continuous_short': continuous_short,
                  'review_only': review_only,
                  'generation_api_calls': 0,
                  'editor_feedback_sha256': hashlib.sha256(editor_feedback.encode('utf-8')).hexdigest(),
                  'revision_feedback_sha256': hashlib.sha256(revision_feedback.encode('utf-8')).hexdigest(),
                  'prompt_sha256': hashlib.sha256(messages[0]['content'].encode()).hexdigest(),
                  'provider': client.provider_name, 'model': client.model_name,
                  'review_provider': reviewer.provider_name, 'review_model': reviewer.model_name,
                  'request_timeout_seconds': getattr(client, 'timeout_seconds', None),
                  'max_output_tokens': getattr(client, 'max_tokens', None),
                  'revision_mode': 'model_field_patch_then_full_validation',
                  'request_extra_body': getattr(client, 'extra_body', None),
                  'validation': 'structural_checks_and_editorial_review; pending_user_review'}
    if staged_provenance:
        generation.update(method='staged_screenplay_bundle',
                          staged_screenplay_bundle=copy.deepcopy(staged_provenance),
                          review_only=True, revision_mode='frozen_stages_final_review_only',
                          configured_author_client_not_called={'provider': client.provider_name,
                                                               'model': client.model_name},
                          provider='staged_artifacts', model=None, request_extra_body=None,
                          request_timeout_seconds=None, max_output_tokens=None)
    if evidence.get('script_reference_selection'):
        generation['script_reference_selection'] = copy.deepcopy(evidence['script_reference_selection'])
        generation['author_request_summary'] = {
            'created_at': created_at,
            'source_overview_count': len(evidence['source_overview']),
            'detailed_source_count': len(json.loads(messages[1]['content'])['source_evidence']),
            'user_payload_characters': len(messages[1]['content']),
            'user_payload_sha256': hashlib.sha256(messages[1]['content'].encode('utf-8')).hexdigest(),
            'full_source_evidence_artifact': 'source_evidence.full.json' if trace else None,
            'notice': '这是实际请求构造时间与输入范围，不是模型完成时间；完整来源与作者投影分开保存。',
        }
        if staged:
            generation['author_request_summary'].update(
                model_call_performed=False,
                purpose='current_source_gate_and_final_review_context_not_author_generation')
        if trace:
            (trace / 'reference_selection.json').write_text(json.dumps({
                'selection': generation['script_reference_selection'],
                'author_request': generation['author_request_summary'],
                'source_evidence_projection': generation['source_evidence_projection'],
            }, ensure_ascii=False, indent=2), encoding='utf-8')
    if trace:
        generation['trace_dir'] = str(trace)
    for attempt in range(1 if review_only or staged else 3):
        patch_response = None
        if attempt == 0 and initial_raw is not None:
            raw = initial_raw
            patch_response = initial_revision
        else:
            call_messages = _revision_messages(messages, candidate, repair_error) if candidate is not None else messages
            if trace:
                (trace / f'call_{attempt+1}.json').write_text(json.dumps(call_messages, ensure_ascii=False, indent=2), encoding='utf-8')
            raw = client.chat_completion_tracked(call_messages, caller='pre_video_script_pair',
                                                 temperature=0.2 if candidate is not None else 0.6, json_mode=True, use_cache=False)
            generation['generation_api_calls'] += 1
            if candidate is not None and raw:
                patch_response = raw
                try:
                    revised = _merge_model_revision(candidate, raw)
                except (ValueError, KeyError, TypeError) as exc:
                    repair_error = f'上次定点修订无效：{exc}；仍须解决：{repair_error}'
                    reviews.append({'attempt': attempt + 1, 'revision_error': str(exc)})
                    if trace:
                        (trace / f'revision_{attempt+1}.json').write_text(raw, encoding='utf-8')
                        (trace / 'attempts.json').write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding='utf-8')
                    if attempt == 2:
                        raise ValueError(f'双剧本定点修订未通过，未交付：{exc}') from exc
                    continue
                raw = json.dumps(revised, ensure_ascii=False)
        if trace:
            if patch_response:
                (trace / f'revision_{attempt+1}.json').write_text(patch_response, encoding='utf-8')
            (trace / f'draft_{attempt+1}.json').write_text(raw or 'null', encoding='utf-8')
            if continuous_short and not staged:
                (trace / f'model_draft_{attempt+1}.json').write_text(raw or 'null', encoding='utf-8', newline='')
            metadata = ({'origin': 'staged_screenplay_bundle', 'generation_api_calls': 0} if staged else
                        getattr(getattr(client, 'provider', None), 'last_response_metadata', {}))
            (trace / f'response_{attempt+1}.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        if not raw:
            failure = {'attempt': attempt + 1, 'request_error': '模型请求失败或未返回可用内容；不是剧本结构错误'}
            reviews.append(failure)
            if trace:
                (trace / 'attempts.json').write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding='utf-8')
            raise RuntimeError('编剧模型请求失败或未返回可用内容；已停止重写，请检查模型连接或超时日志')
        try:
            parsed = json.loads(raw)
            _check_source_abstention(parsed, evidence)
            parsed, shape_changes = (parsed, []) if staged else _normalize_single_participants(parsed)
            if shape_changes:
                generation.setdefault('shape_normalizations', []).append({'attempt':attempt+1, 'changes':shape_changes})
                if trace:
                    (trace / f'model_shape_{attempt+1}.json').write_text(raw, encoding='utf-8')
                raw = json.dumps(parsed, ensure_ascii=False)
                if trace:
                    (trace / f'draft_{attempt+1}.json').write_text(raw, encoding='utf-8')
            parsed, timing = ((parsed, []) if staged else
                              _fit_spoken_timing(parsed, short_seconds=short_seconds, long_seconds=long_seconds))
            if timing:
                generation.setdefault('timing_adjustments', []).append({'attempt': attempt+1, 'changes': timing})
                if trace:
                    (trace / f'model_timeline_{attempt+1}.json').write_text(raw, encoding='utf-8')
                raw = json.dumps(parsed, ensure_ascii=False)
                if trace:
                    (trace / f'draft_{attempt+1}.json').write_text(raw, encoding='utf-8')
            if _can_patch(parsed):
                candidate = parsed
            if continuous_short and not staged:
                before_shared = raw
                parsed, shared = bind_continuous_production(parsed)
                raw = json.dumps(parsed, ensure_ascii=False)
                normalization = {**shared, 'attempt': attempt+1,
                                 'input_sha256': hashlib.sha256(before_shared.encode('utf-8')).hexdigest(),
                                 'output_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest()}
                generation.setdefault('production_normalizations', []).append(normalization)
                generation['continuous_production'] = shared
                if trace:
                    (trace / f'model_before_shared_production_{attempt+1}.json').write_text(before_shared, encoding='utf-8', newline='')
                    (trace / f'shared_production_{attempt+1}.json').write_text(
                        json.dumps(normalization, ensure_ascii=False, indent=2), encoding='utf-8')
                    (trace / f'shared_production_draft_{attempt+1}.json').write_text(raw, encoding='utf-8', newline='')
                    (trace / f'draft_{attempt+1}.json').write_text(raw, encoding='utf-8')
                candidate = parsed
                parsed, bindings = bind_continuous_starts(parsed)
                if bindings:
                    generation.setdefault('continuity_bindings', []).append({'attempt':attempt+1, 'bindings':bindings})
                    if trace:
                        (trace / f'model_before_continuity_binding_{attempt+1}.json').write_text(raw, encoding='utf-8')
                    raw = json.dumps(parsed, ensure_ascii=False)
                    if trace:
                        (trace / f'draft_{attempt+1}.json').write_text(raw, encoding='utf-8')
                    candidate = parsed
                validate_continuous_short(parsed)
            if staged:
                if parsed != staged_pair:
                    raise ValueError('分阶段故事/摄影工件在最终复核前发生变化，禁止自动改写')
                validate_continuous_short(parsed)
            scripts = parse_pair(raw, profile=profile, created_at=created_at,
                                 short_seconds=short_seconds, long_seconds=long_seconds, generation=generation,
                                 source_evidence=evidence['source_evidence'])
            if attempt == 0 and initial_raw is not None and revision_feedback and not initial_revision:
                raise ValueError('当前稿被代理实际读稿退回，需要模型定点修订')
            report = review_pair(reviewer, scripts, evidence, trace_path=trace / f'review_{attempt+1}.json' if trace else None)
            reviews.append({'attempt': attempt + 1, 'report': report})
            if trace:
                (trace / f'review_{attempt+1}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            if not report['checks']['source_semantic_fidelity']:
                raise SourceSemanticReviewError('来源语义复核未通过，已停止编剧交付和自动改稿；须核对所列原始音画证据并修正来源分析：'
                                                + json.dumps(report, ensure_ascii=False))
            if not report['passed']:
                raise ValueError('编辑审稿未通过：' + json.dumps(report, ensure_ascii=False))
            generation['reviews'] = reviews
            generation['accepted_attempt'] = attempt + 1
            generation['completed_at'] = datetime.now(timezone.utc).isoformat()
            for script in scripts:
                script.generation.update(copy.deepcopy(generation))
                script.generation['reference_usage_validation']['status'] = 'identifiers_verified_editorially_reviewed'
            if trace:
                (trace / 'attempts.json').write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding='utf-8')
            return scripts
        except RuntimeError as exc:
            error_kind = 'source_review_error' if isinstance(exc, SourceSemanticReviewError) else 'request_error'
            reviews.append({'attempt': attempt + 1, error_kind: str(exc)})
            if trace:
                (trace / 'attempts.json').write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding='utf-8')
            raise
        except (ValueError, TypeError, KeyError) as exc:
            repair_error = str(exc)
            if revision_feedback:
                repair_error += '\n代理对当前稿的新意见：\n' + revision_feedback
            if not reviews or reviews[-1]['attempt'] != attempt + 1:
                reviews.append({'attempt': attempt + 1, 'structural_error': str(exc)})
            if trace:
                (trace / 'attempts.json').write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding='utf-8')
            if staged:
                raise ValueError(f'分阶段双稿最终复核未通过，须返回对应故事或摄影阶段修订；未触发编剧改写：{exc}') from exc
            if review_only:
                raise ValueError(f'只读复核未通过，未触发改稿：{exc}') from exc
            if attempt == 2:
                raise ValueError(f'双剧本校验或审稿未通过，未交付：{exc}') from exc
            if candidate is None:
                messages.extend([{'role': 'assistant', 'content': raw or '{}'},
                                 {'role': 'user', 'content': f'本轮未通过：{exc}。请完整修正两个剧本的 JSON。'}])
