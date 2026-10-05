from copy import deepcopy
import json,pytest
from jsonschema import ValidationError
from scripts import run_creative_s7_scalar_performance_v34 as r


def plan():return r.previous.latest('plan_s7_d1_p003_r')['output']


def test_complete_six_scalar_slots_project_exact_prose_and_seconds_without_duplicates():
 p=plan();raw={'dialogue_performance':'原列词语气'}
 for i,s in enumerate(r.split.slots(p)):raw[s['slot']+'_seconds']=.4+i*.1;raw[s['slot']+'_performance']='对应原事件'+str(i)
 d=r.decode_performance(raw,p)
 assert len(d['performances'])==6 and [x['slot'] for x in d['performances']]==[s['slot'] for s in r.split.slots(p)]
 assert all(x['seconds']==raw[x['slot']+'_seconds'] and x['performance']==raw[x['slot']+'_performance'] for x in d['performances'])
 for mutate in ('missing','extra','wrong_type'):
  bad=deepcopy(raw)
  if mutate=='missing':bad.pop('A0E2_performance')
  elif mutate=='extra':bad['A0E2_duplicate']='不接受'
  else:bad['A0E0_seconds']='0.4'
  with pytest.raises(ValidationError):r.decode_performance(bad,p)


def test_focused_actual_request_contains_full_R01_S7_and_fixed_plan_without_registry_duplicate():
 c,d=r.previous.direction_source(1);inp=r.physical.build_local_input(c,d,r.previous.local_sources(1,2));p=plan();payload=json.loads(r.focused_performance_messages(inp,p,{})[1]['content'])
 assert payload['read_only_complete_creative_source']['raw_linear_script']==c['raw_linear_script'] and payload['read_only_complete_creative_source']['reference_pack']==c['reference_pack']
 assert payload['complete_same_model_event_plan']==p and payload['current_direction_and_complete_steps']['actual_start_state']==inp['start_state']
 assert 'component_registry' not in payload['read_only_complete_creative_source']


def test_same_S7_cache_binding_valid_and_changed_plan_or_start_state_rejected():
 ctx,d=r.previous.direction_source(1)
 for i in (1,2):
  rec=r.previous.latest(f'local_s7_d1_p{i:03}_r');p=r.previous.latest(f'plan_s7_d1_p{i:03}_r');inp=r.physical.build_local_input(ctx,d,r.previous.local_sources(1,i-1));r.verify_cache_binding(rec,p,inp)
  changed=deepcopy(inp);changed['start_state']['C01']['position']='changed'
  with pytest.raises(RuntimeError):r.verify_cache_binding(rec,p,changed)
  changed=deepcopy(p);changed['output']['actions'][0]['events'][0]['intent']+=' changed'
  with pytest.raises(RuntimeError):r.verify_cache_binding(rec,changed,inp)


def test_two_dialogue_zero_actions_has_one_native_field_and_no_extra_slot():
 raw={'dialogue_performance':'两句拒绝不切开'};assert r.decode_performance(raw,{'actions':[]})=={'dialogue_performance':raw['dialogue_performance'],'performances':[]}
 assert len(r.scalar_performance_schema({'actions':[]})['properties'])==1
 assert r.AUTH['automatic_retry'] is False and r.AUTH['media_calls']==0
