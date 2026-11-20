from copy import deepcopy
import json
import pytest
from src.content_factory import story_first_contract_v4 as c, story_first_production_v4 as p
from src.content_factory.corpus_screenplay_v1 import freeze,digest,read

SOURCE={'chapters':[{'index':1,'text':'林岚和阿禾在厨房，周远在院外。林岚是阿禾的继母。\n林岚把钥匙递给阿禾。'}]}
FOUNDATION={'world':'家庭','characters':[{'id':n,'name':n,'source_ids':['CH1-P001']} for n in ['林岚','阿禾','周远']], 'places':[{'id':n,'name':n,'source_ids':['CH1-P001']} for n in ['厨房','院外']], 'relationships':[],'constraints':[],'visual_style':'写实','creative_additions':[]}
def story():
 return {'title':'钥匙','scenes':[{'id':'S'+str(i),'story_time':'傍晚','temporal_mode':'actual','timeline_id':'CURRENT','place_id':'厨房','seconds':10,'information':'交接' if i==1 else '承接','plot':'交接' if i==1 else '持钥匙','source_ids':['CH1-P002'],'dialogue':[]} for i in (1,2)]}
def initial():
 return [{'id':n,'kind':'location','subject':n,'item':'位置','value':'厨房','source_ids':['CH1-P001']} for n in ['林岚','阿禾']]+[{'id':'key','kind':'prop','subject':'阿禾','item':'钥匙','value':'林岚腰间','source_ids':['CH1-P002']}]
def scene(s,previous=None):
 before=deepcopy(initial() if previous is None else previous);after=deepcopy(before)
 changes=[]
 if s['id']=='S1':
  after[-1]['value']='阿禾右手'
  changes=[{'kind':'prop','subject':'阿禾','item':'钥匙','before':before[-1]['value'],'after':'阿禾右手','action_id':'A1','source_ids':['CH1-P002'],'state_id':'key'}]
 return {'creative_additions':[],'state_before':before,'state_after':after,'scenes':[{'scene_id':s['id'],'cast':['林岚','阿禾'],'positions':[{'person':n,'place_id':'厨房','mark':'桌旁'} for n in ['林岚','阿禾']],'entries':[],'actions':[{'id':'A1','people':['林岚','阿禾'],'description':'递钥匙' if changes else '持钥匙','start':0,'end':4,'source_ids':['CH1-P002']}],'changes':changes,'performance':'自然','camera':'近景','audio':[]}]}
def review(a):
 return {'candidate_sha256':digest(a),'decision':'pass','issues':[],'checks':[{'dimension':d,'verdict':'pass','reason':'fixture'} for d in ('source','space_cast','props_knowledge','audio','timing','information_pacing')]}
def prepare(tmp_path):
 run=tmp_path/'run';run.mkdir();auth={'test':True}
 plan={'implementation_pin':p.pins(),'source_sha256':digest(SOURCE),'authorization_sha256':digest(auth),'routes':{'writer':{'model':p.MODEL},'director':{'model':'deepseek-flash'}},'max_calls':32,'root_repairs':2,'context':131072,'target_seconds':60}
 for name,v in [('PLAN',plan),('SOURCE',SOURCE),('AUTHORIZATION',auth),('STATE',{'status':'prepared','pending':None,'calls_started':0,'reported_tokens':0,'plan_sha256':digest(plan)})]:freeze(run/(name+'.json'),v)
 return run
