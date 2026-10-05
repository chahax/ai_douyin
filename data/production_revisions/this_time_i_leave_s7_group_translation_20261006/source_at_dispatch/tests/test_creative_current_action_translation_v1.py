import json,pytest
from copy import deepcopy
from scripts import run_creative_s7_current_translation_v40 as r

def test_exact_mechanical_subset_and_changed_source_rejected():
 c,d=r.previous.direction_source(1);inp=r.physical.build_local_input(c,d,r.previous.local_sources(1,6));m=r.translator_messages(inp,{});req={'messages':m};v=r.validate_consumed(inp,req,'a','b');assert not v['full_reference_in_this_translation']
 payload=json.loads(m[1]['content']);assert 'read_only_complete_creative_source' not in payload and payload['current_complete_source']['ordered_complete_current_steps']
 bad=deepcopy(req);p=json.loads(bad['messages'][1]['content']);p['current_complete_source']['actual_start_state']['P07']['holder']='none';bad['messages'][1]['content']=json.dumps(p)
 with pytest.raises(ValueError):r.validate_consumed(inp,bad,'a','b')
