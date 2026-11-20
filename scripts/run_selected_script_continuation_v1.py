"""One human-approved native-tail continuation of the selected487 source.

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
from src.content_factory import creative_continuation_probe_contract_v1 as contract
from src.content_factory import creative_video_trial_contract_v1 as source_contract
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig, SeedanceReference
from src.content_factory.creative_legal_short_seedance_execution_v1 import reserve_media_attempt, frame_mime
from src.content_factory.media_review_policy import mark_saved_candidate, validate_approved_tail
from src.content_factory.creative_stage_contracts import persist
from scripts.run_legal_current_production_v10_20261010 import validate_saved_metadata

ROOT = PROJECT / 'data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v1'
OUT = PROJECT / 'data/video_generation/legal_script487_trial_20261011/second_v1'
PARENT = previous.ROOT
PREVIOUS_MEDIA = previous.OUT
MODEL, LOGICAL, SOURCE_SHA = previous.MODEL, previous.LOGICAL, previous.SOURCE_SHA
SID = 'SCRIPT487_MATERIAL02'
COMPLETED = ['B1.S01', 'B1.S02']
REFS = ['B1.S03', 'B1.S04']
REVIEW_CHECKS = ['current_direction_matches_source', 'exact_current_dialogue',
                 'initial_final_state', 'action_speech_timing',
                 'natural_acting_and_camera', 'future_isolation']


def approved_frame():
    rp = PREVIOUS_MEDIA / 'receipt.json'
    review_path = PREVIOUS_MEDIA / 'receipt.human_review.json'
    r = control.read(rp)
    if (r.get('segment_id') != previous.SID or r.get('logical_task_id') != LOGICAL
            or r.get('provider') != 'ark_api' or r.get('model') != MODEL
            or r.get('last_frame_source') != 'generation_service_original'
            or r.get('plan_snapshot', {}).get('script_content_sha256') != SOURCE_SHA
            or r.get('plan_snapshot', {}).get('source_refs') != COMPLETED):
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
        quota_state=None)


def prepare():
    if not (ROOT / 'ANCHOR.json').exists():
        ledger = control.read(PARENT / 'CALL_LEDGER.json')
        inherited, receipts = previous.inherited_known_parent(ledger, PARENT)
        if [r['ordinal'] for r in receipts] != [498] or receipts[0]['status'] != 'contract_valid':
            raise ValueError('exact complete498 review and inherited spend required')
        x = control.read(PARENT / 'INPUT.json')
        script = x['full_current_script']
        if control.digest(script) != SOURCE_SHA:
            raise ValueError('selected full source changed')
        contract.continuation_probe_schema(script, COMPLETED, REFS)
        tail = approved_frame()
        scope = {'schema': 'selected_source_single_continuation_scope/v1',
                 'user_statements': ['下一段', '首段通过，使用原始尾帧继续'],
                 'script_sha256': SOURCE_SHA, 'completed_source_refs': COMPLETED, 'source_refs': REFS,
                 'previous_segment_id': previous.SID, 'segment_id': SID,
                 'max_new_video_submissions': 1, 'batch_authorized': False,
                 'automatic_retry': False, 'publishing_authorized': False, 'budget_reset': False,
                 'source_script_edited': False, 'machine_script_quality_passed': False,
                 'whole_film_direction_accepted': False, 'subsequent_continuation_requires_human_approval': True}
        prior_performance = control.read(PARENT / 'OPENING_PERFORMANCE_COMPILED.json')['native']['performance']
        inp = {'full_current_script': deepcopy(script), 'script_sha256': SOURCE_SHA,
               'actor_names': x['actor_names'], 'scene_and_character_context': x['scene_and_character_context'],
               'reference_fulltext': x['reference_fulltext'], 'production_preferences': x['production_preferences'],
               'original_automatic_decision_retained': x['original_automatic_decision_retained'],
               'completed_source_refs': COMPLETED, 'current_source_refs': REFS,
               'current_source_catalog': {q: source_contract.catalog(script)[q] for q in REFS},
               'previous_planned_ending_state': prior_performance['ending_state'],
               'previous_state_is_text_not_assistant_visual_inspection': True,
               'approved_first_frame': tail, 'source_acceptance_scope': scope,
               'current_scope': '周姐请签申请，小林看清原因栏；不质问、不拒签、不推纸笔、不站起或离开'}
        for n, v in [('INPUT.json', inp), ('USER_SCOPE.json', scope), ('FIRST_FRAME.json', tail)]:
            control.write(ROOT / n, v, True)
        files = [PARENT / n for n in ['CALL_LEDGER.json', 'AUTHORIZATION.json', 'ANCHOR.json',
                 'INPUT.json', 'OPENING_PERFORMANCE_COMPILED.json', 'VIDEO_TEXT_HANDOFF.json']]
        files += [PARENT / row['receipt'] for row in ledger['calls']]
        files += [PREVIOUS_MEDIA / n for n in ['receipt.json', 'receipt.human_review.json', 'PLAN.json']]
        files += [Path(tail['path']), Path(control.read(PREVIOUS_MEDIA / 'receipt.json')['video_path'])]
        sources = [p for folder in [PROJECT / 'scripts', PROJECT / 'src'] for p in folder.rglob('*.py')]
        sources += [ROOT / n for n in ['INPUT.json', 'USER_SCOPE.json', 'FIRST_FRAME.json', 'ANCHOR.json']]
        control.write(ROOT / 'ANCHOR.json', {'inherited': inherited, 'models': ledger['model_configs'],
            'parent_files': {str(p): control.sha_file(p) for p in files},
            'runtime_sources': [p.relative_to(PROJECT).as_posix() for p in sources],
            'budget_reset': False, 'automatic_retry': False, 'whole_film_direction_accepted': False}, True)
    return runtime().prepare()


def wire(role, rule, value, schema, cap):
    r = {'role': role, 'model': runtime().models[role]['model'],
         'operator_version': 'selected_source_continuation/v1',
         'parameters': {'temperature': 0.4, 'thinking': 'disabled', 'max_completion_tokens': cap},
         'messages': [{'role': 'system', 'content': rule},
                      {'role': 'user', 'content': json.dumps(value, ensure_ascii=False)}],
         'structured_schema': schema}
    if role == 'writer':
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
    return {'type': 'object', 'additionalProperties': False,
            'required': ['script_sha256', 'checks', 'revision_requirements'],
            'properties': {'script_sha256': {'const': control.digest(script)},
             'checks': {'type': 'array', 'prefixItems': checks, 'items': False,
                        'minItems': len(checks), 'maxItems': len(checks)},
             'revision_requirements': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}}}


def text():
    prepare(); rt = runtime(); x = control.read(ROOT / 'INPUT.json'); script = x['full_current_script']
    # Writing receives current source only. Whole source remains in independent review.
    inp = {k: deepcopy(x[k]) for k in ['script_sha256', 'actor_names', 'reference_fulltext',
        'production_preferences', 'completed_source_refs', 'current_source_refs', 'current_source_catalog',
        'previous_planned_ending_state', 'approved_first_frame', 'current_scope']}
    inp['actor_and_space_context'] = {k: x['scene_and_character_context'][k] for k in ['characters', 'scenes']}
    inp.update(trial_route='isolated_continuation_probe', whole_film_direction_accepted=False,
               initial_continuity='同一小林周姐、同工牌服装空间和坐姿；纸笔还在周姐一侧，沿批准尾帧接着演，不重演公司通知')
    control.write(ROOT / 'CURRENT_PERFORMANCE_INPUT.json', inp, True)
    schema = contract.continuation_probe_schema(script, COMPLETED, REFS)
    r = rt.dispatch('continuation_performance', wire('writer',
        contract.RULE + '本次只处理B1.S03/B1.S04。先正常请签字，再让听者看清个人原因并接收矛盾；质问属于后段。'
        '不要添加递纸递笔动作，B4才推纸。不要为复位目光强制抬头再低头。当前方向与完整演法都提交原生全文。',
        inp, schema, 6000), lambda v: contract.compile_continuation_probe(v, script, COMPLETED, REFS))
    if r['status'] != 'contract_valid':
        return {'status': 'current_performance_needs_attention', 'media_calls': 0, **rt.summary()}
    native = previous.received_document(r)
    compiled = contract.compile_continuation_probe(native, script, COMPLETED, REFS)
    prompt = contract.render_prompt(compiled, script, actor_names=x['actor_names'])
    control.write(ROOT / 'CURRENT_DIRECTION_COMPILED.json', native['current_direction'], True)
    control.write(ROOT / 'PERFORMANCE_COMPILED.json', compiled, True)
    control.write(ROOT / 'FINAL_PROMPT.json', {'prompt': prompt}, True)
    inp_review = {**x, 'current_native_direction_and_performance': native,
                  'compiled_current_segment': compiled, 'actual_video_prompt': prompt}
    control.write(ROOT / 'PRODUCTION_TEXT_REVIEW_INPUT.json', inp_review, True)
    schema = review_schema(script)
    def validate(v):
        Draft202012Validator(schema).validate(v)
        return {'needs_revision': any(q['status'] != 'pass' for q in v['checks']) or bool(v['revision_requirements'])}
    review = rt.dispatch('production_text_review', wire('director',
        '独立审查当前第二段B1.S03-S04完整导演/演法/实际prompt，只判断当前段。'
        '完整原稿与批准尾帧元数据给出来源，助手未看媒体，不能推定像素质量。'
        '六项逐一有据判断：当前方向对应源文；原S03中文对白完整一次；沿上段末态、纸笔不提前推、工牌人物不重建；'
        'S04识别个人原因在邀请签字时/后自然出现，正常语速与反应时间足够；机位服务于认知和情绪、不拆机械微表情；'
        '没有后段质问、拒签、递纸、出门或对白泄入。源S04的目光方向不得成为无因抬头低头复位。'
        '不确定给unknown，有真实违反给fail与必修。不能因为整片导演未建就否定本次单段，也不能给整片或视频通过。',
        inp_review, schema, 4500), validate)
    if review['status'] != 'contract_valid' or review['validation']['needs_revision']:
        return {'status': 'production_text_needs_attention', 'media_calls': 0, **rt.summary()}
    control.write(ROOT / 'VIDEO_TEXT_HANDOFF.json', {
        'schema': 'selected_source_continuation_handoff/v1', 'script_sha256': SOURCE_SHA,
        'completed_source_refs': COMPLETED, 'current_source_refs': REFS,
        'writer_ordinal': r['ordinal'], 'review_ordinal': review['ordinal'],
        'performance_sha256': control.digest(compiled), 'prompt_sha256': control.digest(prompt),
        'production_text_ready_for_single_trial': True, 'whole_film_direction_accepted': False,
        'whole_film_performance_complete': False, 'machine_script_quality_passed': False,
        'previous_video_user_approved': True, 'actual_video_quality_passed': False,
        'trial_route': 'isolated_continuation_probe', 'max_new_video_submissions': 1}, True)
    return {'status': 'production_text_ready_for_single_continuation',
            'duration_seconds': compiled['performance_compiled']['duration_seconds'], **rt.summary()}


def make_plan():
    rt = runtime(); rt.check(control.read(rt.ledger))
    x = control.read(ROOT / 'INPUT.json'); h = control.read(ROOT / 'VIDEO_TEXT_HANDOFF.json')
    if accepted('production_text_review')['validation']['needs_revision']:
        raise ValueError('unresolved current review')
    c = contract.compile_continuation_probe(previous.received_document(accepted('continuation_performance')),
                                            x['full_current_script'], COMPLETED, REFS)
    prompt = contract.render_prompt(c, x['full_current_script'], actor_names=x['actor_names'])
    if (h['script_sha256'] != SOURCE_SHA or control.digest(x['full_current_script']) != SOURCE_SHA
            or control.read(ROOT / 'CURRENT_DIRECTION_COMPILED.json') != c['current_direction']
            or control.read(ROOT / 'PERFORMANCE_COMPILED.json') != c
            or control.read(ROOT / 'FINAL_PROMPT.json') != {'prompt': prompt}
            or h['performance_sha256'] != control.digest(c) or h['prompt_sha256'] != control.digest(prompt)
            or h['production_text_ready_for_single_trial'] is not True
            or h['completed_source_refs'] != COMPLETED or h['current_source_refs'] != REFS):
        raise ValueError('complete current native handoff changed')
    frame = approved_frame()
    if frame != x['approved_first_frame'] or frame != control.read(ROOT / 'FIRST_FRAME.json'):
        raise ValueError('approved adjacent tail changed')
    files = [ROOT / n for n in ['INPUT.json', 'USER_SCOPE.json', 'FIRST_FRAME.json',
        'CURRENT_DIRECTION_COMPILED.json', 'PERFORMANCE_COMPILED.json', 'FINAL_PROMPT.json',
        'VIDEO_TEXT_HANDOFF.json', 'CALL_LEDGER.json']]
    files += [Path(__file__).resolve(), PROJECT / 'src/content_factory/creative_continuation_probe_contract_v1.py',
              PROJECT / 'src/content_factory/creative_video_trial_contract_v1.py',
              PREVIOUS_MEDIA / 'receipt.json', PREVIOUS_MEDIA / 'receipt.human_review.json', Path(frame['path'])]
    return {'schema': 'selected_source_continuation_plan/v1', 'logical_task_id': LOGICAL,
        'segment_id': SID, 'source_run': None, 'script_content_sha256': SOURCE_SHA,
        'completed_source_refs': COMPLETED, 'source_refs': REFS, 'provider': 'ark_api', 'model': MODEL,
        'resolution': '480p', 'ratio': '9:16', 'duration_seconds': c['performance_compiled']['duration_seconds'],
        'generate_audio': True, 'return_last_frame': True, 'image_role': 'first_frame', 'first_frame': frame,
        'sources': {str(p): {'path': str(p), 'sha256': control.sha_file(p)} for p in files},
        'authorization': x['source_acceptance_scope'], 'prompt': prompt,
        'new_submissions': 1, 'automatic_retry': False, 'budget_reset': False,
        'future_continuation_requires_current_human_approval': True,
        'machine_script_quality_passed': False, 'whole_film_direction_accepted': False}


def validate_plan(p):
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
            or a['completed_source_refs'] != COMPLETED or a['previous_segment_id'] != previous.SID
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
