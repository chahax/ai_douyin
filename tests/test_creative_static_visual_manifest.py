import json
from copy import deepcopy
from pathlib import Path
import pytest
from src.content_factory.creative_static_visual_manifest import validate_static_manifest, style_from_manifest
from src.content_factory.creative_segmented_director import compile_execution_storyboard, bind_segmented_director, STATIC_VISUAL_VERSION, PROJECTED_VISUAL_VERSION, AUTHORITATIVE_VERSION
from src.content_factory.creative_workflow_contract import CreativeContractError


def manifest():
    return {'schema':'static_visual_manifest_v1',
        'render':{'style_option_id':'S01','visual_medium':'二维手绘动画','palette':'低饱和灰蓝米白','light_source':'右上暖灯光与左侧冷色余光'},
        'characters':[{'id':'C01','name':'林遥','age_group':'成年','hair':'中长发','clothing':'深灰长款通勤外套','body_shape':'成年体型'},
                      {'id':'C02','name':'陈禾','age_group':'成年','hair':'短发','clothing':'浅灰针织开衫','body_shape':'成年体型'}],
        'props':[{'id':'P01','name':'文件夹','appearance':'墨蓝色A4平整封面','owner_id':'C02'}],
        'scene':{'name':'办公室','elements':[{'id':'E01','name':'办公桌','appearance':'米白桌面'}, {'id':'E02','name':'椅子','appearance':'深灰靠背椅'}],
                 'relations':[{'subject':'E02','relation':'behind','reference':'E01'}]}}


def test_real_paid_repair_legacy_style_cannot_reenter_execution_prompt():
    path = Path('data/production_trials/say_no_v4_paid_three_20260927/repair.effective.json')
    if not path.exists(): pytest.skip('local paid receipt unavailable')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    original = deepcopy(value)
    effective = compile_execution_storyboard(value, static_manifest=manifest())
    prompt = effective['shots'][0]['prompt']
    assert '双手将墨蓝色文件夹从桌面拿起握于胸前' not in prompt
    assert '肩线自然微紧' not in prompt
    assert '陈禾站立于桌旁，椅在身后空着' not in prompt
    assert original['shots'][0]['visible_performance'] in prompt
    assert '浅灰针织开衫' in prompt
    assert effective['style'] == style_from_manifest(manifest())
    assert value == original
    assert compile_execution_storyboard(value)['shots'][0]['prompt'] == value['shots'][0]['prompt']


def test_manifest_rejects_pose_keys_and_people_as_fixed_geometry():
    value = manifest(); value['characters'][0]['pose'] = '站立'
    with pytest.raises(CreativeContractError, match='字段'): validate_static_manifest(value)
    value = manifest(); value['scene']['relations'][0]['subject'] = 'C01'
    with pytest.raises(CreativeContractError, match='固定空间关系'): validate_static_manifest(value)


def test_manifest_rejects_unknown_owner_and_duplicate_identity():
    value = manifest(); value['props'][0]['owner_id'] = 'C99'
    with pytest.raises(CreativeContractError, match='归属'): validate_static_manifest(value)
    value = manifest(); value['characters'][1]['id'] = 'C01'
    with pytest.raises(CreativeContractError, match='唯一'): validate_static_manifest(value)


def test_new_binding_is_explicit_and_old_binding_unchanged():
    assert bind_segmented_director(authoritative=True)['version'] == AUTHORITATIVE_VERSION
    assert bind_segmented_director(authoritative=True,static_visual=True)['version'] == PROJECTED_VISUAL_VERSION


def test_v4_generates_one_manifest_and_carries_it_through_reviews(tmp_path):
    from tests.test_creative_segmented_director import Harness
    from src.content_factory.creative_segmented_director import generate_reviewed_beats
    class StaticHarness(Harness):
        def _stage(self,name,role,payload,validator):
            if name == 'static_visual_manifest':
                self.seen.append((name,deepcopy(payload)))
                value = manifest(); value['schema'] = payload.get('static_manifest_version', value['schema']); value['render'] = {k:self.answers[3]['style'][k] for k in value['render']}
                validator(value)
                self.answers[3]['style'] = style_from_manifest(value)
                return value
            return super()._stage(name,role,payload,validator)
    w = StaticHarness([[],[]],tmp_path)
    w.state['segmented_director_binding'] = bind_segmented_director(static_visual=True)
    for shot in w.answers[3]['shots']: shot['production_choices'] = []
    result = generate_reviewed_beats(w,w.answers[2],w.answers[1],{})
    assert len(result['shots']) == 2
    assert len([n for n,p in w.seen if n == 'static_visual_manifest']) == 1
    for name,payload in w.seen[1:]:
        assert payload['static_visual_manifest']['schema'] == 'static_visual_manifest_v2'
    assert w.seen[3][1]['style_lock'] == w.seen[1][1]['style_lock']
    for path in tmp_path.glob('*effective_execution.json'):
        assert json.loads(path.read_text(encoding='utf-8'))['binding_version'] == PROJECTED_VISUAL_VERSION


