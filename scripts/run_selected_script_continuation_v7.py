"""One current-segment repair after explicit human rejection of source487.

The complete source and original automatic failure remain intact. This is
current-segment preparation, not a claim of whole-film director completion.
"""
from pathlib import Path
from copy import deepcopy
import argparse, base64, json, subprocess, sys
from jsonschema import Draft202012Validator

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_json_document_transport_v1 as transport
from scripts import run_selected_script_video_trial_v6 as previous
from scripts import run_selected_script_continuation_v4 as prior_segment
from scripts import run_selected_script_continuation_v5 as rejected_segment
from scripts import run_selected_script_continuation_v6 as prior_repair
from scripts.creative_bounded_format_role_clients_v1 import BoundedFormatRoleClients
from src.content_factory import creative_continuation_probe_contract_v6 as contract
from src.content_factory import creative_video_trial_contract_v1 as source_contract
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig, SeedanceReference
from src.content_factory.creative_legal_short_seedance_execution_v1 import reserve_media_attempt, frame_mime
from src.content_factory.media_review_policy import mark_saved_candidate, validate_approved_tail, validate_source_bindings, _candidate_identity
from src.content_factory.creative_stage_contracts import persist
from scripts.run_legal_current_production_v10_20261010 import validate_saved_metadata

ROOT = PROJECT / 'data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v7'
OUT = PROJECT / 'data/video_generation/legal_script487_trial_20261011/third_v7'
PARENT = prior_repair.ROOT
PREVIOUS_MEDIA = prior_segment.OUT
MODEL, LOGICAL, SOURCE_SHA = previous.MODEL, previous.LOGICAL, previous.SOURCE_SHA
SID = 'SCRIPT487_QUESTION03'
USER_FEEDBACK = '这里不行人物位置直接变了多了个人出来，好像并不清楚整体的情况这个要修复下'
PREVIOUS_SID = prior_segment.SID
COMPLETED = prior_segment.COMPLETED + prior_segment.REFS
REFS = ['B2.S01', 'B2.S02']
REVIEW_CHECKS = ['current_direction_matches_source', 'exact_current_dialogue',
                 'initial_final_state', 'action_speech_timing',
                 'natural_acting_and_camera', 'future_isolation',
                 'stimulus_source_channel', 'current_source_action_completed',
                 'closed_cast_spatial_continuity', 'camera_authority']


def approved_frame():
    rp = PREVIOUS_MEDIA / 'receipt.json'
    review_path = PREVIOUS_MEDIA / 'receipt.human_review.json'
    r = control.read(rp)
    if (r.get('segment_id') != PREVIOUS_SID or r.get('logical_task_id') != LOGICAL
            or r.get('provider') != 'ark_api' or r.get('model') != MODEL
            or r.get('last_frame_source') != 'generation_service_original'
            or r.get('plan_snapshot', {}).get('script_content_sha256') != SOURCE_SHA
            or r.get('plan_snapshot', {}).get('source_refs') != prior_segment.REFS
            or r.get('plan_snapshot', {}).get('completed_source_refs') != prior_segment.COMPLETED):
        raise ValueError('exact adjacent selected-source segment required')
    review = control.read(review_path)
    identity = review.get('candidate_identity', {}).get('identifiers', {})
    if (Path(review.get('source_receipt', '')).resolve() != rp.resolve()
            or any(not r.get(k) or identity.get(k) != r.get(k) for k in
                   ['task_id', 'provider', 'model', 'segment_id', 'logical_task_id',
                    'request_sha256', 'plan_sha256'])
            or Path(review.get('original_video', '')).resolve() != Path(r['video_path']).resolve()
            or review.get('original_video_sha256') != r.get('video_sha256')
            or Path(review.get('raw_tail', '')).resolve() != Path(r['last_frame']).resolve()
            or review.get('raw_tail_sha256') != r.get('last_frame_sha256')):
        raise ValueError('approved review belongs to another original candidate')
    frame = validate_approved_tail(review_path, expected_tail_path=Path(r['last_frame']))
    return {**frame, 'role': 'first_frame', 'source': 'generation_service_original',
            'source_task_id': r['task_id'], 'source_segment_id': r['segment_id'],
            'source_video_sha256': r['video_sha256'], 'human_review_path': str(review_path)}


def runtime():
    a = control.read(ROOT / 'ANCHOR.json')
    return control.ContinuationRuntime(PROJECT, ROOT, [PROJECT / p for p in a['runtime_sources']],
        a['inherited'], a['models'], inherited_guard=lambda: previous.verify_files(a['parent_files']),
        client_factory=BoundedFormatRoleClients, quota_state=None)


