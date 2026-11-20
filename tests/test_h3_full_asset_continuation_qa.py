"""Pixel/installed-source protocol tests, with no HTTP/GPU/model calls."""
from copy import deepcopy
import hashlib
from pathlib import Path

from PIL import Image
import pytest

from scripts import qa_h3_full_asset_continuation as qa
from tests.test_h3_story_opening_sample_qa import write


def asset_fixture(root, monkeypatch):
    home = root / 'assets'
    home.mkdir()
    source = home / 'source.png'
    image = Image.new('RGB', (64, 96))
    image.putdata([(x * 3 % 256, y * 2 % 256, (x + y) * 2 % 256) for y in range(96) for x in range(64)])
    image.save(source)
    video = home / 'synthetic_not_video.mp4'
    video.write_bytes(b'CPU protocol fixture only; not generated media')
    record = home / 'synthetic_record.json'
    write(record, dict(fixture_only=True))
    accepted = dict(qa.previous_qa.RETAINED)
    accepted['S02'] = ('synthetic_native', qa.sha(video))
    monkeypatch.setattr(qa.previous_qa, 'RETAINED', accepted)
    verification = home / 'FRAME_VERIFICATION.json'
    write(verification, dict(source_video=qa.bind(video), native_id='synthetic_native', CPU_only=True,
          frames=[dict(frame_index=0, frame=qa.bind(source), exact_source_decode_pixels=True,
                       rgb24_pixels_sha256=hashlib.sha256(image.tobytes()).hexdigest())]))
    refs = []
    regions = [(0, 0, 32, 64), (32, 0, 32, 64), (0, 32, 32, 64), (0, 0, 64, 32), (0, 64, 64, 32)]
    for index, (x, y, width, height) in enumerate(regions):
        p = home / f'P{index+1}.png'
        crop = image.crop((x, y, x + width, y + height))
        crop.save(p)
        refs.append(dict(slot=index, label=f'P{index+1}', tag=f'<Picture {index+1}>',
             asset_version=qa.FIXED_VERSION, kind='character' if index < 3 else 'environment_detail',
             actor_id=qa.EXPECTED_ACTORS[index] if index < 3 else None,
             entity_id=qa.EXPECTED_ACTORS[index] if index < 3 else 'same_approved_room',
             intended_person_count=1 if index < 3 else 0,
             source=dict(native_id='synthetic_native', video=qa.bind(video), frame_index=0, fps=24,
                         frame=qa.bind(source), qa_report=qa.bind(record)),
             roi=dict(x=x, y=y, width=width, height=height), image=qa.bind(p),
             derivation=dict(operation='PIL_RGB_integer_crop_only', resize=None, rotation_degrees=0,
                  upscale=False, source_orientation_preserved=True, exact_pixels_sha256_kind='RGB24_row_major_bytes',
                  exact_pixels_sha256=hashlib.sha256(crop.tobytes()).hexdigest())))
    manifest = home / 'ASSET_MANIFEST.json'
    write(manifest, dict(schema=qa.FIXED_SCHEMA, asset_version=qa.FIXED_VERSION, fixed_reference_count=5,
          fixed_order=['P1', 'P2', 'P3', 'P4', 'P5'], source_native_id='synthetic_native',
          source_video=qa.bind(video), source_native_result=qa.bind(record), source_QA_binding=qa.bind(record),
          source_frame_verification=qa.bind(verification), references=refs))
    return manifest


def test_fixed_refs_are_exact_RGB_crops_not_fake_views(tmp_path, monkeypatch):
    path = asset_fixture(tmp_path, monkeypatch)
    value = qa.fixed_assets(qa.bind(path), tmp_path)
    assert value['reference_order'] == ['P1', 'P2', 'P3', 'P4', 'P5']
    assert value['identity_quality_passed'] is False
    assert all(not r['semantic_identity_verified_by_CPU'] for r in value['references'])


