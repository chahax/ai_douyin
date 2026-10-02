from copy import deepcopy
import pytest
from src.content_factory.creative_plan_patch import (apply_plan_patch, build_patch_request,
    can_patch_plan, plan_digest)
from src.content_factory.creative_workflow_contract import CreativeContractError

def sample():
    return {"schema":"whole_film_state_plan_v3", "initial_state":{"C01":{"posture":"standing"}},
        "beats":[{"beat_id":"B1", "events":[{"start":0,"end":1,"operations":[]}],
        "dialogue_windows":[{"start":1,"end":3}]}]}

def response(plan, *patches):
    return {"source_sha256":plan_digest(plan),"patches":list(patches)}

def test_atomic_copy_and_payload_hash_context():
    plan=sample(); original=deepcopy(plan)
    instruction,payload=build_patch_request({"type":"object"},{"script":{"beats":[]}},"end wrong",plan,["beats.0.events"])
    merged=apply_plan_patch(plan,response(plan,{"path":"beats.0.events.0.end","value":2}),payload['allowed_paths'])
    assert plan==original and merged['beats'][0]['events'][0]['end']==2
    assert payload['source_sha256']==plan_digest(plan) and payload['context']['script']=={'beats':[]}
    assert '完整契约' in instruction

@pytest.mark.parametrize('path,value',[("schema","other"),("beats",[]),("beats.0",{}),
    ("beats.0.beat_id","B2"),("beats.0.events.8.end",2),("beats.0.events.00.end",2),
    ("beats.0.new_field",1),("initial_state.C01",{"speaker":"X"})])
def test_protected_unknown_or_whole_replacement_rejected(path,value):
    plan=sample()
    with pytest.raises(CreativeContractError):
        apply_plan_patch(plan,response(plan,{'path':path,'value':value}))

def test_hash_scope_and_overlap_rejected():
    plan=sample(); patch={'path':'beats.0.events.0.end','value':2}
    bad=response(plan,patch);bad['source_sha256']='wrong'
    with pytest.raises(CreativeContractError,match='sha256'): apply_plan_patch(plan,bad)
    with pytest.raises(CreativeContractError,match='scope'): apply_plan_patch(plan,response(plan,patch),['initial_state.C01'])
    for other in [patch,{'path':'beats.0.events','value':[]}]:
        with pytest.raises(CreativeContractError,match='重叠'):
            apply_plan_patch(plan,response(plan,patch,other))

def test_late_failure_does_not_mutate_original():
    plan=sample(); before=deepcopy(plan)
    with pytest.raises(CreativeContractError):
        apply_plan_patch(plan,response(plan,{'path':'beats.0.events.0.end','value':2}, {'path':'beats.0.bad','value':0}))
    assert plan==before

def test_shape_classifier_and_existing_container_repair():
    assert not can_patch_plan(None)
    assert not can_patch_plan({'schema':'v','initial_state':{},'beats':[]})
    plan=sample();plan['beats'][0]['events']='invalid array'
    assert can_patch_plan(plan)
    merged=apply_plan_patch(plan,response(plan,{'path':'beats.0.events','value':[]}))
    assert merged['beats'][0]['events']==[] # Caller must reject empty events using full validator.


def test_patch_success_does_not_claim_plan_is_valid():
    plan=sample()
    merged=apply_plan_patch(plan,response(plan,{'path':'beats.0.events.0.end','value':-9}))
    assert merged['beats'][0]['events'][0]['end']==-9
    # Merging is data mutation only; deliberately no semantic pass or validator bypass.


def test_new_action_groups_schema_enumerates_only_existing_mutable_paths():
    from src.content_factory.creative_plan_patch import build_patch_schema
    plan=sample(); plan['schema']='whole_film_action_plan_v1'
    plan['beats'][0]['groups']=plan['beats'][0].pop('events')
    schema=build_patch_schema(plan)
    paths=schema['properties']['patches']['items']['properties']['path']['enum']
    assert 'beats.0.groups' in paths and 'initial_state.C01' in paths
    assert not {'beats','beats.0','initial_state','schema','beats.0.beat_id'} & set(paths)
    assert schema['properties']['source_sha256']['enum']==[plan_digest(plan)]
    restricted=build_patch_schema(plan,['beats.0.groups'])
    assert all(p.startswith('beats.0.groups') for p in restricted['properties']['patches']['items']['properties']['path']['enum'])