def rejected_candidate():
    """Only this exact saved, human-rejected third candidate opens a repair."""
    rp = rejected_segment.OUT / 'receipt.json'
    qp = rejected_segment.OUT / 'receipt.human_review.json'
    r, q = control.read(rp), control.read(qp)
    identity = _candidate_identity(r, rp)
    if (r.get('technical_status') != 'succeeded' or r.get('content_status') != 'rejected'
            or q.get('decision') != 'rejected' or q.get('decision_source') != 'explicit_user_statement'
            or q.get('user_statement') != USER_FEEDBACK or q.get('automated_visual_or_voice_verdict') is not False
            or q.get('source_receipt') != str(rp.resolve())
            or q.get('candidate_identity') != identity
            or q.get('candidate_identity_sha256') != control.digest(identity)
            or Path(q.get('original_video', '')).resolve() != Path(r.get('video_path', '')).resolve()
            or q.get('original_video_sha256') != r.get('video_sha256')
            or Path(q.get('raw_tail', '')).resolve() != Path(r.get('last_frame', '')).resolve()
            or q.get('raw_tail_sha256') != r.get('last_frame_sha256')
            or r.get('user_decision_source') != str(qp.resolve())
            or r.get('user_decision_sha256') != control.sha_file(qp)
            or r.get('technical_receipt_sha256') != q.get('source_receipt_sha256')
            or r.get('segment_id') != SID or r.get('logical_task_id') != LOGICAL
            or r.get('provider') != 'ark_api' or r.get('model') != MODEL
            or r.get('plan_snapshot', {}).get('script_content_sha256') != SOURCE_SHA
            or r.get('plan_snapshot', {}).get('source_refs') != REFS
            or r.get('plan_snapshot', {}).get('completed_source_refs') != COMPLETED):
        raise ValueError('exact human rejection required; unresolved candidate cannot open another request')
    validate_source_bindings(r)
    previous.verify_files({r['video_path']: r['video_sha256'], r['last_frame']: r['last_frame_sha256']})
    if Path(approved_frame()['path']).resolve() == Path(r['last_frame']).resolve():
        raise ValueError('rejected third tail may never become the first frame')
    return {'receipt': str(rp), 'receipt_sha256': control.sha_file(rp),
        'review': str(qp), 'review_sha256': control.sha_file(qp),
        'task_id': r['task_id'], 'video_sha256': r['video_sha256'],
        'candidate_identity_sha256': q['candidate_identity_sha256'],
        'user_statement': q['user_statement'], 'decision': 'rejected',
        'observed_by': 'user', 'assistant_content_inspected': False}


def recovery_parent():
    """One final complete content revision; never renew an exhausted repair."""
    ledger = control.read(PARENT / 'CALL_LEDGER.json')
    prior_repair.runtime().check(ledger)
    if [(r['ordinal'], r['label']) for r in ledger['calls']] != [(507, 'continuation_performance'), (508, 'production_text_review')]:
        raise ValueError('exact complete first content revision required')
    inherited, receipts = previous.inherited_known_parent(ledger, PARENT)
    r, review = receipts
    if (any(q['status'] != 'contract_valid' for q in receipts)
            or not review['validation']['needs_revision']):
        raise ValueError('complete known content rejection required; no unknown response recovery')
    old_content = control.read(PARENT / 'CONTENT_REVISION_BINDING.json')
    if old_content['current_segment_content_revision_index'] != 1 or old_content['max_new_writer_requests'] != 1:
        raise ValueError('two complete content revisions exhausted or different lineage')
    if old_content['format_recovery_attempts_remaining'] != 0:
        raise ValueError('historical format recovery cannot be regranted')
    x = control.read(PARENT / 'INPUT.json')
    if control.digest(x['full_current_script']) != SOURCE_SHA or x['script_sha256'] != SOURCE_SHA:
        raise ValueError('selected native source changed')
    user = [control.strict_json(m['content']) for m in r['request']['messages'] if m['role'] == 'user']
    if user[0] != control.read(PARENT / 'CURRENT_PERFORMANCE_INPUT.json'):
        raise ValueError('actual failed source input changed')
    if any((PROJECT / ('data/video_generation/legal_script487_trial_20261011/' + d + '/receipt.json')).exists()
           for d in ['third_v1', 'third_v2', 'third_v3', 'third_v4']):
        raise ValueError('another third-segment submission exists; never redispatch')
    native = previous.received_document(r)
    if native.get('script_sha256') != SOURCE_SHA or native.get('source_refs') != REFS:
        raise ValueError('previous native source changed')
    binding = {'schema': 'human_feedback_current_segment_revision/v1',
        'seed_ordinal': 507, 'seed_receipt_sha256': ledger['calls'][0]['receipt_sha256'],
        'seed_request_sha256': r['request_sha256'], 'source_sha256': SOURCE_SHA,
        'current_segment_content_revision_index': 2, 'historical_previous_segment_content_revision_index': 2,
        'max_current_segment_complete_content_revisions': 2,
        'previous_content_revision_binding_sha256': control.sha_file(PARENT / 'CONTENT_REVISION_BINDING.json'),
        'previous_content_revision_claim_path': old_content['claim_path'],
        'previous_content_revision_claim_sha256': old_content['claim_sha256'],
        'max_new_writer_requests': 1, 'format_recovery_attempts_remaining': 0,
        'prior_complete_text_used_for_full_native_revision': True,
        'rejected_candidate': rejected_candidate(), 'budget_reset': False}
    return inherited, binding, r


