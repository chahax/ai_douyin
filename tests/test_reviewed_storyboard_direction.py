"""Synthetic binding tests; these fixtures certify no real script or media."""
import copy

import pytest
from PIL import Image

from scripts import run_script_video as runner
from src.content_factory import reviewed_storyboard_direction as direction
from src.content_factory.seedance_frames import bind_frame, image_info, reviewed_frame_reference
from src.trend_intelligence.script_pair import CURRENT_SCRIPT_REVIEW_SCHEMA


@pytest.fixture
def staged(tmp_path):
    shots = []
    cursor = 0
    for index, duration in enumerate((7, 8, 7, 8, 8, 7), 1):
        shots.append({
            'shot_id': f'S{index:02d}', 'start_seconds': cursor,
            'end_seconds': cursor + duration, 'participants': ['角色甲', '角色乙'],
            'scene': '合成固定场景', 'blocking': '甲左乙右，相对而坐',
            'shot_size': '双人中景', 'camera_angle': '视线轴一侧斜侧机位',
            'camera_movement': '固定', 'lighting': '合成固定柔光',
            'dialogue_mode': 'in_scene', 'dialogue_speaker': '角色甲',
            'action': f'合成动作{index}', 'dialogue': f'合成台词{index}。',
            'model_prompt_zh': f'原始测试提示{index}\n合成动作{index}；合成台词{index}。',
            'composition': '双人口型与桌面区域均入画', 'camera': '固定中景',
            'start_frame': f'合成状态{index - 1}', 'end_frame': f'合成状态{index}',
            'audio': '角色甲场内对白；角色乙不发声', 'emotion_and_performance': '测试表情',
            'continuity': '测试连续性说明', 'transition': '承接实际尾态',
            'extra_test_metadata': {'labels': [f'未丢失字段{index}']},
        })
        cursor += duration
    script = {
        'schema': 'detailed_video_script/v4', 'format_kind': 'short',
        'title': '纯合成测试', 'target_duration_seconds': 45, 'aspect_ratio': '9:16',
        'characters': [{'name': '角色甲'}, {'name': '角色乙'}], 'shots': shots,
        'generation': {'method': 'staged_screenplay_bundle',
                       'staged_screenplay_bundle': {'fixture': 'synthetic only'}},
    }
    source = tmp_path / 'synthetic_script.json'
    runner.write(source, script)
    source.with_suffix('.md').write_text('Synthetic fixture, not a reviewed production.', encoding='utf-8')
    source.with_suffix('.audit.json').write_text('{}', encoding='utf-8')
    proof = {
        'schema': CURRENT_SCRIPT_REVIEW_SCHEMA, 'current_passed': True,
        'status': 'current_passed', 'script_json_path': str(source.resolve()),
        'script_json_sha256': runner.sha(source), 'report_path': 'synthetic-test-report-only',
        'candidate_sha256': '1' * 64, 'evidence_sha256': '2' * 64,
        'full_source_evidence_sha256': '3' * 64,
    }
    return script, source, proof


def test_binding_preserves_every_original_shot_field_and_prompt(staged):
    script, source, proof = staged
    plan = direction.build_plan(script, source, proof)
    direction.validate_plan(plan, script, runner.sha(source))
    for shot, bound in zip(script['shots'], plan['shots']):
        assert bound == {'shot_id': shot['shot_id'], 'camera_id': direction.CAMERA_ID,
                         'storyboard': shot}
        assert direction.compile_prompt(script, shot, plan) == shot['model_prompt_zh']
    assert plan['generation']['model_calls'] == 0
    assert plan['generation']['media_review_performed'] is False
    plan['shots'][0]['storyboard']['extra_test_metadata']['labels'].append('mutated')
    assert script['shots'][0]['extra_test_metadata']['labels'] == ['未丢失字段1']
    with pytest.raises(ValueError, match='every shot field'):
        direction.validate_plan(plan, script, runner.sha(source))


def test_binding_rejects_changed_source_stale_proof_and_broken_cut(staged):
    script, source, proof = staged
    altered = copy.deepcopy(script)
    altered['shots'][0]['action'] = 'Unreviewed replacement'
    with pytest.raises(ValueError, match='source file'):
        direction.build_plan(altered, source, proof)
    with pytest.raises(ValueError, match='current saved pair review'):
        direction.build_plan(script, source, {**proof, 'script_json_sha256': '0' * 64})
    altered = copy.deepcopy(script)
    altered['shots'][1]['start_frame'] = 'Different opening state'
    runner.write(source, altered)
    with pytest.raises(ValueError, match='preceding shot exactly'):
        direction.build_plan(altered, source, {**proof, 'script_json_sha256': runner.sha(source)})


