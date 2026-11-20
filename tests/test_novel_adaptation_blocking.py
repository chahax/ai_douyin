from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.blocking import blocking_schema,compile_blocking
from src.content_factory.novel_adaptation.scenes import advance,initial_state,production_scene
from test_novel_adaptation_scenes import SOURCE,ENT,PLAN,SCENE

def make():
    raw=deepcopy(SCENE);b=raw['beats'][0]
    for k in ('present','camera','action','moves','transfers'):b.pop(k,None)
    b['blocking']=[{'kind':'transfer','prop':'bread1','origin':'a','destination':'b','phase':'start'}]
    b['shot']={'framing':'medium','motion':'static','angle':'eye','subjects':['a','b','bread1']}
    schema=blocking_schema(PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT),['CH1-P001'])
    return raw,schema

def test_prose_and_transfer_have_one_source_and_do_not_mutate_native():
    raw,schema=make();old=deepcopy(raw)
    scene=compile_blocking(raw,PLAN,ENT,schema)
    assert raw==old and scene['beats'][0]['transfers'][0]['destination']=='b'
    assert '移交至b' in scene['beats'][0]['action']
    assert advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT))['props']['bread1']=='b'
    raw['beats'][0]['action']='甲仍拿着面包。'
    with pytest.raises(c.ContractError):compile_blocking(raw,PLAN,ENT,schema)

def test_placed_prop_cannot_still_be_shown_as_held_by_actor():
    raw,schema=make()
    raw['beats'][0]['blocking']=[
        {'kind':'transfer','prop':'bread1','origin':'a','destination':'room'},
        {'kind':'gesture','actor':'a','verb':'show','target':'bread1'}]
    scene=compile_blocking(raw,PLAN,ENT,schema)
    with pytest.raises(c.ContractError,match='visible_prop_owner_mismatch'):
        advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT))


def test_opening_a_local_bag_does_not_require_lifting_it():
    plan=deepcopy(PLAN);plan['props'].append({'id':'bag','owner':'room'})
    raw,_=make();raw['beats'][0]['blocking']=[{'kind':'gesture','actor':'a','verb':'open_bag','target':'bag'}]
    state=initial_state(plan,ENT)
    schema=blocking_schema(plan,ENT,['f'],SOURCE,state,['CH1-P001'])
    scene=compile_blocking(raw,plan,ENT,schema)
    assert advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,state)['props']['bag']=='room'
    hidden=deepcopy(state);hidden['props']['bag']='other'
    with pytest.raises(c.ContractError,match='gesture_target_not_visible'):
        advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,hidden)

def test_offscreen_actor_cannot_be_touched_or_shown():
    raw,schema=make();state=initial_state(PLAN,ENT);state['locations']['b']='other'
    raw['beats'][0]['blocking']=[{'kind':'gesture','actor':'a','verb':'pat_head','target':'b'}]
    scene=compile_blocking(raw,PLAN,ENT,schema)
    with pytest.raises(c.ContractError,match='gesture_target_not_visible'):
        advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,state)


def test_self_gesture_needs_no_external_target_but_directed_gesture_does():
    raw,schema=make();raw['beats'][0]['blocking']=[{'kind':'gesture','actor':'a','verb':'clench_fists'}]
    old=deepcopy(raw);scene=compile_blocking(raw,PLAN,ENT,schema)
    assert raw==old and scene['beats'][0]['gestures'][0]['target']=='a'
    raw['beats'][0]['blocking'][0]['verb']='look_at'
    with pytest.raises(c.ContractError):compile_blocking(raw,PLAN,ENT,schema)


@pytest.mark.parametrize('phase,index',[('start',None),('after_audio',0),('end',None)])
def test_order_distinguishes_show_then_transfer_from_transfer_then_show(phase,index):
    raw,schema=make()
    timing={'phase':phase}
    if index is not None:timing['after_audio_index']=index
    show={'kind':'gesture','actor':'a','verb':'show','target':'bread1',**timing}
    transfer={'kind':'transfer','prop':'bread1','origin':'a','destination':'b',**timing}
    raw['beats'][0]['blocking']=[show,transfer]
    scene=compile_blocking(raw,PLAN,ENT,schema)
    assert advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT))['props']['bread1']=='b'
    assert scene['beats'][0]['action'].index('展示')<scene['beats'][0]['action'].index('移交')
    raw['beats'][0]['blocking']=[transfer,show]
    scene=compile_blocking(raw,PLAN,ENT,schema)
    with pytest.raises(c.ContractError,match='visible_prop_owner_mismatch'):
        advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT))


def test_order_cannot_skip_or_duplicate_actions():
    raw,schema=make();scene=compile_blocking(raw,PLAN,ENT,schema)
    for order in ([],scene['beats'][0]['action_order']*2):
        bad=deepcopy(scene);bad['beats'][0]['action_order']=order
        with pytest.raises(c.ContractError,match='action_order_coverage'):
            advance(bad,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT))


def test_phase_precedence_and_production_view_share_order_and_state():
    raw,schema=make()
    raw['beats'][0]['blocking']=[
        {'kind':'transfer','prop':'bread1','origin':'a','destination':'b','phase':'end'},
        {'kind':'gesture','actor':'a','verb':'show','target':'bread1','phase':'start'}]
    scene=compile_blocking(raw,PLAN,ENT,schema)
    view=production_scene(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT))
    assert view['end_state']['props']['bread1']=='b'
    assert view['beats'][0]['action_order']==scene['beats'][0]['action_order']
    assert view['beats'][0]['action'].index('展示')<view['beats'][0]['action'].index('移交')


def test_omitted_audio_compiles_as_silence_without_inventing_text():
    raw,schema=make();del raw['beats'][0]['audio'];old=deepcopy(raw)
    with pytest.raises(c.ContractError):compile_blocking(raw,PLAN,ENT,schema)
    schema=blocking_schema(PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT),['CH1-P001'],allow_silent_omission=True)
    scene=compile_blocking(raw,PLAN,ENT,schema)
    assert scene['beats'][0]['audio']==[] and raw==old
    advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT))