def prepare():
    if not (ROOT / 'ANCHOR.json').exists():
        ledger = control.read(PARENT / 'CALL_LEDGER.json')
        inherited, recovery, seed = recovery_parent()
        x = control.read(PARENT / 'INPUT.json')
        script = x['full_current_script']
        if control.digest(script) != SOURCE_SHA:
            raise ValueError('selected full source changed')
        tail = approved_frame()
        scene_context = contract.build_scene_continuity_context(script, x['scene_and_character_context'], tail)
        contract.continuation_probe_schema(script, COMPLETED, REFS, scene_context)
        scope = {'schema': 'selected_source_single_continuation_scope/v1',
                 'user_statements': [USER_FEEDBACK, '第二段通过，使用原始尾帧继续', '那你直接开始吧这些调用minimax的不需要我同意'],
                 'script_sha256': SOURCE_SHA, 'completed_source_refs': COMPLETED, 'source_refs': REFS,
                 'previous_segment_id': PREVIOUS_SID, 'segment_id': SID,
                 'max_new_video_submissions': 1, 'batch_authorized': False,
                 'automatic_retry': False, 'publishing_authorized': False, 'budget_reset': False,
                 'source_script_edited': False, 'machine_script_quality_passed': False,
                 'whole_film_direction_accepted': False, 'subsequent_continuation_requires_human_approval': True,
                 'known_complete_content_revision': True, 'current_segment_content_revision_index': 2,
                 'max_current_segment_complete_content_revisions': 2,
                 'historical_previous_segment_content_revision_index': 2, 'original_receipts_retained': True,
                 'format_recovery_attempts_remaining': 0, 'minimax_calls_require_per_call_confirmation': False}
        recovery_key = control.digest({'script_sha256': SOURCE_SHA, 'source_refs': REFS,
            'completed_source_refs': COMPLETED, 'stage': 'human_feedback_spatial_repair',
            'rejected_candidate_identity_sha256': recovery['rejected_candidate']['candidate_identity_sha256'],
            'rejected_review_sha256': recovery['rejected_candidate']['review_sha256'],
            'content_revision_index': 2,
            'previous_content_revision_binding_sha256': recovery['previous_content_revision_binding_sha256'],
            'previous_video_sha256': tail['source_video_sha256']})
        claim_path = PROJECT / 'data/creative_continuation_stages' / recovery_key / 'CLAIM.json'
        claim = {'schema': 'creative_continuation_stage_claim/v1', 'stage_key': recovery_key,
            'continuation_root': str(ROOT), 'seed_receipt_sha256': control.sha_file(PARENT / 'call_507_continuation_performance.json'),
            'seed_request_sha256': seed['request_sha256'], 'seed_ordinal': 507,
            'source_sha256': SOURCE_SHA, 'max_new_writer_requests': 1,
            'rejected_candidate_identity_sha256': recovery['rejected_candidate']['candidate_identity_sha256'],
            'rejected_review_sha256': recovery['rejected_candidate']['review_sha256'],
            'rejected_review_path': recovery['rejected_candidate']['review'],
            'content_revision_index': 2,
            'max_current_segment_complete_content_revisions': 2,
            'previous_content_revision_binding_sha256': recovery['previous_content_revision_binding_sha256'],
            'format_recovery_attempts_remaining': 0,
            'user_statement': USER_FEEDBACK, 'old_budget_reset': False}
        control.write(claim_path, claim, True)
        prior_performance = control.read(prior_segment.ROOT / 'PERFORMANCE_COMPILED.json')['native']['performance']
        inp = {'full_current_script': deepcopy(script), 'script_sha256': SOURCE_SHA,
               'actor_names': x['actor_names'], 'scene_and_character_context': x['scene_and_character_context'],
               'reference_fulltext': x['reference_fulltext'], 'production_preferences': x['production_preferences'],
               'original_automatic_decision_retained': x['original_automatic_decision_retained'],
               'completed_source_refs': COMPLETED, 'current_source_refs': REFS,
               'current_source_catalog': {q: source_contract.catalog(script)[q] for q in REFS},
               'completed_stimulus_catalog': {q: source_contract.catalog(script)[q] for q in COMPLETED},
               'previous_planned_ending_state': prior_performance['ending_state'],
               'previous_state_is_text_not_assistant_visual_inspection': True,
               'approved_first_frame': tail, 'source_acceptance_scope': scope,
               'scene_continuity_context': scene_context,
               'current_scope': '小林首次质问公司决定与个人原因矛盾，手指悬在字上方不触纸；不重演读纸，不进入B2.S03追问、B2.S04周姐反应或未来回复/推纸/拒签/出门',
               'prior_current_content_revision': {'ordinal': 507,
                   'complete_prior_native': previous.received_document(seed),
                   'complete_prior_review': control.read(PARENT / 'call_508_production_text_review.json')['output'],
                   'required_repairs': [USER_FEEDBACK,
                       '取消无像素依据的机位/左右重排，机位和原有座位以批准第二段原尾帧为准',
                       '507的observation仍写侧脸、纸面下半画面、周姐画右：这是无像素依据的旧布局，本次完整新原生所有字段都不得带入',
                       '完整源稿派生的闭合两人名单和同场景上下文必须实际进入视频模型请求'],
                   'current_segment_new_scope': False, 'previous_segment_revision_history_retained': True},
               'content_revision': {**recovery, 'claim_path': str(claim_path),
                   'claim_sha256': control.sha_file(claim_path),
                   'user_statement': USER_FEEDBACK,
                   'writer_tool_policy': 'provider_default_no_tool_choice',
                   'new_complete_native_required': True}}
        for n, v in [('INPUT.json', inp), ('USER_SCOPE.json', scope), ('FIRST_FRAME.json', tail),
                     ('CONTENT_REVISION_BINDING.json', inp['content_revision'])]:
            control.write(ROOT / n, v, True)
        files = [PARENT / n for n in ['CALL_LEDGER.json', 'AUTHORIZATION.json', 'ANCHOR.json',
                 'INPUT.json', 'CURRENT_PERFORMANCE_INPUT.json', 'CONTENT_REVISION_BINDING.json',
                 'PERFORMANCE_COMPILED.json', 'PRODUCTION_RESULT.json', 'PRODUCTION_TEXT_REVIEW_INPUT.json']]
        files += [Path(p) for p in control.read(PARENT / 'ANCHOR.json')['parent_files']]
        files += [claim_path]
        files += [rejected_segment.OUT / n for n in ['receipt.json', 'receipt.human_review.json', 'PLAN.json', 'PROMPT.txt']]
        files += [Path(control.read(rejected_segment.OUT / 'receipt.json')['video_path'])]
        for ordinal in [507, 508]:
            files += list((PARENT / f'call_evidence/call_{ordinal}').glob('*'))
        files += [PARENT / row['receipt'] for row in ledger['calls']]
        files += [PREVIOUS_MEDIA / n for n in ['receipt.json', 'receipt.human_review.json', 'PLAN.json']]
        files += [Path(tail['path']), Path(control.read(PREVIOUS_MEDIA / 'receipt.json')['video_path'])]
        sources = [p for folder in [PROJECT / 'scripts', PROJECT / 'src'] for p in folder.rglob('*.py')]
        sources += [ROOT / n for n in ['INPUT.json', 'USER_SCOPE.json', 'FIRST_FRAME.json',
                                     'CONTENT_REVISION_BINDING.json', 'ANCHOR.json']]
        control.write(ROOT / 'ANCHOR.json', {'inherited': inherited, 'models': ledger['model_configs'],
            'parent_files': {str(p): control.sha_file(p) for p in files},
            'runtime_sources': [p.relative_to(PROJECT).as_posix() for p in sources],
            'budget_reset': False, 'automatic_retry': False, 'whole_film_direction_accepted': False}, True)
    return runtime().prepare()


