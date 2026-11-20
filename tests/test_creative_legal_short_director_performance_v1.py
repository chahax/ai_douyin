from copy import deepcopy
import pytest
from src.content_factory import creative_legal_short_director_performance_v1 as c
from scripts.run_legal_short_director_performance_v1_20261009 import sources

def fixture():
 s=sources()['full_script'];d={'emotional_arc':'受压到拒签','causal_chain':'要求离开催签拒签收纸','ending_intent':'未解决但未签','spatial_design':'同一办公室','initial_state':deepcopy(c.INITIAL),'assets':[{'id':'room','definition':'办公室','story_function':'同场冲突'}],'shots':[],'reaction_windows':[]};ps=[];state=deepcopy(c.INITIAL)
 for b in s['beats']:
  refs=c.own_refs(s,b['id']);d['shots'].append({'shot_id':'SH'+b['id'][1:],'beat_id':b['id'],'source_refs':refs,'new_information':'当前信息','observation_target':'两人','framing':'两人同框','stimulus_and_response':'当前反应','cut_reason':'新信息'})
  d['reaction_windows'].append({'source_ref':refs[-1],'phase':'after','observer':c.CHARACTERS[0],'minimum_seconds':.5,'purpose':'消化'})
  p={'beat_id':b['id'],'start_state':deepcopy(state),'rows':[]}
  for ref in refs:
   changes=[]
   for k,v in c.SOURCE_STATE_OBLIGATIONS.get(ref,{}).items():
    if state[k]!=v:changes.append({'field':k,'from':state[k],'to':v});state[k]=v
   p['rows'].append({'source_ref':ref,'before_seconds':0,'before_performance':'不占额外时间','active_seconds':6,'active_performance':'只完成原源','after_seconds':.5,'after_performance':'静止消化','state_changes':changes})
  p['end_state']=deepcopy(state);ps.append(p)
 return s,d,ps

def test_exact_new_state_chain():
 s,d,p=fixture();v=c.compile_complete(s,d,p);assert len(v['schedule'])==14;assert v['final_state']['zhou_position']=='outside_room';assert v['final_state']['xiaolin_position']=='seated';assert v['final_state']['badge_location']=='xiaolin_neck'
def test_cross_beat_state_cannot_reset():
 s,d,p=fixture();p[1]['start_state']['paper_location']='zhou_table_side'
 with pytest.raises(ValueError,match='cross-beat'):c.compile_complete(s,d,p)
def test_important_reaction_has_time():
 s,d,p=fixture();p[2]['rows'][-1]['after_seconds']=0
 with pytest.raises(ValueError,match='reaction window'):c.compile_complete(s,d,p)
def test_no_speech_acceleration():
 s,d,p=fixture();p[2]['rows'][1]['active_seconds']=1
 with pytest.raises(ValueError,match='five spoken'):c.compile_complete(s,d,p)
def test_no_badge_operation_in_source():
 s,d,p=fixture();p[0]['rows'][0]['state_changes']=[{'field':'badge_location','from':'xiaolin_neck','to':'xiaolin_table_corner'}]
 with pytest.raises(ValueError):c.compile_complete(s,d,p)
def test_short_limit_and_physical_noncompletion():
 s,d,p=fixture()
 for beat in p:
  for row in beat['rows']:row.update(active_seconds=12,before_seconds=1,after_seconds=1)
 with pytest.raises(ValueError,match='180'):c.compile_complete(s,d,p)
