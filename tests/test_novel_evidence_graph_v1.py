import pytest
from src.content_factory.novel_evidence_graph_v1 import *

SOURCE={'chapters':[{'index':1,'text':'哥哥拿着钱。\n\n弟弟没有收。'}]}
CAT=source_catalog(SOURCE)
def result(ids,verdict='supported'):
 return {'findings':[{'claim_id':id,'atoms':[{'statement':'测试','verdict':verdict,'source_ids':['CH1-P001'],'reason':'原文'}]} for id in ids]}

def test_catalog_preserves_original_positions():
 assert [x['id'] for x in CAT]==['CH1-P001','CH1-P003']

@pytest.mark.parametrize('fault',['missing','duplicate','invalid_source','unsupported_evidence'])
def test_reject_bad_audits(fault):
 r=result(['A'])
 if fault=='missing':r['findings'][0]['claim_id']='B'
 if fault=='duplicate':r['findings']*=2
 if fault=='invalid_source':r['findings'][0]['atoms'][0]['source_ids']=['CH2-P001']
 if fault=='unsupported_evidence':r['findings'][0]['atoms'][0]['source_ids']=[]
 with pytest.raises(ValueError):validate_findings(r,[{'id':'A'}],CAT)

def test_graph_batches_and_does_not_pass_partial_claim():
 calls=[]
 def fake(name,prompt,payload,schema):
  calls.append(name);r=result([x['id'] for x in payload['claims']])
  if name=='AUDIT_01':r['findings'][0]['atoms'].append({'statement':'额外命题','verdict':'not_stated','source_ids':[],'reason':'未交代'})
  return r
 g=build_graph(SOURCE,fake,seeded=True)
 out=g.invoke({'claims':[{'id':str(i),'statement':'x','source_ids':[]} for i in range(7)],'cursor':0,'findings':[]})
 assert calls==['AUDIT_01','AUDIT_02','AUDIT_03']
 assert len(out['accepted'])==6 and out['rejected'][0]['id']=='0'

def test_transport_error_does_not_retry():
 calls=[]
 def fail(*args):calls.append(1);raise TimeoutError('unknown')
 with pytest.raises(TimeoutError):build_graph(SOURCE,fail,seeded=True).invoke({'claims':[{'id':'A'}],'cursor':0,'findings':[]})
 assert len(calls)==1

def test_extraction_requires_target_chapter_and_unique_id():
 c={'id':'A','statement':'原文','source_ids':['CH1-P001']}
 assert validate_claims({'claims':[c]},CAT,1)
 with pytest.raises(ValueError):validate_claims({'claims':[c,c]},CAT,1)
 with pytest.raises(ValueError):validate_claims({'claims':[c]},CAT,2)

def test_sqlite_checkpoint_records_node_results(tmp_path):
 from langgraph.checkpoint.sqlite import SqliteSaver
 def fake(name,prompt,payload,schema):return result([x['id'] for x in payload['claims']])
 config={'configurable':{'thread_id':'fixture'}}
 with SqliteSaver.from_conn_string(str(tmp_path/'graph.sqlite')) as saver:
  graph=build_graph(SOURCE,fake,saver,seeded=True)
  out=graph.invoke({'claims':[{'id':'A','statement':'x','source_ids':[]}],'cursor':0,'findings':[]},config)
  assert out['status']=='evidence_checked'
 with SqliteSaver.from_conn_string(str(tmp_path/'graph.sqlite')) as saver:
  snapshot=build_graph(SOURCE,fake,saver,seeded=True).get_state(config)
  assert snapshot.values['accepted'][0]['id']=='A'

def test_inline_schema_preserves_array_contract():
 from src.content_factory.novel_evidence_protocol_v2 import inline_schema
 import json
 from jsonschema import validate,ValidationError
 schema=inline_schema(Findings.model_json_schema())
 assert '$ref' not in json.dumps(schema) and '$defs' not in json.dumps(schema)
 valid=result(['A']);validate(valid,schema)
 valid['findings'][0]['atoms']={'item':valid['findings'][0]['atoms']}
 with pytest.raises(ValidationError):validate(valid,schema)

def test_independent_guards_block_missing_event_and_no_auto_accept():
 from src.content_factory.novel_evidence_guards_v1 import build_guards
 claims=[{'id':'A','statement':'x','source_ids':['CH1-P001']}]
 def fake(name,prompt,payload,schema):
  return {'checked_claim_ids':['A'],'issues':[] if name=='RELATION_GUARD' else [{'kind':'missing_event','claim_ids':[],'source_ids':['CH1-P003'],'explanation':'遗漏拒收'}]}
 out=build_guards(SOURCE,claims,fake).invoke({})
 assert out['status']=='needs_revision'
 def good(*args):return {'checked_claim_ids':['A'],'issues':[]}
 assert build_guards(SOURCE,claims,good).invoke({})['status']=='pending_independent_acceptance'

def test_stage_guard_schema_matches_prompt_and_validator():
 from src.content_factory.novel_evidence_guards_v2 import gate_schema,KINDS
 from jsonschema import validate,ValidationError
 for name,kinds in KINDS.items():
  for kind in ['timeline','causality','certainty','missing_event','missing_relationship']:
   candidate={'checked_claim_ids':['A'],'issues':[{'kind':kind,'claim_ids':['A'],'source_ids':['CH1-P001'],'explanation':'测试'}]}
   if kind in kinds:validate(candidate,gate_schema(name))
   else:
    with pytest.raises(ValidationError):validate(candidate,gate_schema(name))
