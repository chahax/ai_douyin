"""Selected full native script -> whole direction -> current acting -> one video.

Human trial acceptance never rewrites the original automatic text decision.
No old acting bundle, transport retry, batch continuation, or publishing.
"""
from pathlib import Path
from copy import deepcopy
import argparse, base64, json, subprocess, sys
from jsonschema import Draft202012Validator

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_json_document_transport_v1 as document_transport
from src.content_factory import creative_video_trial_contract_v1 as contract
from src.content_factory import creative_video_trial_direction_v2 as direction_contract
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig, SeedanceReference
from src.content_factory.creative_legal_short_seedance_execution_v1 import reserve_media_attempt, frame_mime
from src.content_factory.media_review_policy import mark_saved_candidate, validate_approved_tail
from src.content_factory.creative_stage_contracts import persist
from scripts.run_legal_current_production_v10_20261010 import validate_saved_metadata

ROOT = PROJECT / 'data/production_revisions/selected_script_video_trial_20261011/script487_v3'
OUT = PROJECT / 'data/video_generation/legal_script487_trial_20261011/opening_v3'
PARENT = PROJECT / 'data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_15'
KNOWN_PARENT = PROJECT / 'data/production_revisions/selected_script_video_trial_20261011/script487_v2'
ASSET = PROJECT / 'data/video_generation/legal_trend_20261008/opening_SH01_v1'
MODEL = 'doubao-seedance-2-0-mini-260615'
LOGICAL = 'legal_trend_text_trial_20261008_adopted_r8'
SID = 'SCRIPT487_OPENING01'
SOURCE_SHA = 'cbb125ea23dbefca1c314d53bc26ce7c231d1b3ab39b256b1b20d8dcde520d0d'
REFS = ['B1.S01', 'B1.S02']


def validate_trial_sources(scope, script, source_decision, asset_receipt, asset_review):
    if scope.get('script_sha256') != control.digest(script):
        raise ValueError('selected complete native source changed')
    if scope.get('source_decision_sha256') != control.digest(source_decision):
        raise ValueError('original automatic decision changed')
    required = {'human_trial_acceptance_recorded': True, 'machine_script_quality_passed': False,
                'max_new_video_submissions': 1, 'batch_authorized': False,
                'automatic_retry': False, 'publishing_authorized': False,
                'budget_reset': False, 'source_script_edited': False}
    if any(type(scope.get(k)) is not type(v) or scope.get(k) != v for k, v in required.items()):
        raise ValueError('one selected native trial scope required')
    if not scope.get('user_statements') or scope.get('source_validation_findings_retained') is not True:
        raise ValueError('actual trial instruction and retained automatic findings required')
    if source_decision.get('script_sha256') != scope['script_sha256']:
        raise ValueError('original automatic decision belongs to a different script')
    if source_decision.get('status') in ('text_ready_for_director', 'passed'):
        raise ValueError('this trial intake must preserve its actual nonpassed source decision')
    if (asset_receipt.get('technical_status') != 'succeeded'
            or asset_receipt.get('last_frame_source') != 'generation_service_original'
            or asset_receipt.get('content_status') != 'approved'
            or asset_review.get('decision') != 'approved'
            or asset_review.get('decision_source') != 'explicit_user_statement'
            or asset_review.get('automated_visual_or_voice_verdict') is not False):
        raise ValueError('approved original identity/environment asset required')
    review_bindings = {'raw_tail': 'last_frame', 'raw_tail_sha256': 'last_frame_sha256',
                       'original_video': 'video_path', 'original_video_sha256': 'video_sha256'}
    if any(asset_review.get(k) != asset_receipt.get(v) or not asset_review.get(k)
           for k, v in review_bindings.items()):
        raise ValueError('approved original asset review belongs to different video/tail')
    identity = asset_review.get('candidate_identity', {}).get('identifiers', {})
    if any(identity.get(k) != asset_receipt.get(k) or not identity.get(k)
           for k in ['task_id', 'provider', 'model', 'request_sha256', 'plan_sha256']):
        raise ValueError('approved original asset candidate identity differs')
    return {'script_sha256': control.digest(script), 'machine_script_quality_passed': False,
            'user_accepted_for_trial': True, 'old_source_decision_unchanged': True}


