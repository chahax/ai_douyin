"""Pure, evidence-bound audio repair planning. No processor is dispatched here.

Full-track ASR input is a scope check, not an acoustic/speaker-quality verdict.
Every modified media version must acquire its own inspection and conformance.
"""
from fractions import Fraction

from . import audio_full_scope_v1 as scope
from . import h3_audio_conformance_v1 as conformance

CASE_SCHEMA = 'audio_repair_routing_case/v1'
SCHEMA = 'audio_repair_route/v1'
KINDS = {'extra_speech', 'wrong_words', 'missing_speech', 'wrong_speaker',
         'dialogue_overlap', 'noise_only'}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _same(value, case):
    require(value.get('native_id') == case['native_id'] and value.get('media') == case['media'],
            'evidence_native_media_mismatch')
    if 'segment_id' in value:
        require(value['segment_id'] == case['segment_id'], 'evidence_segment_mismatch')


def _evidence(values):
    require(isinstance(values, list) and values, 'nonempty_bound_evidence_required')
    for value in values:
        scope.checked(value)


def _confirmation(binding, case):
    if binding is None:
        return None
    value = scope.read(binding)
    require(value.get('schema') == conformance.USER_ISSUE_SCHEMA and value.get('confirmed') is True
            and value.get('confirmed_by') in ('user', 'independent_review'),
            'explicit_confirmation_required')
    _same(value, case)
    require(isinstance(value.get('description'), str) and value['description'].strip(),
            'confirmation_description_required')
    # Legacy confirmation proves a problem, not its kind or independence.
    if 'kind' not in value:
        return value
    require(value['kind'] in KINDS, 'unsupported_confirmation_kind')
    _evidence(value.get('evidence'))
    windows = value.get('intervals_ms', [])
    require(isinstance(windows, list) and all(isinstance(w, list) and len(w) == 2
            and all(type(t) is int for t in w) and 0 <= w[0] < w[1] for w in windows),
            'confirmation_intervals_invalid')
    if value['kind'] in ('extra_speech', 'noise_only', 'dialogue_overlap'):
        require(windows, 'confirmation_time_intervals_required')
    return value


def _visual(binding, case):
    if binding is None:
        return 'unknown'
    value = scope.read(binding)
    if value.get('schema') == 'h3_repair_visual_review/v1':
        _same(value.get('subject', {}), case)
        evidence = value.get('evidence', {})
        require(isinstance(evidence, dict) and evidence, 'visual_review_evidence_required')
        for item in evidence.values():
            if isinstance(item, list):
                for child in item:
                    scope.checked(child)
            else:
                scope.checked(item)
        if value.get('visual_review_passed') is False and value.get('decisive_findings'):
            return 'major'
        return 'accepted' if value.get('visual_review_passed') is True else 'unknown'
    require(value.get('schema') == 'media_visual_review/v1', 'supported_visual_review_required')
    _same(value, case)
    _evidence(value.get('evidence'))
    require(bool(value.get('reviewed_by')), 'visual_reviewer_required')
    require(value.get('status') in ('major', 'accepted', 'unknown'), 'visual_status_invalid')
    return value['status']


def _full_quotes(report):
    quotes = report['expected_coverage']
    summary = report.get('coverage_summary', {})
    return bool(quotes) and summary.get('expected_quotes') == summary.get('fully_recognized_quotes') == len(quotes) and all(
        q.get('recognized_match') is True and q.get('match_kind') in ('normalized_exact', 'limited_de_di_homophone')
        and type(q.get('actual_start_ms')) is int and type(q.get('actual_end_ms')) is int
        and 0 <= q['actual_start_ms'] < q['actual_end_ms'] for q in quotes)