def test_relabelled_or_reordered_character_slot_is_rejected(tmp_path, monkeypatch):
    path = asset_fixture(tmp_path, monkeypatch)
    value = qa.read(path)
    value['references'][1], value['references'][2] = value['references'][2], value['references'][1]
    write(path, value)
    with pytest.raises(ValueError, match='fixed_slot_label_or_reference_order'):
        qa.fixed_assets(qa.bind(path), tmp_path)


def test_consistent_but_invented_crop_metadata_cannot_replace_source_pixels(tmp_path, monkeypatch):
    path = asset_fixture(tmp_path, monkeypatch)
    value = qa.read(path)
    row = value['references'][1]
    image = Image.new('RGB', (32, 64), 'orange')
    image.save(row['image']['path'])
    row['image'] = qa.bind(Path(row['image']['path']))
    row['derivation']['exact_pixels_sha256'] = hashlib.sha256(image.tobytes()).hexdigest()
    write(path, value)
    with pytest.raises(ValueError, match='fixed_crop_actual_RGB_pixels'):
        qa.fixed_assets(qa.bind(path), tmp_path)


def test_background_slot_is_not_an_unlabelled_extra_character(tmp_path, monkeypatch):
    path = asset_fixture(tmp_path, monkeypatch)
    value = qa.read(path)
    value['references'][3]['intended_person_count'] = 1
    write(path, value)
    with pytest.raises(ValueError, match='environment_details_not_additional_cast'):
        qa.fixed_assets(qa.bind(path), tmp_path)


def test_official_nodes_and_model_encode_all_six_plus_guide(tmp_path, monkeypatch):
    path = asset_fixture(tmp_path, monkeypatch)
    refs = qa.fixed_assets(qa.bind(path), tmp_path)['references']
    tail = tmp_path / 'native_tail.png'
    Image.new('RGB', (736, 1312), 'gray').save(tail)
    result = qa.cpu_source_protocol(refs, qa.bind(tail), tmp_path)
    assert [r['tag'] for r in result['reference_VAE_calls']] == ['P1', 'P2', 'P3', 'P4', 'P5', 'P6']
    assert result['guide_VAE_call']['tag'] == 'P6'
    assert result['guide_VAE_call']['pixel_sha'] == result['reference_VAE_calls'][5]['pixel_sha']
    assert result['model_positive_refs'] == 6 and result['model_positive_keyframes'] == 1
    assert result['guide_frame'] == 0 and result['GPU_model_inference'] is False


def test_reference_capacity_does_not_silently_drop_a_fixed_asset(tmp_path, monkeypatch):
    path = asset_fixture(tmp_path, monkeypatch)
    refs = qa.fixed_assets(qa.bind(path), tmp_path)['references']
    tail = tmp_path / 'native_tail.png'
    Image.new('RGB', (736, 1312)).save(tail)
    with pytest.raises(ValueError, match='five_fixed_refs_required'):
        qa.cpu_source_protocol(refs[:4], qa.bind(tail), tmp_path)


