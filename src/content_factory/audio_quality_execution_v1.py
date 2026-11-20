"""Opt-in, one-edit audio-only trial bridge; never generate H3 or assemble.

The parent authorizes a reversible CPU trial, not acceptance of the movie.
Every edited version receives a new local-edit identity and its own inspection.
An incomplete processor/ASR claim is retained, never automatically retried.
"""
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from . import audio_full_scope_v1 as scope
from . import audio_quality_flow_v1 as flow
from . import audio_gap_repair_v1 as gap
from . import audio_repair_routing_v1 as routing
from . import h3_audio_conformance_v1 as conformance
from .visual_image_jobs_v3 import run_lock

VERSION = 'audio_quality_execution/v1'
INPUT = 'audio_quality_execution_input/v1'
AUTHORITY = 'audio_quality_execution_authority/v1'
_AUDIO_SCHEMAS = {
    VERSION, INPUT, AUTHORITY, 'audio_quality_execution_grant/v1',
    'audio_quality_flow/v1', 'audio_quality_flow_batch/v1',
    'audio_quality_processor_preparation/v1', 'audio_repair_routing_case/v1',
    'audio_repair_route/v1', 'audio_repair_processor_request/v1',
    'audio_gap_repair/v1', 'audio_gap_repair_spec/v1', 'audio_gap_repair_proof/v1',
    'media_repair_candidate/v1', 'media_repair_candidate_clock/v1',
    'media_repair_audio_result/v1', 'media_audio_derivation/v1',
    'local_audio_inspection/v1', 'local_audio_inspection_authority/v1',
    'local_audio_inspection_claim/v1', 'local_audio_inspection_process/v1',
    'local_audio_wave_header/v1', 'h3_audio_conformance/v1',
    'h3_audio_conformance_case/v1', 'h3_audio_transcript_receipt/v1',
    'h3_audio_user_confirmed_issue/v1', 'full_audio_inspection/v1',
    'local_video_transcript/v1', 'h3_continuity_input/v33',
    'media_visual_review/v1', 'h3_repair_visual_review/v1',
    'media_repair_capability/v1',
}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _inspector():
    from . import local_audio_inspector_v1
    return local_audio_inspector_v1


def _codes():
    return [scope.bind(p) for p in (Path(__file__),
        scope.PROJECT / 'scripts/run_audio_quality_execution_v1.py',
        Path(scope.__file__), Path(flow.__file__), Path(gap.__file__),
        Path(routing.__file__), Path(conformance.__file__), Path(_inspector().__file__))]


def _deep_check(value, seen=None):
    """Deep-check this audio protocol, not unrelated historical model graphs.

    Opaque asset/native records retain their exact file SHA. Their applicable
    media/clock fields are checked by the specific scope/processor validators.
    """
    seen = set() if seen is None else seen
    if isinstance(value, dict):
        if set(value) == {'path', 'sha256'}:
            key = (value['path'], value['sha256'])
            if key in seen:
                return
            path = scope.checked(value)
            seen.add(key)
            if path.suffix.lower() == '.json':
                record = json.loads(path.read_text(encoding='utf-8-sig'))
                if isinstance(record, dict) and record.get('schema') in _AUDIO_SCHEMAS:
                    _deep_check(record, seen)
        else:
            for child in value.values():
                _deep_check(child, seen)
    elif isinstance(value, list):
        for child in value:
            _deep_check(child, seen)


