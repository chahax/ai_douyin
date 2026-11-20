from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import lifecycle as lc,contracts as c
from src.content_factory.novel_adaptation.scenes import initial_state,advance,production_scene
from src.content_factory.novel_adaptation.handoff import export_handoff,inherit_design,continue_state
from src.content_factory.novel_adaptation.events import validate_requirements
from src.content_factory.novel_adaptation.blocking import blocking_schema,compile_blocking
from test_novel_adaptation_scenes import PLAN,ENT,SOURCE,SCENE


def fixture():
    plan=deepcopy(PLAN)
    plan['props'] += [{'id':'bag','owner':'a'},{'id':'meal','owner':'room'}]
    plan.update(containers={'bread1':'bag'},container_actions=True,planned_props=['meal'],
        recipes=[{'id':'cook','action':'烹饪','inputs':['bread1'],'outputs':['meal'],
                  'retained_inputs':[],'source_ids':['CH1-P001']}])
    return plan,initial_state(plan,ENT)


def cook(state):
    lc.apply(state,{'actor':'a','prop':'bread1','container':'bag','destination':'a'},'unpack','room')
    lc.apply(state,{'actor':'a','recipe':'cook','destination':'room'},'transform','room')


def test_unpack_then_cook_consumes_input_and_creates_output_once():
    plan,state=fixture();before=deepcopy(state)
    assert not lc.exists(state,'meal') and lc.exists(state,'bread1')
    with pytest.raises(ValueError,match='contained'):
        lc.apply(state,{'actor':'a','recipe':'cook','destination':'room'},'transform','room')
    assert state==before
    cook(state)
    assert lc.exists(state,'meal') and not lc.exists(state,'bread1')
    assert state['containers']=={} and state['recipes_completed']==['cook']
    before=deepcopy(state)
    with pytest.raises(ValueError,match='already_applied'):
        lc.apply(state,{'actor':'a','recipe':'cook','destination':'room'},'transform','room')
    assert state==before


@pytest.mark.parametrize('kind,row',[
    ('unpack',{'actor':'b','prop':'bread1','container':'meal','destination':'b'}),
    ('pack',{'actor':'a','prop':'bag','container':'bread1'}),
    ('unpack',{'actor':'a','prop':'bread1','container':'bag','destination':'other'}),
    ('pack',{'actor':'a','prop':'meal','container':'bag'}),
])
def test_invalid_operation_is_atomic(kind,row):
    _,state=fixture();before=deepcopy(state)
    with pytest.raises(ValueError):lc.apply(state,row,kind,'room')
    assert state==before


def test_ordered_scene_and_renderer_agree_and_extraction_changes_transfer_evidence():
    plan,state=fixture();scene=deepcopy(SCENE);b=scene['beats'][0]
    b['unpacks']=[{'actor':'a','prop':'bread1','container':'bag','destination':'a'}]
    b['transforms']=[{'actor':'a','recipe':'cook','destination':'room'}]
    b['transfers']=[{'prop':'bag','origin':'a','destination':'b','action':'交给'}]
    b['action_order']=[{'field':k,'index':0} for k in ('unpacks','transforms','transfers')]
    effects=[]
    end=advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,state,effects=effects)
    assert end['props']['bag']=='b' and end['props']['bread1']=='a'
    assert end['prop_status']['bread1']=='consumed' and end['prop_status']['meal']=='present'
    assert production_scene(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,state)['end_state']==end
    event={'id':'e','scene_id':'s1','kind':'transfer','prop':'bread1','origin':'a','destination':'b'}
    with pytest.raises(c.ContractError):
        validate_requirements({'scenes':[scene],'containers':state['containers']},{'events':[event]},transition_effects=effects)
    assert state['containers']=={'bread1':'bag'}