def wire(role, rule, value, schema, cap):
    r = {'role': role, 'model': runtime().models[role]['model'],
         'operator_version': 'selected_source_continuation/v7_bounded_complete_spatial_repair',
         'parameters': {'temperature': 0.4, 'thinking': 'disabled', 'max_completion_tokens': cap},
         'messages': [{'role': 'system', 'content': rule},
                      {'role': 'user', 'content': json.dumps(value, ensure_ascii=False)}],
         'structured_schema': schema}
    if role == 'writer':
        r['content_revision_policy'] = {'max_new_requests': 1, 'revision_index': 2,
            'max_complete_content_revisions': 2,
            'previous_complete_native_ordinal': 507, 'format_recovery_attempts_remaining': 0,
            'writer_tool_policy': 'provider_default_no_tool_choice',
            'binding_sha256': control.sha_file(ROOT / 'CONTENT_REVISION_BINDING.json')}
        r.update(output_transport=transport.VERSION, inner_document_schema=deepcopy(schema),
                 structured_schema=transport.build_envelope_schema(),
                 messages=transport.build_messages(r['messages'], schema))
    return r


def accepted(label):
    rt = runtime(); ledger = control.read(rt.ledger); rt.check(ledger)
    rows = [r for r in ledger['calls'] if r['label'] == label]
    if len(rows) != 1:
        raise ValueError('missing or repeated stage: ' + label)
    r = rt.effective_receipt(rows[0])
    if r['status'] != 'contract_valid':
        raise ValueError('stage unresolved; original response retained: ' + label)
    return r


def review_schema(script):
    row = {'type': 'object', 'additionalProperties': False,
           'required': ['check', 'status', 'source_refs', 'reason'],
           'properties': {'check': {'type': 'string'}, 'status': {'enum': ['pass', 'fail', 'unknown']},
              'source_refs': {'type': 'array', 'items': {'enum': REFS}, 'uniqueItems': True},
              'reason': {'type': 'string', 'minLength': 1, 'maxLength': 220}}}
    checks = []
    for name in REVIEW_CHECKS:
        q = deepcopy(row); q['properties']['check'] = {'const': name}; checks.append(q)
    all_pass = {'items': {'properties': {'status': {'const': 'pass'}}, 'required': ['status']}}
    nonpass = {'contains': {'properties': {'status': {'enum': ['fail', 'unknown']}}, 'required': ['status']}}
    return {'type': 'object', 'additionalProperties': False,
            'required': ['script_sha256', 'checks', 'revision_requirements', 'review_limitations'],
            'properties': {'script_sha256': {'const': control.digest(script)},
             'checks': {'type': 'array', 'prefixItems': checks, 'items': False,
                        'minItems': len(checks), 'maxItems': len(checks)},
             'revision_requirements': {'type': 'array', 'maxItems': 10,
                 'items': {'type': 'string', 'minLength': 1, 'maxLength': 220}},
             'review_limitations': {'type': 'array', 'maxItems': 6,
                 'items': {'type': 'string', 'minLength': 1, 'maxLength': 220}}},
            'allOf': [
                {'if': {'properties': {'checks': all_pass}},
                 'then': {'properties': {'revision_requirements': {'maxItems': 0}}}},
                {'if': {'properties': {'revision_requirements': {'minItems': 1}}},
                 'then': {'properties': {'checks': nonpass}}}]}