def _input(run, binding):
    value = scope.read(binding)
    require(value.get('schema') == INPUT and value.get('trial_scope') == 'audio_only_test',
            'explicit_audio_only_trial_required')
    required = ('source_candidate', 'source_case', 'asset_manifest', 'conformance_case',
                'conformance_report', 'full_audio_inspection', 'confirmation',
                'known_visual_review', 'authority')
    for key in required:
        scope.checked(value[key])
    require(value.get('allow_ambient_loss') is True, 'explicit_trial_ambient_loss_authority_required')
    require(isinstance(value.get('capabilities'), list) and value['capabilities'],
            'explicit_verified_processor_capability_required')
    for item in value['capabilities']:
        scope.checked(item)
    candidate = scope.read(value['source_candidate'])
    require(candidate.get('schema') == 'media_repair_candidate/v1'
            and candidate.get('completion_known') is True and candidate.get('outcome_unknown') is False,
            'known_completed_source_candidate_required')
    require(candidate.get('segment_id') == value.get('segment_id')
            and candidate.get('source_case') == value['source_case']
            and candidate.get('asset_manifest') == value['asset_manifest'],
            'source_candidate_case_assets_mismatch')
    require(scope.read(value['source_case']).get('schema') == 'h3_continuity_input/v33',
            'original_v33_source_case_required')
    require(not scope.checked(candidate['media']).is_relative_to(run),
            'source_media_must_stay_outside_trial')
    source_case = scope.read(value['conformance_case'])
    require(source_case.get('source_case') == value['source_case'], 'original_dialogue_source_changed')
    subject = {k: candidate[k] for k in ('segment_id', 'native_id', 'media')}
    require({k: source_case.get(k) for k in subject} == subject, 'source_conformance_subject_mismatch')
    full = scope.validate_bound(value['full_audio_inspection'])
    require(full.get('candidate') == value['source_candidate']
            and {k: full.get(k) for k in subject} == subject, 'source_full_scope_candidate_mismatch')
    visual_state = routing._visual(value['known_visual_review'], subject)
    auth = scope.read(value['authority'])
    require(auth.get('schema') == AUTHORITY and auth.get('trial_run') == str(run)
            and auth.get('trial_scope') == 'audio_only_test' and auth.get('confirmed_by') == 'user',
            'same_trial_parent_authority_required')
    for key in ('source_candidate', 'source_case', 'asset_manifest'):
        require(auth.get(key) == value[key], 'parent_source_authority_mismatch:' + key)
    require(all(type(auth.get(k)) is int and auth[k] == n for k, n in
                (('max_CPU_edits', 1), ('max_ASR_calls', 1), ('max_H3_calls', 0)))
            and auth.get('allow_ambient_loss') is True and auth.get('assembly_allowed') is False,
            'one_CPU_edit_one_ASR_zero_H3_no_assembly_authority_required')
    settings = value['inspector']
    require(scope.local(settings['model_root']).is_dir(), 'existing_local_ASR_model_directory_required')
    require(scope.checked(settings['transcriber']) == scope.PROJECT / 'scripts/transcribe_video_local.py',
            'pinned_current_local_transcriber_required')
    require(type(settings.get('timeout_seconds')) is int and 0 < settings['timeout_seconds'] <= 3600,
            'bounded_ASR_timeout_required')
    _deep_check(value)
    return value, candidate, visual_state


def prepare(run, input_binding):
    run = scope.local(run)
    run.mkdir(parents=True, exist_ok=True)
    with run_lock(run, 'AUDIO_QUALITY_EXECUTION.lock'):
        value, source, visual = _input(run, input_binding)
        case = dict(schema=routing.CASE_SCHEMA, **{k: source[k] for k in
            ('segment_id', 'native_id', 'media')}, conformance_case=value['conformance_case'],
            conformance_report=value['conformance_report'], full_audio_inspection=value['full_audio_inspection'],
            confirmation=value['confirmation'], capabilities=value['capabilities'], allow_ambient_loss=True,
            trial_scope='audio_only_test', visual_assessment_excluded_for_audio_trial=True,
            known_visual_review_retained_externally=value['known_visual_review'])
        case_binding = flow.freeze(run / 'source_route/CASE.json', case)
        batch = flow.freeze(run / 'source_route/BATCH.json', dict(schema='audio_quality_flow_batch/v1',
            segments=[dict(**{k: source[k] for k in ('segment_id', 'native_id', 'media')}, case=case_binding)]))
        routed = flow.prepare_batch(run / 'source_route/flow', batch)
        plan = dict(schema=VERSION, input=input_binding, input_digest=_digest(value), code=_codes(),
            parent_authority=value['authority'], source_candidate=value['source_candidate'],
            source_route_plan=routed['plan'], known_visual_review=value['known_visual_review'],
            known_visual_state=visual, trial_scope='audio_only_test',
            max_CPU_edits=1, max_ASR_calls=1, max_H3_calls=0, overall_video_quality_passed=False,
            visual_acceptance_upgraded=False, assembly_allowed=False, automatic_publication=False)
        return dict(status='prepared_audio_only_trial', plan=flow.freeze(run / 'PLAN.json', plan),
                    source_audio_route=routed['routes'][0]['route'], media_execution_performed=False)


