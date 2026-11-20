"""Preparation/failure checks only; never load LaMa or process real media."""
from pathlib import Path

import pytest

from scripts import repair_h3_native_subtitles as repair


@pytest.fixture(autouse=True)
def no_weight_loading(monkeypatch):
    monkeypatch.setattr(repair.pixel, 'CpuLama', lambda *a, **k: pytest.fail('unit test must not load weights'))


def test_wrong_source_SHA_refuses_before_probe_or_output(tmp_path, monkeypatch):
    source = tmp_path/'source.mp4'; source.write_bytes(b'synthetic fixture')
    monkeypatch.setattr(repair, 'probe', lambda *a: pytest.fail('must reject SHA before probe'))
    out = tmp_path/'isolated'
    with pytest.raises(ValueError, match='source_SHA'):
        repair.setup(source, '0'*64, out, tmp_path/'no_weights', None)
    assert not out.exists()


def test_output_cannot_be_source_parent_or_ancestor(tmp_path):
    source = tmp_path/'source.mp4'; source.write_bytes(b'preserve original')
    before = source.read_bytes()
    with pytest.raises(ValueError, match='isolated_output'):
        repair.setup(source, repair.bind(source)['sha256'], tmp_path, tmp_path/'weights', None)
    assert source.read_bytes() == before


def test_unsupported_geometry_fails_without_loading_model(tmp_path, monkeypatch):
    source = tmp_path/'source.mp4'; source.write_bytes(b'fixture')
    weights = tmp_path/'weights.pt'; weights.write_bytes(b'not a real model; protocol fixture')
    monkeypatch.setattr(repair, 'WEIGHT_BYTES', weights.stat().st_size)
    monkeypatch.setattr(repair, 'WEIGHT_SHA', repair.bind(weights)['sha256'])
    monkeypatch.setattr(repair, 'probe', lambda _: dict(streams=[
        dict(codec_type='video', width=512, height=512, r_frame_rate='24/1', nb_read_frames='124'),
        dict(codec_type='audio', codec_name='aac')]))
    with pytest.raises(ValueError, match='736x1312'):
        repair.setup(source, repair.bind(source)['sha256'], tmp_path/'out', weights, None)


def test_full_missing_or_changed_canary_refuses_before_model_load(tmp_path, monkeypatch):
    run = tmp_path/'run'; run.mkdir()
    config = dict(source={'path':'fixture','sha256':'0'*64}, detector=repair.pixel.DEFAULT)
    repair.freeze(run/'CONFIG.json', config)
    monkeypatch.setattr(repair, 'setup', lambda *a: (run, config))
    args = ['full','--source','fixture','--expected-sha','0'*64,'--run',str(run),
            '--weights','fixture','--detector-config','fixture']
    with pytest.raises(ValueError, match='canary_required'):
        repair.main(args)
    repair.freeze(run/'CANARY.json', dict(config=repair.bind(run/'CONFIG.json'), source=config['source'],
        artifacts=[], rows=[{}]*8, all_mask_outside_diff_before_encode_zero=True))
    (run/'CONFIG.json').write_text('{"changed_detector":true}', encoding='utf-8')
    with pytest.raises(ValueError, match='canary_source_config_or_code'):
        repair.main(args)


def test_FFmpeg_mapping_preserves_original_audio_without_video_trimming(tmp_path):
    source = tmp_path/'original with spaces.mp4'
    decoder, encoder = repair.commands(source, tmp_path/'partial.mp4', 362)
    assert decoder[decoder.index('-map')+1] == '0:v:0'
    assert [encoder[i+1] for i, value in enumerate(encoder) if value == '-map'] == ['0:v:0','1:a:0']
    assert encoder[encoder.index('-c:a')+1] == 'copy'
    assert encoder[encoder.index('-frames:v')+1] == '362'
    assert '-n' in encoder and str(source) in encoder
    assert not set(('-ss','-t','-shortest')) & set(encoder)


def test_encoder_start_failure_closes_only_its_own_decoder_and_preserves_source(tmp_path, monkeypatch):
    source = tmp_path/'source.mp4'; source.write_bytes(b'unchanged source fixture')
    run = tmp_path/'out'; run.mkdir()
    config = dict(source=repair.bind(source), frames=362)
    events = []
    class Decoder:
        def poll(self): return None
        def terminate(self): events.append('terminate')
        def wait(self, timeout): events.append(('wait',timeout)); return 0
    def popen(*args, **kwargs):
        if not events:
            events.append('started'); return Decoder()
        raise OSError('synthetic encoder startup failure')
    monkeypatch.setattr(repair, 'validate_canary', lambda *a: {})
    monkeypatch.setattr(repair.pixel, 'audio_packets', lambda *a: {'fixture_only':True})
    monkeypatch.setattr(repair.subprocess, 'Popen', popen)
    with pytest.raises(OSError, match='encoder startup'):
        repair.full(run, config, None)
    assert events == ['started','terminate',('wait',30)]
    assert source.read_bytes() == b'unchanged source fixture'
    assert not (run/'FULL_RESULT.json').exists()