def verify_files(bindings):
    for path, digest in bindings.items():
        if control.sha_file(path) != digest:
            raise ValueError('bound file changed: ' + str(path))


def runtime():
    anchor = control.read(ROOT / 'ANCHOR.json')
    def guard():
        verify_files(anchor['parent_files'])
    sources = [PROJECT / p for p in anchor['runtime_sources']]
    return control.ContinuationRuntime(PROJECT, ROOT, sources, anchor['inherited'],
                                     anchor['models'], inherited_guard=guard, quota_state=None)


def inherited_known_parent(ledger, parent):
    """Carry complete paid failures as spend; unknown results never allow repair."""
    if control.sha_file(parent / 'AUTHORIZATION.json') != ledger['authorization_sha256']:
        raise ValueError('parent authorization changed')
    anchor = control.read(parent / 'ANCHOR.json')
    verify_files(anchor['parent_files'])
    if ledger['starting_spend'] != anchor['inherited'] or ledger['model_configs'] != anchor['models']:
        raise ValueError('parent inherited spend/model binding changed')
    if ledger.get('old_budget_reset') is not False or ledger.get('automatic_retry') is not False:
        raise ValueError('parent budget and retry boundary changed')
    verify_files({str(PROJECT / p): h for p, h in ledger['source_manifest'].items()})
    verify_files({str(parent / 'source_at_dispatch' / p): h for p, h in ledger['source_manifest'].items()})
    receipts = []
    for row in ledger['calls']:
        p = parent / row['receipt']; r = control.read(p)
        if control.sha_file(p) != row['receipt_sha256']:
            raise ValueError('parent receipt changed')
        m = r.get('response_metadata', {})
        if (type(m.get('total_tokens')) is not int or m['total_tokens'] < 0
                or m.get('response_body_complete') is not True
                or m.get('finish_reason') not in ('tool_calls', 'stop')
                or not isinstance(r.get('output'), dict)
                or r['status'] not in ('contract_valid', 'contract_rejected')):
            raise ValueError('unknown or incomplete parent result cannot be redispatched')
        if r['status'] == 'contract_rejected' and r.get('failure', {}).get('category') not in ('validation', 'state_contract'):
            raise ValueError('parent failure must be a known complete content-contract failure')
        receipts.append(r)
    inherited = deepcopy(ledger['starting_spend'])
    inherited.update(calls_started=inherited['calls_started'] + len(receipts),
                     reported_tokens=inherited['reported_tokens'] + sum(r['response_metadata']['total_tokens'] for r in receipts),
                     calls_with_known_usage=inherited['calls_with_known_usage'] + len(receipts),
                     parent_ledger_sha256=control.sha_file(parent / 'CALL_LEDGER.json'))
    return inherited, receipts


def stage_inputs(x):
    """Whole-film planning cannot inherit the one-video dispatch boundary."""
    whole = {k: deepcopy(x[k]) for k in ['full_current_script', 'script_sha256', 'actor_names',
             'scene_and_character_context', 'reference_fulltext', 'selected_asset_feedback', 'production_preferences']}
    whole['full_source_catalog'] = contract.catalog(x['full_current_script'])
    whole['first_refs'] = REFS
    whole['whole_film_requirement'] = '全25个实际steps完整规划；正文steps为唯一事件与对白来源。摘要声称但steps没有的行为不得补演。'
    whole['prior_complete_direction_failure'] = deepcopy(x['prior_complete_direction_failure'])
    acting = {k: deepcopy(x[k]) for k in ['full_current_script', 'script_sha256', 'actor_names',
              'scene_and_character_context', 'reference_fulltext', 'selected_asset_feedback', 'production_preferences', 'current_scope']}
    return whole, acting