def text():
    prepare(); rt = runtime(); x = control.read(ROOT / 'INPUT.json'); script = x['full_current_script']
    # Writing receives current source only. Whole source remains in independent review.
    inp = {k: deepcopy(x[k]) for k in ['script_sha256', 'actor_names', 'reference_fulltext',
        'production_preferences', 'completed_source_refs', 'current_source_refs', 'current_source_catalog', 'completed_stimulus_catalog',
        'previous_planned_ending_state', 'approved_first_frame', 'current_scope', 'prior_current_content_revision',
        'content_revision', 'scene_continuity_context']}
    inp['actor_and_space_context'] = {k: x['scene_and_character_context'][k] for k in ['characters', 'scenes']}
    inp.update(trial_route='isolated_continuation_probe', whole_film_direction_accepted=False,
               initial_continuity='同一小林周姐、同工牌服装空间和坐姿；纸笔还在周姐一侧，小林已读到个人原因，沿批准尾帧直接质问，不重复读纸或通知')
    control.write(ROOT / 'CURRENT_PERFORMANCE_INPUT.json', inp, True)
    schema = contract.continuation_probe_schema(script, COMPLETED, REFS, x['scene_continuity_context'])
    r = rt.dispatch('continuation_performance', wire('writer',
        contract.RULE + '本次是用户拒绝第三段后的完整新原生返修。只处理B2.S01/B2.S02。小林已读到个人原因，开口质问公司决定与纸面内容的矛盾，手指悬在字上方不碰纸。'
        '质问由已完成B1.S04及前段公司通知触发；completed_stimulus_catalog只供因果接收引用，不重新演出或复抄过去对白。'
        '情绪重心在小林9秒左右完整质问：由不信转为带委屈的着急，但不吼叫；手指动作与说话同步，不能插切吞掉面部接收时间。'
        '纸笔B4才推，不换位置；不进入B2.S03追问、B2.S04周姐眼神晃/嘴角动或B3公司劝说，不站起出门。'
        '按反馈重写完整演法，不拼接旧原生稿。角色场景由scene_continuity_context闭合，camera只能retain_approved_frame。'
        '你没有尾帧像素，禁止猜测或声称人物在哪个画面方向、景别、机位或新座位；所有自由文字也应遵守。'
        '保持源动作，不加入第三人，不拆成眼唇呼吸等微动作清单；旧稿作为错误证据，完整新演法不用旧句逐字复抄。'
        '必须用submit_creative_json提交完整新原生文档；不朗读字段说明。',
        inp, schema, 6000), lambda v: contract.compile_continuation_probe(v, script, COMPLETED, REFS, x['scene_continuity_context']))
    if r['status'] != 'contract_valid':
        return {'status': 'current_performance_needs_attention', 'media_calls': 0, **rt.summary()}
    native = previous.received_document(r)
    compiled = contract.compile_continuation_probe(native, script, COMPLETED, REFS, x['scene_continuity_context'])
    prompt = contract.render_prompt(compiled, script, actor_names=x['actor_names'])
    control.write(ROOT / 'CURRENT_DIRECTION_COMPILED.json', native['current_direction'], True)
    control.write(ROOT / 'PERFORMANCE_COMPILED.json', compiled, True)
    control.write(ROOT / 'FINAL_PROMPT.json', {'prompt': prompt}, True)
    inp_review = {k: deepcopy(x[k]) for k in ['full_current_script', 'script_sha256',
        'actor_names', 'reference_fulltext', 'production_preferences', 'completed_source_refs',
        'current_source_refs', 'current_source_catalog', 'completed_stimulus_catalog', 'previous_planned_ending_state',
        'approved_first_frame', 'current_scope', 'scene_continuity_context', 'prior_current_content_revision']}
    inp_review['actor_and_space_context'] = inp['actor_and_space_context']
    inp_review['known_source_repair_requirements'] = x['prior_current_content_revision']['required_repairs']
    timing = {k: deepcopy(v) for k, v in compiled['performance_compiled'].items() if k != 'native'}
    inp_review.update(current_native_direction_and_performance=native,
        compiled_timing=timing, compiled_sha256=control.digest(compiled), actual_video_prompt=prompt,
        whole_film_direction_accepted=False, prior_bad_native_and_review_kept_locally=True)
    control.write(ROOT / 'PRODUCTION_TEXT_REVIEW_INPUT.json', inp_review, True)
    schema = review_schema(script)
    def validate(v):
        Draft202012Validator(schema).validate(v)
        return {'needs_revision': any(q['status'] != 'pass' for q in v['checks']) or bool(v['revision_requirements'])}
    review = rt.dispatch('production_text_review', wire('director',
        '独立审查当前第三段B2.S01-S02完整导演/演法/实际prompt，只判断当前段。'
        '完整原稿与批准尾帧元数据给出来源，助手未看媒体，不能推定像素质量。'
        '十项逐一有据判断：当前方向对应源文；B2.S01中文对白完整一次；沿上段已读到个人原因的末态、纸笔不提前推、工牌人物不重建；'
        '质问约9.4秒正常语速，手指悬空动作自然同步，反应时间足够；面部质问可读，机位不拆机械微表情，不用纸面特写吞掉情绪主线；'
        '没有B2.S03第二次追问、B2.S04周姐眼神晃/嘴角动、B3软化或未来对白/拒签/递纸/出门。'
        '逐个核对actor_goals.source_reception.stimuli的phase=current/completed与response、dialogue_delivery.listener_behavior、continuous_performance和实际prompt：'
        '质问由已完成读纸与公司通知触发，不能声称看见自己的手才开始质问；completed来源只供接收记忆，不能重复演出。spoken不能用自己对白作听觉刺激，visible须动作；纸面字不伪造成周姐说出。'
        'current_source_action_completed必须确认本段B2.S02手指悬在原因栏上方、不碰纸；纸仍原处，不能悄悄移动靠近来实现指字。'
        'closed_cast_spatial_continuity确认实际prompt包含只两人、同会议室，未暗示额外人物/分身/换座/重新入场；'
        'camera_authority确认camera=retain_approved_frame且本次新原生所有自由文字未猜测画面左右、景别或重新定机位；像素状态只以原尾帧为准。'
        '旧505/506八项通过但用户视频拒绝，旧原生只作反例，不把旧坏字段当作新稿字段；不能借旧通过绕过本次反馈。文字审查不能替代视频审核。'
        'revision_requirements只列需要改动新稿的具体错误，必须对应fail/unknown；全部pass时该数组必须为空。'
        '视频需人工审核、像素未看、旧记录保留等权限和审查边界写入review_limitations，不写成内容必修改。'
        '不确定给unknown，有真实违反给fail与必修。不能因为整片导演未建就否定本次单段，也不能给整片或视频通过。',
        inp_review, schema, 4500), validate)
    if review['status'] != 'contract_valid' or review['validation']['needs_revision']:
        return {'status': 'production_text_needs_attention', 'media_calls': 0, **rt.summary()}
    control.write(ROOT / 'VIDEO_TEXT_HANDOFF.json', {
        'schema': 'selected_source_continuation_handoff/v1', 'script_sha256': SOURCE_SHA,
        'completed_source_refs': COMPLETED, 'current_source_refs': REFS,
        'writer_ordinal': r['ordinal'], 'review_ordinal': review['ordinal'],
        'scene_continuity_context_sha256': control.digest(x['scene_continuity_context']),
        'rejected_candidate': x['content_revision']['rejected_candidate'],
        'review_limitations': review['output']['review_limitations'],
        'performance_sha256': control.digest(compiled), 'prompt_sha256': control.digest(prompt),
        'production_text_ready_for_single_trial': True, 'whole_film_direction_accepted': False,
        'whole_film_performance_complete': False, 'machine_script_quality_passed': False,
        'previous_video_user_approved': True, 'actual_video_quality_passed': False,
        'trial_route': 'isolated_continuation_probe', 'max_new_video_submissions': 1}, True)
    return {'status': 'production_text_ready_for_single_continuation',
            'duration_seconds': compiled['performance_compiled']['duration_seconds'], **rt.summary()}


