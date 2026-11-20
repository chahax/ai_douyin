import hashlib
import json
import sys
from pathlib import Path

import pytest

from scripts import prepare_source_emotion_analysis as prepare_module
from scripts import publish_source_emotion_analysis as publish_module
from src.trend_intelligence.emotion_evidence import source_emotion


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


@pytest.mark.parametrize('duration,seconds,count', [(104, 12, 9), (36, 12, 3), (2, 12, 1), (25.1, 8, 4)])
def test_full_windows_cover_original_timeline_without_gaps(duration, seconds, count):
    spans = prepare_module.full_windows(duration, seconds)
    assert len(spans) == count
    assert spans[0][0] == 0
    assert spans[-1][1] == duration
    assert all(end > start and end - start <= seconds for start, end in spans)
    assert all(left[1] == right[0] for left, right in zip(spans, spans[1:]))
    assert sum(end - start for start, end in spans) == pytest.approx(duration)


@pytest.mark.parametrize('seconds', [0, 3.9, 30.1, float('nan'), float('inf')])
def test_full_windows_reject_unbounded_model_input(seconds):
    with pytest.raises(ValueError, match='window-seconds'):
        prepare_module.full_windows(104, seconds)


@pytest.mark.parametrize('duration', [-1, 0, float('nan'), float('inf')])
def test_full_windows_reject_invalid_source_duration(duration):
    with pytest.raises(ValueError, match='duration'):
        prepare_module.full_windows(duration)


def test_tiny_final_remainder_is_covered_without_an_empty_media_job():
    spans = prepare_module.full_windows(24.001)
    assert spans[0] == (0, 12)
    assert spans[-1][1] == 24.001
    assert spans[-2][1] == spans[-1][0]
    assert all(1 <= end - start <= 12 for start, end in spans)


def preparation_fixture(tmp_path, monkeypatch, *, duration=104, mode='full'):
    video = tmp_path / 'original.mp4'
    video.write_bytes(b'original source media')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    transcript = tmp_path / 'transcript.json'
    write_json(transcript, {'provenance': {'source_video_sha256': digest},
                            'result': [{'text': '测试转写'}]})
    sources, manifest, output = tmp_path / 'sources.json', tmp_path / 'originals.json', tmp_path / 'prepared'
    write_json(sources, [{'source_id': 'douyin:123', 'title': 'reference', 'metric_kind': 'likes',
                         'metric_value': 1000, 'media_evidence': {
                             'source_video_sha256': digest, 'duration_seconds': duration}}])
    write_json(manifest, {'items': [{'item_id': 'douyin:123', 'video': str(video),
                                     'transcript': str(transcript)}]})
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(json.dumps(command).encode('utf-8'))

    monkeypatch.setattr(prepare_module.subprocess, 'run', run)
    prepared = prepare_module.prepare(sources, manifest, output, sampling_mode=mode)
    return output, prepared['sources'][0], commands, digest


def test_default_prepare_maps_full_windows_and_keeps_preview_continuous(tmp_path, monkeypatch):
    output, source, commands, _ = preparation_fixture(tmp_path, monkeypatch)
    assert source['coverage'] == 'full'
    assert source['audio_coverage_seconds'] == 104
    assert source['preview_has_artificial_joins'] is False
    assert source['artificial_preview_joins'] == []
    assert len(source['windows']) == 9
    assert source['windows'][-1]['source_start'] == 96
    assert source['windows'][-1]['source_end'] == 104
    assert all(w['sample_start'] == w['source_start'] and w['sample_end'] == w['source_end']
               and w['clip_start'] == 0 for w in source['windows'])
    # The preview is a single transcode from the original, not a concat of
    # independently encoded analysis windows that could invent source cuts.
    assert len(commands) == 10
    assert not any('concat' in command for command in commands)
    assert Path(commands[-1][-1]).name == 'sample.mp4'
    assert commands[-1][commands[-1].index('-t') + 1] == '104.0'
    jobs = json.loads((output / 'jobs.json').read_text(encoding='utf-8'))
    assert len(jobs) == 9 and all(job['max_new_tokens'] <= 600 for job in jobs)
    assert all('sample.mp4' not in job['video'] for job in jobs)
    assert '96.000—104.000' in jobs[-1]['question']
    assert '演员表现与观众感受不同' in jobs[-1]['question']
    assert '不臆测人物动机' in jobs[-1]['question']
    assert '限100' not in jobs[-1]['question']
    assert '分析分窗边界不是原片剪辑点' in jobs[-1]['question']
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['schema'] == 'source_emotion_samples/v1'
    assert manifest['status'] == 'prepared_not_observed'
    assert manifest['external_upload'] is False


