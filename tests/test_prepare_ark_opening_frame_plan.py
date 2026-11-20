"""Offline mechanical still-plan checks; no model calls or media approval."""
import copy
import hashlib
import json
from datetime import datetime

import pytest

from scripts import run_script_video as runner
from src.content_factory import ark_opening_frame as opening
from src.content_factory import opening_frame_plan as plan_module
from src.content_factory.seedance_client import ARK_BASE_URL, ARK_MINI_MODEL, SeedanceConfig
from test_reviewed_storyboard_direction import staged


OLD_STATE = '角色乙左手贴在P2左上角，右手在桌沿，目光看P2。'
NEW_STATE = '角色乙双手搭在桌沿，目光看P2。'
PROPS = ('角色甲两手在桌沿；P1（第一份合同）：角色甲面前摊开，未签；'
         'P2（第二份合同）：角色乙面前摊开，未签；P3（黑色签字笔）：桌中平放。')
DYNAMIC = ('ACTION_MARKER_ONLY', 'DIALOGUE_MARKER_ONLY', 'END_FRAME_MARKER_ONLY',
           'ARC_MARKER_ONLY', 'PERFORMANCE_MARKER_ONLY', 'MODEL_PROMPT_MARKER_ONLY')


@pytest.fixture
def plan_case(staged, tmp_path, monkeypatch):
    original, _, original_proof = staged
    config = SeedanceConfig(api_key='synthetic-only', base_url=ARK_BASE_URL,
                            model=ARK_MINI_MODEL, provider='ark_api')
    monkeypatch.setattr(SeedanceConfig, 'from_env', classmethod(lambda cls, *args, **kw: config))
    proofs = {}
    monkeypatch.setattr('src.trend_intelligence.saved_script_review.require_current_saved_script_review',
                        lambda path: copy.deepcopy(proofs[str(path)]))

    def create(name='default', state=NEW_STATE, *, appearance=True, camera='方桌西侧固定斜侧机位'):
        source = tmp_path / (name + '.json')
        script = copy.deepcopy(original)
        for index, person in enumerate(script['characters']):
            person.update(appearance=f'外观固定{index}，黑发。', wardrobe=f'服装固定{index}，纯色衬衫。',
                          performance_arc=DYNAMIC[3])
        if not appearance:
            script['characters'][0].pop('appearance')
        for index, shot in enumerate(script['shots']):
            shot.update(scene='固定茶室方桌前。', blocking='角色甲北侧朝南、角色乙南侧朝北，隔桌相向对坐。',
                        camera_angle=camera, camera='固定双人中景；' + camera,
                        action=DYNAMIC[0], dialogue=DYNAMIC[1], emotion_and_performance=DYNAMIC[4],
                        model_prompt_zh=DYNAMIC[5], end_frame=DYNAMIC[2] + str(index))
            shot['start_frame'] = state + '；' + PROPS if index == 0 else DYNAMIC[2] + str(index - 1)
        runner.write(source, script)
        source.with_suffix('.md').write_text('Synthetic source only', encoding='utf-8')
        source.with_suffix('.audit.json').write_text('{}', encoding='utf-8')
        proof = copy.deepcopy(original_proof)
        proof.update(script_json_path=str(source.resolve()), script_json_sha256=runner.sha(source))
        proofs[str(source.resolve())] = proof
        folder = tmp_path / 'data/video_generation' / ('run_' + name)
        manifest = runner.prepare(folder, source, 'Synthetic test only', provider='ark_api')
        output = folder / 'opening_plan.json'
        return {'folder': folder, 'script': script, 'source': source, 'manifest': manifest,
                'output': output, 'proof': proof}
    return create


def prepare(case):
    return plan_module.prepare_opening_frame_plan(case['folder'], case['output'])


@pytest.mark.parametrize('state,expected,absent', [
    (OLD_STATE, '左手贴在第二份合同左上角', '双手搭在桌沿'),
    (NEW_STATE, '双手搭在桌沿', '左手贴在第二份合同左上角'),
])
def test_exact_current_source_initial_hand_state_is_used(plan_case, state, expected, absent):
    case = plan_case(state=state)
    snapshots = {path: path.read_bytes() for path in case['folder'].rglob('*') if path.is_file()}
    plan = prepare(case)
    assert plan['schema'] == opening.PLAN_SCHEMA and plan['shot_id'] == 'S01'
    assert plan['script_sha256'] == case['manifest']['script_sha256']
    assert plan['direction_sha256'] == case['manifest']['direction_sha256']
    assert expected in plan['prompt'] and absent not in plan['prompt']
    assert runner.read(case['output']) == plan
    assert all(path.read_bytes() == raw for path, raw in snapshots.items())
    assert plan['provenance']['source_fields']['/shots/0/start_frame']['value'] == case['script']['shots'][0]['start_frame']