def prepare():
    if not (ROOT / 'ANCHOR.json').exists():
        ledger = control.read(KNOWN_PARENT / 'CALL_LEDGER.json')
        inherited, receipts = inherited_known_parent(ledger, KNOWN_PARENT)
        if len(receipts) != 1 or receipts[0]['ordinal'] != 493 or receipts[0]['status'] != 'contract_rejected':
            raise ValueError('this scope repair binds the exact complete493 failure')
        script = control.read(PARENT / 'versions/07/FULL_SCRIPT.json')
        if control.digest(script) != SOURCE_SHA:
            raise ValueError('current selected487 identity changed')
        decision = control.read(PARENT / 'versions/07/AUTOMATIC_DECISION.json')
        prior, review = control.read(ASSET / 'receipt.json'), control.read(ASSET / 'receipt.human_review.json')
        frame = validate_approved_tail(ASSET / 'receipt.human_review.json')
        scope = {'schema': 'selected_native_script_single_video_trial/v1',
                 'user_statements': ['开始视频流程。', '刚刚这个版本感觉ok了你评价没通过？'],
                 'interpretation': '紧邻487完整正文获用户认可试拍；保持原正文及自动失败，不解释为普遍质量通过',
                 'script_sha256': SOURCE_SHA, 'script_ordinal': 487,
                 'source_decision_sha256': control.digest(decision),
                 'source_validation_findings_retained': True,
                 'human_trial_acceptance_recorded': True, 'machine_script_quality_passed': False,
                 'max_new_video_submissions': 1, 'batch_authorized': False, 'automatic_retry': False,
                 'publishing_authorized': False, 'budget_reset': False, 'source_script_edited': False,
                 'first_source_refs': REFS, 'reference_image_only': True,
                 'later_tail_continuation_requires_human_approval': True}
        validate_trial_sources(scope, script, decision, prior, review)
        asset = {'path': frame['path'], 'sha256': frame['sha256'], 'source': 'generation_service_original',
                 'role': 'reference_image', 'use': '同一小林、周姐、服装与小会议室身份环境参考；重建487起态，不沿旧图纸朝下或工牌在桌起态',
                 'source_task_id': prior['task_id'], 'source_video_sha256': prior['video_sha256'],
                 'human_review_path': str(ASSET / 'receipt.human_review.json')}
        parent_input = control.read(PARENT / 'INPUT.json')
        inp = {'full_current_script': script, 'script_sha256': SOURCE_SHA,
               'actor_names': {'zhou': '周姐', 'xiaolin': '小林'},
               'scene_and_character_context': {k: parent_input['brief'][k] for k in ['characters', 'scenes', 'initial_state']},
               'reference_fulltext': parent_input['reference_fulltext'], 'selected_asset_feedback': asset,
               'source_acceptance_scope': scope, 'original_automatic_decision_retained': decision,
               'prior_complete_direction_failure': {'ordinal': 493, 'status': receipts[0]['status'],
                   'native_output': receipts[0]['output'], 'failure': receipts[0]['failure'],
                   'repair_requirement': '原完整响应把镜段字段泄到顶层/item，并重复一个来源；须完整新计划全部25项且数组为JSON数组，不拼旧段。'},
               'current_scope': {'source_refs': REFS, 'end': '公司通知整句说完，小林接收；尚未说B1.S03、看纸、推纸或拒签'},
               'production_preferences': {'language': '普通话', 'no_subtitles': True, 'native_segment_max_seconds': 15,
                                          'normal_spoken_characters_per_second': 3.3, 'no_speed_fitting': True,
                                          'whole_film_max_seconds': 180, 'acting': '行动目的与听懂后的自然反应；说话与当前必要动作可重叠'}}
        for n, v in [('INPUT.json', inp), ('USER_SCOPE.json', scope), ('ASSET_FEEDBACK.json', asset)]:
            control.write(ROOT / n, v, True)
        files = [PARENT / 'CALL_LEDGER.json', PARENT / 'STATE.json', PARENT / 'AUTHORIZATION.json',
                 PARENT / 'INPUT.json', PARENT / 'versions/07/FULL_SCRIPT.json',
                 PARENT / 'versions/07/AUTOMATIC_DECISION.json', ASSET / 'receipt.json',
                 ASSET / 'receipt.human_review.json', Path(frame['path']), Path(prior['video_path'])]
        original_ledger = control.read(PARENT / 'CALL_LEDGER.json')
        files += [PARENT / row['receipt'] for row in original_ledger['calls']]
        files += [KNOWN_PARENT / n for n in ['CALL_LEDGER.json', 'AUTHORIZATION.json', 'ANCHOR.json', 'INPUT.json']]
        files += [KNOWN_PARENT / row['receipt'] for row in ledger['calls']]
        sources = [p for folder in [PROJECT / 'scripts', PROJECT / 'src'] for p in folder.rglob('*.py')]
        sources += [ROOT / n for n in ['INPUT.json', 'USER_SCOPE.json', 'ASSET_FEEDBACK.json', 'ANCHOR.json']]
        control.write(ROOT / 'ANCHOR.json', {'inherited': inherited, 'models': ledger['model_configs'],
                      'parent_files': {str(p): control.sha_file(p) for p in files},
                      'runtime_sources': [p.relative_to(PROJECT).as_posix() for p in sources],
                      'parent_source_manifest_sha256': control.digest(ledger['source_manifest']),
                      'automatic_quality_assertion': False, 'budget_reset': False}, True)
    return runtime().prepare()