def _load(run):
    run = scope.local(run)
    plan = json.loads((run / 'PLAN.json').read_text(encoding='utf-8-sig'))
    require(plan.get('schema') == VERSION and plan.get('code') == _codes(), 'frozen_execution_code_changed')
    value, source, visual = _input(run, plan['input'])
    require(plan['input_digest'] == _digest(value) and plan['parent_authority'] == value['authority']
            and plan['source_candidate'] == value['source_candidate']
            and plan['known_visual_review'] == value['known_visual_review']
            and plan['known_visual_state'] == visual and plan.get('overall_video_quality_passed') is False
            and plan.get('assembly_allowed') is False, 'frozen_execution_plan_changed')
    require(plan['source_route_plan'] == scope.bind(run / 'source_route/flow/PLAN.json'),
            'source_route_plan_binding_changed')
    routed = flow.status(run / 'source_route/flow')
    _deep_check(plan)
    return run, plan, value, source, routed


def _edited_candidate(run, plan, value, source, prepared, repaired):
    processor_plan = prepared['prepared']['plan']
    processor_run = scope.checked(processor_plan).parent
    verified = gap.qa(processor_run)
    require(verified['file'] == repaired['file'] and verified['receipt'] == repaired['receipt']
            and verified['proof'] == repaired['proof'], 'processor_saved_QA_binding_changed')
    details = scope.read(processor_plan)['details']
    proof = scope.read(repaired['proof'])
    require(details['media'] == source['media'] and proof.get('input') == source['media']
            and proof.get('output') == repaired['file'] and proof.get('video_streamcopy') is True
            and proof.get('video_frames_PTS_and_decoded_hashes_unchanged') is True
            and proof.get('duration_or_story_cut_performed') is False,
            'verified_duration_and_video_preserving_CPU_result_required')
    clock = details['frame_clock']
    samples = Fraction(clock['frames'], clock['fps']) * 48000
    pcm = scope.checked(proof['final_decoded_PCM'])
    require(samples.denominator == 1 and samples > 0 and pcm.stat().st_size == int(samples) * 4,
            'actual_48k_stereo_normalized_PCM_sample_count_mismatch')
    local_id = 'local-audio-edit-' + _digest(dict(source=source['native_id'],
        processor_plan=processor_plan, output=repaired['file']))[:24]
    result = flow.freeze(run / 'edited/RESULT.json', dict(schema='media_repair_audio_result/v1',
        native_id=local_id, source_native_id=source['native_id'], segment_id=value['segment_id'],
        media=repaired['file'], files=dict(video=repaired['file']), operation='cleanup_gap',
        source_candidate=value['source_candidate'], source_case=value['source_case'], asset_manifest=value['asset_manifest'],
        processor_plan=processor_plan, processor_result=repaired['receipt'], processor_proof=repaired['proof'],
        H3_generation_performed=False, overall_video_quality_passed=False))
    clock_receipt = flow.freeze(run / 'edited/CLOCK.json', dict(schema='media_repair_candidate_clock/v1',
        native_id=local_id, media=repaired['file'], result=result, nominal_frame_clock=clock,
        normalization_verified=True, content_trimmed=False,
        native_audio_clock=dict(rate=48000, samples=int(samples), media=proof['final_decoded_PCM']),
        native_audio_clock_basis='normalized_decoded_PCM_not_container_raw_samples',
        delivery_clock=dict(rate=48000, samples=int(samples)),
        codec_output_normalization=proof['output_normalization'],
        evidence=[processor_plan, repaired['receipt'], repaired['proof'], proof['final_decoded_PCM'],
                  proof['source_framehash'], proof['output_framehash']]))
    candidate = flow.freeze(run / 'edited/CANDIDATE.json', dict(schema='media_repair_candidate/v1',
        attempt_id='AUDIO_EDIT_001', segment_id=value['segment_id'], native_id=local_id,
        result=result, media=repaired['file'], source_case=value['source_case'], asset_manifest=value['asset_manifest'],
        nominal_frame_clock=clock, native_audio_clock=scope.read(clock_receipt)['native_audio_clock'],
        native_audio_clock_basis='normalized_decoded_PCM_not_container_raw_samples',
        delivery_clock=dict(rate=48000, samples=int(samples)), audio_clock_receipt=clock_receipt,
        completion_known=True, outcome_unknown=False, generation_kind='local_CPU_audio_edit', H3_generation_performed=False))
    derivation = flow.freeze(run / 'edited/DERIVATION.json', dict(schema='media_audio_derivation/v1',
        source_candidate=value['source_candidate'], source_case=value['source_case'], asset_manifest=value['asset_manifest'],
        source_native_id=source['native_id'], source_media=source['media'], native_id=local_id, media=repaired['file'],
        operation='cleanup_gap', processor_plan=processor_plan, processor_result=repaired['receipt'],
        processor_proof=repaired['proof'], parent_authority=value['authority'],
        evidence=[processor_plan, repaired['receipt'], repaired['proof']]))
    authority = flow.freeze(run / 'inspection/AUTHORITY.json', dict(schema='local_audio_inspection_authority/v1',
        candidate=candidate, source_full_audio_inspection=value['full_audio_inspection'], derivation=derivation,
        parent_authority=value['authority'], issued_by='audio_quality_execution_v1',
        confirmed_by='parent_authority_delegation', max_ASR_calls=1, **value['inspector']))
    return candidate, authority


