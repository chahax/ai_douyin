"""Opt-in full-segment audio routing and processor preparation, without execution.

The caller supplies every expected segment. This entry never calls a model,
transcribes, edits media, selects a movie version or changes a background task.
"""
import json
from pathlib import Path

from . import audio_full_scope_v1 as scope
from . import audio_repair_routing_v1 as routing

PROJECT = scope.PROJECT
SCHEMA = 'audio_quality_flow/v1'


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def freeze(path, value):
    path = scope.local(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(json.loads(path.read_text(encoding='utf-8-sig')) == value,
                'audio_flow_frozen_record_changed')
    else:
        with path.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    return scope.bind(path)


def _code():
    return [scope.bind(p) for p in (Path(__file__), Path(scope.__file__), Path(routing.__file__),
        PROJECT / 'src/content_factory/h3_audio_conformance_v1.py',
        PROJECT / 'src/content_factory/audio_gap_repair_v1.py')]


def _evaluate_manifest(manifest_binding):
    manifest = scope.read(manifest_binding)
    require(manifest.get('schema') == 'audio_quality_flow_batch/v1', 'audio_batch_manifest_schema_required')
    segments = manifest.get('segments')
    require(isinstance(segments, list) and segments, 'all_expected_segments_required')
    ids = [row.get('segment_id') for row in segments]
    require(all(isinstance(i, str) and i.strip() for i in ids) and len(set(ids)) == len(ids),
            'unique_explicit_segment_ids_required')
    results = []
    for row in segments:
        require(isinstance(row.get('native_id'), str) and row['native_id'], 'segment_native_identity_required')
        scope.checked(row['media'])
        expected = {k: row[k] for k in ('segment_id', 'native_id', 'media')}
        if row.get('case') is None:
            decision = dict(schema='audio_repair_route/v1', route='verify_audio', desired_route='verify_audio',
                subject=expected, input_valid=False, full_audio_inputs_verified=False,
                processor_request=None, reason='expected_segment_has_no_detection_case')
        else:
            case = scope.read(row['case'])
            require({k: case.get(k) for k in expected} == expected,
                    'case_not_current_expected_segment_or_media')
            decision = routing.evaluate_bound(row['case'])
            require(decision.get('subject') == expected, 'routing_subject_changed')
        results.append(dict(**expected, case=row.get('case'), evaluation=decision))
    full_ids = [r['segment_id'] for r in results if r['evaluation']['full_audio_inputs_verified'] is True]
    valid_ids = [r['segment_id'] for r in results if r['evaluation']['input_valid'] is True]
    return dict(schema=SCHEMA, status='routing_planned_without_execution', manifest=manifest_binding,
        code=_code(), scope='declared_batch', expected_segment_ids=ids, segments=results,
        full_audio_input_verified_ids=full_ids, conformance_input_valid_ids=valid_ids,
        all_segment_audio_inputs_verified=set(full_ids) == set(ids),
        all_segment_conformance_inputs_valid=set(valid_ids) == set(ids),
        all_audio_routes_accept=all(r['evaluation']['route'] == 'accept' for r in results),
        media_execution_performed=False, new_ASR_calls=0, new_model_calls=0,
        overall_video_quality_passed=False, automatic_publication=False)


def prepare_batch(run, manifest_binding):
    from .visual_image_jobs_v3 import run_lock
    run = scope.local(run)
    run.mkdir(parents=True, exist_ok=True)
    with run_lock(run, 'AUDIO_QUALITY_FLOW.lock'):
        plan = _evaluate_manifest(manifest_binding)
        for row in plan['segments']:
            require(not scope.local(row['media']['path']).is_relative_to(run),
                    'source_media_must_stay_outside_new_audio_flow_run')
        binding = freeze(run / 'PLAN.json', plan)
        return dict(status=plan['status'], plan=binding,
            all_segment_audio_inputs_verified=plan['all_segment_audio_inputs_verified'],
            routes=[dict(segment_id=r['segment_id'], route=r['evaluation']['route'],
                         desired_route=r['evaluation'].get('desired_route')) for r in plan['segments']],
            execute_allowed=False)


def status(run):
    run = scope.local(run)
    plan = json.loads((run / 'PLAN.json').read_text(encoding='utf-8-sig'))
    require(plan['code'] == _code(), 'audio_flow_frozen_code_changed')
    require(plan == _evaluate_manifest(plan['manifest']), 'audio_flow_cached_evidence_changed')
    return plan


def prepare_cleanup(run, segment_id):
    """Compile a qualifying cleanup job through the existing CPU processor.

    Other backend requests remain explicit plans. In particular an advertised
    audio-regeneration capability does not cause an arbitrary module to run.
    """
    from . import audio_gap_repair_v1 as gap
    from .visual_image_jobs_v3 import run_lock
    run = scope.local(run)
    with run_lock(run, 'AUDIO_QUALITY_FLOW.lock'):
        plan = status(run)
        rows = [r for r in plan['segments'] if r['segment_id'] == segment_id]
        require(len(rows) == 1, 'one_declared_segment_required')
        decision = rows[0]['evaluation']
        require(decision['route'] == 'cleanup_gap' and decision['input_valid'] is True
                and decision['full_audio_inputs_verified'] is True, 'segment_not_ready_for_gap_cleanup')
        request = decision['processor_request']
        require(request.get('dry_run') is True and request.get('execute_allowed') is False,
                'processor_preparation_only_required')
        require(request.get('executor_module') == scope.bind(gap.__file__)
                and request.get('method') == 'prepare', 'only_existing_pinned_gap_preparer_allowed')
        job = run / 'processors' / ('segment_' + str(plan['expected_segment_ids'].index(segment_id)))
        spec_binding = freeze(job / 'SPEC.json', request['processor_spec'])
        prepared = gap.prepare(job / 'prepared', spec_binding)
        receipt = freeze(job / 'PREPARED.json', dict(schema='audio_quality_processor_preparation/v1',
            routing_plan=scope.bind(run / 'PLAN.json'), segment_id=segment_id,
            processor_spec=spec_binding, prepared=prepared, media_execution_performed=False,
            fresh_full_audio_detection_required_after_any_later_edit=True,
            overall_video_quality_passed=False))
        return dict(status='cleanup_prepared_not_executed', receipt=receipt, prepared=prepared)