def wire(role, instruction, value, schema, cap):
    rt = runtime()
    result = {'role': role, 'model': rt.models[role]['model'], 'operator_version': 'selected_video_trial/v3',
            'parameters': {'temperature': 0.4, 'thinking': 'disabled', 'max_completion_tokens': cap},
            'messages': [{'role': 'system', 'content': instruction},
                         {'role': 'user', 'content': json.dumps(value, ensure_ascii=False)}],
            'structured_schema': schema}
    if role == 'writer':
        result.update(output_transport=document_transport.VERSION,
                      inner_document_schema=deepcopy(schema),
                      structured_schema=document_transport.build_envelope_schema(),
                      messages=document_transport.build_messages(result['messages'], schema))
    return result


def received_document(receipt):
    """Return strictly decoded original payload, never repair a native response."""
    if receipt['request'].get('output_transport'):
        value = document_transport.extract_original_inner(receipt['response_text'], receipt['request']['inner_document_schema'])['document']
        if value != receipt.get('document_output'):
            raise ValueError('decoded document differs from preserved original payload')
        return value
    return receipt['output']


def accepted(label):
    rt = runtime(); ledger = control.read(rt.ledger); rt.check(ledger)
    rows = [q for q in ledger['calls'] if q['label'] == label]
    if len(rows) != 1:
        raise ValueError('accepted stage missing: ' + label)
    r = rt.effective_receipt(rows[0])
    if r['status'] != 'contract_valid':
        raise ValueError('stage not complete/valid; preserve original result: ' + label)
    return r


def whole_wire_schema(script):
    return direction_contract.whole_direction_schema(script, REFS)


def compile_direction(value, script):
    return direction_contract.compile_direction(value, script, REFS)