class Fake:
 def __init__(self,repair=False,reject=False,fail=None):self.calls=[];self.repair=repair;self.reject=reject;self.fail=fail
 def call(self,role,messages,schema):
  x=json.loads(messages[1]['content']);self.calls.append((role,x))
  if self.fail=='unknown':raise TimeoutError('fixture')
  fields=schema['properties']
  if 'world' in fields:v=deepcopy(FOUNDATION)
  elif 'title' in fields:v=story()
  elif 'state_before' in fields:v=scene(x['current_scene'],x['previous_state'])
  elif 'findings' in fields:v={'candidate_sha256':x['candidate_sha256'],'issue_set_sha256':x['issue_set_sha256'],'findings':[{'index':i,'verdict':'rejected' if self.reject else 'upheld','reason':'fixture'} for i in range(len(x['issues']))]}
  else:
   v=review(x['artifacts'])
   if self.repair and len(self.calls)==5:
    eid=next(r['id'] for r in c.evidence_catalog(x['artifacts']) if r['stage']=='staging' and r['path'][:2]==['scenes',1])
    v.update(decision='revise',issues=[{'severity':'hard_error','responsible_stage':'staging','evidence_ids':[eid],'source_ids':['CH1-P002'],'reason':'fixture','required_change':'repair this scene'}]);v['checks'][1]['verdict']='revise'
  response={'id':'fake','model':p.MODEL if role=='writer' else 'deepseek-flash','usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2},'choices':[{'finish_reason':'tool_calls' if role=='writer' else 'stop','message':{'tool_calls':[{'function':{'name':'submit_result','arguments':json.dumps(v)}}]} if role=='writer' else {'content':json.dumps(v)}}]}
  if self.fail=='length':response['choices'][0]['finish_reason']='length'
  return response

def test_whole_chain(tmp_path):
 run=prepare(tmp_path);f=Fake();out=p.execute(run,client=f,verify_routes=False)
 assert not out['error'] and len(f.calls)==7
 assert [x[0] for x in f.calls]==['writer']*5+['director']*2
 assert f.calls[3][1]['previous_state'][-1]['value']=='阿禾右手'
 assert (run/'SCREENPLAY.md').exists()

def test_repair_only_affected_scene(tmp_path):
 run=prepare(tmp_path);f=Fake(repair=True);out=p.execute(run,client=f,verify_routes=False)
 assert not out['error']
 assert (run/'SCENE_01_00_REUSED.json').exists()
 assert (run/'SCENE_01_01_BOUND.json').exists()
 assert not (run/'STORY_01.json').exists()
 assert len(f.calls)==10

def test_rejected_hard_issue_does_not_change_story(tmp_path):
 run=prepare(tmp_path);f=Fake(repair=True,reject=True);out=p.execute(run,client=f,verify_routes=False)
 assert out['error']['reason']=='review_rejected_requires_independent_resolution'
 assert not (run/'SCENE_01_01_BOUND.json').exists()

@pytest.mark.parametrize('failure',['unknown','length'])
def test_native_failure_no_replay(tmp_path,failure):
 run=prepare(tmp_path);f=Fake(fail=failure);out=p.execute(run,client=f,verify_routes=False)
 assert out['error'] and len(f.calls)==1
 assert (out['state']['pending'] is not None)==(failure=='unknown')
 with pytest.raises(ValueError):p.execute(run,client=f,verify_routes=False)

@pytest.mark.parametrize('failure',['silent_return','wrong_before','renamed_slot','no_location','missing_person','wrong_entry','too_long','wrong_scene','duplicated_scene'])
def test_continuity_rejects(failure):
 s=story()['scenes'][0];v=scene(s)
 if failure=='silent_return':v['state_after'][-1]['value']='口袋'
 elif failure=='wrong_before':v['scenes'][0]['changes'][0]['before']='柜锁'
 elif failure=='renamed_slot':v['state_after'][-1]['id']='other'
 elif failure=='no_location':v['state_before']=v['state_before'][1:];v['state_after']=v['state_after'][1:]
 elif failure=='missing_person':v['scenes'][0]['cast']=['阿禾']
 elif failure=='wrong_entry':v['scenes'][0]['entries']=[{'person':'阿禾','from_place':'院外','to_place':'厨房','action_id':'A1'}]
 elif failure=='too_long':v['scenes'][0]['camera']='字'*241
 elif failure=='wrong_scene':v['scenes'][0]['scene_id']='S2'
 else:v['scenes'].append(deepcopy(v['scenes'][0]))
 with pytest.raises(Exception):c.validate_scene(v,SOURCE,FOUNDATION,s)

def test_correct_carry_and_silent_jump_rejected():
 s=story()['scenes'];one=scene(s[0]);c.validate_scene(one,SOURCE,FOUNDATION,s[0]);two=scene(s[1],one['state_after'])
 c.validate_scene(two,SOURCE,FOUNDATION,s[1],one['state_after'])
 two['state_before'][-1]['value']='口袋'
 with pytest.raises(ValueError,match='discontinuity'):c.validate_scene(two,SOURCE,FOUNDATION,s[1],one['state_after'])

def test_schema_and_validator_agree_on_duration():
 v=story();v['scenes'][0]['seconds']=16
 with pytest.raises(Exception):c.validate_story(v,SOURCE,FOUNDATION)

def test_memory_cannot_mutate_current_timeline():
 v=story();v['scenes'][1]['temporal_mode']='memory'
 with pytest.raises(ValueError,match='timeline_mode'):c.validate_story(v,SOURCE,FOUNDATION)

def test_adjudication_binds_issue_set():
 a={'foundation':FOUNDATION};issues=[{'reason':'x'}]
 raw={'candidate_sha256':digest(a),'issue_set_sha256':'wrong','findings':[{'index':0,'verdict':'rejected','reason':'fixture'}]}
 with pytest.raises(Exception):c.validate_adjudication(raw,a,issues)

def test_changed_end_state_invalidates_dependent_scene(tmp_path):
 class Changed(Fake):
  def call(self,role,messages,schema):
   result=super().call(role,messages,schema)
   if role!='writer':return result
   fn=result['choices'][0]['message']['tool_calls'][0]['function'];v=json.loads(fn['arguments'])
   if len(self.calls)==5:
    a=self.calls[-1][1]['artifacts']
    v['issues'][0]['evidence_ids']=[next(r['id'] for r in c.evidence_catalog(a) if r['stage']=='staging' and r['path'][:2]==['scenes',0])]
   if len(self.calls)==7:
    v['state_after'][-1]['value']='阿禾口袋'
    v['scenes'][0]['changes'][0]['after']='阿禾口袋'
   fn['arguments']=json.dumps(v)
   return result
 run=prepare(tmp_path);f=Changed(repair=True);out=p.execute(run,client=f,verify_routes=False)
 assert not out['error']
 assert (run/'SCENE_01_00_BOUND.json').exists() and (run/'SCENE_01_01_BOUND.json').exists()
 assert not (run/'SCENE_01_01_REUSED.json').exists()
 assert f.calls[7][1]['previous_state'][-1]['value']=='阿禾口袋'


def test_absent_recipient_does_not_have_to_take_letter():
 s=story()['scenes'][0];v=scene(s)
 for k in ('state_before','state_after'):v[k][-1]['subject']='周远'
 v['scenes'][0]['changes'][0]['subject']='周远'
 c.validate_scene(v,SOURCE,FOUNDATION,s)
 assert '周远' not in v['scenes'][0]['cast']

def test_absent_person_cannot_acquire_knowledge_without_action():
 s=story()['scenes'][0];v=scene(s)
 for k in ('state_before','state_after'):v[k][-1].update(subject='周远',kind='knowledge')
 v['scenes'][0]['changes'][0].update(subject='周远',kind='knowledge')
 with pytest.raises(ValueError,match='state_change_action_not_bound'):c.validate_scene(v,SOURCE,FOUNDATION,s)

def test_record_index_preserves_exact_values():
 a={'foundation':FOUNDATION,'story':story(),'staging':{'scenes':scene(story()['scenes'][0])['scenes'],'continuity':[{'state_before':initial()}]}}
 for row in c.evidence_catalog(a):
  v=a[row['stage']]
  for k in row['path']:v=v[k]
  assert v==row['value']

def test_seed_revalidated_and_tampering_rejected(tmp_path):
 import hashlib
 donor=prepare(tmp_path);f=Fake();p.execute(donor,client=f,verify_routes=False)
 seed={'donor_run':str(donor),'donor_state_sha256':digest(read(donor/'STATE.json')),'target_seconds':60,'inherited_calls':7,
 'file_sha256':{x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in donor.iterdir() if x.is_file()},
 'foundation':FOUNDATION,'story':story(),'scenes':[scene(story()['scenes'][0])]}
 p.validate_seed(seed,SOURCE)
 seed['scenes'][0]['state_after'][-1]['value']='secret hand edit'
 with pytest.raises(ValueError,match='seed_not_native'):p.validate_seed(seed,SOURCE)
