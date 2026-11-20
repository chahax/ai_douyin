from copy import deepcopy
import json
import pytest
from src.content_factory import story_first_contract_v2 as c
from src.content_factory import story_first_production_v2 as p
from src.content_factory.corpus_screenplay_v1 import freeze,digest,read

SOURCE={'chapters':[{'index':1,'text':'林岚是阿禾的继母。林岚和阿禾在厨房，周远在院外。\n林岚把钥匙递给阿禾。'}]}
FOUNDATION={'world':'一家人的钥匙交接','characters':[{'id':x,'name':x,'source_ids':['CH1-P001']} for x in ['林岚','阿禾','周远']],
 'places':[{'id':x,'name':x,'source_ids':['CH1-P001']} for x in ['厨房','院外']],
 'relationships':[{'subject':'林岚','object':'阿禾','relation':'是继母','source_ids':['CH1-P001']}],
 'constraints':[],'visual_style':'现实','creative_additions':[]}
STORY={'title':'钥匙','scenes':[{'id':'S1','story_time':'傍晚','temporal_mode':'actual','place_id':'厨房','seconds':10,
 'information':'交接','plot':'林岚把钥匙交给阿禾','source_ids':['CH1-P002'],
 'dialogue':[{'id':'D1','speaker':'林岚','mode':'onscreen','text':'给你。'}]}]}
STAGING={'creative_additions':[],'scenes':[{'scene_id':'S1','cast':['林岚','阿禾'],
 'positions':[{'person':x,'place_id':'厨房','mark':'桌旁'} for x in ['林岚','阿禾']],
 'entries':[],'actions':[{'id':'A1','people':['林岚','阿禾'],'description':'递钥匙','start':0,'end':4,'source_ids':['CH1-P002']}],
 'changes':[{'kind':'prop','subject':'阿禾','item':'钥匙','before':'没有','after':'手持','action_id':'A1','source_ids':['CH1-P002']}],
 'performance':'专注','camera':'近景','audio':[{'dialogue_id':'D1','start':0,'end':2}]}]}

def artifacts():return deepcopy(dict(foundation=FOUNDATION,story=STORY,staging=STAGING))
def review(a):return {'candidate_sha256':digest(a),'decision':'pass','issues':[],
 'checks':[{'dimension':d,'verdict':'pass','reason':'fixture'} for d in ['source','space_cast','props_knowledge','audio','timing','information_pacing']]}

def test_valid_story_then_staging():
 c.validate_foundation(FOUNDATION,SOURCE);c.validate_story(STORY,SOURCE,FOUNDATION);c.validate_staging(STAGING,SOURCE,FOUNDATION,STORY)
 assert '[onscreen]' in c.render(artifacts())

@pytest.mark.parametrize('kind',['background_person','wrong_place','unknown_audio','absent_speaker','action_overrun','fast_audio','entry_unbound','state_unbound','duplicate_cast_position'])
def test_reject_actual_previous_failure_patterns(kind):
 b=deepcopy(STAGING);s=deepcopy(STORY);d=b['scenes'][0]
 if kind=='background_person':d['actions'][0]['people'].append('周远')
 elif kind=='wrong_place':d['positions'][0]['place_id']='院中'
 elif kind=='unknown_audio':d['audio'][0]['dialogue_id']='D999'
 elif kind=='absent_speaker':s['scenes'][0]['dialogue'][0]['speaker']='周远'
 elif kind=='action_overrun':d['actions'][0]['end']=11
 elif kind=='fast_audio':d['audio'][0]['end']=.1
 elif kind=='entry_unbound':d['entries']=[{'person':'阿禾','from_place':'院外','to_place':'厨房','action_id':'X'}]
 elif kind=='state_unbound':d['changes'][0]['action_id']='X'
 else:d['positions'].append(deepcopy(d['positions'][0]))
 with pytest.raises(Exception):c.validate_staging(b,SOURCE,FOUNDATION,s)