def review_schema(script, direction):
    refs = list(contract.catalog(script)); ids = [q['segment_id'] for q in direction['segments']]
    check = {'type': 'object', 'additionalProperties': False,
             'required': ['check', 'status', 'source_refs', 'reason'],
             'properties': {'check': {'type': 'string'}, 'status': {'enum': ['pass', 'fail', 'unknown']},
                            'source_refs': {'type': 'array', 'items': {'enum': refs}, 'uniqueItems': True},
                            'reason': {'type': 'string', 'minLength': 1, 'maxLength': 220}}}
    names = ['full_source_coverage', 'segment_information_and_cut', 'opening_source_and_dialogue',
             'opening_initial_and_final_state', 'opening_action_speech_timing', 'opening_acting_and_camera',
             'opening_future_isolation']
    checks = []
    for name in names:
        row = deepcopy(check); row['properties']['check'] = {'const': name}; checks.append(row)
    return {'type': 'object', 'additionalProperties': False,
            'required': ['script_sha256', 'checks', 'revision_requirements'],
            'properties': {'script_sha256': {'const': control.digest(script)},
                           'checks': {'type': 'array', 'prefixItems': checks, 'items': False,
                                      'minItems': len(checks), 'maxItems': len(checks)},
                           'revision_requirements': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}}}