def make_plan():
    rejected_candidate()
    rt = runtime(); rt.check(control.read(rt.ledger))
    if any((PROJECT / ('data/video_generation/legal_script487_trial_20261011/' + d + '/receipt.json')).exists()
           for d in ['third_v1', 'third_v2', 'third_v3', 'third_v4']):
        raise ValueError('another original third-segment submission exists; reconcile, never redispatch')
    x = control.read(ROOT / 'INPUT.json'); h = control.read(ROOT / 'VIDEO_TEXT_HANDOFF.json')
    if accepted('production_text_review')['validation']['needs_revision']:
        raise ValueError('unresolved current review')
    c = contract.compile_continuation_probe(previous.received_document(accepted('continuation_performance')),
                                            x['full_current_script'], COMPLETED, REFS, x['scene_continuity_context'])
    prompt = contract.render_prompt(c, x['full_current_script'], actor_names=x['actor_names'])
    if (h['script_sha256'] != SOURCE_SHA or control.digest(x['full_current_script']) != SOURCE_SHA
            or control.read(ROOT / 'CURRENT_DIRECTION_COMPILED.json') != c['current_direction']
            or control.read(ROOT / 'PERFORMANCE_COMPILED.json') != c
            or control.read(ROOT / 'FINAL_PROMPT.json') != {'prompt': prompt}
            or h['performance_sha256'] != control.digest(c) or h['prompt_sha256'] != control.digest(prompt)
            or h['scene_continuity_context_sha256'] != control.digest(x['scene_continuity_context'])
            or h['rejected_candidate'] != rejected_candidate()
            or h['production_text_ready_for_single_trial'] is not True
            or h['completed_source_refs'] != COMPLETED or h['current_source_refs'] != REFS):
        raise ValueError('complete current native handoff changed')
    frame = approved_frame()
    if frame != x['approved_first_frame'] or frame != control.read(ROOT / 'FIRST_FRAME.json'):
        raise ValueError('approved adjacent tail changed')
    files = [ROOT / n for n in ['INPUT.json', 'USER_SCOPE.json', 'FIRST_FRAME.json',
        'CONTENT_REVISION_BINDING.json',
        'CURRENT_DIRECTION_COMPILED.json', 'PERFORMANCE_COMPILED.json', 'FINAL_PROMPT.json',
        'VIDEO_TEXT_HANDOFF.json', 'CALL_LEDGER.json']]
    files += [Path(__file__).resolve(), PROJECT / 'src/content_factory/creative_continuation_probe_contract_v6.py',
              PROJECT / 'src/content_factory/creative_continuation_probe_contract_v5.py',
              PROJECT / 'src/content_factory/creative_continuation_probe_contract_v4.py',
              PROJECT / 'src/content_factory/creative_continuation_probe_contract_v3.py',
              PROJECT / 'scripts/creative_bounded_format_role_clients_v1.py',
              PROJECT / 'src/content_factory/creative_continuation_probe_contract_v2.py',
              PROJECT / 'src/content_factory/creative_continuation_probe_contract_v1.py',
              PROJECT / 'src/content_factory/creative_video_trial_contract_v1.py',
              PREVIOUS_MEDIA / 'receipt.json', PREVIOUS_MEDIA / 'receipt.human_review.json', Path(frame['path'])]
    files += [rejected_segment.OUT / 'receipt.json', rejected_segment.OUT / 'receipt.human_review.json']
    return {'schema': 'selected_source_continuation_plan/v1', 'logical_task_id': LOGICAL,
        'segment_id': SID, 'source_run': None, 'script_content_sha256': SOURCE_SHA,
        'completed_source_refs': COMPLETED, 'source_refs': REFS, 'provider': 'ark_api', 'model': MODEL,
        'resolution': '480p', 'ratio': '9:16', 'duration_seconds': c['performance_compiled']['duration_seconds'],
        'generate_audio': True, 'return_last_frame': True, 'image_role': 'first_frame', 'first_frame': frame,
        'sources': {str(p): {'path': str(p), 'sha256': control.sha_file(p)} for p in files},
        'authorization': x['source_acceptance_scope'], 'prompt': prompt,
        'scene_continuity_context': x['scene_continuity_context'],
        'rejected_candidate': rejected_candidate(),
        'new_submissions': 1, 'automatic_retry': False, 'budget_reset': False,
        'future_continuation_requires_current_human_approval': True,
        'machine_script_quality_passed': False, 'whole_film_direction_accepted': False}


