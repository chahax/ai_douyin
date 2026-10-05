import json,pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import run_creative_s7_native_events_v38 as r

def test_native_focused_complete_sources_and_motion_rejection():
 c,d=r.previous.direction_source(1);inp=r.physical.build_local_input(c,d,r.previous.local_sources(1,6));s=r.restrict_schema(r.window_base.supported_plan_schema(inp),inp);m=r.native_plan_messages(inp,{})
 p=json.loads(m[1]['content']);assert p['read_only_complete_creative_source']['raw_linear_script']==c['raw_linear_script'];assert p['read_only_complete_creative_source']['reference_pack']==c['reference_pack'];assert p['current_direction_and_complete_steps']['actual_start_state']==inp['start_state']
 op=s['properties']['actions']['prefixItems'][0]['properties']['events']['items']['properties']['operation'];Draft202012Validator(op).validate(None)
 for kind in ('take','place','stand','move'):
  with pytest.raises(ValidationError):Draft202012Validator(op).validate({'kind':kind,'actor':'C02','target':'P07','value':'right_hand'})
 req=r.director_base.direction_wire(m,s,3000,{})
 assert 'output_transport' not in req and 'inner_document_schema' not in req and 'payload_json' not in req['structured_schema']['properties']
