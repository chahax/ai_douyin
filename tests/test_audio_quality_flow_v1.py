"""Blackbox wiring of scope, transcript routing and CPU-job preparation only."""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import uuid

import pytest

from src.content_factory import audio_full_scope_v1 as scope
from src.content_factory import audio_quality_flow_v1 as flow


def _fixture_builder():
    source = scope.PROJECT / 'tests/test_audio_repair_routing_v1.py'
    spec = importlib.util.spec_from_file_location('_audio_route_test_fixtures', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.make_case


@pytest.fixture
def example(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No subprocess, model, network or real media operation in this test')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    folder = scope.PROJECT / 'data/test_runs' / ('audio_flow_' + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    return folder, _fixture_builder()


def _row(case):
    return {**{k: case['case'][k] for k in ('native_id', 'segment_id', 'media')},
            'case': case['put']('PUBLIC_FLOW_CASE.json', case['case'])}


def test_public_batch_reports_missing_segments_instead_of_claiming_full_movie_pass(example):
    folder, make_case = example
    case = make_case(folder / 'source', extra=False)
    pending = folder / 'ANOTHER_UNCHECKED_MEDIA.bin'
    pending.write_bytes(b'Another explicitly expected segment')
    manifest = case['put']('BATCH.json', dict(schema='audio_quality_flow_batch/v1', segments=[_row(case),
        dict(segment_id='next_segment', native_id='next_native', media=scope.bind(pending), case=None)]))
    result = flow.prepare_batch(folder / 'flow', manifest)
    assert not result['all_segment_audio_inputs_verified']
    plan = flow.status(folder / 'flow')
    assert plan['full_audio_input_verified_ids'] == ['segment_arbitrary']
    assert [r['evaluation']['route'] for r in plan['segments']] == ['accept', 'verify_audio']
    assert not plan['overall_video_quality_passed']


def test_route_to_existing_gap_preparer_without_editing_or_reusing_old_ASR_for_new_media(example):
    folder, make_case = example
    case = make_case(folder / 'source')
    case['confirm']()
    case['capability']('cleanup_gap')
    manifest = case['put']('BATCH.json', dict(schema='audio_quality_flow_batch/v1', segments=[_row(case)]))
    out = flow.prepare_batch(folder / 'flow', manifest)
    assert out['routes'][0]['route'] == 'cleanup_gap'
    prepared = flow.prepare_cleanup(folder / 'flow', case['case']['segment_id'])
    assert prepared['status'] == 'cleanup_prepared_not_executed'
    job_plan = json.loads(Path(prepared['prepared']['plan']['path']).read_text())
    assert job_plan['details']['patches'][0]['patch_ms'] == [8860, 12060]
    assert not list((folder / 'flow').rglob('EXECUTE_CLAIM.json'))
    assert not list((folder / 'flow').rglob('*.mp4'))
    request = flow.status(folder / 'flow')['segments'][0]['evaluation']['processor_request']
    assert request['post_repair']['requires_new_media_full_audio_inspection']
    assert not request['post_repair']['reuse_source_ASR_for_acceptance']


def test_expected_media_versions_and_segment_ids_must_match_exactly(example):
    folder, make_case = example
    case = make_case(folder / 'source', extra=False)
    row = _row(case)
    row['native_id'] = 'older_native_version'
    manifest = case['put']('BATCH.json', dict(schema='audio_quality_flow_batch/v1', segments=[row]))
    with pytest.raises(ValueError, match='case_not_current_expected_segment'):
        flow.prepare_batch(folder / 'flow', manifest)
    row = _row(case)
    duplicate = case['put']('DUPLICATE_BATCH.json', dict(schema='audio_quality_flow_batch/v1', segments=[row, row]))
    with pytest.raises(ValueError, match='unique_explicit_segment_ids'):
        flow.prepare_batch(folder / 'duplicate', duplicate)


def test_cached_plan_deep_evidence_and_real_reentry_never_dispatch(example):
    folder, make_case = example
    case = make_case(folder / 'source', extra=False)
    manifest = case['put']('BATCH.json', dict(schema='audio_quality_flow_batch/v1', segments=[_row(case)]))
    first = flow.prepare_batch(folder / 'flow', manifest)
    assert flow.prepare_batch(folder / 'flow', manifest) == first
    case_file = Path(case['case']['conformance_case']['path'])
    conformance = json.loads(case_file.read_text())
    receipt = json.loads(Path(conformance['asr_receipt']['path']).read_text())
    Path(receipt['raw_asr']['path']).write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='audio_flow_cached_evidence_changed'):
        flow.status(folder / 'flow')