def text():
    prepare(); rt = runtime(); x = control.read(ROOT / 'INPUT.json'); s = x['full_current_script']
    whole_input, acting_input = stage_inputs(x)
    whole_input['normal_dialogue_seconds_by_source'] = {
        ref: round(contract.spoken_seconds(row), 6) for ref, row in contract.catalog(s).items() if row['kind'] == 'dialogue'}
    control.write(ROOT / 'WHOLE_DIRECTION_INPUT.json', whole_input, True)
    rule = ('你是MiniMax整片导演。只安排已选完整正文的25个实际steps，不改台词、不补摘要声称却未演出的首次拒签。'
            'reference_fulltext借镜头与表演表达机制。'
            '整片规划明确每段新增信息、观察对象、情绪变化和切镜理由；source_refs按原顺序全覆盖一次。'
            '每个生成段4至15秒，正常3.3发音字每秒，不拆一句、删句或提速塞入；只选择必要活动，不堆微动作。'
            '首段M001固定只含B1.S01与B1.S02；移夹露纸指字抬眼与公司通知允许自然重叠。'
            'source_assignments按全部25来源逐项指定归属，segments连续M001起给全部段创作信息，'
            '相邻必要动作可与当下对白同段自然发生，不把每个手势和停顿各切一个4秒镜头。'
            'target_seconds须大于该段normal_dialogue_seconds_by_source之和加reaction_reserve_seconds。'
            '整片后续必须规划到周姐收走未签纸笔出门、小林留坐且门关后的反应。只返回完整新计划，简洁按Schema。')
    r = rt.dispatch('whole_direction', wire('writer', rule, whole_input, whole_wire_schema(s), 7000),
                    lambda v: {'compiled_sha256': control.digest(compile_direction(v, s))})
    if r['status'] != 'contract_valid':
        return {'status': r['status'], 'stage': 'whole_direction', 'failure': r.get('failure')}
    direction = compile_direction(received_document(r), s)
    if direction['segments'][0]['source_refs'] != REFS:
        raise ValueError('first source scope changed; no patching')
    control.write(ROOT / 'WHOLE_DIRECTION_COMPILED.json', direction, True)
    rule = ('你是MiniMax表演导演。只为B1.S01–S02给完整当前演法，全文只作因果背景。'
            '演员对眼前对象采取行动并接收刺激，镜头看清小林听到通知的变化；用连贯活动、目的和潜台词，'
            '不写眉眼肩膝逐秒清单、不强制凝视、不给角色朗读创作说明。周姐移夹露纸指字抬眼可与原通知自然重叠，'
            '小林倾听，纸笔仍在周姐侧，尚未催签、看原因或推紙。正常普通话3.3字每秒，原通知完整说一次，'
            '末留自然接收窗口；不复写台词、不写后续对白和动作。身份环境参考图不继承旧起态。按Schema简洁完整返回。')
    inp = {**acting_input, 'whole_direction': direction, 'current_source_catalog': {q: contract.catalog(s)[q] for q in REFS}}
    control.write(ROOT / 'OPENING_PERFORMANCE_INPUT.json', inp, True)
    r = rt.dispatch('opening_performance', wire('writer', rule, inp, contract.opening_performance_schema(s, REFS), 3000),
                    lambda v: {'compiled_sha256': control.digest(contract.compile_opening_performance(v, s, REFS, user_trial_acceptance=True))})
    if r['status'] != 'contract_valid':
        return {'status': r['status'], 'stage': 'opening_performance', 'failure': r.get('failure')}
    compiled = contract.compile_opening_performance(received_document(r), s, REFS, user_trial_acceptance=True)
    prompt = contract.render_opening_prompt(compiled, s, actor_names=x['actor_names'])
    for n, v in [('OPENING_PERFORMANCE_COMPILED.json', compiled), ('FINAL_PROMPT.json', {'prompt': prompt})]:
        control.write(ROOT / n, v, True)
    inp = {**acting_input, 'whole_direction': direction, 'current_performance': received_document(r),
           'compiled_opening': compiled, 'actual_video_prompt': prompt}
    control.write(ROOT / 'PRODUCTION_TEXT_REVIEW_INPUT.json', inp, True)
    rule = ('你是DeepSeek独立制作文本审查。全文采用身份是当前487实际steps，先前自动验收失败必须保留，'
            '这次不把先前冻结brief的首次拒签/期限要求重写成通过，也不代写新剧情。只核对导演完整源覆盖、'
            '每段叙事用途与切镜、首段确实只含两个原steps、原通知说一次、当前动作起态与末态、动作对白自然重叠、'
            '正常语速承载和反应窗口、机位与观察对象、没有后续对白泄入。必要条件不成立fail，不能判断unknown。'
            '图是同人物环境身份参考，需要按当前剧本重建，不把旧纸朝下工牌在桌强行延续。简明给证据与必修，不声称视频通过。')
    schema = review_schema(s, direction)
    def validate_review(v):
        Draft202012Validator(schema).validate(v)
        return {'needs_revision': any(q['status'] != 'pass' for q in v['checks']) or bool(v['revision_requirements'])}
    r = rt.dispatch('production_text_review', wire('director', rule, inp, schema, 4500), validate_review)
    if r['status'] != 'contract_valid' or r['validation']['needs_revision']:
        return {'status': 'production_text_needs_attention', 'review_status': r['status'], 'media_calls': 0}
    control.write(ROOT / 'VIDEO_TEXT_HANDOFF.json', {'schema': 'selected_script_trial_handoff/v1',
                  'script_sha256': SOURCE_SHA, 'direction_sha256': control.digest(direction),
                  'performance_sha256': control.digest(compiled), 'prompt_sha256': control.digest(prompt),
                  'review_ordinal': r['ordinal'], 'current_source_refs': REFS,
                  'production_text_ready_for_single_trial': True, 'machine_script_quality_passed': False,
                  'human_trial_acceptance_recorded': True, 'whole_film_performance_complete': False,
                  'actual_video_quality_passed': False, 'first_video_only': True}, True)
    return {'status': 'production_text_ready_for_single_trial', 'duration_seconds': compiled['duration_seconds'],
            'media_calls': 0, **rt.summary()}


