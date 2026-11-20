from copy import deepcopy
import json
from pathlib import Path
import pytest
from src.content_factory import creative_legal_director_performance_v1 as m
ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture
def sample():
 s=json.loads((ROOT/'data/production_revisions/legal_trend_text_trial_20261008/round_11/DELIVERABLE_r8/FULL_SCRIPT.json').read_text(encoding='utf-8-sig'))
 d={'emotional_arc':'压力到核对','causal_chain':'公司提出却催个人签字','ending_intent':'暂停未胜诉','spatial_design':'同一会议室双人轴线','initial_state':deepcopy(m.INITIAL),'assets':[{'id':'paper','definition':'A4申请','story_function':'口头与书面矛盾'}],'shots':[{'shot_id':'SH'+str(i+1),'beat_id':b['id'],'source_refs':m.own_refs(s,b['id']),'new_information':'新信息','observation_target':'小林','framing':'中近景','stimulus_and_response':'先听后反应','cut_reason':'叙事重心转移'} for i,b in enumerate(s['beats'])],'reaction_windows':[{'source_ref':m.own_refs(s,b['id'])[0],'phase':'after','observer':m.CHARACTERS[0],'minimum_seconds':1.2,'purpose':'消化变化'} for b in s['beats']]}
 state=deepcopy(m.INITIAL);performances=[]
 for b in s['beats']:
  start=deepcopy(state);rows=[]
  for ref in m.own_refs(s,b['id']):
   changes=[]
   for k,v in m.SOURCE_STATE_OBLIGATIONS.get(ref,{}).items():
    if state[k]!=v:changes.append({'field':k,'from':state[k],'to':v});state[k]=v
   rows.append({'source_ref':ref,'before_seconds':.5,'before_performance':'听者静止消化','active_seconds':40,'active_performance':'仅演原动作或原句','after_seconds':1.2,'after_performance':'听者眼神反应','state_changes':changes})
  performances.append({'beat_id':b['id'],'start_state':start,'rows':rows,'end_state':deepcopy(state)})
 return s,d,performances

def test_complete_original_dialogue_and_state(sample):
 s,d,p=sample;c=m.compile_complete(s,d,p)
 assert [r['original_text'] for r in c['schedule']]==[x['text'] for b in s['beats'] for x in b['steps']]
 assert c['final_state']['badge_location']=='xiaolin_neck' and c['final_state']['paper_location']=='zhou_folder'
 assert c['final_state']['paper_signed']=='unsigned' and c['real_audio_or_video_verified'] is False

def test_changed_upstream_invalidates_next_beat(sample):
 s,d,p=sample;p[1]['start_state']['paper_location']='zhou_folder'
 with pytest.raises(ValueError,match='cross-beat'):m.compile_complete(s,d,p)

def test_wrong_prop_precondition_rejected(sample):
 s,d,p=sample;p[0]['rows'][0]['state_changes'][0]['from']='xiaolin_table_corner'
 with pytest.raises(ValueError,match='precondition'):m.compile_complete(s,d,p)

def test_reaction_window_cannot_disappear(sample):
 s,d,p=sample;p[2]['rows'][0]['after_seconds']=.1
 with pytest.raises(ValueError,match='window too short'):m.compile_complete(s,d,p)

def test_long_dialogue_not_squeezed(sample):
 s,d,p=sample;p[1]['rows'][2]['active_seconds']=2
 with pytest.raises(ValueError,match='dialogue compressed'):m.compile_complete(s,d,p)

def test_no_duplicate_source_or_shot_cover(sample):
 s,d,p=sample;d['shots'][1]['source_refs'].append(d['shots'][1]['source_refs'][0])
 with pytest.raises(ValueError,match='once'):m.compile_complete(s,d,p)

def test_unfinished_prefix_not_delivery(sample):
 s,d,p=sample
 assert m.compile_prefix(s,d,p[:2])['complete'] is False
 with pytest.raises(ValueError,match='complete performance'):m.compile_complete(s,d,p[:2])

def test_review_requires_actual_performance_as_well_as_source(sample):
 s,d,p=sample;c=m.compile_complete(s,d,p);ctx={'script':s,'director':d,'compiled':c};cat=m.evidence_catalog(ctx)
 rows=[]
 for i,b in enumerate(s['beats']):
  refs=[next(k for k,v in cat.items() if v['path'].startswith(f'script.beats.{i}.'))]
  j=next(j for j,v in enumerate(c['schedule']) if v['beat_id']==b['id'])
  refs.append(next(k for k,v in cat.items() if v['path']==f'compiled.schedule.{j}.active_performance'))
  rows.append({'beat_id':b['id'],'emotion':'按原文检查','causality_and_state':'状态连贯','dialogue_and_reaction_timing':'窗口有时间','evidence_refs':refs})
 v={'story_preserved':True,'coverage':rows,'issues':[],'suggestions':[],'assessment':'全文完成'}
 expanded,result=m.validate_review(v,ctx)
 assert result['issues']==0 and expanded['coverage'][0]['evidence_refs'][0]['quote'] in str(ctx)
 v['coverage'][0]['evidence_refs']=v['coverage'][0]['evidence_refs'][:1]
 with pytest.raises(ValueError,match='actual performance'):m.validate_review(v,ctx)