def _grant(run, plan, value, source, processor_plan, *, writing):
    """Separate trial execution authority; leave the planning request untouched."""
    grant = dict(schema='audio_quality_execution_grant/v1', parent_authority=value['authority'],
        execution_plan=scope.bind(run / 'PLAN.json'), input=plan['input'],
        prepared_processor_plan=processor_plan, processor_module=scope.bind(gap.__file__),
        source_candidate=value['source_candidate'], source_media=source['media'],
        trial_scope='audio_only_test', max_CPU_edits=1, max_ASR_calls=1, max_H3_calls=0,
        assembly_allowed=False, planning_request_is_not_execution_authority=True)
    if writing:
        return flow.freeze(run / 'EXECUTION_GRANT.json', grant)
    binding = scope.bind(run / 'EXECUTION_GRANT.json')
    require(scope.read(binding) == grant, 'trial_execution_grant_changed')
    return binding


def _finalize(run, plan, value, candidate_binding, inspected):
    candidate = scope.read(candidate_binding)
    full = scope.validate_bound(inspected['full_audio_inspection'])
    require(full['candidate'] == candidate_binding and full['asr_receipt'] == inspected['asr_receipt'],
            'fresh_full_scope_not_same_edited_candidate')
    require(scope.read(inspected['asr_receipt'])['media'] == candidate['media']
            and candidate['media'] != scope.read(value['source_candidate'])['media'],
            'new_media_requires_its_own_full_ASR')
    case = flow.freeze(run / 'fresh/CONFORMANCE_CASE.json', dict(schema=conformance.CASE_SCHEMA,
        **{k: candidate[k] for k in ('attempt_id', 'segment_id', 'native_id', 'media')},
        source_case=value['source_case'], asr_receipt=inspected['asr_receipt']))
    report = flow.freeze(run / 'fresh/CONFORMANCE_REPORT.json', conformance.evaluate_bound(case))
    route_case = flow.freeze(run / 'fresh/ROUTING_CASE.json', dict(schema=routing.CASE_SCHEMA,
        **{k: candidate[k] for k in ('segment_id', 'native_id', 'media')}, conformance_case=case,
        conformance_report=report, full_audio_inspection=inspected['full_audio_inspection'],
        capabilities=[], allow_ambient_loss=False, trial_scope='audio_only_test',
        visual_assessment_excluded_for_audio_trial=True,
        known_source_visual_review_retained_externally=value['known_visual_review']))
    decision = routing.evaluate_bound(route_case)
    decision_binding = flow.freeze(run / 'fresh/ROUTE.json', decision)
    result = dict(schema=VERSION, status='audio_only_trial_completed', plan=scope.bind(run / 'PLAN.json'),
        execution_grant=scope.bind(run / 'EXECUTION_GRANT.json'),
        candidate=candidate_binding, inspection=inspected, conformance_case=case, conformance_report=report,
        routing_case=route_case, routing_decision=decision_binding, audio_route=decision['route'],
        audio_text_conformance_accepted=decision['route'] == 'accept',
        source_confirmation_not_inherited_by_fresh_candidate=True,
        source_confirmation=value['confirmation'], actual_extra_words_or_language_confirmed=False,
        known_visual_review=value['known_visual_review'], known_visual_state=plan['known_visual_state'],
        trial_scope='audio_only_test', ambient_loss_authorized_for_this_trial_only=True,
        overall_video_quality_passed=False, visual_acceptance_upgraded=False,
        voice_identity_verified=False, human_listening_performed=False,
        assembly_performed=False, new_H3_calls=0, new_ASR_limit=1, CPU_edit_limit=1,
        limitations=['Audio text/scope and CPU clocks only; source visual findings remain applicable.',
                    'ASR does not verify every sound, voice identity, age or human listening quality.',
                    'The confirmed gap attenuation also removes mixed ambience inside its bounded envelope.'])
    binding = flow.freeze(run / 'RESULT.json', result)
    return dict(status=result['status'], result=binding, audio_route=result['audio_route'],
                overall_video_quality_passed=False, assembly_performed=False)