def test_prepare_binds_staged_and_rejects_legacy_plan_without_changing_legacy_path(staged, tmp_path, monkeypatch):
    script, source, proof = staged
    monkeypatch.setattr(
        'src.trend_intelligence.saved_script_review.require_current_saved_script_review',
        lambda path: copy.deepcopy(proof),
    )
    folder = tmp_path / 'staged_run'
    manifest = runner.prepare(folder, source, 'Synthetic test authorization only')
    plan = runner.read(folder / 'direction_plan.json')
    assert plan['schema'] == direction.SCHEMA
    assert manifest['direction_sha256'] == runner.sha(folder / 'direction_plan.json')
    assert runner.locked(folder)[1] == script
    old_plan = tmp_path / 'old_plan.json'
    runner.write(old_plan, {'schema': 'conversation_direction/v1'})
    with pytest.raises(ValueError, match='reviewed storyboard mechanical binding'):
        runner.prepare(tmp_path / 'wrong_plan', source, 'Synthetic only', old_plan)
    legacy = copy.deepcopy(script)
    legacy['generation'] = {'method': 'custom_test'}
    runner.write(source, legacy)
    with pytest.raises(ValueError, match='固定座位'):
        runner.prepare(tmp_path / 'legacy', source, 'Synthetic only')


def test_mechanical_camera_accepts_previous_tail_without_reauthoring_actions(staged, tmp_path, monkeypatch):
    script, source, proof = staged
    monkeypatch.setattr(
        'src.trend_intelligence.saved_script_review.require_current_saved_script_review',
        lambda path: copy.deepcopy(proof),
    )
    folder = tmp_path / 'frame_run'
    manifest = runner.prepare(folder, source, 'Synthetic test authorization only')
    plan = runner.read(folder / 'direction_plan.json')
    image = folder / 'synthetic_tail.png'
    Image.new('RGB', (320, 480), 'white').save(image)
    from src.content_factory.script_video_review import REVIEW_CHECKS
    video = folder / 'S01.synthetic.mp4'
    video.write_bytes(b'Synthetic fixture only, not an actual video')
    passed_review = folder / 'S01.synthetic_review.json'
    runner.write(passed_review, {'decision': 'passed', 'checks': {key: True for key in REVIEW_CHECKS},
                                'source_sha256': runner.sha(video), 'script_sha256': manifest['script_sha256']})
    campaign = folder / 'synthetic_campaign.json'
    runner.write(campaign, {'current_series_id': 'series_001', 'attempts': [{
        'id': 'synthetic_1', 'shot': 'S01', 'status': 'passed', 'series_id': 'series_001',
        'video_sha256': runner.sha(video), 'review_path': str(passed_review),
        'review_sha256': runner.sha(passed_review)}]})
    manifest.update(campaign_path=str(campaign), campaign_series_id='series_001')
    runner.write(folder / 'S01.json', {'shot': 'S01', 'provider': 'ark_api', 'status': 'downloaded',
        'script_sha256': manifest['script_sha256'], 'direction_sha256': manifest['direction_sha256'],
        'campaign_attempt_id': 'synthetic_1', 'local_video': str(video), 'video_sha256': runner.sha(video),
        'last_frame': str(image), 'last_frame_sha256': image_info(image)['sha256']})
    synthetic_review = {
        'shot_id': 'S02', 'camera_id': direction.CAMERA_ID,
        'checks': {'composition': True, 'identity': True, 'opening_state': True},
        'notes': 'Synthetic API compatibility test; no actual media reviewed.',
        'evidence': [image.name],
    }
    bind_frame(folder, 'S02', image, synthetic_review, manifest, plan)
    ref, binding = reviewed_frame_reference(folder, 'S02', image, manifest, plan)
    assert binding['camera_id'] == plan['shots'][0]['camera_id'] == plan['shots'][1]['camera_id']
    assert ref.role == 'first_frame'
    shot = script['shots'][1]
    prompt = runner.compile_execution_prompt(script, shot, plan, use_input_first_frame=True,
                                              timing_mode='ordered')
    assert prompt.startswith(shot['model_prompt_zh'] + '\n')
    assert '真实首帧' in prompt and '复位道具' in prompt
    assert shot == plan['shots'][1]['storyboard']
    with pytest.raises(ValueError, match='exact reviewed storyboard'):
        direction.compile_prompt(script, {**shot, 'action': 'replacement'}, plan)