def _capability(case, desired, confirmation):
    for binding in case.get('capabilities', []):
        value = scope.read(binding)
        if value.get('capability') != desired:
            continue
        require(value.get('schema') == 'media_repair_capability/v1' and value.get('verified') is True,
                'backend_capability_not_verified')
        module = scope.checked(value['executor_module'])
        require(module.suffix == '.py' and isinstance(value.get('method'), str) and value['method'],
                'bound_backend_method_required')
        _evidence(value.get('evidence'))
        require(value.get('preserves_duration') is True, 'duration_preservation_capability_required')
        if desired != 'regenerate_av':
            require(value.get('preserves_video_and_duration') is True,
                    'audio_only_video_preservation_capability_required')
        if desired == 'regenerate_audio':
            voice = value.get('source_voice_preservation', {})
            require(voice.get('verified') is True and voice.get('strategy') == 'preserve_existing_speakers',
                    'verified_same_speaker_audio_backend_missing')
            _evidence(voice.get('evidence'))
        if confirmation is not None:
            require(confirmation['confirmed_by'] in value.get('confirmation_types', []),
                    'backend_confirmation_contract_missing')
        if desired == 'cleanup_gap':
            # The existing processor explicitly requires user confirmation.
            if module.name == 'audio_gap_repair_v1.py':
                require(confirmation['confirmed_by'] == 'user', 'gap_v1_requires_user_confirmation')
            require(value.get('processor_schema') == 'audio_gap_repair_spec/v1',
                    'gap_processor_spec_contract_missing')
        return binding, value
    raise ValueError('verified_backend_missing:' + desired)


def _request(case, case_binding, report, full, route, confirmation, cleanup=None):
    try:
        backend_binding, backend = _capability(case, route, confirmation)
    except (ValueError, KeyError, OSError) as error:
        return 'capability_missing', None, str(error)
    request = dict(schema='audio_repair_processor_request/v1', operation=route,
        dry_run=True, execute_allowed=False, backend=backend_binding,
        executor_module=backend['executor_module'], method=backend['method'],
        input=dict(case=case_binding, native_id=case['native_id'], segment_id=case['segment_id'],
                   media=case['media'], conformance_case=case['conformance_case'],
                   conformance_report=case['conformance_report'],
                   full_audio_inspection=case['full_audio_inspection'],
                   confirmation=case.get('confirmation'), visual_review=case.get('visual_review')),
        constraints=dict(preserve_duration=True, preserve_video=route != 'regenerate_av',
                         adult_voice_fallback_allowed=False, automatic_dispatch_allowed=False),
        post_repair=dict(requires_new_media_full_audio_inspection=True,
                         requires_new_media_conformance=True, reuse_source_ASR_for_acceptance=False,
                         visual_acceptance_unchanged=True, overall_video_accepted=False))
    if cleanup is not None:
        request['processor_spec'] = dict(schema='audio_gap_repair_spec/v1', native_id=case['native_id'],
            segment_id=case['segment_id'], media=case['media'],
            conformance_case=case['conformance_case'], conformance_report=case['conformance_report'],
            user_issue=case['confirmation'], selected_unmapped_indices=cleanup['indices'],
            frame_clock=full['frame_clock'], audio_target=dict(rate=48000, channels=2),
            padding_ms=80, fade_ms=40, quote_protection_ms=80)
        request['patches'] = cleanup['patches']
        request['constraints']['ambient_audio_inside_patch_will_also_be_attenuated'] = True
    return route, request, 'verified_backend_plan_only'


def _cleanup(report, confirmation, full):
    require(_full_quotes(report), 'full_actual_quote_matches_required')
    require(confirmation.get('independent_of_expected_quotes') is True,
            'extra_audio_independence_not_confirmed')
    windows = confirmation['intervals_ms']
    quotes = [[q['actual_start_ms'], q['actual_end_ms']] for q in report['expected_coverage']]
    # Confirmation windows can be rough. Only the actual recognized gap and
    # its envelope determine overlap; never mute the entire reported window.
    gaps = report['unmapped_recognized_spans']
    require(gaps, 'actual_unmapped_intervals_required')
    seconds = Fraction(full['frame_clock']['frames'], full['frame_clock']['fps'])
    patches = []
    for index, gap in enumerate(gaps):
        a, b = gap['start_ms'], gap['end_ms']
        require(type(a) is int and type(b) is int and 0 <= a < b
                and any(x <= a < b <= y for x, y in windows), 'all_unmapped_audio_requires_confirmation')
        outer = [a - 80, b + 80]
        require(0 <= outer[0] < outer[1] <= seconds * 1000
                and all(outer[1] <= max(0, x - 80) or outer[0] >= y + 80 for x, y in quotes),
                'patch_overlaps_actual_quote_protection')
        patches.append(dict(unmapped_index=index, core_ms=[a, b], patch_ms=outer, fade_ms=40))
    patches.sort(key=lambda p: p['patch_ms'][0])
    require(all(a['patch_ms'][1] <= b['patch_ms'][0] for a, b in zip(patches, patches[1:])),
            'patch_envelopes_overlap')
    return dict(indices=[p['unmapped_index'] for p in patches], patches=patches)