def test_provenance_contains_only_source_static_fields_with_exact_values_and_hashes(plan_case):
    case = plan_case()
    plan = prepare(case)
    provenance = plan['provenance']
    assert provenance['schema'] == 'mechanical_opening_frame_plan/v1'
    assert provenance['method'] == 'mechanical' and provenance['model_calls'] == 0
    assert provenance['text_review'] == provenance['media_review'] == 'pending'
    assert provenance['render_template'] == 'locked_static_opening/v1'
    assert provenance['character_count'] == 2 and provenance['prop_count'] == 3
    assert datetime.fromisoformat(provenance['created_at']).utcoffset() is not None
    expected = {'/aspect_ratio': case['script']['aspect_ratio']}
    for index, character in enumerate(case['script']['characters']):
        for key in ('name', 'appearance', 'wardrobe'):
            expected[f'/characters/{index}/{key}'] = character[key]
    for key in ('scene', 'blocking', 'camera', 'shot_size', 'camera_angle', 'camera_movement',
                'lighting', 'start_frame', 'participants'):
        expected['/shots/0/' + key] = case['script']['shots'][0][key]
    assert set(provenance['source_fields']) == set(expected)
    for pointer, value in expected.items():
        assert provenance['source_fields'][pointer] == {
            'value': value, 'sha256': hashlib.sha256(opening._bytes(value)).hexdigest()}
    encoded = json.dumps(plan, ensure_ascii=False)
    assert all(marker not in encoded for marker in DYNAMIC)
    assert not (case['folder'] / 'frame_reviews').exists()


def test_two_runs_never_reuse_an_earlier_opening_state(plan_case):
    old = plan_case('old', OLD_STATE)
    new = plan_case('new', NEW_STATE)
    old_plan, new_plan = prepare(old), prepare(new)
    assert old_plan['script_sha256'] != new_plan['script_sha256']
    assert '左手贴在第二份合同左上角' in old_plan['prompt']
    assert '左手贴在第二份合同左上角' not in new_plan['prompt']
    assert '双手搭在桌沿' in new_plan['prompt']


def test_revoked_current_review_blocks_output(plan_case, monkeypatch):
    case = plan_case()
    monkeypatch.setattr(runner, 'require_project_script_review', lambda *args: {'current_passed': False})
    with pytest.raises(ValueError):
        prepare(case)
    assert not case['output'].exists()


def test_changed_locked_source_blocks_output(plan_case):
    case = plan_case()
    source = case['folder'] / 'locked_script.json'
    source.write_bytes(source.read_bytes() + b'\n')
    with pytest.raises(ValueError):
        prepare(case)
    assert not case['output'].exists()


def test_outside_run_output_is_rejected(plan_case):
    case = plan_case()
    outside = case['folder'].parent / 'outside.json'
    with pytest.raises(ValueError):
        plan_module.prepare_opening_frame_plan(case['folder'], outside)
    assert not outside.exists()


def test_existing_output_is_preserved(plan_case):
    case = plan_case()
    prepare(case)
    before = case['output'].read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        prepare(case)
    assert case['output'].read_bytes() == before


@pytest.mark.parametrize('options', [{'appearance': False}, {'camera': '正面朝向角色甲的固定机位'}])
def test_missing_appearance_or_unsupported_camera_requires_explicit_resolution(plan_case, options):
    case = plan_case(**options)
    with pytest.raises(ValueError):
        prepare(case)
    assert not case['output'].exists()


def test_cli_prepares_plan_without_instantiating_model_or_making_http_request(plan_case, monkeypatch, capsys):
    from scripts import prepare_ark_opening_frame_plan as cli
    from src.shared.llm_client import LLMClient
    import httpx
    case = plan_case()
    monkeypatch.setattr(cli, 'ROOT', case['folder'].parents[2])
    def forbidden(*args, **kwargs):
        raise AssertionError('Mechanical plan preparation cannot call a model or HTTP')
    monkeypatch.setattr(LLMClient, '__init__', forbidden)
    monkeypatch.setattr(httpx.Client, 'request', forbidden)
    monkeypatch.setattr(cli.sys, 'argv', ['prepare_ark_opening_frame_plan.py', '--run-dir', str(case['folder']),
                                        '--output', str(case['output'])])
    cli.main()
    assert case['output'].is_file()
    plan = runner.read(case['output'])
    assert plan['provenance']['model_calls'] == 0 and plan['provenance']['media_review'] == 'pending'
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary['model_calls'] == 0 and summary['media_generation'] is False