def pixel_graph_fixture(root, monkeypatch):
    manifest = asset_fixture(root, monkeypatch)
    fixed = qa.fixed_assets(qa.bind(manifest), root)['references']
    tail = root / 'native_tail.png'
    Image.new('RGB', (736, 1312), 'gray').save(tail)
    images = [r['image'] for r in fixed] + [qa.bind(tail)]
    graph, rows = {}, []
    for i, image in enumerate(images):
        staged = root / 'staged' / f'P{i+1}.png'
        staged.parent.mkdir(exist_ok=True)
        staged.write_bytes(Path(image['path']).read_bytes())
        graph[f'ref_{i}'] = dict(class_type='LoadImage', inputs=dict(image=f'fixture/P{i+1}.png'))
        rows.append(dict(slot=i, label=f'P{i+1}', source=image, staged=qa.bind(staged),
                         node_id=f'ref_{i}', input_name=f'fixture/P{i+1}.png'))
    inputs = dict(clip=['128', 0], vae=['119', 0], width=736, height=1312, length=362,
                  ref_image_size='match', prompt=' '.join(f'<Picture {i}>' for i in range(1, 7)))
    for i in range(6):
        inputs[f'ref_images.ref_image_{i}'] = [f'ref_{i}', 0]
    graph.update(condition=dict(class_type='MiniMaxH3ReferenceToVideo', inputs=inputs),
         guide_start=dict(class_type='MiniMaxH3AddGuide', inputs=dict(positive=['condition', 0],
                          latent=['condition', 1], vae=['119', 0], image=['ref_5', 0], frame_idx=0)))
    graph['119'] = dict(class_type='VAELoader', inputs=dict(vae_name='minimax_h3_video_vae.safetensors'))
    graph['128'] = dict(class_type='CLIPLoader', inputs=dict(clip_name='synthetic_protocol_encoder'))
    graph['127'] = dict(class_type='UNETLoader', inputs=dict(unet_name=qa.REF_MODEL))
    graph['126'] = dict(class_type='BasicGuider', inputs=dict(conditioning=['guide_start', 0], model=['127', 0]))
    graph['125'] = dict(class_type='SamplerCustomAdvanced', inputs=dict(guider=['126', 0], latent_image=['condition', 1]))
    for role, index in [('first', 0), ('last', 361)]:
        graph['pick_' + role] = dict(class_type='ImageFromBatch', inputs=dict(image=['122', 0], batch_index=index, length=1))
        graph['save_' + role] = dict(class_type='SaveImage', inputs=dict(images=['pick_' + role, 0]))
    return graph, rows


def test_actual_six_pixels_reach_ref_VAE_positive_and_guide0(tmp_path, monkeypatch):
    graph, rows = pixel_graph_fixture(tmp_path, monkeypatch)
    result = qa.graph_pixel_routes(graph, rows, tmp_path)
    assert result['actual_positive_reference_count'] == 6
    assert result['actual_positive_guide_frame'] == 0
    assert result['CPU_identity_quality_verified'] is False


def test_loaded_but_disconnected_or_swapped_reference_is_not_counted(tmp_path, monkeypatch):
    graph, rows = pixel_graph_fixture(tmp_path, monkeypatch)
    graph['condition']['inputs']['ref_images.ref_image_3'] = ['ref_2', 0]
    with pytest.raises(ValueError, match='actual_six_autogrow_image_inputs_or_order'):
        qa.graph_pixel_routes(graph, rows, tmp_path)


def test_optional_VAE_cannot_be_omitted_and_called_pixel_conditioning(tmp_path, monkeypatch):
    graph, rows = pixel_graph_fixture(tmp_path, monkeypatch)
    graph['condition']['inputs'].pop('vae')
    with pytest.raises(ValueError, match='real_video_VAE_required'):
        qa.graph_pixel_routes(graph, rows, tmp_path)


def test_guide_bypass_does_not_count_as_positive_sampler_consumption(tmp_path, monkeypatch):
    graph, rows = pixel_graph_fixture(tmp_path, monkeypatch)
    graph['126']['inputs']['conditioning'] = ['condition', 0]
    with pytest.raises(ValueError, match='actual_positive_sampler'):
        qa.graph_pixel_routes(graph, rows, tmp_path)


def test_tail_ref_slot_is_also_the_exact_guide_not_a_fixed_portrait(tmp_path, monkeypatch):
    graph, rows = pixel_graph_fixture(tmp_path, monkeypatch)
    graph['guide_start']['inputs']['image'] = ['ref_0', 0]
    with pytest.raises(ValueError, match='P6_must_also_be_actual_frame_zero'):
        qa.graph_pixel_routes(graph, rows, tmp_path)


def test_old_fl2va_model_name_cannot_pass_ref2va_metadata(tmp_path, monkeypatch):
    graph, rows = pixel_graph_fixture(tmp_path, monkeypatch)
    graph['127']['inputs']['unet_name'] = 'minimax_h3_fl2va_pruned_int8_convrot.safetensors'
    with pytest.raises(ValueError, match='real_Ref2VA_checkpoint_required'):
        qa.graph_pixel_routes(graph, rows, tmp_path)
