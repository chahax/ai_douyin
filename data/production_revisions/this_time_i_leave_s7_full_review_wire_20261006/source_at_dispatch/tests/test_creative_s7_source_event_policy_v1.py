from copy import deepcopy
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import run_creative_s7_source_event_policy_v37 as r

def test_schema_accepts_complete_generated_intents_rejects_known_state_faults():
 c,d=r.previous.direction_source(1);inp=r.physical.build_local_input(c,d,r.previous.local_sources(1,5));s=r.restrict_schema(r.window_base.supported_plan_schema(inp),inp);a=s['properties']['actions']['prefixItems'];doc={'actions':[]}
 for action in a:
  es=action['properties']['events']['prefixItems'];doc['actions'].append({'source_step_ref':action['properties']['source_step_ref']['const'],'events':[{'intent':'模型必须完整生成原事件自然意图','subject':'C02','operation':e['properties']['operation']['const'],'satisfies':e['properties']['satisfies']['const']} for e in es]})
 Draft202012Validator(s).validate(doc)
 for case in ('hidden_gaze','release_pen','body_turn'):
  bad=deepcopy(doc)
  if case=='hidden_gaze':bad['actions'][0]['events']=bad['actions'][0]['events'][:1]
  else:bad['actions'][1]['events'][0]['operation']={'kind':'place' if case=='release_pen' else 'face','actor':'C02','target':'P07' if case=='release_pen' else '','value':'surface:E02:edge' if case=='release_pen' else 'toward_E02'}
  with pytest.raises(ValidationError):Draft202012Validator(s).validate(bad)
