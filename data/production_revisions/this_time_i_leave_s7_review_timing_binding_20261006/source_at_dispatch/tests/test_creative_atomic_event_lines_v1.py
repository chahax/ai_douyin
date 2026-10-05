import pytest,json
from scripts import run_creative_s7_event_lines_v39 as r
from scripts.creative_atomic_event_lines_v1 import decode,lines,messages

def test_strict_complete_lines_and_context():
 c,d=r.previous.direction_source(1);inp=r.physical.build_local_input(c,d,r.previous.local_sources(1,6));text='A0E0|C02|gaze|-|at_P05|-|看明细单\nA0E1|C02|hold|-|-|-|原右手持笔落字'
 doc=decode(text,inp);assert doc['actions'][0]['events'][1]['operation'] is None;assert doc['actions'][0]['events'][0]['operation']['actor']=='C02'
 assert doc['actions'][0]['events'][0]['intent']=='看明细单'
 for bad in (text.replace('A0E1','A0E2'),text.replace('A0E0','A1E0'),'```'+text+'```',text.replace('hold|-|-','hold|P07|right_hand')):
  with pytest.raises(ValueError):decode(bad,inp)
 payload=json.loads(messages(inp,{})[1]['content']);assert payload['read_only_complete_creative_source']['raw_linear_script']==c['raw_linear_script'];assert payload['read_only_complete_creative_source']['reference_pack']==c['reference_pack']

def test_model_line_intent_not_trimmed():
 assert lines('A0E0|C02|hold|-|-|-| 原意图 ')[0][-1]==' 原意图 '
