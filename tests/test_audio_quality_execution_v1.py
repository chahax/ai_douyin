"""Full bridge protocol with synthetic bytes/WAV and injected CPU/ASR process I/O.

No real source media is read/encoded; real scope/conformance/route/inspector
validators run, while the CPU gap processor and ASR child are simulated.
"""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import uuid
import wave

import pytest

from src.content_factory import audio_full_scope_v1 as scope
from src.content_factory import audio_quality_execution_v1 as execution
from src.content_factory import audio_gap_repair_v1 as gap
from src.content_factory import local_audio_inspector_v1 as inspector
from src.content_factory import h3_audio_conformance_v1 as conformance


def _fixtures():
    file = scope.PROJECT / 'tests/test_audio_repair_routing_v1.py'
    spec = importlib.util.spec_from_file_location('_audio_execution_test_materials', file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.make_case


@pytest.fixture
def example(monkeypatch, tmp_path):
    assert tmp_path.resolve().is_relative_to(scope.PROJECT)
    def forbidden(*a, **kw):
        raise AssertionError('No model, network or real subprocess allowed')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    base = _fixtures()(tmp_path / 'source')
    put = base['put']
    old_case = scope.read(base['case']['conformance_case'])
    asset = put('ASSETS.json', dict(synthetic=True))
    original = scope.read(base['candidate'])
    original.update(source_case=old_case['source_case'], asset_manifest=asset)
    source = put('SOURCE_CANDIDATE_WITH_MATERIALS.json', original)
    full = put('SOURCE_FULL_SCOPE.json', scope.verify(old_case['asr_receipt'], source))
    base['case']['full_audio_inspection'] = full
    original_issue = put('ORIGINAL_USER_WORDS.json', dict(text='8–12秒还有声音问题',
        native_id=original['native_id'], media=original['media'], intervals_ms=[[8000, 12000]]))
    issue = base['confirm'](intervals_ms=[[8000, 12000]], original_user_confirmation=original_issue,
        classification_provenance='rule plus ASR gap separated from complete actual quotes',
        actual_words_confirmed=False, language_confirmed=False)
    base['capability']('cleanup_gap')
    visual = put('KNOWN_VISUAL_MAJOR.json', dict(schema='media_visual_review/v1',
        native_id=original['native_id'], media=original['media'], status='major',
        reviewed_by='synthetic_independent_reviewer', evidence=[base['evidence']]))
    run = tmp_path / 'trial'
    authority = dict(schema=execution.AUTHORITY, trial_run=str(run), source_candidate=source,
        source_case=original['source_case'], asset_manifest=asset, confirmed_by='user',
        trial_scope='audio_only_test', max_CPU_edits=1, max_ASR_calls=1, max_H3_calls=0,
        allow_ambient_loss=True, assembly_allowed=False)
    model_root = tmp_path / 'FAKE_MODELS_NOT_LOADED'
    for model in ('paraformer-zh', 'fsmn-vad'):
        folder = model_root / model
        folder.mkdir(parents=True)
        (folder / 'config.yaml').write_text('synthetic: true')
        (folder / 'model.pt').write_bytes(b'not a real model, never loaded')
    value = dict(schema=execution.INPUT, trial_scope='audio_only_test',
        segment_id=original['segment_id'], source_candidate=source, source_case=original['source_case'],
        asset_manifest=asset, conformance_case=base['case']['conformance_case'],
        conformance_report=base['case']['conformance_report'], full_audio_inspection=full,
        confirmation=base['case']['confirmation'], capabilities=base['case']['capabilities'],
        allow_ambient_loss=True, known_visual_review=visual, authority=put('AUTHORITY.json', authority),
        inspector=dict(model_root=str(model_root), transcriber=scope.bind(scope.PROJECT / 'scripts/transcribe_video_local.py'),
                       timeout_seconds=30))
    calls = dict(edits=0, ASR=0, extracts=0)
    mode = dict(ASR_extra=False, ASR_unknown=False, edit_unknown=False)

    def fake_qa(job):
        result = scope.read(scope.bind(job / 'RESULT.json'))
        for item in result['artifacts']:
            scope.checked(item)
        return dict(status='verified_CPU_audio_repair', file=result['file'],
            receipt=scope.bind(job / 'RESULT.json'), proof=result['proof'], no_subprocess_on_reentry=True)

    def fake_edit(job):
        if (job / 'RESULT.json').exists():
            return fake_qa(job)
        if (job / 'EXECUTE_CLAIM.json').exists():
            return dict(status='outcome_unknown', automatic_retry=False)
        calls['edits'] += 1
        execution.flow.freeze(job / 'EXECUTE_CLAIM.json', dict(synthetic=True))
        if mode['edit_unknown']:
            return dict(status='outcome_unknown', automatic_retry=False)
        plan = scope.read(scope.bind(job / 'PLAN.json'))
        samples = plan['details']['effective_samples']
        media = job / 'SYNTHETIC_EDITED.mp4'
        media.write_bytes(b'Synthetic edited media protocol; never decoded')
        pcm = job / 'FINAL_AAC_DECODED_PCM.s16le'
        pcm.write_bytes(bytes(samples * 4))
        hashes = []
        for name in ('SOURCE_FRAMEHASH.txt', 'OUTPUT_FRAMEHASH.txt'):
            file = job / name
            file.write_text('synthetic frame/PTS proof, gap.qa is injected')
            hashes.append(scope.bind(file))
        proof = execution.flow.freeze(job / 'PROOF.json', dict(schema='audio_gap_repair_proof/v1',
            input=plan['details']['media'], output=scope.bind(media), video_streamcopy=True,
            video_frames_PTS_and_decoded_hashes_unchanged=True, duration_or_story_cut_performed=False,
            final_decoded_PCM=scope.bind(pcm), source_framehash=hashes[0], output_framehash=hashes[1],
            output_normalization=dict(decoded_samples=samples + 896, container_effective_samples=samples,
                removed_codec_tail_samples=896, tail_pad_samples=0, meaningful_content_trimmed=False)))
        artifacts = [scope.bind(job / 'PLAN.json'), proof, scope.bind(media), scope.bind(pcm), *hashes]
        execution.flow.freeze(job / 'RESULT.json', dict(schema=gap.VERSION,
            plan=scope.bind(job / 'PLAN.json'), file=scope.bind(media), proof=proof, artifacts=artifacts))
        return fake_qa(job)

    def fake_process(folder, label, command, timeout):
        if label == 'extract':
            calls['extracts'] += 1
            with wave.open(command[-1], 'wb') as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
                stream.writeframes(bytes(240000 * 2))
        else:
            calls['ASR'] += 1
            if mode['ASR_unknown']:
                raise TimeoutError('synthetic ASR result unknown')
            rows = []
            for text, start, end in [('这是正常的第一句话。', 420, 8760), ('别去了！', 12820, 14285)]:
                text = conformance.normalize_text(text)
                rows.extend((c, start + i * (end-start)//len(text), start+(i+1)*(end-start)//len(text))
                            for i, c in enumerate(text))
            if mode['ASR_extra']:
                rows += [('疑', 9000, 9500), ('似', 9500, 10000)]
                rows.sort(key=lambda r:r[1])
            Path(command[5]).write_text(json.dumps(dict(schema='local_video_transcript/v1',
                audio=command[4], result=[dict(text=' '.join(r[0] for r in rows),
                timestamp=[[a, b] for _, a, b in rows])]), ensure_ascii=False), encoding='utf-8')
        return inspector._freeze(folder / 'processes' / (label + '.json'),
            dict(command=command, exit_code=0, outcome_unknown=False, timed_out=False, synthetic=True))

    monkeypatch.setattr(gap, 'execute', fake_edit)
    monkeypatch.setattr(gap, 'qa', fake_qa)
    monkeypatch.setattr(inspector, '_process', fake_process)
    return dict(run=run, input=value, put=put, base=base, source=original, calls=calls, mode=mode,
                binding=lambda: put('INPUT.json', value))


def test_prepare_is_plan_only_and_keeps_source_visual_major_and_user_provenance(example):
    e = example
    out = execution.prepare(e['run'], e['binding']())
    assert out['source_audio_route'] == 'cleanup_gap'
    assert e['calls'] == dict(edits=0, ASR=0, extracts=0)
    plan = scope.read(out['plan'])
    assert plan['known_visual_state'] == 'major' and not plan['overall_video_quality_passed']
    issue = scope.read(e['input']['confirmation'])
    assert issue['intervals_ms'] == [[8000, 12000]] and not issue['actual_words_confirmed']
    assert execution.status(e['run'])['no_dispatch_performed']


def test_full_execute_new_edit_identity_fresh_full_ASR_route_and_zero_dispatch_reentry(example):
    e = example
    execution.prepare(e['run'], e['binding']())
    first = execution.execute(e['run'])
    assert first['audio_route'] == 'accept' and not first['overall_video_quality_passed']
    result = scope.read(first['result'])
    fresh = scope.read(result['candidate'])
    original = scope.read(e['input']['source_candidate'])
    assert fresh['native_id'].startswith('local-audio-edit-') and fresh['native_id'] != original['native_id']
    assert fresh['media'] != original['media'] and not scope.read(fresh['result']).get('prompt_id')
    assert result['known_visual_state'] == 'major' and not result['visual_acceptance_upgraded']
    assert result['source_confirmation_not_inherited_by_fresh_candidate']
    assert 'user_confirmed_issue' not in scope.read(result['conformance_case'])
    assert 'confirmation' not in scope.read(result['routing_case'])
    assert e['calls'] == dict(edits=1, ASR=1, extracts=1)
    assert execution.execute(e['run'])['no_dispatch_on_reentry']
    assert execution.status(e['run'])['audio_route'] == 'accept'
    assert e['calls'] == dict(edits=1, ASR=1, extracts=1)
    route = execution.flow.status(e['run'] / 'source_route/flow')['segments'][0]['evaluation']
    assert route['processor_request']['execute_allowed'] is False
    grant = scope.read(result['execution_grant'])
    assert grant['parent_authority'] == e['input']['authority']
    assert grant['planning_request_is_not_execution_authority']
    clock = scope.read(fresh['audio_clock_receipt'])
    assert clock['native_audio_clock']['samples'] == 720000
    assert clock['codec_output_normalization']['decoded_samples'] == 720896


def test_fresh_ASR_uncertain_extra_is_not_source_user_confirmed_or_second_edit(example):
    e = example; e['mode']['ASR_extra'] = True
    execution.prepare(e['run'], e['binding']())
    out = execution.execute(e['run'])
    assert out['audio_route'] == 'verify_audio'
    result = scope.read(out['result'])
    assert not result['audio_text_conformance_accepted']
    assert e['calls']['edits'] == e['calls']['ASR'] == 1


def test_CPU_claim_unknown_never_replayed_or_inspected(example):
    e = example; e['mode']['edit_unknown'] = True
    execution.prepare(e['run'], e['binding']())
    assert execution.execute(e['run'])['status'] == 'CPU_edit_outcome_unknown'
    assert execution.execute(e['run'])['status'] == 'CPU_edit_outcome_unknown'
    assert e['calls']['edits'] == 1 and e['calls']['ASR'] == 0


def test_ASR_claim_unknown_never_replayed_and_no_repeat_CPU_edit(example):
    e = example; e['mode']['ASR_unknown'] = True
    execution.prepare(e['run'], e['binding']())
    assert execution.execute(e['run'])['status'] == 'ASR_outcome_unknown'
    assert execution.execute(e['run'])['status'] == 'ASR_outcome_unknown'
    assert e['calls']['edits'] == e['calls']['ASR'] == 1
    assert not (e['run'] / 'RESULT.json').exists()


@pytest.mark.parametrize('field,value', [('max_CPU_edits', 2), ('max_ASR_calls', True),
                                       ('max_H3_calls', 1), ('assembly_allowed', True)])
def test_parent_authority_bounds_are_not_relaxed(example, field, value):
    e = example
    auth = scope.read(e['input']['authority']); auth[field] = value
    e['input']['authority'] = e['put']('WRONG_AUTHORITY.json', auth)
    with pytest.raises(ValueError, match='one_CPU_edit'):
        execution.prepare(e['run'], e['binding']())
    assert e['calls']['edits'] == e['calls']['ASR'] == 0


def test_source_old_media_or_asset_mismatch_rejected_before_dispatch(example):
    e = example
    e['input']['asset_manifest'] = e['put']('OTHER_ASSET.json', dict(other=True))
    with pytest.raises(ValueError, match='source_candidate_case_assets_mismatch'):
        execution.prepare(e['run'], e['binding']())


@pytest.mark.parametrize('tamper', ['raw_ASR', 'PCM', 'grant', 'summary'])
def test_completed_cache_deep_tamper_errors_without_any_reexecution(example, tamper):
    e = example
    execution.prepare(e['run'], e['binding']())
    out = execution.execute(e['run']); result = scope.read(out['result'])
    if tamper == 'raw_ASR':
        receipt = scope.read(result['inspection']['asr_receipt'])
        Path(receipt['raw_asr']['path']).write_text('{}')
    elif tamper == 'PCM':
        candidate = scope.read(result['candidate'])
        clock = scope.read(candidate['audio_clock_receipt'])
        Path(clock['native_audio_clock']['media']['path']).write_bytes(b'changed')
    elif tamper == 'grant':
        Path(result['execution_grant']['path']).write_text('{}')
    else:
        result['audio_route'] = 'invented_accept'
        Path(out['result']['path']).write_text(json.dumps(result), encoding='utf-8')
    with pytest.raises(ValueError):
        execution.execute(e['run'])
    assert e['calls'] == dict(edits=1, ASR=1, extracts=1)


def test_historical_native_asset_record_is_SHA_locked_without_traversing_model_install(example):
    e = example
    opaque = e['put']('OLD_ASSET_MANIFEST.json', dict(schema='h3_asset_flow_manifest/v2',
        historical_model=dict(path=r'D:\different_model_install\opaque_model.safetensors', sha256='0' * 64)))
    execution._deep_check(dict(asset_manifest=opaque))
    Path(opaque['path']).write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='audio_evidence_changed'):
        execution._deep_check(dict(asset_manifest=opaque))


def test_CLI_resolves_relative_run_and_has_no_H3_or_assembly_command(example, monkeypatch, capsys):
    file = scope.PROJECT / 'scripts/run_audio_quality_execution_v1.py'
    spec = importlib.util.spec_from_file_location('_audio_execution_cli', file)
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    seen = []
    monkeypatch.setattr(execution, 'status', lambda run: seen.append(run) or dict(status='test'))
    rel = example['run'].relative_to(Path.cwd())
    assert cli.main(['status', '--run', str(rel)]) == 0
    assert seen == [example['run'].resolve()]
    assert json.loads(capsys.readouterr().out)['ok']
    with pytest.raises(SystemExit):
        cli.main(['generate-H3', '--run', str(rel)])