def test_explicit_legacy_preserves_old_sampling_and_marks_artificial_joins(tmp_path, monkeypatch):
    output, source, commands, _ = preparation_fixture(tmp_path, monkeypatch, mode='legacy')
    assert [(w['source_start'], w['source_end']) for w in source['windows']] == [(0, 8), (48, 56), (96, 104)]
    assert source['coverage'] == 'sampled_begin_middle_end'
    assert source['audio_coverage_seconds'] == 24
    assert source['preview_has_artificial_joins'] is True
    assert source['artificial_preview_joins'] == [8, 16]
    assert len(commands) == 4 and 'concat' in commands[-1]
    before = (output / 'manifest.json').read_bytes()
    with pytest.raises(ValueError, match='new output'):
        prepare_module.prepare(tmp_path / 'sources.json', tmp_path / 'originals.json', output)
    assert (output / 'manifest.json').read_bytes() == before


def write_observations(source):
    for window, path in zip(source['windows'], source['window_observation_paths'], strict=True):
        write_json(Path(path), {'video': window['clip_path'], 'source_sha256': window['clip_sha256'],
                               'use_audio_in_video': True, 'audio_only': False,
                               'response': '语气急切，动作是放下物件。末尾语气不能确认。'})


def test_publish_full_windows_remains_unverified_and_legacy_consumer_can_read(tmp_path, monkeypatch):
    output, source, _, digest = preparation_fixture(tmp_path, monkeypatch)
    write_observations(source)
    index = tmp_path / 'index.json'
    monkeypatch.setattr(sys, 'argv', ['publish_source_emotion_analysis', str(output / 'manifest.json'),
                                     '--index', str(index)])
    publish_module.main()
    result = source_emotion('douyin:123', digest, index_path=index)
    assert result['status'] == 'model_observed_unverified'
    assert result['coverage'] == 'full'
    assert len(result['windows']) == 9
    limits = ' '.join(result['limitations'])
    assert '全片原声音轨按连续窗口覆盖' in limits
    assert '逐帧完整审核' in limits and '观众情绪测量' in limits
    assert '仅取开头' not in limits
    report = Path(json.loads(index.read_text())['sources']['douyin:123']['artifact_path'])
    before = report.read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        publish_module.main()
    assert report.read_bytes() == before


@pytest.mark.parametrize('mutate', ['gap', 'ending', 'overlap'])
def test_publish_does_not_label_incomplete_window_map_as_full(mutate):
    source = {'source_duration_seconds': 24, 'coverage': 'full', 'windows': [
        {'source_start': 0, 'source_end': 12}, {'source_start': 12, 'source_end': 24}]}
    if mutate == 'gap':
        source['windows'][1]['source_start'] = 13
    elif mutate == 'ending':
        source['windows'][1]['source_end'] = 23
    else:
        source['windows'][1]['source_start'] = 11
    with pytest.raises(ValueError):
        publish_module.coverage_limitations(source)


def test_publish_rejects_observation_bound_to_another_window(tmp_path, monkeypatch):
    output, source, _, _ = preparation_fixture(tmp_path, monkeypatch)
    write_observations(source)
    first = Path(source['window_observation_paths'][0])
    first.write_bytes(Path(source['window_observation_paths'][1]).read_bytes())
    monkeypatch.setattr(sys, 'argv', ['publish_source_emotion_analysis', str(output / 'manifest.json'),
                                     '--index', str(tmp_path / 'index.json')])
    with pytest.raises(ValueError, match='prepared source window'):
        publish_module.main()


def test_publish_legacy_limitations_remain_sampled():
    limits = publish_module.coverage_limitations({'source_duration_seconds': 104,
        'coverage': 'sampled_begin_middle_end',
        'windows': [{'source_start': start, 'source_end': end}
                    for start, end in prepare_module.windows(104)]})
    assert '仅取开头、中部和末尾各8秒' in ' '.join(limits)