def validate_media_plan(plan):
    if (plan.get('schema') != 'selected_script_video_trial_plan/v1' or plan.get('logical_task_id') != LOGICAL
            or plan.get('segment_id') != SID or plan.get('source_refs') != REFS
            or plan.get('image_role') != 'reference_image' or plan.get('source_run') is not None):
        raise ValueError('one first trial in the same story budget required')
    a = plan['authorization']
    auth_required = {'max_new_video_submissions': 1, 'batch_authorized': False, 'automatic_retry': False,
                     'publishing_authorized': False, 'budget_reset': False,
                     'human_trial_acceptance_recorded': True, 'machine_script_quality_passed': False,
                     'source_script_edited': False}
    if any(type(a.get(k)) is not type(v) or a.get(k) != v for k, v in auth_required.items()):
        raise ValueError('no automatic repeat, batch or publication')
    required = {'new_submissions': 1, 'automatic_retry': False, 'budget_reset': False,
                'future_continuation_requires_current_human_approval': True,
                'generate_audio': True, 'return_last_frame': True, 'ratio': '9:16'}
    if any(type(plan.get(k)) is not type(v) or plan.get(k) != v for k, v in required.items()):
        raise ValueError('exact one-segment media and human review boundary required')
    if (plan.get('script_content_sha256') != a.get('script_sha256')
            or plan.get('script_content_sha256') != SOURCE_SHA):
        raise ValueError('exact selected native script identity required')
    if type(plan.get('duration_seconds')) is not int or not 4 <= plan['duration_seconds'] <= 15:
        raise ValueError('native duration must be integer four to fifteen seconds')
    if plan['machine_script_quality_passed'] is not False or plan['content_status_at_prepare'] != 'not_available':
        raise ValueError('old text or unseen media quality cannot be approved')
    verify_files({q['path']: q['sha256'] for q in plan['sources'].values()})
    if control.sha_file(plan['reference_image']['path']) != plan['reference_image']['sha256']:
        raise ValueError('selected original reference changed')
    if plan['model'] != MODEL or plan['provider'] != 'ark_api' or plan['resolution'] != '480p':
        raise ValueError('unverified model change')
    return plan


def build_request(client, plan):
    p = Path(plan['reference_image']['path'])
    image = SeedanceReference('image', f'data:{frame_mime(p)};base64,' + base64.b64encode(p.read_bytes()).decode(), 'reference_image')
    return client.build_task_payload(plan['prompt'], duration=plan['duration_seconds'], ratio='9:16',
                                    resolution='480p', generate_audio=True, return_last_frame=True,
                                    watermark=False, seed=20261011, references=[image], task_type='reference')


def make_media_plan():
    rt = runtime(); rt.check(control.read(rt.ledger))
    x = control.read(ROOT / 'INPUT.json'); h = control.read(ROOT / 'VIDEO_TEXT_HANDOFF.json')
    if not h['production_text_ready_for_single_trial'] or accepted('production_text_review')['validation']['needs_revision']:
        raise ValueError('unresolved current production text')
    c = contract.compile_opening_performance(received_document(accepted('opening_performance')), x['full_current_script'], REFS, user_trial_acceptance=True)
    prompt = contract.render_opening_prompt(c, x['full_current_script'], actor_names=x['actor_names'])
    if h['performance_sha256'] != control.digest(c) or h['prompt_sha256'] != control.digest(prompt):
        raise ValueError('native current handoff changed')
    files = [ROOT / n for n in ['INPUT.json', 'USER_SCOPE.json', 'ASSET_FEEDBACK.json', 'WHOLE_DIRECTION_COMPILED.json',
              'OPENING_PERFORMANCE_COMPILED.json', 'FINAL_PROMPT.json', 'VIDEO_TEXT_HANDOFF.json', 'CALL_LEDGER.json']]
    files += [Path(__file__).resolve(), PROJECT / 'src/content_factory/creative_video_trial_contract_v1.py',
              PROJECT / 'src/content_factory/creative_video_trial_direction_v2.py',
              ASSET / 'receipt.json', ASSET / 'receipt.human_review.json', Path(x['selected_asset_feedback']['path'])]
    return {'schema': 'selected_script_video_trial_plan/v1', 'logical_task_id': LOGICAL, 'segment_id': SID,
            'source_run': None, 'source_refs': REFS, 'script_content_sha256': SOURCE_SHA,
            'provider': 'ark_api', 'model': MODEL, 'resolution': '480p', 'ratio': '9:16',
            'duration_seconds': c['duration_seconds'], 'generate_audio': True, 'return_last_frame': True,
            'image_role': 'reference_image', 'reference_image': x['selected_asset_feedback'],
            'sources': {str(p): {'path': str(p), 'sha256': control.sha_file(p)} for p in files},
            'authorization': x['source_acceptance_scope'], 'prompt': prompt,
            'machine_script_quality_passed': False, 'content_status_at_prepare': 'not_available',
            'human_trial_acceptance_recorded': True, 'new_submissions': 1, 'automatic_retry': False,
            'future_continuation_requires_current_human_approval': True, 'budget_reset': False}


