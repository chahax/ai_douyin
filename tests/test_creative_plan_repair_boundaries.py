from copy import deepcopy
import pytest
from src.content_factory.creative_workflow_contract import CreativeContractError
from src.content_factory.creative_action_plan_v2 import build_action_plan_schema, schedule_action_plan
from src.content_factory.creative_plan_patch import apply_plan_patch, build_patch_schema, plan_digest
from tests.test_creative_action_plan_v2 import sample


def test_schema_descriptions_do_not_leak_between_action_and_dialogue_fields():
    p,s,m=sample()
    schema=build_action_plan_schema({'script':s,'static_visual_manifest':m})
    beat=schema['properties']['beats']['items']['properties']
    group=beat['groups']['items']['properties']
    assert 'during组不得重演' in group['performance']['description']
    assert '实际对白窗口' in beat['dialogue_performance']['description']
    assert 'description' not in group['id']
    assert 'description' not in beat['reaction']['properties']['anchor']


def test_take_then_place_cannot_hide_intermediate_holder_in_one_group():
    p,s,m=sample();g=p['beats'][0]['groups'][0]
    g['operations'].append({'kind':'place','actor':'C02','target':'P01','value':'桌面'})
    before=deepcopy(p)
    with pytest.raises(CreativeContractError,match='PLAN_GROUP_'):
        schedule_action_plan(p,s,m)
    assert p==before


def test_initial_holder_cannot_place_then_take_in_one_group():
    p,s,m=sample();p['initial_state']['P01']['holder']='C02'
    p['beats'][0]['groups'][0]['operations'].insert(0,{'kind':'place','actor':'C02','target':'P01','value':'桌面'})
    with pytest.raises(CreativeContractError,match='PLAN_GROUP_'):
        schedule_action_plan(p,s,m)


def test_two_writes_to_same_gaze_are_not_simultaneous():
    p,s,m=sample();g=p['beats'][0]['groups'][0]
    g['operations'] += [{'kind':'gaze','actor':'C01','target':'','value':'门'},
                        {'kind':'gaze','actor':'C01','target':'','value':'桌面'}]
    with pytest.raises(CreativeContractError,match='PLAN_GROUP_'):
        schedule_action_plan(p,s,m)


def test_separate_take_then_place_preserves_intermediate_state_and_locked_dialogue():
    p,s,m=sample();take=deepcopy(p['beats'][0]['groups'][0])
    p['beats'][1]['groups'].append({**take,'id':'place_later','script_slot':'after',
        'operations':[{'kind':'place','actor':'C02','target':'P01','value':'桌面'}]})
    p['beats'][1]['cut_after_event_id']='place_later'
    scheduled,report=schedule_action_plan(p,s,m)
    from src.content_factory.creative_action_plan_v2 import compile_action_plan
    compiled=compile_action_plan(p,s,m)
    assert 'C02' in compiled['shots'][0]['end_state']
    assert compiled['shots'][0]['end_state']==compiled['shots'][1]['start_state']
    assert compiled['shots'][0]['dialogue_lock']==s['beats'][0]['dialogue']
    assert report['group_operation_checks']
    assert scheduled['beats'][1]['events'][1]['operations'][0]['kind']=='place'


def test_manifest_bound_patch_schema_is_used_when_applying_the_patch():
    import jsonschema
    p,s,m=sample();m['scene']['elements'].append({'id':'E03','name':'凳子','appearance':'木凳'})
    schema=build_action_plan_schema({'script':s,'static_visual_manifest':m})
    # E03 is legitimate manifest evidence even though the old plan has no seat entry for it.
    groups=deepcopy(p['beats'][1]['groups']);groups[0]['operations'][0]['target']='E03'
    patch={'source_sha256':plan_digest(p),'patches':[{'path':'beats.1.groups','value':groups}]}
    jsonschema.validate(patch,build_patch_schema(p,target_schema=schema))
    result=apply_plan_patch(p,patch,target_schema=schema)
    assert result['beats'][1]['groups'][0]['operations'][0]['target']=='E03'
    with pytest.raises(CreativeContractError,match='PLAN_SEAT_ACCESS_UNKNOWN'):
        schedule_action_plan(result,s,m)