def validate_plan(p):
    if p.get('rejected_candidate') != rejected_candidate():
        raise ValueError('repair rejection binding changed')
    x = control.read(ROOT / 'INPUT.json')
    expected_context = contract.build_scene_continuity_context(x['full_current_script'], x['scene_and_character_context'], approved_frame())
    if p.get('scene_continuity_context') != expected_context:
        raise ValueError('closed cast/scene continuity context changed')
    required = {'schema': 'selected_source_continuation_plan/v1', 'logical_task_id': LOGICAL,
        'segment_id': SID, 'source_run': None, 'script_content_sha256': SOURCE_SHA, 'image_role': 'first_frame',
        'provider': 'ark_api', 'model': MODEL, 'resolution': '480p', 'ratio': '9:16',
        'generate_audio': True, 'return_last_frame': True, 'new_submissions': 1,
        'automatic_retry': False, 'budget_reset': False,
        'future_continuation_requires_current_human_approval': True,
        'machine_script_quality_passed': False, 'whole_film_direction_accepted': False}
    if any(type(p.get(k)) is not type(v) or p.get(k) != v for k, v in required.items()):
        raise ValueError('one exact current continuation required')
    a = p['authorization']
    ar = {'max_new_video_submissions': 1, 'batch_authorized': False, 'automatic_retry': False,
          'publishing_authorized': False, 'budget_reset': False, 'source_script_edited': False,
          'machine_script_quality_passed': False, 'whole_film_direction_accepted': False,
          'subsequent_continuation_requires_human_approval': True}
    if (any(type(a.get(k)) is not type(v) or a.get(k) != v for k, v in ar.items())
            or a['script_sha256'] != SOURCE_SHA or a['source_refs'] != REFS
            or a['completed_source_refs'] != COMPLETED or a['previous_segment_id'] != PREVIOUS_SID
            or a['segment_id'] != SID or p['source_refs'] != REFS
            or p['completed_source_refs'] != COMPLETED or p['first_frame'] != approved_frame()):
        raise ValueError('source scope or approved adjacent tail changed')
    if type(p.get('duration_seconds')) is not int or not 4 <= p['duration_seconds'] <= 15:
        raise ValueError('normal duration four to fifteen required')
    previous.verify_files({q['path']: q['sha256'] for q in p['sources'].values()})
    return p


def build_request(client, p):
    f = Path(p['first_frame']['path'])
    image = SeedanceReference('image', f'data:{frame_mime(f)};base64,' + base64.b64encode(f.read_bytes()).decode(), 'first_frame')
    return client.build_task_payload(p['prompt'], duration=p['duration_seconds'], ratio='9:16', resolution='480p',
        generate_audio=True, return_last_frame=True, watermark=False, seed=20261012,
        references=[image], task_type='first_frame')