def test_real_round1_on_relation_supported_by_v2_only():
    from src.content_factory.creative_static_visual_manifest import VERSION_V2, build_static_manifest_prompt, build_static_manifest_repair
    path = Path('data/production_trials/say_no_three_production_cycles_20260927/round_01/static_visual_manifest.json')
    if not path.exists(): pytest.skip('local paid receipt unavailable')
    record = json.loads(path.read_text(encoding='utf-8-sig'))
    raw = record['response_text'].strip().removeprefix('```json').removesuffix('```').strip()
    value = json.loads(raw)
    with pytest.raises(CreativeContractError,match=r'scene.relations.1.relation'):
        validate_static_manifest(value)
    value['schema'] = VERSION_V2
    validate_static_manifest(value)
    value['scene']['relations'][1]['relation'] = 'on_top_of'
    with pytest.raises(CreativeContractError,match='允许值.*on'):
        validate_static_manifest(value)
    payload = {'static_manifest_version': VERSION_V2}
    instruction, request = build_static_manifest_repair('bad relation',payload,value)
    assert request['target_contract'] == build_static_manifest_prompt(payload)
    assert '固定场景资产的桌椅' in request['target_contract']
    assert '不得输出error' in instruction
    assert 'source_evidence' in instruction
    assert 'inside|on' in request['target_contract']
    assert 'inside|on' not in build_static_manifest_prompt({})


def test_round2_model_style_is_projected_without_mutating_raw_receipt(tmp_path):
    from src.content_factory.creative_segmented_director import project_static_style, _save_style_projection, build_execution_repair
    from types import SimpleNamespace
    path = Path('data/production_trials/say_no_three_production_cycles_20260927/round_02/director_shots__beat_01_00.json')
    if not path.exists(): pytest.skip('local paid receipt unavailable')
    record = json.loads(path.read_text(encoding='utf-8-sig'))
    raw = json.loads(record['response_text'].strip().removeprefix('```json').removesuffix('```').strip())
    before = deepcopy(raw)
    projected = project_static_style(raw,manifest())
    assert projected['style'] == style_from_manifest(manifest())
    assert raw == before
    assert projected['shots'] == raw['shots']  # no semantic edits or invented pass
    workflow = SimpleNamespace(run_dir=tmp_path)
    _save_style_projection(workflow,'director_shots__test',raw,projected)
    receipt = json.loads(next(tmp_path.glob('*projection.json')).read_text(encoding='utf-8'))
    assert receipt['discarded_model_style'] == raw['style']
    assert 'performance_not_approved' in receipt['reason']
    request = {'segment_instructions':bind_segmented_director(static_visual=True)['prompt'], 'static_visual_manifest':manifest(), 'upcoming_beats':[{'id':'next'}]}
    instruction,payload = build_execution_repair('production_choices必须为空',request,raw)
    assert payload['original_request'] == request
    assert payload['target_root_fields'] == ['style','shots','media_assumptions']
    assert '不返回patches' in instruction


def test_v5_workflow_repair_uses_full_target_contract(tmp_path):
    from src.content_factory.creative_workflow import CreativeWorkflow
    from src.content_factory.creative_segmented_director import validate_execution_contract
    from tests.test_creative_workflow import FakeClients, _answers
    raw = _answers()[3]
    raw['shots'][0]['production_choices'] = ['duplicate motion']
    repaired = deepcopy(raw)
    for shot in repaired['shots']: shot['production_choices'] = []
    repaired['style'] = {}
    clients = FakeClients([repaired])
    root = tmp_path/'run'; root.mkdir()
    workflow = CreativeWorkflow(root,clients=clients)
    workflow.state = {'calls_started':0,'max_calls':5,'max_total_tokens':100000,
        'budget_policy_version':'v4_20260923','max_contract_repairs':3,
        'contract_repairs_used':0,'format_repairs_used':0,'revision_rounds':0,'stages':[]}
    payload = {'execution_projection_version':PROJECTED_VISUAL_VERSION,
               'segment_instructions':bind_segmented_director(static_visual=True)['prompt'],
               'script':_answers()[2],'static_visual_manifest':manifest()}
    result = workflow._validate_or_repair('director_shots__beat_01_00','director',payload,raw,validate_execution_contract)
    assert result == repaired
    system = clients.calls[0][1][0]['content']
    assert '不返回patches' in system
    assert '三个根字段' in system
    actual = json.loads(clients.calls[0][1][1]['content'])
    assert actual['original_request']['static_visual_manifest'] == manifest()
    assert actual['target_root_fields'] == ['style','shots','media_assumptions']
    assert workflow.state['calls_started'] == 1