def test_full_plan_content_revision_is_reviewed_as_the_new_whole_plan(tmp_path,monkeypatch):
    import src.content_factory.creative_segmented_director as director
    from src.content_factory.creative_segmented_director import bind_state_plan_director
    from tests.test_creative_plan_patch_integration import setup
    p,s,m=sample();m['schema']='static_visual_manifest_v2'
    revised=deepcopy(p);revised['beats'][0]['purpose']='本次完整新稿的关系变化'
    w,clients=setup(tmp_path,[m,p,revised])
    w.max_revisions=1
    w.state.update(segmented_director_binding=bind_state_plan_director(state_plan_version=p['schema'],plan_thinking_mode='disabled'),
        writer_prompt_binding={'creative_brief':{}},revision_committed=[])
    decisions=iter([[{'owner':'director','reason':'情绪重心不清楚'}],[]])
    contexts=[]
    def decide(name,review,context):
        contexts.append(deepcopy(context))
        return next(decisions)
    w._verified_review=decide
    original_stage=w._stage
    def stage(name,role,payload,validator):
        if name.startswith('writer_check'):
            # Explicit reviewer fixture: only verify full context routing here.
            w.state['calls_started']+=1
            return {}
        return original_stage(name,role,payload,validator)
    w._stage=stage
    monkeypatch.setattr(director,'validate_static_manifest',lambda value: None)
    monkeypatch.setattr(director,'validate_shots',lambda *args: None)
    monkeypatch.setattr('src.content_factory.creative_review_gate.validate_review',lambda *args: None)
    shots=director.generate_reviewed_state_plan(w,s,{'selected_style_id':'S01'}, {})
    assert contexts[-1]['state_plan']==revised
    assert len(contexts[-1]['shots']['shots'])==len(s['beats'])
    assert shots['shots'][0]['purpose']==revised['beats'][0]['purpose']
    assert w.state['revision_rounds']==1 and w.state['calls_started']==5
    import json
    messages=json.loads((tmp_path/'director_state_plan__01.json').read_text(encoding='utf-8'))['request']['messages']
    payload=json.loads(next(m['content'] for m in messages if m['role']=='user'))
    assert payload['previous_draft']==p and payload['issues']
    assert 'plan_patch_base' not in payload
    assert not (tmp_path/'director_state_plan__01__action_patch_merge.json').exists()


def test_physical_contract_error_requires_complete_model_plan_without_local_patch(tmp_path):
    from tests.test_creative_plan_patch_integration import setup
    p,s,m=sample();invalid=deepcopy(p);invalid['initial_state']['P01']['holder']='C02'
    payload={'state_plan_version':p['schema'],'script':s,'static_visual_manifest':m,'plan_thinking_mode':'disabled'}
    w,clients=setup(tmp_path,[p])
    result=w._validate_or_repair('director_state_plan__00','director',payload,invalid,
        lambda value: schedule_action_plan(value,s,m))
    assert result==p and invalid['initial_state']['P01']['holder']=='C02'
    import json
    receipt=json.loads((tmp_path/'director_state_plan__00__contract_repair.json').read_text(encoding='utf-8'))
    assert receipt['repair_protocol']=='action_plan_full_rebuild/v1'
    assert not list(tmp_path.glob('*__action_patch_merge.json'))
    assert w.state['contract_repairs_used']==1 and w.state['calls_started']==1


def test_schema_type_repair_still_uses_bound_model_patch_then_full_compile(tmp_path):
    from tests.test_creative_plan_patch_integration import setup
    p,s,m=sample();p['beats'][0]['groups'][0]['duration_seconds']='1'
    payload={'state_plan_version':p['schema'],'script':s,'static_visual_manifest':m,'plan_thinking_mode':'disabled'}
    patch={'source_sha256':plan_digest(p),'patches':[{'path':'beats.0.groups.0.duration_seconds','value':1}]}
    w,clients=setup(tmp_path,[patch])
    result=w._validate_or_repair('director_state_plan__00','director',payload,p,
        lambda value: schedule_action_plan(value,s,m))
    assert result['beats'][0]['groups'][0]['duration_seconds']==1
    import json
    receipt=json.loads((tmp_path/'director_state_plan__00__contract_repair.json').read_text(encoding='utf-8'))
    assert receipt['repair_protocol']=='action_plan_local_patch/v1'
    assert json.loads(receipt['response_text'])==patch
    merge=json.loads(next(tmp_path.glob('*__action_patch_merge.json')).read_text(encoding='utf-8'))
    assert merge['semantic_approval'] is False


def test_runtime_merge_uses_same_manifest_schema_for_dependency_recheck(tmp_path):
    from tests.test_creative_plan_patch_integration import setup
    p,s,m=sample();m['scene']['elements'].append({'id':'E03','name':'凳子','appearance':'木凳'})
    schema=build_action_plan_schema({'script':s,'static_visual_manifest':m})
    groups=deepcopy(p['beats'][1]['groups']);groups[0]['operations'][0]['target']='E03'
    patch={'source_sha256':plan_digest(p),'patches':[{'path':'beats.1.groups','value':groups}]}
    w,_=setup(tmp_path,[])
    result=w._merge_action_plan_patch('repair',p,patch,target_schema=schema)
    assert result['beats'][1]['groups'][0]['operations'][0]['target']=='E03'
    import json
    receipt=json.loads((tmp_path/'repair__action_patch_merge.json').read_text(encoding='utf-8'))
    assert receipt['dependency_recheck']['requires_full_compile']
    assert receipt['dependency_recheck']['requires_semantic_review']
    assert receipt['semantic_approval'] is False