def media(operation):
    OUT.mkdir(parents=True, exist_ok=True); pp = OUT / 'PLAN.json'; rp = OUT / 'receipt.json'
    lock = OUT / '.execution.lock'
    with lock.open('x', encoding='utf-8') as f: f.write('one approved native-tail continuation')
    try:
        with SeedanceClient(SeedanceConfig.from_env('ark_api', require_key=True)) as client:
            if client.config.model != MODEL: raise ValueError('unverified video model change')
            if operation == 'media_prepare':
                if rp.exists(): raise ValueError('original submission exists; query only')
                p = validate_plan(make_plan()); req = build_request(client, p)
                control.write(pp, p, True); control.write(OUT / 'REQUEST.preview.json', req, True)
                (OUT / 'PROMPT.txt').write_text(p['prompt'] + '\n', encoding='utf-8')
                return {'status': 'prepared', 'duration_seconds': p['duration_seconds'], 'new_paid_calls': 0}
            if operation == 'media_submit':
                if rp.exists(): raise ValueError('never resubmit existing request')
                p = validate_plan(control.read(pp))
                if p != make_plan(): raise ValueError('current handoff changed')
                req = build_request(client, p)
                if req != control.read(OUT / 'REQUEST.preview.json'): raise ValueError('actual request changed')
                r = {'schema': 'selected_source_continuation_receipt/v1', 'status': 'submitting',
                    'technical_status': 'running', 'content_status': 'not_available', 'logical_task_id': LOGICAL,
                    'segment_id': SID, 'model': MODEL, 'provider': 'ark_api', 'created_at': control.now(),
                    'plan_snapshot': p, 'plan': str(pp), 'plan_path': str(pp), 'plan_sha256': control.sha_file(pp),
                    'source_bindings': p['sources'], 'request': req, 'request_sha256': control.digest(req),
                    'new_submissions': 1, 'automatic_retry': False}
                control.write(rp, r, True)
                try: reserve_media_attempt(pp, p, rp)
                except Exception as exc:
                    r.update(status='blocked_before_submit', technical_status='not_submitted', new_submissions=0, error=str(exc))
                    persist(rp, r); raise
                try:
                    created = client.create_task(req)
                    if not created.get('id'): raise ValueError('missing provider ID; outcome unknown')
                except Exception as exc:
                    code = getattr(exc, 'status_code', None); known = isinstance(code, int) and 400 <= code < 500
                    r.update(status='request_rejected' if known else 'submit_outcome_unknown',
                             technical_status='failed' if known else 'unknown', error=str(exc), http_status=code)
                    persist(rp, r); raise
                r.update(task_id=created['id'], created=created, status='submitted'); persist(rp, r)
            elif operation == 'media_query':
                r = control.read(rp)
                if not r.get('task_id'): raise ValueError('missing original ID; reconcile, never resubmit')
            else: raise ValueError('explicit media operation required')
            if r.get('technical_status') == 'succeeded':
                previous.verify_files({r['video_path']: r['video_sha256']})
                if r.get('last_frame'): previous.verify_files({r['last_frame']: r['last_frame_sha256']})
                return {k: r.get(k) for k in ['technical_status', 'content_status', 'task_id', 'video_path']}
            t = client.get_task(r['task_id']); r.update(latest_response=t, status=t['status'], last_queried_at=control.now()); persist(rp, r)
            if t['status'] in ('failed', 'expired', 'cancelled'):
                r.update(technical_status='failed', final=t); persist(rp, r)
            elif t['status'] == 'succeeded':
                r.update(final=t, provider_task_status='succeeded'); persist(rp, r)
                stage = 'video_download'
                try:
                    video = client.download_video(t, OUT / (SID + '.mp4'))
                    if not video.stat().st_size: raise ValueError('empty saved video')
                    r.update(video_path=str(video), video_sha256=control.sha_file(video), video_bytes=video.stat().st_size); persist(rp, r)
                    stage = 'technical_probe'
                    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(video)], text=True, encoding='utf-8'))
                    r['technical_metadata'] = validate_saved_metadata(probe, r['plan_snapshot']); persist(rp, r)
                    stage = 'tail_download'
                    if t.get('content', {}).get('last_frame_url'):
                        tail = client.download_last_frame(t, OUT / (SID + '.provider_last.png'))
                        if not tail.stat().st_size: raise ValueError('empty provider original tail')
                        r.update(last_frame=str(tail), last_frame_sha256=control.sha_file(tail), last_frame_source='generation_service_original', tail_status='saved_unapproved')
                    else: r.update(last_frame=None, tail_status='not_returned; continuation blocked')
                    r.update(human_decision=None, next_segment_dispatch_allowed=False,
                             assistant_content_inspected=False, completed_at=control.now())
                    mark_saved_candidate(r); persist(rp, r)
                except Exception as exc:
                    r.update(status='artifact_save_pending', failure_stage=stage, artifact_error=str(exc)); persist(rp, r); raise
            return {k: r.get(k) for k in ['technical_status', 'content_status', 'status', 'task_id', 'video_path', 'tail_status']}
    finally: lock.unlink()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(); parser.add_argument('operation', choices=['prepare', 'text', 'status', 'media_prepare', 'media_submit', 'media_query'])
    op = parser.parse_args().operation
    result = prepare() if op == 'prepare' else text() if op == 'text' else runtime().summary() if op == 'status' else media(op)
    print(json.dumps(result, ensure_ascii=False), flush=True)