def evaluate_bound(case_binding):
    """Plan one immutable media version. Reads only; never invokes a backend."""
    result = dict(schema=SCHEMA, route='verify_audio', desired_route=None, input_valid=False,
        full_audio_inputs_verified=False, subject=None, processor_request=None, dry_run=True,
        overall_video_accepted=False, new_ASR_calls=0, new_model_calls=0, HTTP_calls=0,
        limitations=['Full-track ASR input does not verify every sound or speaker identity.',
                     'Gap attenuation also removes mixed ambience within the patch.',
                     'ASR quote protection margins are heuristic, not a listening guarantee.'])
    try:
        case = scope.read(case_binding)
        require(case.get('schema') == CASE_SCHEMA, 'routing_case_schema_invalid')
        require(isinstance(case.get('native_id'), str) and case['native_id']
                and isinstance(case.get('segment_id'), str) and case['segment_id'], 'media_identity_required')
        scope.checked(case['media'])
        result['subject'] = {k: case[k] for k in ('native_id', 'segment_id', 'media')}
        source_case = scope.read(case['conformance_case'])
        _same(source_case, case)
        report = scope.read(case['conformance_report'])
        require(report == conformance.evaluate_bound(case['conformance_case']), 'conformance_report_not_recomputed')
        require(report.get('input_valid') is True, 'conformance_input_invalid')
        _same(report, case)
        result['input_valid'] = True
        require('full_audio_inspection' in case, 'full_track_inspection_missing')
        full = scope.validate_bound(case['full_audio_inspection'])
        _same(full, case)
        require(full['asr_receipt'] == source_case['asr_receipt'], 'full_scope_conformance_receipt_mismatch')
        result['full_audio_inputs_verified'] = True
        confirmation = _confirmation(case.get('confirmation'), case)
        visual = _visual(case.get('visual_review'), case)
        result['visual_state'] = visual
        desired, cleanup = None, None
        if visual == 'major':
            desired = 'regenerate_av'
        elif confirmation is not None:
            kind = confirmation.get('kind')
            if kind in ('wrong_words', 'missing_speech', 'wrong_speaker', 'dialogue_overlap'):
                desired = 'regenerate_audio'
            elif kind == 'noise_only':
                desired = 'denoise_audio'
            elif kind == 'extra_speech':
                try:
                    cleanup = _cleanup(report, confirmation, full)
                except ValueError as error:
                    if 'overlap' in str(error):
                        desired = 'regenerate_audio'
                    else:
                        result['reason'] = str(error)
                        return result
                if desired is None:
                    if case.get('allow_ambient_loss') is not True:
                        result['reason'] = 'mixed_ambient_loss_not_authorized'
                        return result
                    desired = 'cleanup_gap'
            else:
                result['reason'] = 'confirmation_kind_and_independence_need_verification'
                return result
        elif report.get('decision') == 'accept' and _full_quotes(report) and not report['unmapped_recognized_spans']:
            result.update(route='accept', reason='complete_text_checks_and_full_track_input_verified',
                          audio_text_conformance_accepted=True)
            return result
        else:
            result['reason'] = 'recognition_alone_does_not_confirm_audio_defect'
            return result
        result['desired_route'] = desired
        route, request, reason = _request(case, case_binding, report, full, desired, confirmation, cleanup)
        result.update(route=route, processor_request=request, reason=reason)
        return result
    except (ValueError, KeyError, TypeError, OSError) as error:
        result.update(route='verify_audio', input_valid=False, reason=str(error), processor_request=None)
        return result
