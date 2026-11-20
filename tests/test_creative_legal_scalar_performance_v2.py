from copy import deepcopy
import pytest
from tests.test_creative_legal_director_performance_v1 import sample
from src.content_factory import creative_legal_scalar_performance_v2 as m

def wire(p):
 v={k:deepcopy(p[k]) for k in ('beat_id','start_state','end_state')}
 for row in p['rows']:
  r=deepcopy(row);ref=r.pop('source_ref');r['state_changes']={c['field']:{'from':c['from'],'to':c['to']} for c in r['state_changes']};v[m.key(ref)]=r
 return v

def test_no_values_rewritten_on_keyed_projection(sample):
 s,d,p=sample
 for beat in p:assert m.expand(wire(beat),s,beat['beat_id'])==beat

def test_missing_seconds_still_rejected(sample):
 s,d,p=sample;v=wire(p[0]);v['B1_S03'].pop('active_seconds')
 with pytest.raises(Exception):m.expand(v,s,'B1')

def test_dollar_text_or_item_no_fallback(sample):
 s,d,p=sample;v=wire(p[0]);v['B1_S03']['active_seconds']={'$text':'5.5'}
 with pytest.raises(Exception):m.expand(v,s,'B1')

def test_no_dialogue_prop_operation(sample):
 s,d,p=sample;v=wire(p[0]);v['B1_S02']['state_changes']={'badge_location':{'from':'xiaolin_table_corner','to':'xiaolin_neck'}}
 with pytest.raises(Exception):m.expand(v,s,'B1')

def test_native_schema_rejects_short_dialogue(sample):
 s,d,p=sample;v=wire(p[1]);v['B2_S03']['active_seconds']=1
 with pytest.raises(Exception):m.expand(v,s,'B2')
