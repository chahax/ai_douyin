import pytest
from src.content_factory.novel_literal_review_v3 import *
from src.content_factory.novel_evidence_graph_v1 import source_catalog
SRC={'chapters':[{'index':1,'text':'甲先出门。\n乙后来出门。'}]}
CAT=source_catalog(SRC)
FACT={'id':'F','statement':'甲先出门','time_scope':'current','source_ids':['CH1-P001']}
def finding(fragment='甲先出门'):
 return {'claim_id':'F','verdict':'supported','claim_fragment':fragment,'claim_reading':'甲先出门','source_reading':'甲先出门','source_ids':['CH1-P001'],'reason':'一致'}

def test_reviewer_cannot_substitute_predicate():
 assert validate_review({'findings':[finding()]},[FACT],CAT)
 with pytest.raises(ValueError,match='rewritten_claim_fragment'):validate_review({'findings':[finding('乙先出门')]},[FACT],CAT)

def test_explicit_scope_required_and_more_than_18_allowed():
 facts=[{**FACT,'id':str(i)} for i in range(25)]
 assert len(validate_material({'claims':facts},CAT)['claims'])==25
 del facts[0]['time_scope']
 with pytest.raises(ValueError):validate_material({'claims':facts},CAT)

def test_graph_routes_completeness_and_never_auto_accepts():
 calls=[]
 def caller(name,prompt,payload,schema):
  calls.append(name)
  if name=='EXTRACT':return {'claims':[FACT]}
  if name=='COMPLETENESS':return {'omissions':[{'source_ids':['CH1-P002'],'missing_content':'乙出门','why_important':'顺序'}]}
  return {'findings':[finding()]}
 out=build_graph(SRC,caller).invoke({})
 assert calls==['EXTRACT','REVIEW_01','COMPLETENESS'] and out['status']=='needs_revision'

def test_review_requires_exact_complete_batch():
 with pytest.raises(ValueError):validate_review({'findings':[finding(),finding()]},[FACT],CAT)

def test_invalid_source_rejected():
 f=finding();f['source_ids']=['CH9-P001']
 with pytest.raises(ValueError):validate_review({'findings':[f]},[FACT],CAT)

def test_focus_retains_full_chapter_and_fixed_statement():
 from src.content_factory.novel_focus_review_v4 import context_for
 x=context_for(FACT,CAT)
 assert x['fixed_candidate']==FACT and x['complete_related_chapters']==CAT

def test_supported_does_not_override_unknown_or_wrong_time_scope():
 from src.content_factory.novel_focus_review_v4 import validate_decision
 raw={'claim_id':'F','decision':'supported','source_time_scope':'original_novel_future','source_ids':['CH1-P001'],'reason':'fixture','temporal_reason':'fixture'}
 assert not validate_decision(raw,FACT,CAT)['accepted']
 assert not validate_decision(raw,{**FACT,'time_scope':'unknown'},CAT)['accepted']
 assert validate_decision(raw,{**FACT,'time_scope':'original_novel_future'},CAT)['accepted']

def test_blind_reader_never_receives_candidate_or_prior_verdict():
 from src.content_factory.novel_blind_source_v5 import build_graph
 calls=[]
 def caller(name,prompt,payload,schema):
  calls.append(name)
  if name.startswith('SOURCE'):
   assert set(payload)=={'focused_context','complete_related_chapters'}
   return {'facts':[{'id':'S','statement':'甲先出门','certainty':'established','source_ids':['CH1-P001']}]}
  assert payload['fixed_candidate']==FACT and payload['independent_source_reading']['facts'][0]['id']=='S'
  return {'claim_id':'F','decision':'supported','source_time_scope':'current','source_ids':['CH1-P001'],'reason':'相同','temporal_reason':'当前'}
 out=build_graph(SRC,[FACT],caller).invoke({'cursor':0,'findings':[]})
 assert calls==['SOURCE_01','COMPARE_01'] and out['status']=='pending_independent_acceptance'
