"""Bounded, evidence-bound media repair controller; transports are injected.

This module has no model/ASR/HTTP implementation. The executable CLI loads only
explicitly SHA-pinned local adapter factories. An accepted *fresh* audit is the
only route to version selection. Duration/content trimming is never a repair.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import traceback

from .visual_image_jobs_v3 import run_lock

VERSION = 'media_repair_loop/v1'
SPEC = 'media_repair_loop_spec/v1'
PROJECT = Path(__file__).resolve().parents[2]
DECISIONS = ('accept', 'reject', 'needs_review')
TERMINAL = ('complete', 'needs_review', 'attempts_exhausted', 'outcome_unknown')

# The public wire contract lives beside its executable validator. Adapter
# authors use these literal names; no example placeholders are model prompts.
SPEC_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'title': SPEC, 'type': 'object',
    'required': ['schema', 'case_binding', 'asset_manifest', 'evidence', 'authorization',
                 'segments', 'repair_segment_id', 'max_attempts', 'mode',
                 'require_fresh_candidate', 'regenerate_on', 'adapters'],
    'properties': {
        'schema': {'const': SPEC}, 'mode': {'enum': ['regen_segment', 'audio_repair']},
        'adapter_context': {'type': 'object', 'required': ['path', 'sha256'], 'additionalProperties': False,
                            'properties': {'path': {'type': 'string'}, 'sha256': {'type': 'string'}}},
        'max_attempts': {'type': 'integer', 'minimum': 1, 'maximum': 2},
        'require_fresh_candidate': {'const': True},
        'regenerate_on': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
                          'items': {'enum': ['reject', 'needs_review']}},
        'segments': {'type': 'array', 'minItems': 1, 'items': {'type': 'object',
                     'required': ['id', 'native_id', 'result', 'media', 'source_case',
                                  'asset_manifest', 'frames', 'fps', 'audio_rate', 'audio_samples']}},
        'adapters': {'type': 'object', 'required': ['executor', 'auditor', 'assembler'],
                     'additionalProperties': False,
                     'properties': {role: {'type': 'object', 'required': ['module', 'factory']}
                                    for role in ('executor', 'auditor', 'assembler')}},
    },
}
WIRE_FIELDS = {
    'request': ['schema', 'run', 'spec', 'attempt_id', 'attempt_dir', 'segment_id', 'phase',
                'mode', 'original', 'case_binding', 'asset_manifest', 'evidence', 'authorization', 'candidate'],
    'candidate': ['schema', 'attempt_id', 'segment_id', 'native_id', 'result', 'media',
                  'source_case', 'asset_manifest', 'nominal_frame_clock', 'native_audio_clock',
                  'delivery_clock', 'audio_clock_receipt',
                  'completion_known', 'outcome_unknown'],
    'audit': ['schema', 'attempt_id', 'segment_id', 'native_id', 'candidate_result', 'candidate_media',
              'case_binding', 'asset_manifest', 'fresh_detection', 'decision', 'evidence', 'findings', 'detector_receipt'],
    'assembly_receipt': ['schema', 'selection', 'file', 'clock', 'completion_known', 'outcome_unknown'],
}
CANDIDATE_SCHEMA = {
    'title': 'media_repair_candidate/v1', 'type': 'object',
    'required': WIRE_FIELDS['candidate'],
    'properties': {
        'schema': {'const': 'media_repair_candidate/v1'},
        'nominal_frame_clock': {'type': 'object', 'required': ['frames', 'fps'], 'additionalProperties': False,
                                'properties': {k: {'type': 'integer', 'minimum': 1} for k in ('frames', 'fps')}},
        'native_audio_clock': {'type': 'object', 'required': ['rate', 'samples', 'media'],
                               'additionalProperties': False,
                               'properties': {'rate': {'type': 'integer', 'minimum': 1},
                                              'samples': {'type': 'integer', 'minimum': 1}, 'media': {'type': 'object'}}},
        'delivery_clock': {'type': 'object', 'required': ['rate', 'samples'], 'additionalProperties': False,
                            'properties': {k: {'type': 'integer', 'minimum': 1} for k in ('rate', 'samples')}},
    },
}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def path(value):
    p = Path(value)
    require(p.is_absolute() and '://' not in str(value), 'absolute_local_path_required')
    p = p.resolve()
    require(p.is_relative_to(PROJECT.resolve()), 'local_path_outside_project')
    return p


def bind(value):
    p = path(value)
    with p.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(path=str(p), sha256=sha)


def checked(value):
    require(isinstance(value, dict) and set(value) == {'path', 'sha256'}, 'exact_file_binding_required')
    p = path(value['path'])
    require(bind(p) == value, 'bound_file_changed')
    return p


def read(value):
    return json.loads(path(value).read_text(encoding='utf-8-sig'))


def freeze(run, relative, value):
    run = path(run); dest = (run / relative).resolve()
    require(dest.is_relative_to(run) and dest != run, 'write_outside_repair_run')
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        require(digest(read(dest)) == digest(value), 'immutable_repair_evidence_changed')
    else:
        with dest.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    return bind(dest)


def _clock(rows):
    require(isinstance(rows, list) and rows, 'ordered_original_segments_required')
    fps, rate = rows[0]['fps'], rows[0]['audio_rate']
    require(type(fps) is int and type(rate) is int and fps > 0 and rate > 0, 'integral_clock_profile_required')
    require(len(set(r['id'] for r in rows)) == len(rows), 'unique_segment_ids_required')
    for row in rows:
        require(type(row['frames']) is int and row['frames'] > 0
                and type(row['fps']) is int and row['fps'] == fps
                and type(row['audio_rate']) is int and row['audio_rate'] == rate
                and type(row['audio_samples']) is int
                and Fraction(row['frames'], fps) * rate == row['audio_samples'],
                'preserved_frame_sample_clock_required')
    return dict(frames=sum(r['frames'] for r in rows), fps=fps, audio_rate=rate,
                audio_samples=sum(r['audio_samples'] for r in rows),
                seconds=str(Fraction(sum(r['frames'] for r in rows), fps)))


def validate_spec(value):
    require(value.get('schema') == SPEC and value.get('mode') in ('regen_segment', 'audio_repair'), 'supported_repair_spec_required')
    budget = value.get('max_attempts')
    require(type(budget) is int and 1 <= budget <= 2, 'bounded_one_or_two_attempts_required')
    auth = read(checked(value['authorization']))
    limit = auth.get('max_attempts', auth.get('scope', {}).get('max_attempts'))
    require(type(limit) is int and budget <= limit <= 2, 'attempt_budget_exceeds_bound_authority')
    for item in (value['case_binding'], value['asset_manifest'], *value.get('evidence', [])):
        checked(item)
    if 'adapter_context' in value:
        checked(value['adapter_context'])
    require(isinstance(value.get('evidence'), list) and value['evidence'], 'bound_defect_evidence_required')
    rows = value.get('segments')
    _clock(rows)
    require(len({r['native_id'] for r in rows}) == len(rows), 'distinct_original_native_ids_required')
    for row in rows:
        for key in ('result', 'media', 'source_case', 'asset_manifest'):
            checked(row[key])
    require(sum(r['id'] == value.get('repair_segment_id') for r in rows) == 1, 'one_existing_segment_to_repair_required')
    require(value.get('require_fresh_candidate') is True, 'fresh_regeneration_required_for_this_repair_controller')
    allowed = value.get('regenerate_on', ['reject'])
    require(isinstance(allowed, list) and allowed and set(allowed) <= {'reject', 'needs_review'}
            and len(set(allowed)) == len(allowed), 'explicit_repair_decisions_required')
    adapters = value.get('adapters')
    require(isinstance(adapters, dict) and set(adapters) == {'executor', 'auditor', 'assembler'}, 'three_explicit_adapter_factories_required')
    for adapter in adapters.values():
        checked(adapter['module'])
        require(isinstance(adapter.get('factory'), str) and adapter['factory'].isidentifier(), 'named_adapter_factory_required')
    if value['mode'] == 'audio_repair':
        capability = read(checked(value['capability_receipt']))
        require(capability.get('schema') == 'media_repair_capability/v1'
                and capability.get('capability') == 'audio_repair' and capability.get('verified') is True
                and capability.get('preserves_video_and_duration') is True
                and capability.get('executor_module') == adapters['executor']['module'],
                'verified_bound_audio_repair_capability_required')
        require(isinstance(capability.get('evidence'), list) and capability['evidence'], 'capability_evidence_required')
        for item in capability['evidence']:
            checked(item)
    return deepcopy(value)


def prepare(run, spec_binding):
    run = path(run); run.mkdir(parents=True, exist_ok=True)
    with run_lock(run, 'REPAIR_LOOP.lock'):
        value = validate_spec(read(checked(spec_binding)))
        require(not any(path(r[k]['path']).is_relative_to(run) for r in value['segments'] for k in ('result', 'media')),
                'originals_must_be_outside_new_repair_run')
        plan = dict(schema=VERSION, spec=spec_binding, spec_digest=digest(value),
                    authority=value['authorization'], max_attempts=value['max_attempts'],
                    original_clock=_clock(value['segments']), controller=bind(__file__),
                    original_files_modified=False, trim_or_shorten_allowed=False,
                    automatic_publication=False, service_changes=False)
        plan_binding = freeze(run, 'PLAN.json', plan)
        return dict(status='prepared', plan=plan_binding, clock=plan['original_clock'])


def _load(run):
    run = path(run); plan = read(run/'PLAN.json')
    require(plan.get('schema') == VERSION and plan.get('controller') == bind(__file__), 'frozen_controller_changed')
    value = validate_spec(read(checked(plan['spec'])))
    require(plan['spec_digest'] == digest(value) and plan['authority'] == value['authorization']
            and plan['max_attempts'] == value['max_attempts'] and plan['original_clock'] == _clock(value['segments']),
            'plan_must_match_frozen_spec_and_budget')
    return run, plan, value


def load_adapters(run):
    """Pinned code only; imports do not themselves authorize a production call."""
    _, _, spec = _load(run)
    values = {}
    for role, adapter in spec['adapters'].items():
        source = checked(adapter['module'])
        module_spec = importlib.util.spec_from_file_location('_repair_adapter_'+role+'_'+adapter['module']['sha256'][:12], source)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        factory = getattr(module, adapter['factory'])
        values[role] = factory(deepcopy(spec))
    return values


def _original(spec):
    return next(deepcopy(row) for row in spec['segments'] if row['id'] == spec['repair_segment_id'])


def _request(run, plan, spec, attempt_id, phase, candidate=None):
    return dict(schema='media_repair_request/v1', run=str(run), spec=plan['spec'],
                attempt_id=attempt_id, attempt_dir=str(run/'attempts'/attempt_id),
                segment_id=spec['repair_segment_id'], phase=phase, mode=spec['mode'],
                original=_original(spec), case_binding=spec['case_binding'],
                asset_manifest=spec['asset_manifest'], evidence=spec['evidence'],
                authorization=spec['authorization'], candidate=deepcopy(candidate))


def _notice(run, name, status, reason, **extra):
    dest = path(run)/name
    if dest.exists():
        prior = read(dest)
        require(prior.get('schema') == VERSION and prior.get('status') == status, 'notice_status_changed')
        return dict(prior, notice=bind(dest))
    item = dict(schema=VERSION, status=status, reason=reason, automatic_retry=False,
                original_files_preserved=True, **extra)
    binding = freeze(run, name, item)
    return dict(item, notice=binding)


def _candidate(value, request, native_id, original_ids):
    if isinstance(value, dict) and set(value) == {'path', 'sha256'}:
        value = read(checked(value))
    require(isinstance(value, dict) and value.get('schema') == 'media_repair_candidate/v1', 'explicit_fresh_candidate_required')
    require(value.get('attempt_id') == request['attempt_id'] and value.get('segment_id') == request['segment_id']
            and value.get('native_id') == native_id and native_id not in original_ids
            and value.get('completion_known') is True and value.get('outcome_unknown') is False,
            'fresh_candidate_identity_or_completion_mismatch')
    require(value.get('source_case') == request['case_binding'] and value.get('asset_manifest') == request['asset_manifest'],
            'fresh_candidate_case_or_assets_changed')
    raw = read(checked(value['result'])); checked(value['media'])
    require(raw.get('prompt_id', raw.get('native_id')) == native_id, 'native_result_identity_mismatch')
    if request['mode'] == 'regen_segment':
        require(raw.get('technical_status') in ('technical_saved', 'saved')
                and raw.get('files', {}).get('video', {}).get('sha256') == value['media']['sha256'],
                'saved_native_result_must_bind_candidate_video')
    else:
        require(raw.get('schema') == 'media_repair_audio_result/v1' and raw.get('media') == value['media'],
                'audio_repair_result_must_bind_candidate')
    original = request['original']
    nominal = value.get('nominal_frame_clock', {})
    native = value.get('native_audio_clock', {})
    delivery = value.get('delivery_clock', {})
    require(not set(value) & {'frames', 'fps', 'audio_rate', 'audio_samples'}, 'use_three_distinct_clock_namespaces')
    require(set(nominal) == {'frames', 'fps'}
            and all(type(nominal.get(k)) is int and nominal[k] == original[k] for k in ('frames', 'fps')),
            'candidate_must_not_cut_or_shorten_content_clock')
    require(set(native) == {'rate', 'samples', 'media'} and
            all(type(native.get(k)) is int and native[k] > 0 for k in ('rate', 'samples')),
            'actual_native_audio_clock_required')
    require(delivery == {'rate': original['audio_rate'], 'samples': original['audio_samples']}
            and all(type(delivery.get(k)) is int for k in ('rate', 'samples')), 'delivery_audio_target_changed')
    proof = read(checked(value['audio_clock_receipt']))
    require(proof.get('schema') == 'media_repair_candidate_clock/v1'
            and proof.get('native_id') == native_id and proof.get('media') == value['media']
            and proof.get('result') == value['result'] and proof.get('nominal_frame_clock') == nominal
            and proof.get('native_audio_clock') == native and proof.get('delivery_clock') == delivery
            and proof.get('normalization_verified') is True and proof.get('content_trimmed') is False,
            'native_audio_normalization_subject_or_target_changed')
    require(abs(Fraction(native['samples'], native['rate']) - Fraction(nominal['frames'], nominal['fps'])) <= Fraction(1, 4),
            'native_audio_duration_requires_real_repair_not_normalization')
    checked(native['media'])
    require(isinstance(proof.get('evidence'), list) and proof['evidence'], 'actual_clock_normalization_evidence_required')
    for item in proof['evidence']:
        checked(item)
    if request['mode'] == 'regen_segment':
        require(raw.get('files', {}).get('audio', {}).get('sha256') == native['media']['sha256'],
                'normalization_audio_must_be_native_original')
    return deepcopy(value)


def _audit(run, relative, request, auditor):
    result_file = run/relative/'AUDIT.json'
    if result_file.exists():
        binding = read(result_file)['audit']
    else:
        claim_file = run/relative/'DETECTION_CLAIM.json'
        if claim_file.exists():
            return _notice(run, str(Path(relative)/'UNKNOWN.json'), 'outcome_unknown', 'detection_claim_has_no_known_result')
        freeze(run, str(Path(relative)/'DETECTION_CLAIM.json'), request)
        try:
            binding = auditor.detect(deepcopy(request))
            checked(binding)
            freeze(run, str(Path(relative)/'AUDIT.json'), dict(audit=binding, request_sha256=digest(request)))
        except Exception as error:
            freeze(run, str(Path(relative)/'ERROR.json'), dict(error=str(error), traceback=traceback.format_exc()))
            return _notice(run, str(Path(relative)/'UNKNOWN.json'), 'outcome_unknown', 'detector_failed_or_returned_unknown')
    saved = read(result_file)
    require(saved['request_sha256'] == digest(request), 'detection_request_changed')
    return _validated_audit(binding, request)


def _validated_audit(binding, request):
    """Pure read validation, also used by completed-cache reentry."""
    audit = read(checked(binding)); c = request['candidate']
    require(audit.get('schema') == 'media_repair_audit/v1' and audit.get('decision') in DECISIONS
            and audit.get('fresh_detection') is True and audit.get('attempt_id') == request['attempt_id']
            and audit.get('segment_id') == request['segment_id'] and audit.get('native_id') == c['native_id']
            and audit.get('candidate_result') == c['result'] and audit.get('candidate_media') == c['media']
            and audit.get('case_binding') == request['case_binding'] and audit.get('asset_manifest') == request['asset_manifest'],
            'audit_must_match_exact_fresh_detection_subject')
    require(isinstance(audit.get('evidence'), list) and audit['evidence']
            and isinstance(audit.get('findings'), list), 'audit_bound_evidence_and_findings_required')
    for item in [*audit['evidence'], audit['detector_receipt']]:
        checked(item)
    detector = read(audit['detector_receipt']['path'])
    require(detector.get('attempt_id') == request['attempt_id'] and detector.get('native_id') == c['native_id']
            and detector.get('media') == c['media'] and detector.get('decision') == audit['decision'],
            'actual_detector_receipt_must_match_fresh_subject_and_decision')
    return dict(status='detected', audit=binding, decision=audit['decision'])


def _selection_document(plan, spec, candidate, candidate_binding, audit_binding, review_binding=None):
    require(candidate['attempt_id'] != 'BASELINE', 'original_baseline_is_not_fresh_repair')
    rows = deepcopy(spec['segments'])
    for index, row in enumerate(rows):
        if row['id'] == spec['repair_segment_id']:
            rows[index] = dict(row, native_id=candidate['native_id'], result=candidate['result'], media=candidate['media'],
                               source_case=candidate['source_case'], asset_manifest=candidate['asset_manifest'],
                               kind='accepted_repair', repaired_from=row['result'])
        else:
            row['kind'] = 'preserved_original'
    require(_clock(rows) == plan['original_clock'], 'replacement_must_preserve_complete_story_clock')
    return dict(schema='media_repair_selection/v1', spec=plan['spec'],
                  segments=rows, accepted_candidate=candidate_binding, accepted_audit=audit_binding,
                  accepted_review=review_binding, effective_decision='accept',
                  original_clock=plan['original_clock'], selected_only_after_accept=True,
                  original_files_modified=False, production_approved=False)


def _selection(run, plan, spec, candidate, candidate_binding, audit_binding, review_binding=None):
    return freeze(run, 'SELECTED_VERSION.json', _selection_document(
        plan, spec, candidate, candidate_binding, audit_binding, review_binding))


def _review(candidate, audit_binding, review_binding, spec):
    value = read(checked(review_binding))
    require(value.get('schema') == 'media_repair_review/v1' and value.get('decision') in ('accept', 'reject')
            and isinstance(value.get('reviewed_by'), str) and value['reviewed_by']
            and value.get('attempt_id') == candidate['attempt_id']
            and value.get('native_id') == candidate['native_id']
            and value.get('candidate_result') == candidate['result']
            and value.get('candidate_media') == candidate['media']
            and value.get('audit') == audit_binding and value.get('case_binding') == spec['case_binding']
            and value.get('asset_manifest') == spec['asset_manifest'], 'review_must_match_this_exact_fresh_candidate_and_audit')
    require(isinstance(value.get('evidence'), list) and value['evidence'], 'actual_review_evidence_required')
    for item in value['evidence']:
        checked(item)
    return value


def record_review(run, attempt_id, review_binding):
    """Attach an explicit subject-bound review to an uncertain fresh detection.

    This is a new evidence record, never a rewrite of the model/ASR audit. It
    cannot rescue a rejected/unknown candidate or apply baseline feedback to it.
    """
    run = path(run)
    with run_lock(run, 'REPAIR_LOOP.lock'):
        run, _, spec = _load(run)
        require(attempt_id in [f'A{i:03d}' for i in range(1, spec['max_attempts']+1)], 'known_attempt_to_review_required')
        folder = run/'attempts'/attempt_id
        candidate = read(folder/'CANDIDATE.json')
        audit_binding = read(folder/'detection/AUDIT.json')['audit']
        require(read(checked(audit_binding))['decision'] == 'needs_review', 'only_uncertain_fresh_audit_accepts_review')
        value = _review(candidate, audit_binding, review_binding, spec)
        receipt = freeze(run, f'attempts/{attempt_id}/REVIEW_RECEIPT.json', dict(review=review_binding, decision=value['decision']))
        return dict(status='review_recorded', attempt_id=attempt_id, receipt=receipt, decision=value['decision'])


def _assemble(run, plan, selection, assembler):
    selected = read(checked(selection)); request = dict(schema='media_repair_assembly_request/v1',
              run=str(run), spec=plan['spec'], selection=selection, segments=selected['segments'],
              expected_clock=plan['original_clock'], original_files_modified=False)
    result_path = run/'ASSEMBLY_RESULT.json'
    if result_path.exists():
        response = read(result_path)
    else:
        if (run/'ASSEMBLY_CLAIM.json').exists():
            return _notice(run, 'ASSEMBLY_UNKNOWN.json', 'outcome_unknown', 'assembly_claim_has_no_known_result')
        freeze(run, 'ASSEMBLY_CLAIM.json', request)
        try:
            response = assembler.assemble(deepcopy(request))
            freeze(run, 'ASSEMBLY_RESULT.json', response)
        except Exception as error:
            freeze(run, 'ASSEMBLY_ERROR.json', dict(error=str(error), traceback=traceback.format_exc()))
            return _notice(run, 'ASSEMBLY_UNKNOWN.json', 'outcome_unknown', 'assembly_failed_unknown_output_preserved')
    require(response.get('status') == 'complete', 'known_complete_assembly_required')
    checked(response['file']); receipt = read(checked(response['receipt']))
    require(receipt.get('schema') == 'media_repair_assembly/v1' and receipt.get('selection') == selection
            and receipt.get('file') == response['file'] and receipt.get('completion_known') is True
            and receipt.get('outcome_unknown') is False and receipt.get('clock') == plan['original_clock'],
            'actual_assembly_receipt_and_preserved_clock_required')
    final = dict(schema=VERSION, status='complete', plan=bind(run/'PLAN.json'), selection=selection,
                 file=response['file'], assembly_receipt=response['receipt'], clock=plan['original_clock'],
                 original_files_modified=False, old_failed_candidates_preserved=True,
                 repair_criteria_passed=True, accepted_for_replacement=True,
                 content_quality_passed=False, production_approved=False, publication=False,
                 quality_scope='Only the pinned accepted detector criteria; other visual/voice limitations remain.')
    freeze(run, 'FINAL_RECEIPT.json', final)
    return final


def _embedded_bindings(value):
    """Verify bindings in an already-read receipt, without arbitrary traversal."""
    if isinstance(value, dict):
        if set(value) == {'path', 'sha256'}:
            checked(value)
            return [value]
        result = []
        for item in value.values():
            result.extend(_embedded_bindings(item))
        return result
    if isinstance(value, list):
        return [binding for item in value for binding in _embedded_bindings(item)]
    return []


def _completed_cache(run, plan, spec):
    """Deep-check a completed chain, invoking zero adapter methods or media tools.

    A receipt hash alone cannot attest that its referenced fresh artifacts still
    exist unchanged. Read known candidate/audit/review/assembly links explicitly;
    missing or changed evidence is an error, never a fresh detection/submit.
    """
    final = read(run/'FINAL_RECEIPT.json')
    require(final.get('status') == 'complete' and final.get('plan') == bind(run/'PLAN.json')
            and final.get('clock') == plan['original_clock'], 'completed_loop_plan_or_clock_changed')
    checked(final['file'])
    require(checked(final['selection']) == run/'SELECTED_VERSION.json', 'completed_selection_scope_changed')
    selected = read(final['selection']['path'])
    candidate_binding = selected['accepted_candidate']
    candidate_file = checked(candidate_binding); raw_candidate = read(candidate_file)
    aid = raw_candidate.get('attempt_id')
    require(aid in [f'A{i:03d}' for i in range(1, spec['max_attempts']+1)]
            and candidate_file == run/'attempts'/aid/'CANDIDATE.json', 'completed_candidate_scope_changed')
    folder = candidate_file.parent
    submission = read(folder/'SUBMISSION.json')
    require(submission.get('status') == 'submitted' and submission.get('native_id') == raw_candidate.get('native_id')
            and read(folder/'SUBMIT_CLAIM.json') == _request(run, plan, spec, aid, 'submission'),
            'completed_candidate_original_submit_claim_changed')
    req = _request(run, plan, spec, aid, 'candidate', raw_candidate)
    candidate = _candidate(raw_candidate, req, submission['native_id'], {r['native_id'] for r in spec['segments']})
    native_result = read(candidate['result']['path'])
    for native_file in native_result.get('files', {}).values():
        # Native RESULTs may use project-relative locators and extra source-path
        # fields. Normalize a derived binding, never rewrite the original record.
        p = Path(native_file['path'])
        canonical = p if p.is_absolute() else PROJECT/p
        checked(dict(path=str(path(canonical)), sha256=native_file['sha256']))
    saved_audit = read(folder/'detection/AUDIT.json')
    require(saved_audit.get('request_sha256') == digest(req)
            and saved_audit.get('audit') == selected['accepted_audit'], 'completed_detection_link_changed')
    decision = _validated_audit(selected['accepted_audit'], req)
    review_binding = selected.get('accepted_review')
    if decision['decision'] == 'needs_review':
        review_receipt = read(folder/'REVIEW_RECEIPT.json')
        require(review_receipt.get('review') == review_binding and review_receipt.get('decision') == 'accept',
                'completed_fresh_review_link_changed')
        require(_review(candidate, selected['accepted_audit'], review_binding, spec)['decision'] == 'accept',
                'completed_fresh_review_not_accept')
    else:
        require(decision['decision'] == 'accept' and review_binding is None, 'completed_fresh_audit_not_accept')
    expected = _selection_document(plan, spec, candidate, candidate_binding,
                                   selected['accepted_audit'], review_binding)
    require(digest(expected) == digest(selected), 'completed_selected_version_changed')
    assembled = read(run/'ASSEMBLY_RESULT.json')
    require(assembled.get('status') == 'complete' and assembled.get('file') == final['file']
            and assembled.get('receipt') == final['assembly_receipt'], 'completed_assembly_response_changed')
    receipt = read(checked(final['assembly_receipt']))
    require(receipt.get('schema') == 'media_repair_assembly/v1'
            and receipt.get('selection') == final['selection'] and receipt.get('file') == final['file']
            and receipt.get('clock') == plan['original_clock'] and receipt.get('completion_known') is True
            and receipt.get('outcome_unknown') is False, 'completed_assembly_receipt_link_or_clock_changed')
    # Assembly receipts expose proof/process/filter artifacts as bindings. Check
    # those files and binding objects in their JSON bodies as well, without
    # recursively executing loaders or following arbitrary source catalogs.
    for binding in _embedded_bindings(receipt):
        if Path(binding['path']).suffix.lower() == '.json':
            _embedded_bindings(read(binding['path']))
    require(read(run/'ASSEMBLY_CLAIM.json') == dict(schema='media_repair_assembly_request/v1',
            run=str(run), spec=plan['spec'], selection=final['selection'], segments=selected['segments'],
            expected_clock=plan['original_clock'], original_files_modified=False), 'completed_assembly_claim_changed')
    return final


def step(run, *, executor, auditor, assembler):
    """Advance one bounded operation. Known-ID collection may safely be polled."""
    run = path(run)
    with run_lock(run, 'REPAIR_LOOP.lock'):
        run, plan, spec = _load(run)
        if (run/'FINAL_RECEIPT.json').exists():
            return _completed_cache(run, plan, spec)
        original = _original(spec)
        baseline = dict(original, segment_id=original['id'], attempt_id='BASELINE')
        req = _request(run, plan, spec, 'BASELINE', 'baseline', baseline)
        detected = _audit(run, 'baseline', req, auditor)
        if detected['status'] != 'detected':
            return detected
        allowed = spec.get('regenerate_on', ['reject'])
        if detected['decision'] not in allowed:
            return _notice(run, 'BASELINE_REVIEW.json', 'needs_review', 'baseline_decision_does_not_authorize_regeneration', decision=detected['decision'])
        for index in range(1, spec['max_attempts']+1):
            aid = f'A{index:03d}'; folder = run/'attempts'/aid
            req = _request(run, plan, spec, aid, 'submission')
            submission_file = folder/'SUBMISSION.json'
            if not submission_file.exists():
                if (folder/'SUBMIT_CLAIM.json').exists():
                    return _notice(run, f'attempts/{aid}/SUBMIT_UNKNOWN.json', 'outcome_unknown', 'submit_claim_has_no_known_native_ID', attempt_id=aid)
                # Recheck actual claims under the same OS lock immediately before
                # dispatch; neither changed PLAN nor concurrent callers may add one.
                claims = list((run/'attempts').glob('A*/SUBMIT_CLAIM.json'))
                require(len(claims) < spec['max_attempts'], 'actual_submission_budget_exhausted')
                freeze(run, f'attempts/{aid}/SUBMIT_CLAIM.json', req)
                try:
                    response = executor.submit(deepcopy(req))
                    freeze(run, f'attempts/{aid}/SUBMISSION.json', response)
                except Exception as error:
                    freeze(run, f'attempts/{aid}/SUBMIT_ERROR.json', dict(error=str(error), traceback=traceback.format_exc()))
                    return _notice(run, f'attempts/{aid}/SUBMIT_UNKNOWN.json', 'outcome_unknown', 'submission_failed_native_outcome_unknown', attempt_id=aid)
                return dict(status='progress', phase='submitted', attempt_id=aid)
            submission = read(submission_file)
            if submission.get('status') != 'submitted' or not isinstance(submission.get('native_id'), str) or not submission['native_id']:
                return _notice(run, f'attempts/{aid}/SUBMIT_UNKNOWN.json', 'outcome_unknown', 'submission_has_no_confirmed_native_ID', attempt_id=aid)
            require(read(folder/'SUBMIT_CLAIM.json') == req, 'original_submission_claim_changed')
            native_id = submission['native_id']
            original_ids = {r['native_id'] for r in spec['segments']}
            require(native_id not in original_ids, 'native_ID_must_be_new_not_original_replay')
            for prev in range(1, index):
                require(read(run/'attempts'/f'A{prev:03d}'/'SUBMISSION.json')['native_id'] != native_id, 'attempt_native_ID_reused')
            candidate_path = folder/'CANDIDATE.json'
            collect_req = dict(req, phase='collection', native_id=native_id, submission=submission)
            if not candidate_path.exists():
                if (folder/'COLLECTION_RESULT.json').exists():
                    response = read(folder/'COLLECTION_RESULT.json')
                else:
                    try:
                        response = executor.collect(deepcopy(collect_req))
                    except Exception as error:
                        return dict(status='pending', phase='known_ID_collection', attempt_id=aid, native_id=native_id,
                                    error=str(error), no_new_submission=True)
                if response.get('status') == 'pending':
                    return dict(status='pending', phase='known_ID_collection', attempt_id=aid, native_id=native_id, no_new_submission=True)
                if response.get('status') != 'saved':
                    return _notice(run, f'attempts/{aid}/COLLECT_UNKNOWN.json', 'outcome_unknown', 'original_native_result_not_known_saved', attempt_id=aid, native_id=native_id)
                freeze(run, f'attempts/{aid}/COLLECTION_RESULT.json', response)
                candidate = _candidate(response.get('candidate'), collect_req, native_id, original_ids)
                freeze(run, f'attempts/{aid}/CANDIDATE.json', candidate)
                return dict(status='progress', phase='collected', attempt_id=aid, native_id=native_id)
            candidate = _candidate(read(candidate_path), collect_req, native_id, original_ids)
            audit_req = _request(run, plan, spec, aid, 'candidate', candidate)
            decision = _audit(run, f'attempts/{aid}/detection', audit_req, auditor)
            if decision['status'] != 'detected':
                return decision
            if decision['decision'] == 'needs_review':
                if not (folder/'REVIEW_RECEIPT.json').exists():
                    return _notice(run, f'attempts/{aid}/REVIEW_REQUIRED.json', 'needs_review', 'fresh_candidate_detection_uncertain',
                                   candidate=bind(candidate_path), audit=decision['audit'])
                reviewed = _review(candidate, decision['audit'], read(folder/'REVIEW_RECEIPT.json')['review'], spec)
                decision = dict(decision, decision=reviewed['decision'], review=read(folder/'REVIEW_RECEIPT.json')['review'])
            if decision['decision'] == 'accept':
                selection = _selection(run, plan, spec, candidate, bind(candidate_path), decision['audit'], decision.get('review'))
                return _assemble(run, plan, selection, assembler)
            # Rejected candidate remains on disk. Only a known, bound rejection
            # permits the next configured attempt; a fresh audit is never reused.
        return _notice(run, 'ATTEMPTS_EXHAUSTED.json', 'attempts_exhausted', 'no_accepted_fresh_candidate_within_budget',
                       attempted=spec['max_attempts'], selection_performed=False)


def drive(run, *, executor, auditor, assembler, max_steps=12):
    require(type(max_steps) is int and 1 <= max_steps <= 30, 'bounded_drive_steps_required')
    for _ in range(max_steps):
        result = step(run, executor=executor, auditor=auditor, assembler=assembler)
        if result['status'] != 'progress':
            return result
    return dict(status='pending', phase='bounded_driver_yield', no_new_submission=True)


def status(run):
    run, plan, spec = _load(run)
    if (run/'FINAL_RECEIPT.json').exists():
        value = _completed_cache(run, plan, spec)
        return dict(status='complete', receipt=bind(run/'FINAL_RECEIPT.json'), file=value['file'])
    notices = [p for p in run.rglob('*.json') if p.name.endswith('UNKNOWN.json') or p.name in ('ATTEMPTS_EXHAUSTED.json', 'REVIEW_REQUIRED.json', 'BASELINE_REVIEW.json')]
    return dict(status='notice' if notices else 'prepared_or_in_progress', plan=bind(run/'PLAN.json'),
                max_attempts=spec['max_attempts'], actual_submission_claims=len(list((run/'attempts').glob('A*/SUBMIT_CLAIM.json'))),
                notices=[bind(p) for p in sorted(notices)])
