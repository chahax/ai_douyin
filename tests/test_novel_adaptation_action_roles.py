from copy import deepcopy
import pytest
from test_novel_adaptation_blocking import make
from test_novel_adaptation_scenes import PLAN, ENT, SOURCE
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.blocking import blocking_schema, compile_blocking
from src.content_factory.novel_adaptation.scenes import initial_state, advance


def setup_case():
    plan=deepcopy(PLAN)
    plan['action_contract_version']=2
    plan['props'].append({'id':'knife','owner':'a'})
    raw,_=make()
    raw['beats'][0]['blocking']=[{'kind':'gesture','actor':'a','verb':'cut','target':'bread1','instrument':'knife'}]
    schema=blocking_schema(plan,ENT,['f'],SOURCE,initial_state(plan,ENT),['CH1-P001'])
    return plan,raw,schema


def test_cut_uses_held_tool_on_distinct_object_and_preserves_native():
    plan,raw,schema=setup_case();old=deepcopy(raw)
    compiled=compile_blocking(raw,plan,ENT,schema)
    assert '用knife切开（bread1）' in compiled['beats'][0]['action']
    advance(compiled,plan['scenes'][0],plan,ENT,['f'],SOURCE,initial_state(plan,ENT))
    assert raw==old


@pytest.mark.parametrize('case,error',[('same','instrument_is_affected_target'),('other_holder','instrument_not_held'),('remote','instrument_not_visible'),('contained','instrument_still_contained')])
def test_invalid_tool_usage_is_rejected_at_execution(case,error):
    plan,raw,schema=setup_case();state=initial_state(plan,ENT)
    if case=='same':raw['beats'][0]['blocking'][0]['target']='knife'
    elif case=='other_holder':state['props']['knife']='b'
    elif case=='contained':state.setdefault('containers',{})['knife']='bread1'
    else:state['props']['knife']='other'
    compiled=compile_blocking(raw,plan,ENT,schema)
    with pytest.raises(c.ContractError,match=error):
        advance(compiled,plan['scenes'][0],plan,ENT,['f'],SOURCE,state)


def test_new_contract_rejects_ambiguous_cut_without_tool():
    plan,raw,schema=setup_case();del raw['beats'][0]['blocking'][0]['instrument']
    with pytest.raises(c.ContractError):compile_blocking(raw,plan,ENT,schema)


def test_versioned_prompt_matches_required_roles_and_completion():
    from src.content_factory.novel_adaptation.blocking import action_contract_prompt
    plan,_,_=setup_case()
    prompt=action_contract_prompt(plan)
    assert 'instrument' in prompt and 'completion_action' in prompt
    assert action_contract_prompt(PLAN)==''


def test_completion_does_not_repeat_full_recipe_and_requires_performance():
    plan,raw,_=setup_case()
    plan['recipes']=[{'id':'recipe','action':'FULL PROCESS SHOULD NOT RENDER','inputs':['bread1'],'outputs':[],'retained_inputs':[],'source_ids':['CH1-P001']}]
    schema=blocking_schema(plan,ENT,['f'],SOURCE,None,['CH1-P001'])
    raw['beats'][0]['blocking']=[{'kind':'transform','actor':'a','recipe':'recipe','destination':'a','completion_action':'将成品盛出'}]
    compiled=compile_blocking(raw,plan,ENT,schema)
    assert '将成品盛出' in compiled['beats'][0]['action']
    assert 'FULL PROCESS' not in compiled['beats'][0]['action']
    del raw['beats'][0]['blocking'][0]['completion_action']
    with pytest.raises(c.ContractError):compile_blocking(raw,plan,ENT,schema)