def _cached(run, plan, value):
    result_binding = scope.bind(run / 'RESULT.json')
    result = scope.read(result_binding)
    require(result.get('schema') == VERSION and result.get('plan') == scope.bind(run / 'PLAN.json')
            and result.get('overall_video_quality_passed') is False
            and result.get('known_visual_review') == value['known_visual_review']
            and result.get('known_visual_state') == plan['known_visual_state']
            and result.get('assembly_performed') is False, 'cached_trial_result_changed')
    _deep_check(result)
    inspected = _inspector().verify(run / 'inspection')
    require(inspected == result['inspection'], 'cached_inspection_receipt_changed')
    require(result['candidate'] == scope.bind(run / 'edited/CANDIDATE.json')
            and scope.read(inspected['full_audio_inspection'])['candidate'] == result['candidate'],
            'cached_trial_candidate_subject_changed')
    decision = routing.evaluate_bound(result['routing_case'])
    require(scope.read(result['conformance_report']) == conformance.evaluate_bound(result['conformance_case'])
            and scope.read(result['routing_decision']) == decision
            and result['audio_route'] == decision['route']
            and result['audio_text_conformance_accepted'] == (decision['route'] == 'accept'),
            'cached_fresh_audio_decision_changed')
    processor_plan = scope.read(scope.read(result['candidate'])['result'])['processor_plan']
    source = scope.read(value['source_candidate'])
    require(result['execution_grant'] == _grant(run, plan, value, source, processor_plan, writing=False),
            'cached_execution_grant_mismatch')
    gap.qa(scope.checked(processor_plan).parent)
    return dict(status=result['status'], result=result_binding, audio_route=result['audio_route'],
                overall_video_quality_passed=False, assembly_performed=False, no_dispatch_on_reentry=True)


def execute(run):
    run = scope.local(run)
    with run_lock(run, 'AUDIO_QUALITY_EXECUTION.lock'):
        run, plan, value, source, routed = _load(run)
        if (run / 'RESULT.json').exists():
            return _cached(run, plan, value)
        decision = routed['segments'][0]['evaluation']
        if decision['route'] != 'cleanup_gap':
            return dict(status='source_audio_route_not_executable', route=decision['route'],
                        desired_route=decision.get('desired_route'), media_execution_performed=False,
                        overall_video_quality_passed=False)
        prepared = flow.prepare_cleanup(run / 'source_route/flow', value['segment_id'])
        processor_run = scope.checked(prepared['prepared']['plan']).parent
        _grant(run, plan, value, source, prepared['prepared']['plan'], writing=True)
        # The processor itself owns the only edit claim. Completed reentry is read-only.
        repaired = gap.qa(processor_run) if (processor_run / 'RESULT.json').exists() else gap.execute(processor_run)
        if repaired.get('status') == 'outcome_unknown':
            return dict(status='CPU_edit_outcome_unknown', processor=repaired, automatic_retry=False,
                        overall_video_quality_passed=False)
        candidate, authority = _edited_candidate(run, plan, value, source, prepared, repaired)
        inspected = _inspector().inspect(run / 'inspection', candidate, authority)
        if inspected.get('status') != 'saved':
            return dict(status='ASR_outcome_unknown', inspection=inspected, automatic_retry=False,
                        overall_video_quality_passed=False)
        return _finalize(run, plan, value, candidate, inspected)


def status(run):
    """Validate cached evidence without invoking edit, inspection or recognition."""
    run, plan, value, _, routed = _load(run)
    if (run / 'RESULT.json').exists():
        return _cached(run, plan, value)
    return dict(status='audio_only_trial_pending', plan=scope.bind(run / 'PLAN.json'),
        source_audio_route=routed['segments'][0]['evaluation']['route'],
        CPU_edit_claim_exists=(run / 'source_route/flow/processors/segment_0/prepared/EXECUTE_CLAIM.json').exists(),
        ASR_claim_exists=(run / 'inspection/ASR_CLAIM.json').exists(),
        overall_video_quality_passed=False, no_dispatch_performed=True)
