"""One model-authored short-script patch; output is never an approved script pair."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.shared.config import settings
from src.shared.llm_client import LLMClient
from src.trend_intelligence.script_outline import build_outline_messages, text_sha
from src.trend_intelligence.script_pair import (
    PROMPT_PATH, _can_patch, _check_source_abstention, _merge_model_revision,
    _reference_source_ids, _revision_messages, _source_json, _source_overview,
)


def now_bjt():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def _source_input(workflow, full_path):
    """Restore complete sources only when the saved request binds their content."""
    result = copy.deepcopy(workflow)
    payload = json.loads(result[1]['content'])
    full_text = full_path.read_bytes().decode('utf-8') if full_path.exists() else None
    if full_text is not None:
        full = json.loads(full_text)
        if not isinstance(full, list):
            raise ValueError('完整来源审计必须为数组')
        by_id = {s['source_id']: s for s in full}
        if len(by_id) != len(full):
            raise ValueError('完整来源审计的来源ID重复')
        scope = payload.get('script_reference_selection')
        if scope:
            if scope['full_source_evidence_sha256'] != text_sha(_source_json(full)):
                raise ValueError('完整来源审计与原工作流的SHA不匹配')
        elif {s['source_id'] for s in payload['source_evidence']} != set(by_id):
            raise ValueError('完整来源审计与原工作流的来源集合不匹配')
        for source in payload['source_evidence']:
            original = by_id.get(source['source_id'])
            expected = source.get('evidence_projection', {}).get('full_source_sha256')
            if original is None or (text_sha(_source_json(original)) != expected if expected else source != original):
                raise ValueError('完整来源审计与原工作流的逐源证据绑定不匹配')
        payload['source_evidence'] = full
        result[1]['content'] = json.dumps(payload, ensure_ascii=False)
    return result, full_text


def _merge_short_patch(baseline, raw):
    patch = json.loads(raw)
    if not isinstance(patch, dict) or set(patch) != {'changes'} or not isinstance(patch['changes'], list) or not patch['changes']:
        raise ValueError('候选修订只接受非空changes数组，不接受重写整稿')
    for change in patch['changes']:
        if not isinstance(change, dict):
            raise ValueError('changes中的每项必须是字段修订对象')
        if change.get('script') != 'short' and not (
                change.get('script') == 'both' and change.get('field') == 'core_message'
                and change.get('shot_id', '') == ''):
            raise ValueError('本轮只能修改short或共同core_message；long禁止改动')
    merged = _merge_model_revision(baseline, raw)
    if not _can_patch(merged):
        raise ValueError('修订后必须保留原始双稿对象和既有镜号')
    if _source_json(merged['long']) != _source_json(baseline['long']):
        raise ValueError('长稿必须逐字段原文保持不变')
    if [s['shot_id'] for s in merged['short']['shots']] != [s['shot_id'] for s in baseline['short']['shots']]:
        raise ValueError('本轮不得增加、删除或改名短稿镜头')
    return merged


SHORT_FIELDS = {'title', 'premise', 'dramatic_question', 'resolution', 'closing_line', 'legal_review_note',
                'expression_plan', 'reference_usage', 'characters', 'story_beats', 'shots'}
SHOT_FIELDS = {'shot_id', 'start_seconds', 'end_seconds', 'scene', 'participants', 'composition', 'lighting',
               'shot_size', 'camera_angle', 'camera_movement', 'blocking', 'start_frame', 'action', 'end_frame',
               'emotion_and_performance', 'dialogue_mode', 'dialogue_speaker', 'dialogue', 'audio', 'transition',
               'narrative_purpose', 'continuity'}


def _replace_complete_short(baseline, raw):
    """Require complete current-schema fields, then replace rather than inherit short."""
    import math
    rewritten = json.loads(raw)

    def fields(row, expected, label, *, lists=(), numbers=(), objects=(), empty=()):
        if not isinstance(row, dict) or set(row) != expected:
            raise ValueError(f'{label}字段须完整且仅含当前schema字段：{sorted(expected)}')
        for key, value in row.items():
            if key in lists:
                valid = isinstance(value, list) and bool(value)
                if valid and key in ('shot_ids', 'evidence_ids', 'participants'):
                    valid = all(isinstance(item, str) and item.strip() for item in value) and len(set(value)) == len(value)
            elif key in numbers:
                valid = type(value) in (int, float) and math.isfinite(value)
            elif key in objects:
                valid = isinstance(value, dict)
            else:
                valid = isinstance(value, str) and (bool(value.strip()) or key in empty)
            if not valid:
                raise ValueError(f'{label}.{key}缺失、为空或类型错误')

    fields(rewritten, {'core_message', 'short'}, 'rewrite', objects=('short',))
    short = rewritten['short']
    fields(short, SHORT_FIELDS, 'short', lists=('reference_usage', 'characters', 'story_beats', 'shots'),
           objects=('expression_plan',))
    for row in short['characters']:
        fields(row, {'name', 'identity', 'appearance', 'wardrobe', 'performance_arc'}, 'characters')
    plan = short['expression_plan']
    fields(plan, {'presentation_mode', 'account_fit', 'source_pattern_rationale', 'protagonist', 'goal', 'obstacle',
                  'stakes', 'action_chain', 'turn', 'ending'}, 'expression_plan', lists=('action_chain',), objects=('turn', 'ending'))
    for row in plan['action_chain']:
        fields(row, {'shot_ids', 'visible_action', 'state_change'}, 'action_chain', lists=('shot_ids',))
    fields(plan['turn'], {'shot_ids', 'visible_trigger', 'result'}, 'turn', lists=('shot_ids',))
    fields(plan['ending'], {'shot_ids', 'visible_result', 'core_answer'}, 'ending', lists=('shot_ids',))
    for row in short['reference_usage']:
        fields(row, {'source_id', 'evidence_ids', 'borrowed_expression', 'adaptation', 'shot_ids'},
               'reference_usage', lists=('evidence_ids', 'shot_ids'))
    for row in short['story_beats']:
        fields(row, {'role', 'because', 'change', 'shot_ids'}, 'story_beats', lists=('shot_ids',))
    for row in short['shots']:
        fields(row, SHOT_FIELDS, 'shots', lists=('participants',), numbers=('start_seconds', 'end_seconds'),
               empty=('dialogue', 'dialogue_speaker'))
    if [row['shot_id'] for row in short['shots']] != [row['shot_id'] for row in baseline['short']['shots']]:
        raise ValueError('完整重写须保留基线全部短稿镜号及其顺序，不得增删镜头')
    # No merge/update of the previous short object: omitted legacy fields cannot leak in.
    return {'core_message': rewritten['core_message'], 'short': copy.deepcopy(short),
            'long': copy.deepcopy(baseline['long'])}


def _previous_candidate(path, *, root, original, baseline_text, baseline):
    candidate_path = Path(path).resolve()
    if candidate_path.name != 'candidate.json' or (root/'data').resolve() not in candidate_path.parents:
        raise ValueError('previous-candidate须为本项目data中本工具输出的candidate.json')
    candidate_text = candidate_path.read_bytes().decode('utf-8')
    run_path = candidate_path.with_name('run.json')
    run_text = run_path.read_bytes().decode('utf-8')
    run, candidate = json.loads(run_text), json.loads(candidate_text)
    if (run.get('schema') != 'script_candidate_revision_run/v1'
            or run.get('status') != 'candidate_pending_independent_review'
            or run.get('candidate_sha256') != text_sha(candidate_text)
            or run.get('workflow_request_sha256') != text_sha(original)
            or run.get('baseline_draft_sha256') != text_sha(baseline_text)):
        raise ValueError('上一候选状态、内容SHA、原工作流或原基线绑定不匹配')
    if (not _can_patch(candidate)
            or _source_json(candidate['long']) != _source_json(baseline['long'])
            or [s['shot_id'] for s in candidate['short']['shots']] != [s['shot_id'] for s in baseline['short']['shots']]):
        raise ValueError('上一候选必须保留原长稿及原短稿镜号范围')
    provenance = {'path': str(candidate_path), 'sha256': text_sha(candidate_text),
                  'run_path': str(run_path), 'run_sha256': text_sha(run_text),
                  'notice': '仅续接已绑定的待审核候选，不代表其内容通过。'}
    return candidate, candidate_text, run_text, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workflow-request', required=True)
    parser.add_argument('--baseline-draft', required=True)
    parser.add_argument('--editor-feedback-file', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--reference-source-id', action='append', default=[])
    parser.add_argument('--rewrite-short', action='store_true', help='完整重写short全部字段，仅保存待独立审核候选')
    parser.add_argument('--previous-candidate', default='', help='续接同一原始工作流与基线的本工具待审候选')
    parser.add_argument('--omit-rejected-short', action='store_true', help='仅完整重写时不向模型发送被退回的短稿原文')
    args = parser.parse_args()
    if args.omit_rejected_short and not args.rewrite_short:
        raise ValueError('--omit-rejected-short仅可与--rewrite-short同时使用')
    root = Path(__file__).resolve().parents[1]
    source, baseline_path = Path(args.workflow_request).resolve(), Path(args.baseline_draft).resolve()
    if (root / 'data/pre_video_scripts/_runs').resolve() not in source.parents or source.name != 'request.json':
        raise ValueError('只接受本项目_runs中已保存的原始工作流request.json')
    if baseline_path.parent != source.parent or baseline_path == source or baseline_path.suffix != '.json':
        raise ValueError('基线须为同一工作流目录中的双剧本JSON草稿')
    original = source.read_bytes().decode('utf-8')
    baseline_text = baseline_path.read_bytes().decode('utf-8')
    baseline = json.loads(baseline_text)
    if not _can_patch(baseline):
        raise ValueError('基线需要已有完整双稿对象；本工具不补造缺失版本或镜头')
    editing_baseline = baseline
    previous_provenance = None
    if args.previous_candidate:
        editing_baseline, previous_text, previous_run_text, previous_provenance = _previous_candidate(
            args.previous_candidate, root=root, original=original, baseline_text=baseline_text, baseline=baseline)
    feedback_path = Path(args.editor_feedback_file).resolve()
    feedback = feedback_path.read_bytes().decode('utf-8')
    if not feedback.strip():
        raise ValueError('短稿修订意见不能为空')
    selected = _reference_source_ids(args.reference_source_id)
    workflow = json.loads(original)
    if not isinstance(workflow, list) or len(workflow) != 2:
        raise ValueError('原工作流请求格式无效')
    source_workflow, full_text = _source_input(workflow, source.with_name('source_evidence.full.json'))
    outline_messages = build_outline_messages(source_workflow, feedback, reference_source_ids=selected)
    evidence = json.loads(outline_messages[1]['content'])
    revision_basis = [{'role': 'system', 'content': PROMPT_PATH.read_text(encoding='utf-8')},
                      {'role': 'user', 'content': json.dumps(evidence, ensure_ascii=False)}]
    messages = _revision_messages(revision_basis, editing_baseline, '按本轮用户意见修订短稿。')
    scope_instruction = (
        '\n本轮专用范围（优先于上文允许修改两版的规则）：只修订short既有字段和既有镜头，long全部字段、文字、数字保持原样。'
        '允许修订共同core_message，但须知道这会影响两版共同解释，长稿不会因此获得通过。'
        '只返回changes数组；script只能为short，或在改共同core_message时为both且shot_id为空。'
        '禁止重写整份双稿、增加/删除/改名镜头或自行填写通过状态。'
        '完整current_pair是待修基线，不是应该复制的正确范本；末尾current_editor_feedback是本轮必须落实的最新任务。'
        'source_overview仅作全批对照，不能代替详细source_evidence原文；本轮不生成视频。')
    messages[0]['content'] += scope_instruction
    sent = json.loads(messages[1]['content'])
    sent['short_seconds'] = evidence.get('short_seconds')
    sent['candidate_revision_scope'] = {'format': 'short', 'long': 'unchanged_not_reviewed_in_this_run',
        'reference_source_ids': [s['source_id'] for s in evidence['source_evidence']]}
    if 'planning_evidence_scope' in evidence:
        sent['planning_evidence_scope'] = evidence['planning_evidence_scope']
    if args.rewrite_short:
        sent = {key: copy.deepcopy(value) for key, value in evidence.items()
                if key not in ('long_seconds', 'current_editor_feedback')}
        all_sources = json.loads(source_workflow[1]['content'])['source_evidence']
        sent.setdefault('source_overview', _source_overview(all_sources))
        sent['candidate_revision_scope'] = {'format': 'short', 'mode': 'complete_short_replacement',
            'required_shot_ids': [s['shot_id'] for s in editing_baseline['short']['shots']],
            'long': 'not_sent_unchanged_not_reviewed_in_this_run'}
        sent['current_core_message'] = editing_baseline['core_message']
        sent['current_short'] = copy.deepcopy(editing_baseline['short'])
        messages = [{'role': 'system', 'content': PROMPT_PATH.read_text(encoding='utf-8') + (
            '\n本轮专用完整重写范围，覆盖上文双版本输出规则：本轮只输出单版本完整short，顶层必须且只能是'
            '{"core_message":"共同核心","short":{完整短稿}}，禁止changes、long或任何审核状态。'
            '完整重写short全部字段，包括premise、resolution、closing_line、expression_plan、story_beats，以及每镜'
            'blocking、action、audio、transition、首尾状态等，不得只改对白动作后保留矛盾旧字段。'
            'short及每镜严格使用上文当前schema的完整字段，不输出已废弃的camera摘要字段。'
            '保留candidate_revision_scope.required_shot_ids全部既有镜号与顺序，不增删镜头。'
            'current_short是被退回的旧稿，只供识别问题，不能当作正确范本复制；长稿内容未提供，也不在本轮重写或审核。'
            'source_overview只是对照概览，实际借鉴须查详细source_evidence；最后的current_editor_feedback是最新任务。'
            '程序会用本次short整块替换旧short，不继承任何遗漏字段。'
            '输出JSON时，在short内先输出characters与shots，再根据已经写出的实际shots填写premise、resolution、'
            'expression_plan、story_beats、closing_line等其余全部字段；字段集合不变，只调整书写顺序。'
            '共同core_message也须与实际镜头一致，不先许诺结局再用未发生的动作补齐。'
            '输出只会成为待独立审核候选，本轮不生成视频。')},
                    {'role': 'user', 'content': ''}]
        if args.omit_rejected_short:
            characters = editing_baseline['short'].get('characters')
            if (not isinstance(characters, list) or len(characters) != 2
                    or any(not isinstance(c, dict) or any(not isinstance(c.get(k), str) or not c[k].strip()
                           for k in ('name', 'identity')) for c in characters)
                    or characters[0]['name'] == characters[1]['name']):
                raise ValueError('省略旧稿重写须保留两个明确且不同角色的name和identity')
            sent.pop('current_short')
            sent.pop('current_core_message')
            sent['character_constraints'] = [{k: c[k] for k in ('name', 'identity')} for c in characters]
            messages[0]['content'] += (
                '\n本轮不发送current_short或current_core_message：旧稿仅在本地归档，不模仿旧文本。'
                '以character_constraints中的同两人姓名和身份、既有required_shot_ids及short_seconds为约束，'
                'characters中逐字复用这两人的name与identity，其他外形和表演字段仍需完整创作。'
                '根据最后的编辑说明重构同题材完整短稿；不能增加角色、改换人物身份或自行续写旧签字结果。'
                '输出仍只能是core_message与完整short，先写characters和shots再据实际镜头填齐其余字段；本轮不生成视频。')
    sent.pop('current_editor_feedback', None)
    sent['current_editor_feedback'] = feedback
    messages[1]['content'] = json.dumps(sent, ensure_ascii=False)
    output = Path(args.output_dir).resolve()
    if (root / 'data').resolve() not in output.parents:
        raise ValueError('候选修订输出须位于本项目data目录内的新目录')
    output.mkdir(parents=True, exist_ok=False)

    def save(name, value):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        (output / name).write_text(text, encoding='utf-8', newline='')

    state = {'schema': 'script_candidate_revision_run/v1', 'status': 'running',
        'started_at': now_bjt(), 'workflow_request_path': str(source), 'workflow_request_sha256': text_sha(original),
        'baseline_draft_path': str(baseline_path), 'baseline_draft_sha256': text_sha(baseline_text),
        'feedback_path': str(feedback_path), 'feedback_sha256': text_sha(feedback),
        'reviewed_source_count': len(json.loads(source_workflow[1]['content'])['source_evidence']),
        'reference_source_ids': [s['source_id'] for s in evidence['source_evidence']],
        'media_generation': False, 'model_calls': 0,
        'short_review_status': 'not_reviewed', 'long_review_status': 'unchanged_no_new_approval',
        'notice': '仅检查补丁范围与长稿未改；未运行结构、法律、语义或音视频通过审核。原长稿失败或待审状态不因此改变。'}
    if args.rewrite_short:
        state.update(revision_mode='complete_short_replacement',
                     notice='仅检查完整字段、既有镜号与冻结长稿；时长、道具、动作、法律、来源语义及声音仍须独立审核，未标记通过。')
    if args.omit_rejected_short:
        state['rejected_short_sent_to_model'] = False
    save('workflow_request.original.json', original)
    save('baseline.original.json', baseline_text)
    if previous_provenance:
        state['previous_candidate'] = previous_provenance
        save('previous_candidate.original.json', previous_text)
        save('previous_run.original.json', previous_run_text)
    save('feedback.md', feedback)
    save('source_evidence.full.json', full_text if full_text is not None else json.loads(source_workflow[1]['content'])['source_evidence'])
    save('request.json', messages)
    state.update(prompt_sha256=text_sha(messages[0]['content']),
        request_sha256=text_sha((output/'request.json').read_bytes().decode('utf-8')),
        source_evidence_sha256=text_sha((output/'source_evidence.full.json').read_bytes().decode('utf-8')))
    save('run.json', state)
    try:
        model = settings.SCRIPT_LLM_MODEL or settings.LLM_MODEL
        thinking = settings.SCRIPT_LLM_THINKING
        extra = None
        if thinking:
            if model.lower() != 'minimax-m3' or thinking not in ('disabled', 'adaptive'):
                raise ValueError('候选修订沿用项目支持的编剧thinking配置')
            extra = {'thinking': {'type': thinking}, 'reasoning_split': True}
        limit = settings.SCRIPT_LLM_MAX_TOKENS if thinking == 'adaptive' else min(settings.SCRIPT_LLM_MAX_TOKENS, 12000)
        state.update(model=model, thinking=thinking, max_output_tokens=limit,
                     request_timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS, extra_body=extra,
                     temperature=0.2, max_retries=0)
        client = LLMClient(timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS, max_retries=0,
            max_tokens=limit, preserve_invalid_json=True, model=settings.SCRIPT_LLM_MODEL or None, extra_body=extra)
        if client.provider_name == 'mock':
            raise ValueError('候选修订不允许模拟模型')
        state.update(provider=client.provider_name, model_calls=1)
        save('run.json', state)
        raw = client.chat_completion_tracked(messages, caller='pre_video_script_candidate_revision',
            temperature=0.2, json_mode=True, use_cache=False)
        save('response.json', getattr(getattr(client, 'provider', None), 'last_response_metadata', {}))
        raw_name = 'model_rewrite' if args.rewrite_short else 'model_patch'
        save(raw_name + '.json', raw or 'null')
        state[raw_name + '_sha256'] = text_sha(raw or 'null')
        if not raw:
            raise RuntimeError('候选修订模型未返回可用内容')
        _check_source_abstention(json.loads(raw), evidence)
        merged = _replace_complete_short(editing_baseline, raw) if args.rewrite_short else _merge_short_patch(editing_baseline, raw)
        if args.omit_rejected_short:
            roles = lambda rows: sorted((row['name'], row['identity']) for row in rows)
            if roles(merged['short']['characters']) != roles(sent['character_constraints']):
                raise ValueError('完整重写未保留已提供的两位角色name/identity约束')
        state.update(shared_core_changed=merged['core_message'] != editing_baseline['core_message'],
            long_original_sha256=text_sha(_source_json(baseline['long'])),
            long_candidate_sha256=text_sha(_source_json(merged['long'])),
            shared_core_impact='共同核心变化须另审其与长稿的关系；长稿原文冻结且不会自动通过。')
        save('candidate.json', merged)
        state.update(status='candidate_pending_independent_review',
                     candidate_sha256=text_sha((output/'candidate.json').read_bytes().decode('utf-8')))
    except Exception as exc:
        state.update(status='failed', error=str(exc))
        raise
    finally:
        state['finished_at'] = now_bjt()
        save('run.json', state)
    print(json.dumps(state, ensure_ascii=False))


if __name__ == '__main__':
    main()