def test_inner_voice_is_explicit_and_no_forced_cast():
 s=deepcopy(STORY);s['scenes'][0]['dialogue'][0].update(speaker='周远',mode='inner_voice')
 c.validate_staging(STAGING,SOURCE,FOUNDATION,s)
 assert '[inner_voice]' in c.render({'foundation':FOUNDATION,'story':s,'staging':STAGING})

def test_null_and_empty_are_addressed_by_id():
 cat=c.evidence_catalog({'foundation':{'a':'','b':None,'c':[]}})
 assert [x['value_state'] for x in cat]==['empty','null','empty']
 assert [x['value'] for x in cat]==['',None,[]]

@pytest.mark.parametrize('kind',['foreign_id','bad_sha','wrong_owner','pass_with_hard_issue','missing_dimension'])
def test_review_contract(kind):
 a=artifacts();r=review(a);e=c.evidence_catalog(a)[0]['id']
 issue={'severity':'hard_error','responsible_stage':'foundation','evidence_ids':[e],'source_ids':['CH1-P001'],'reason':'fixture','required_change':'fixture'}
 if kind=='foreign_id':issue['evidence_ids']=['E99999'];r.update(decision='revise',issues=[issue]);r['checks'][0]['verdict']='revise'
 elif kind=='bad_sha':r['candidate_sha256']='wrong'
 elif kind=='wrong_owner':issue['responsible_stage']='staging';r.update(decision='revise',issues=[issue]);r['checks'][0]['verdict']='revise'
 elif kind=='pass_with_hard_issue':r['issues']=[issue]
 else:r['checks'].pop()
 with pytest.raises(Exception):c.validate_review(r,SOURCE,a)

def prepare_fixture(tmp_path):
 run=tmp_path/'run';run.mkdir()
 scope={'test':True};plan={'implementation_pin':p.pins(),'source_sha256':digest(SOURCE),'authorization_sha256':digest(scope),
 'routes':{'writer':{'model':p.MODEL},'director':{'model':'deepseek-flash'}},'max_calls':32,'root_repairs':2,'context':131072,'target_seconds':60}
 for name,v in [('PLAN',plan),('SOURCE',SOURCE),('AUTHORIZATION',scope),('STATE',{'status':'prepared','pending':None,'calls_started':0,'reported_tokens':0,'plan_sha256':digest(plan)})]:freeze(run/(name+'.json'),v)
 return run

class Fake:
 def __init__(self,fail=None):self.calls=[];self.fail=fail
 def call(self,role,messages,schema):
  payload=json.loads(messages[1]['content']);self.calls.append((role,payload))
  if self.fail=='timeout':raise TimeoutError('fixture')
  fields=schema['properties']
  if 'world' in fields:v=deepcopy(FOUNDATION)
  elif 'title' in fields:v=deepcopy(STORY)
  elif 'candidate_sha256' in fields:v=review(payload['artifacts'])
  else:v=deepcopy(STAGING)
  native={'id':'fixture','model':p.MODEL if role=='writer' else 'deepseek-flash',
   'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2},
   'choices':[{'finish_reason':'tool_calls' if role=='writer' else 'stop','message':{
    'tool_calls':[{'function':{'name':'submit_result','arguments':json.dumps(v,ensure_ascii=False)}}]} if role=='writer' else {'content':json.dumps(v)}}]}
  if self.fail=='length':native['choices'][0]['finish_reason']='length'
  if self.fail=='usage':native['usage']['total_tokens']=3
  return native

def test_native_full_chain_and_pins(tmp_path):
 run=prepare_fixture(tmp_path);client=Fake();r=p.execute(run,client=client,verify_routes=False)
 assert not r['error'] and len(client.calls)==6
 assert [x[0] for x in client.calls]==['writer']*4+['director']*2
 assert 'story' in client.calls[2][1]['accepted_upstream']
 assert 'staging' not in client.calls[1][1]['accepted_upstream']
 assert (run/'SCREENPLAY.md').exists()
 with pytest.raises(ValueError):p.execute(run,client=client,verify_routes=False)

