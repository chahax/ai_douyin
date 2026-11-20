import pytest
from tests.test_creative_legal_director_performance_v1 import sample
from src.content_factory import creative_legal_director_performance_v1 as base
from src.content_factory import creative_legal_split_review_evidence_v2 as m

def review(sample):
 s,d,p=sample;c=base.compile_complete(s,d,p);ctx={'script':s,'director':d,'compiled':c};cat=base.evidence_catalog(ctx);rows=[]
 for i,b in enumerate(s['beats']):
  src=next(k for k,v in cat.items() if v['path'].startswith(f'script.beats.{i}.'))
  j=next(j for j,v in enumerate(c['schedule']) if v['beat_id']==b['id']);actual=next(k for k,v in cat.items() if v['path']==f'compiled.schedule.{j}.active_performance')
  rows.append({'beat_id':b['id'],'emotion':'情绪','causality_and_state':'连续','dialogue_and_reaction_timing':'窗口','script_evidence_refs':[src],'performance_evidence_refs':[actual]})
 return ctx,{'story_preserved':True,'coverage':rows,'issues':[],'suggestions':[],'assessment':'完整结论'}

def test_all_reasons_preserved_with_complete_citations(sample):
 ctx,v=review(sample);expanded,result=m.expand(v,ctx)
 assert result['issues']==0 and expanded['assessment']==v['assessment']
 assert expanded['coverage'][0]['emotion']==v['coverage'][0]['emotion']
 assert len(expanded['coverage'][0]['evidence_refs'])==2

def test_current_performance_field_cannot_omit(sample):
 ctx,v=review(sample);v['coverage'][0].pop('performance_evidence_refs')
 with pytest.raises(Exception):m.expand(v,ctx)

def test_other_beat_citation_rejected(sample):
 ctx,v=review(sample);v['coverage'][0]['performance_evidence_refs']=v['coverage'][1]['performance_evidence_refs']
 with pytest.raises(Exception):m.expand(v,ctx)

def test_catalog_navigation_does_not_change_original_source(sample):
 ctx,v=review(sample);cat=m.compact_catalog(ctx)
 assert all(len(r['excerpt'])<=48 for r in cat)
 assert ctx['script']['beats'][0]['steps'][0]['text'].endswith('纸旁')