def test_planned_food_cannot_be_transferred_before_creation():
    plan,state=fixture();scene=deepcopy(SCENE)
    scene['beats'][0]['transfers'][0].update(prop='meal',origin='room')
    with pytest.raises(c.ContractError,match='prop_not_present'):
        advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,state)


def test_native_typed_operations_compile_to_same_execution_order():
    plan,state=fixture();raw=deepcopy(SCENE);b=raw['beats'][0]
    for key in ('present','camera','action','moves','transfers'):b.pop(key,None)
    b['blocking']=[{'kind':'unpack','actor':'a','prop':'bread1','container':'bag','destination':'a'},
                   {'kind':'transform','actor':'a','recipe':'cook','destination':'room'},
                   {'kind':'transfer','prop':'meal','origin':'room','destination':'b'}]
    b['shot']={'framing':'medium','motion':'static','angle':'eye','subjects':['a','b','meal']}
    original=deepcopy(raw)
    schema=blocking_schema(plan,ENT,['f'],SOURCE,state,['CH1-P001'])
    scene=compile_blocking(raw,plan,ENT,schema)
    assert raw==original
    assert [r['field'] for r in scene['beats'][0]['action_order']]==['unpacks','transforms','transfers']
    end=advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,state)
    assert end['props']['meal']=='b' and end['prop_status']['bread1']=='consumed'
    b['blocking'][0],b['blocking'][1]=b['blocking'][1],b['blocking'][0]
    invalid=compile_blocking(raw,plan,ENT,schema)
    with pytest.raises(c.ContractError,match='recipe_input_unavailable_or_contained'):
        advance(invalid,plan['scenes'][0],plan,ENT,['f'],SOURCE,state)


def test_cross_episode_preserves_consumption_and_recipe_history():
    plan,state=fixture();cook(state)
    candidate={'design':plan,'end_state':state}
    review={'verdict':'accepted','candidate_sha256':c.digest(candidate),'source_sha256':c.digest(SOURCE)}
    h=export_handoff(candidate,ENT,SOURCE,review,book_id='book',episode_id='one',timeline_id='now')
    design=inherit_design({'places':[],'props':[],'scenes':plan['scenes'],'initial_locations':plan['initial_locations']},h)
    kw=dict(book_id='book',episode_id='two',timeline_id='now')
    end=continue_state(h,c.digest(h),design,ENT,**kw)
    assert end['prop_status']==state['prop_status'] and end['recipes_completed']==['cook']
    design['initial_prop_status']['bread1']='present'
    with pytest.raises(ValueError,match='lifecycle_reset'):continue_state(h,c.digest(h),design,ENT,**kw)


def test_retained_input_allows_portioning_but_not_repeated_portions():
    plan,state=fixture();cook(state)
    state['props']['portion']='room';state['prop_status']['portion']='planned'
    state['recipes']['serve']={'inputs':['meal'],'outputs':['portion'],'retained_inputs':['meal']}
    lc.apply(state,{'actor':'a','recipe':'serve','destination':'b'},'transform','room')
    assert lc.exists(state,'meal') and lc.exists(state,'portion') and state['props']['portion']=='b'
    with pytest.raises(ValueError,match='already_applied'):
        lc.apply(state,{'actor':'a','recipe':'serve','destination':'b'},'transform','room')


def test_required_transformation_cannot_be_omitted_or_repeated():
    scene={'id':'s','beats':[{'transforms':[{'recipe':'cook'}]}]}
    contract={'events':[{'id':'e','scene_id':'s','kind':'transform','recipe':'cook'}]}
    assert validate_requirements({'scenes':[scene]},contract)
    scene['beats'][0]['transforms']=[]
    with pytest.raises(c.ContractError,match='required_transform_not_once'):
        validate_requirements({'scenes':[scene]},contract)
    scene['beats'][0]['transforms']=[{'recipe':'cook'},{'recipe':'cook'}]
    with pytest.raises(c.ContractError,match='required_transform_not_once'):
        validate_requirements({'scenes':[scene]},contract)