def media(operation):
    OUT.mkdir(parents=True, exist_ok=True); pp = OUT / 'PLAN.json'; rp = OUT / 'receipt.json'
    lock = OUT / '.execution.lock'
    with lock.open('x', encoding='utf-8') as f:
        f.write('one selected complete native script opening')
    try:
        with SeedanceClient(SeedanceConfig.from_env('ark_api', require_key=True)) as client:
            if client.config.model != MODEL:
                raise ValueError('configured video model differs')
            if operation == 'media_prepare':
                if rp.exists(): raise ValueError('existing original submission; query only')
                p = validate_media_plan(make_media_plan()); req = build_request(client, p)
                control.write(pp, p, True); control.write(OUT / 'REQUEST.preview.json', req, True)
                (OUT / 'PROMPT.txt').write_text(p['prompt'] + '\n', encoding='utf-8')
                return {'status': 'prepared', 'duration_seconds': p['duration_seconds'], 'new_paid_calls': 0}
            if operation == 'media_submit':
                if rp.exists(): raise ValueError('existing submission, never create again; query original ID')
                p = validate_media_plan(control.read(pp))
                if make_media_plan() != p: raise ValueError('current handoff changed')
                req = build_request(client, p)
                if req != control.read(OUT / 'REQUEST.preview.json'): raise ValueError('actual request changed')
                r = {'schema': 'selected_script_video_trial_receipt/v1', 'status': 'submitting',
                     'technical_status': 'running', 'content_status': 'not_available', 'logical_task_id': LOGICAL,
                     'segment_id': SID, 'model': MODEL, 'provider': 'ark_api', 'created_at': control.now(),
                     'plan_snapshot': p, 'plan': str(pp), 'plan_path': str(pp), 'plan_sha256': control.sha_file(pp),
                     'source_bindings': p['sources'], 'request': req,
                     'request_sha256': control.digest(req), 'new_submissions': 1, 'automatic_retry': False}
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
                if not r.get('task_id'): raise ValueError('original ID missing; reconcile, never resubmit')
            else: raise ValueError('explicit media operation required')
            if r.get('technical_status') == 'succeeded':
                verify_files({r['video_path']: r['video_sha256']})
                if r.get('last_frame'): verify_files({r['last_frame']: r['last_frame_sha256']})
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
                        if not tail.stat().st_size: raise ValueError('empty original provider tail')
                        r.update(last_frame=str(tail), last_frame_sha256=control.sha_file(tail), last_frame_source='generation_service_original', tail_status='saved_unapproved')
                    else: r.update(last_frame=None, tail_status='not_returned; continuation blocked')
                    r.update(human_decision=None, next_segment_dispatch_allowed=False, assistant_content_inspected=False,
                             completed_at=control.now())
                    mark_saved_candidate(r); persist(rp, r)
                except Exception as exc:
                    r.update(status='artifact_save_pending', failure_stage=stage, artifact_error=str(exc)); persist(rp, r); raise
            return {k: r.get(k) for k in ['technical_status', 'content_status', 'status', 'task_id', 'video_path', 'tail_status']}
    finally:
        lock.unlink()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(); parser.add_argument('operation', choices=['prepare', 'text', 'media_prepare', 'media_submit', 'media_query'])
    args = parser.parse_args()
    result = prepare() if args.operation == 'prepare' else text() if args.operation == 'text' else media(args.operation)
    print(json.dumps(result, ensure_ascii=False), flush=True)
