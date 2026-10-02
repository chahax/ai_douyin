import sys,json,hashlib,re
from copy import deepcopy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.creative_workflow_roles import CreativeRoleClients
from src.content_factory.creative_original_director import PROMPT
from src.content_factory.creative_segmented_director import AUTHORITATIVE_RULES,project_previous_execution,validate_execution_contract,compile_execution_storyboard
from src.content_factory.creative_dialogue_normalization import normalize_dialogue_lock_timing
from src.content_factory.creative_workflow_contract import validate_shots
from src.content_factory.creative_review_v4 import build_review_prompt,validate_review_v4
from src.content_factory.creative_review_v3 import canonicalize_unique_leaf_refs
PARENT=Path('data/creative_workflows/say_no_reviewed_segments_20260927')
ROOT=Path('data/production_trials/say_no_v4_paid_three_20260927')
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
ROOT.mkdir(parents=True,exist_ok=True)
ledger_path=ROOT/'CALL_LEDGER.json'
if not ledger_path.exists():
 write(ledger_path,dict(schema='authorized_production_continuation/v1',authorization='用户明确授权修复后付费3轮生产调用；本执行限定最多3个文本API请求，无自动重试',parent_run=str(PARENT.resolve()),same_story=True,parent_calls=30,parent_content_revisions=6,parent_contract_repairs=4,max_new_calls=3,calls_started=0,media_calls=0,requests=[]))
mode=sys.argv[1]
old=read(PARENT/'director_shots__beat_04_00.json');payload=json.loads(old['request']['messages'][1]['content'])
payload['previous_shot']=project_previous_execution(read(PARENT/'director_shots__beat_03_02.json')['output']['shots'][-1])
payload['segment_instructions']=AUTHORITATIVE_RULES
payload['issues']=read(PARENT/'writer_check__segment_scope_v2_beat_04_00__assistant_decision.json')['additional_issues']
payload['previous_draft']=old['output']
payload['upcoming_beats']=[]
payload['next_shot_number']=4
if mode in ('generate','repair'):
 role='writer';prompt=PROMPT+'\n'+AUTHORITATIVE_RULES
 if mode=='repair':
  payload['previous_draft']=read(ROOT/'generate.parsed.json')
  payload['issues']=read(ROOT/'REPAIR_ISSUES.json')
elif mode=='review':
 role='director';payload={'creative_brief':payload['creative_brief'],'script':payload['script'],'shots':read(ROOT/('repair.effective.json' if (ROOT/'repair.effective.json').exists() else 'generate.effective.json')),'previous_shot':payload['previous_shot'],'whole_story_outline':payload['whole_story_outline'],'upcoming_beats':[],'review_scope':'storyboard_segment'};prompt=build_review_prompt(payload)
else:raise ValueError('unsupported mode')
record_path=ROOT/(mode+'.request.json')
if record_path.exists():raise RuntimeError('阶段已请求，拒绝隐式再次计费；读取原回执')
ledger=read(ledger_path)
if ledger['calls_started']>=ledger['max_new_calls']:raise RuntimeError('用户授权的三次请求已满')
messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
record=dict(mode=mode,status='request_reserved',request={'messages':messages,'max_tokens':16000,'temperature':0.2 if role=='director' else 0.4,'thinking':'disabled'},request_sha256=digest(messages),provider_role=role)
write(record_path,record)
ledger['calls_started']+=1;ledger['requests'].append(dict(number=ledger['calls_started'],mode=mode,request_sha256=digest(messages)));write(ledger_path,ledger)
try:
 result=CreativeRoleClients().call(role,messages,max_tokens=16000,temperature=0.2 if role=='director' else 0.4,thinking='disabled')
 record.update(status='response_received',response_text=result.text,response_metadata=result.metadata);write(record_path,record)
 raw=result.text.strip();raw=re.sub(r'^```(?:json)?\s*','',raw);raw=re.sub(r'\s*```$','',raw);v=json.loads(raw)
 if mode in ('generate','repair'):
  v,changes=normalize_dialogue_lock_timing(v,payload['script']);validate_shots(v,payload['director_brief'],payload['script']);validate_execution_contract(v)
  if v['style']!=payload['style_lock']:raise ValueError('style_lock changed')
  first=v['shots'][0]
  if first['continuity_mode']=='raw_tail_continuation' and first['start_state']!=payload['previous_shot']['end_state']:raise ValueError('raw tail requires exact previous end state; changed camera requires adapter')
  if [x['id'] for x in v['shots']]!=[f'SH{i:02}' for i in range(4,4+len(v['shots']))]:raise ValueError('shot ids not consecutive')
  if any(not 4<=x['duration_seconds']<=15 for x in v['shots']):raise ValueError('executor duration range')
  effective=compile_execution_storyboard(v);validate_shots(effective,payload['director_brief'],payload['script']);write(ROOT/(mode+'.effective.json'),effective)
 else:
  v,changes=canonicalize_unique_leaf_refs(v,payload);validate_review_v4(v,payload)
 record.update(status='contract_validated_content_pending',output=v,normalization_changes=changes);write(record_path,record)
 print(json.dumps(dict(status=record['status'],calls=ledger['calls_started'],mode=mode,total_tokens=result.metadata.get('total_tokens'),issues=v.get('issues')),ensure_ascii=False))
except Exception as exc:
 record.update(status='needs_attention',error=str(exc));write(record_path,record);print(json.dumps(dict(status='needs_attention',calls=ledger['calls_started'],mode=mode,error=str(exc)),ensure_ascii=False));raise SystemExit(2)
