from copy import deepcopy
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import run_creative_s7_declared_windows_v33 as r


def fixture():
 ctx=deepcopy(r.previous.context());film=r.previous.assembled_film()['output'];opening=r.previous.latest('opening_s7_r')['output'];return ctx,film,opening


def test_exact_policy_compiles_five_source_bound_windows_without_rewriting_direction():
 ctx,f,s=fixture();p=r.make_policy(ctx,f);d=r.compile_policy(ctx,f,s,p)
 assert p['model_authored'] is False and p['actual_timing_verified'] is False
 assert sum(len(x['performance_requirements']) for x in r.physical._shots(d))==5
 for old,new in zip(r.physical._shots(f),r.physical._shots(d)):
  for key in old:assert old[key]==new[key]
 assert [q['minimum_seconds'] for shot in r.physical._shots(d) for q in shot['performance_requirements']]==[2,2,1.5,2,2]
 assert d['initial_state']==s['initial_state']


@pytest.mark.parametrize('field,value',[('subject','C02'),('reaction_path','raw_linear_script.beats.0.steps.0'),('relation','during'),('minimum_seconds',.2)])
def test_modified_policy_or_wrong_actor_or_time_fails_before_paid_dispatch(field,value):
 ctx,f,s=fixture();p=r.make_policy(ctx,f);p['targets'][0][field]=value
 with pytest.raises(RuntimeError):r.compile_policy(ctx,f,s,p)


def test_changed_script_or_director_invalidates_policy():
 ctx,f,s=fixture();p=r.make_policy(ctx,f);ctx['raw_linear_script']['beats'][0]['steps'][0]['text']+=' changed'
 with pytest.raises(RuntimeError):r.compile_policy(ctx,f,s,p)
 ctx,f,s=fixture();p=r.make_policy(ctx,f);f['ending_intent']+=' changed'
 with pytest.raises(RuntimeError):r.compile_policy(ctx,f,s,p)


def test_supported_plan_rejects_untracked_affect_and_accepts_original_two_dialogues():
 ctx,f,s=fixture();d=r.compile_policy(ctx,f,s,r.make_policy(ctx,f));inp=r.physical.build_local_input(ctx,d,[]);schema=r.supported_plan_schema(inp)
 action={'source_step_ref':d['beats'][0]['shots'][0]['source_step_refs'][0],'events':[{'intent':'首动作前站在自己工位，原物件不取','subject':'C01','operation':{'kind':'affect','actor':'C01','target':'','value':'firm'},'satisfies':[]}]}
 # Complete actions to distinguish bad kind from incomplete array.
 other={'source_step_ref':d['beats'][0]['shots'][0]['source_step_refs'][1],'events':[{'intent':'原推单','subject':'C02','operation':None,'satisfies':[]}]}
 with pytest.raises(ValidationError):Draft202012Validator(schema).validate({'actions':[action,other]})
 no_actions={'actions':[]};Draft202012Validator(r.split.performance_schema(no_actions)).validate({'dialogue_performance':'原两句完整拒绝','performances':[]})


def test_policy_configuration_has_no_paid_or_media_side_effects():
 assert r.AUTH['automatic_retry'] is False and r.AUTH['media_calls']==0 and r.AUTH['aggregate_token_cap'] is None