@pytest.mark.parametrize('failure,expected_pending',[('timeout',1),('usage',1),('length',None)])
def test_unknown_and_truncated_never_replayed(tmp_path,failure,expected_pending):
 run=prepare_fixture(tmp_path);f=Fake(failure);r=p.execute(run,client=f,verify_routes=False)
 assert r['error'] and len(f.calls)==1 and r['state']['pending']==expected_pending
 with pytest.raises(ValueError):p.execute(run,client=f,verify_routes=False)

def test_tampered_source_no_dispatch(tmp_path):
 run=prepare_fixture(tmp_path);(run/'SOURCE.json').write_text('{}');f=Fake()
 with pytest.raises(ValueError):p.execute(run,client=f,verify_routes=False)
 assert not f.calls

def test_invalidation_order():
 assert c.earliest_stage([{'issues':[{'severity':'hard_error','responsible_stage':'staging'},{'severity':'hard_error','responsible_stage':'story'}]}])=='story'

def test_compact_review_index_resolves_every_original_value(tmp_path):
 run=prepare_fixture(tmp_path);client=Fake();result=p.execute(run,client=client,verify_routes=False)
 assert not result['error']
 payload=client.calls[3][1]
 assert payload['evidence_catalog_columns']==['id','stage','path','value_state']
 original={r['id']:r for r in c.evidence_catalog(payload['artifacts'])}
 for identifier,stage,path,value_state in payload['evidence_catalog']:
  value=payload['artifacts'][stage]
  for component in path:value=value[component]
  assert value==original[identifier]['value']
  assert value_state==original[identifier]['value_state']
 assert payload['complete_chapters']==SOURCE['chapters']

def test_staging_repair_preserves_story_and_rechecks_same_candidate(tmp_path):
 class Repair(Fake):
  def call(self,role,messages,schema):
   result=super().call(role,messages,schema)
   if len(self.calls)==4:
    a=self.calls[-1][1]['artifacts'];v=review(a)
    evidence=next(row['id'] for row in c.evidence_catalog(a) if row['stage']=='staging')
    v.update(decision='revise',issues=[{'severity':'hard_error','responsible_stage':'staging',
      'evidence_ids':[evidence],'source_ids':['CH1-P002'],'reason':'fixture staging issue','required_change':'repair staging'}])
    v['checks'][1]['verdict']='revise'
    result['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps(v)
   return result
 run=prepare_fixture(tmp_path);client=Repair();result=p.execute(run,client=client,verify_routes=False)
 assert not result['error'] and len(client.calls)==8
 assert (run/'STAGING_01.json').exists() and not (run/'STORY_01.json').exists()
 assert client.calls[4][1]['required_corrections'][0]['bound_evidence']
 assert client.calls[-1][1]['candidate_sha256']==client.calls[-2][1]['candidate_sha256']

def test_uncertain_review_stops_before_final_dispatch(tmp_path):
 class Uncertain(Fake):
  def call(self,role,messages,schema):
   result=super().call(role,messages,schema)
   if len(self.calls)==4:
    a=self.calls[-1][1]['artifacts'];v=review(a)
    v.update(decision='uncertain',issues=[{'severity':'uncertain','responsible_stage':'foundation',
       'evidence_ids':[c.evidence_catalog(a)[0]['id']],'source_ids':[],
       'reason':'insufficient evidence','required_change':'check evidence'}])
    v['checks'][0]['verdict']='uncertain'
    result['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps(v)
   return result
 run=prepare_fixture(tmp_path);client=Uncertain();result=p.execute(run,client=client,verify_routes=False)
 assert result['error']['reason']=='review_evidence_insufficient'
 assert len(client.calls)==4 and result['state']['pending'] is None
 assert not (run/'SCREENPLAY.md').exists()