def test_v2_patch_rejects_stringified_array_both_schema_and_runtime():
    import jsonschema
    from tests.test_creative_action_plan_v2 import sample as v2_sample
    from src.content_factory.creative_plan_patch import build_patch_schema
    plan,_,_=v2_sample();path='beats.0.groups.0.operations'
    bad=response(plan,{'path':path,'value':'[]'})
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(bad,build_patch_schema(plan,[path]))
    with pytest.raises(CreativeContractError,match='PLAN_PATCH_VALUE_SCHEMA'): apply_plan_patch(plan,bad)
    good=response(plan,{'path':path,'value':[]})
    jsonschema.validate(good,build_patch_schema(plan,[path]))
    assert apply_plan_patch(plan,good)['beats'][0]['groups'][0]['operations']==[]


def test_v2_type_is_derived_from_contract_even_if_original_value_is_corrupted():
    import jsonschema
    from tests.test_creative_action_plan_v2 import sample as v2_sample
    from src.content_factory.creative_plan_patch import build_patch_schema
    plan,_,_=v2_sample();plan['beats'][0]['groups'][0]['operations']='[]'
    fixed=response(plan,{'path':'beats.0.groups.0.operations','value':[]})
    jsonschema.validate(fixed,build_patch_schema(plan))
    assert apply_plan_patch(plan,fixed)['beats'][0]['groups'][0]['operations']==[]


def test_v2_unknown_path_and_malformed_operation_cannot_hide_in_typed_patch():
    import jsonschema
    from tests.test_creative_action_plan_v2 import sample as v2_sample
    from src.content_factory.creative_plan_patch import build_patch_schema
    plan,_,_=v2_sample();schema=build_patch_schema(plan)
    for item in [{'path':'beats.3.groups.3.operations','value':[]},
                 {'path':'beats.0.groups.0.operations','value':[{'kind':'place'}]},
                 {'path':'beats.0.groups.0.operations','value':[{'kind':'place','actor':'C02','target':'E01','value':'P01'}]}]:
        bad=response(plan,item)
        with pytest.raises(jsonschema.ValidationError):jsonschema.validate(bad,schema)
        with pytest.raises(CreativeContractError):apply_plan_patch(plan,bad)


def test_v2_schema_groups_equal_value_types_and_limits_known_hold_scope():
    from tests.test_creative_action_plan_v2 import sample as v2_sample
    from src.content_factory.creative_plan_patch import build_patch_schema,repair_paths_for_error,editable_paths
    plan,_,_=v2_sample();plan['beats'][0]['groups'][0].update(kind='hold',hold_subject='C01')
    scopes=repair_paths_for_error(plan,'PLAN_HOLD_HAS_ACTION')
    assert scopes==['beats.0.groups']
    schema=build_patch_schema(plan)
    assert len(schema['properties']['patches']['items']['oneOf'])<len(editable_paths(plan))
    scoped=build_patch_schema(plan,scopes)
    paths=[p for branch in scoped['properties']['patches']['items']['oneOf'] for p in branch['properties']['path']['enum']]
    assert all(p.startswith(scopes[0]) for p in paths)



def test_hold_repair_scope_allows_reclassification_and_split_without_dropping_action():
    import jsonschema
    from tests.test_creative_action_plan_v2 import sample as v2_sample
    from src.content_factory.creative_plan_patch import build_patch_schema,repair_paths_for_error
    plan,_,_=v2_sample();group=plan['beats'][0]['groups'][0]
    group.update(kind='hold',hold_subject='C01')
    scope=repair_paths_for_error(plan,'PLAN_HOLD_HAS_ACTION')
    schema=build_patch_schema(plan,scope)
    new_groups=deepcopy(plan['beats'][0]['groups'])
    new_groups[0].update(kind='action',hold_subject='')
    hold=deepcopy(new_groups[0]);hold.update(id='hold_after_action',kind='hold',hold_subject='C01',operations=[])
    new_groups.append(hold)
    patch=response(plan,{'path':'beats.0.groups','value':new_groups})
    jsonschema.validate(patch,schema)
    result=apply_plan_patch(plan,patch,scope)
    assert result['beats'][0]['groups'][0]['operations']==group['operations']
    assert result['beats'][0]['groups'][1]['kind']=='hold'
    assert result['beats'][1]==plan['beats'][1]
    # Reclassification without a needless added hold is also representable.
    patch=response(plan,{'path':'beats.0.groups','value':new_groups[:1]})
    jsonschema.validate(patch,schema)
    assert apply_plan_patch(plan,patch,scope)['beats'][0]['groups'][0]['kind']=='action'
    # The model must not silently erase actions; semantic source review remains
    # mandatory even though the typed patch itself cannot infer story intent.
