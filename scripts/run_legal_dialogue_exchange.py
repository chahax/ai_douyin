"""Reusable current pure-dialogue operator; one generation per human-approved tail."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts import run_legal_film_refusal_sample_v5_20261010 as media_base
from src.content_factory import creative_film_dialogue_exchange_v1 as contract
from src.content_factory.media_review_policy import validate_approved_tail
from src.content_factory.creative_legal_short_seedance_execution_v1 import sha
from jsonschema import Draft202012Validator
MODEL='doubao-seedance-2-0-mini-260615'
LOGICAL='legal_trend_text_trial_20261008_adopted_r8'

def write_text(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists():
  if path.read_text(encoding='utf-8')!=value:raise ValueError('immutable text changed')
 else:
  with path.open('x',encoding='utf-8',newline='\n') as f:f.write(value)

class Exchange:
 def __init__(self,root):
  self.root=Path(root).resolve();self.settings=control.read(self.root/'SETUP.json');self.out=PROJECT/self.settings['media_directory'];self.previous=PROJECT/self.settings['predecessor_directory'];self.refs=self.settings['contract_spec']['source_refs']
 def prepare(self):
  if not (self.root/'ANCHOR.json').exists():
   parent=PROJECT/self.settings['parent_text_directory'];l=control.read(parent/'CALL_LEDGER.json');verify_files({str(PROJECT/p):h for p,h in l['source_manifest'].items()})
   receipts=[]
   for q in l['calls']:
    p=parent/q['receipt'];r=control.read(p)
    if sha(p)!=q['receipt_sha256'] or r['status']!='contract_valid' or type(r['response_metadata']['total_tokens']) is not int:raise ValueError('unresolved parent receipt, reconcile original')
    receipts.append(r)
   inherited=deepcopy(l['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(receipts),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(receipts),parent_ledger_sha256=sha(parent/'CALL_LEDGER.json'))
   sx=control.read(PROJECT/self.settings['parent_input_path']);s=sx['background_full_script'];spec=self.settings['contract_spec'];contract.validate_spec(s,spec)
   prior=control.read(self.previous/'receipt.json');asset={'path':prior['last_frame'],'sha256':prior['last_frame_sha256'],'role':'first_frame','source':prior['last_frame_source'],'source_task_id':prior['task_id'],'source_video_sha256':prior['video_sha256'],'human_approval_required_at_media_dispatch':True,'state_basis':'prior compiled state; actual acceptance requires separate human decision'}
   if asset['source']!='generation_service_original' or sha(asset['path'])!=asset['sha256'] or prior['logical_task_id']!=LOGICAL or prior['plan_snapshot']['script_content_sha256']!=contract.digest(s):raise ValueError('predecessor source changed')
   scope={'user_statement':self.settings['user_request'],'script_sha256':contract.digest(s),'previous_task_id':prior['task_id'],'previous_video_sha256':prior['video_sha256'],'max_new_submissions':1,'later_segments_authorized':False,'automatic_retry':False,'human_previous_approval_required':True,'publish_authorized':False}
   x={'background_full_script':s,'contract_spec':spec,'current_interaction':{'source_refs':self.refs,'source_catalog':contract.current_catalog(s,spec)},'current_initial_state':spec['initial_state'],'film_method_current_brief':spec['brief'],'reference_fulltext':sx['reference_fulltext'],'selected_asset_feedback':asset,'scope':scope,'previous_current_coverage':spec['prior_source_refs'],'human_face_feedback':self.settings.get('human_face_feedback','')}
   control.write(self.root/'INPUT.json',x,True);control.write(self.root/'PREDECESSOR_CANDIDATE_SNAPSHOT.json',prior,True);control.write(self.root/'WRITER_SCHEMA.json',contract.schema(s,spec),True)
   paths={str(PROJECT/p):h for p,h in l['source_manifest'].items()}
   for p in [parent/'CALL_LEDGER.json',*[parent/q['receipt'] for q in l['calls']],PROJECT/self.settings['parent_input_path'],PROJECT/'docs/FILM_SKILL_ADAPTATION_20261010.md',Path(prior['video_path']),Path(prior['last_frame'])]:paths[str(p)]=sha(p)
   control.write(self.root/'ANCHOR.json',{'inherited':inherited,'models':l['model_configs'],'parent_files':paths,'automatic_retry':False,'budget_reset':False,'predecessor_mutable_receipt_not_hashed':True},True)
  self.runtime().prepare();return self.summary()
 def runtime(self):
  a=control.read(self.root/'ANCHOR.json');paths=[Path(__file__).resolve(),Path(media_base.__file__).resolve(),PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'src/content_factory/creative_film_dialogue_exchange_v1.py',PROJECT/'src/content_factory/media_review_policy.py',*[self.root/n for n in ['SETUP.json','ANCHOR.json','INPUT.json','WRITER_SCHEMA.json','PREDECESSOR_CANDIDATE_SNAPSHOT.json']]]+[Path(p) for p in a['parent_files']]
  return control.ContinuationRuntime(PROJECT,self.root,paths,a['inherited'],a['models'],inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)
 def summary(self):
  s=self.runtime().summary();s['unknown_token_reservations']+=control.read(self.root/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s
 def accepted(self,label):
  rt=self.runtime();l=control.read(rt.ledger);rt.check(l);rows=[q for q in l['calls'] if q['label']==label]
  if len(rows)!=1:raise ValueError('one original response required; no retry')
  r=rt.effective_receipt(rows[0])
  if r['status']!='contract_valid':raise ValueError('response invalid or unknown')
  return r
 def compiled(self):
  x=control.read(self.root/'INPUT.json');return contract.compile_contract(self.accepted('current_performance')['output'],x['background_full_script'],x['contract_spec'])
 def candidate(self):return contract.pack_first(self.compiled())
 def prompt(self):
  x=control.read(self.root/'INPUT.json');return contract.render_prompt(self.candidate(),x['background_full_script'],x['contract_spec'])
 def review_schema(self):
  text={'type':'string','minLength':1};refs={'type':'array','minItems':1,'items':{'enum':self.refs}};issue={'type':'object','additionalProperties':False,'required':['problem','required_revision','evidence_refs'],'properties':{'problem':text,'required_revision':text,'evidence_refs':refs}}
  props={'full_source_read':{'const':True},'current_interaction_valid':{'type':'boolean'},'exact_dialogue_and_scope_preserved':{'type':'boolean'},'natural_exchange_assessment':text,'causal_physical_assessment':text,'evidence_refs':refs,'issues':{'type':'array','items':issue},'suggestions':{'type':'array','items':text},'assessment':text}
  return {'type':'object','additionalProperties':False,'required':list(props),'properties':props}
 def dispatch(self,stage):
  self.prepare();x=control.read(self.root/'INPUT.json');s=x['background_full_script'];spec=x['contract_spec'];models=control.read(self.root/'ANCHOR.json')['models']
  if stage=='performance':
   role='writer';label='current_performance';cap=2400;schema=control.read(self.root/'WRITER_SCHEMA.json');payload={k:deepcopy(x[k]) for k in ['current_interaction','current_initial_state','film_method_current_brief','reference_fulltext','selected_asset_feedback','human_face_feedback']}
   rule='MiniMax表演导演，提交完整六字段演法，不分析、不补丁。只处理当前source_refs，原句由编译器各插一次，不在演法引用或改写原对白、不新增对白。按当前brief写人物对对手的行动目的、听到对方后的理解变化与自然回应，不设计按字或固定肌肉顺序的嘴眼肩线微动作任务。少量自然视线、表情、姿态变化允许发生，不冻结演员，不逐字计音量。保持同空间道具起态，不重复前段，不预演后续。说话是自然普通话和正常谈话速度；camera服务当前关系变化，不为轮换说话者强制切镜；delivery只写表演方向，不写实现词。post_pause_seconds为当前最后答复后必要接收时间0至1.5秒。human_face_feedback是真实前段观感，具体成因尚未查明，不写成已经修复或模型原因已证实。R01只借鉴表达机制。'
   def validator(v):
    Draft202012Validator(schema).validate(v);c=contract.compile_contract(v,s,spec);first=contract.pack_first(c)
    if not first['dispatch_ready']:raise ValueError('complete exchange exceeds native limit; no speed fitting')
    contract.render_prompt(first,s,spec);return {'source_sha256':contract.digest(s),'compiled_sha256':contract.digest(c),'complete_current_interaction':True,'quality_passed':False}
  elif stage=='review':
   role='director';label='full_source_review';cap=4200;schema=self.review_schema();c=self.compiled();payload=deepcopy(x);payload.update(full_model_current_performance=self.accepted('current_performance')['output'],compiled_current_interaction=c,actual_first_sample=self.candidate(),actual_first_prompt=self.prompt())
   rule='DeepSeek同源全文复审，完整读取正文、R01、当前原始完整演法、编译与实际提示词。只审核当前source_refs回合，前段已发生的不复演，后段不预演。核对两原句各一次和顺序、当前因果与对手反应、正常语速及最后答复后接收、同空间不移动纸笔、不新增对白或操作。必修须依据当前实际指令与源/合同矛盾；明确逐字密集肌肉顺序、身体固定不动、时序冲突可列issues，注视对手和少量自然随动不是当然冻结；已有接收时间不能称缺窗口。潜在僵硬、五官变化、语言与口型等未实测风险放suggestions，不声称视频自然度通过。完整提交复审，不改演法或写补丁。'
   def validator(v):
    Draft202012Validator(schema).validate(v);return {'source_sha256':contract.digest(s),'compiled_sha256':contract.digest(c),'full_source_read':True,'needs_revision':bool(v['issues']) or not v['current_interaction_valid'] or not v['exact_dialogue_and_scope_preserved'],'actual_media_quality_passed':False}
  else:raise ValueError('explicit text stage required')
  req={'role':role,'model':models[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},'input_provenance':{'operator_version':'reusable_legal_dialogue_exchange/v1','source_script_sha256':contract.digest(s),'full_script_in_actual_messages':stage=='review','current_actor_request_excludes_future_story':stage=='performance','reference_fulltext_in_actual_messages':True,'reference_fulltext_sha256':contract.digest(x['reference_fulltext']),'current_interaction_refs':self.refs,'film_current_method_brief_sha256':contract.digest(spec['brief']),'old_global_acting_prose_in_actual_messages':False,'human_media_quality_claimed':False}}
  control.write(self.root/'request_previews'/f'{stage}.json',req,True);r=self.runtime().dispatch(label,req,validator)
  if stage=='performance' and r['status']=='contract_valid':
   for n,v in [('FULL_MODEL_CURRENT_PERFORMANCE.json',r['output']),('CURRENT_INTERACTION_COMPILED.json',self.compiled()),('FIRST_SAMPLE.json',self.candidate())]:control.write(self.root/n,v,True)
   write_text(self.root/'ACTUAL_PROMPT.txt',self.prompt()+'\n')
  return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':self.summary()}
 def finish(self):
  x=control.read(self.root/'INPUT.json');d=self.accepted('current_performance');r=self.accepted('full_source_review');c=self.compiled();first=self.candidate()
  if r['validation']['needs_revision'] or not first['dispatch_ready']:raise ValueError('text unresolved; no media dispatch')
  gate=control.read(self.root/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json')
  if not gate['text_sample_qualified'] or gate['unresolved_mandatory_findings'] or gate['source_sha256']!=contract.digest(x['background_full_script']) or gate['compiled_sha256']!=contract.digest(c):raise ValueError('independent current gate unresolved')
  folder=self.root/'DELIVERABLE'
  for n,v in [('FULL_SCRIPT.json',x['background_full_script']),('FULL_MODEL_CURRENT_PERFORMANCE.json',d['output']),('CONTRACT_SPEC.json',x['contract_spec']),('CURRENT_INTERACTION_COMPILED.json',c),('FIRST_SAMPLE.json',first),('FULL_SOURCE_REVIEW.json',r['output']),('INDEPENDENT_PERFORMANCE_GATE.json',gate),('ASSET_FEEDBACK.json',x['selected_asset_feedback']),('USER_SCOPE.json',x['scope'])]:control.write(folder/n,v,True)
  control.write(folder/'HANDOFF.json',{'source_sha256':contract.digest(x['background_full_script']),'compiled_sha256':contract.digest(c),'source_refs':self.refs,'complete_current_interaction':True,'full_film_complete':False,'human_media_quality_approved':False,'performance_ordinal':d['ordinal'],'review_ordinal':r['ordinal'],'spend':self.summary()},True)
  write_text(folder/'ACTUAL_PROMPT.txt',self.prompt()+'\n');body=['# 当前完整对白回合','',*[(q['speaker']+'：'+q['original_text']) for q in c['schedule']],'','## 完整模型演法','',*[(k+'：'+str(v)) for k,v in d['output'].items()],'','文本资格不表示实际视频通过；前段人审批准仍是媒体派发前置。']
  write_text(folder/'CURRENT_EXCHANGE_READABLE.md','\n\n'.join(body)+'\n');return {'handoff':str(folder),'duration_seconds':first['duration_seconds'],'spend':self.summary()}
 def media_plan(self,client):
  self.runtime().check(control.read(self.runtime().ledger));x=control.read(self.root/'INPUT.json');folder=self.root/'DELIVERABLE';review=self.accepted('full_source_review');handoff=control.read(folder/'HANDOFF.json');c=self.compiled();first=self.candidate();scope=x['scope'];asset=x['selected_asset_feedback'];snapshot=control.read(self.root/'PREDECESSOR_CANDIDATE_SNAPSHOT.json')
  if review['validation']['needs_revision'] or handoff['compiled_sha256']!=contract.digest(c) or handoff['source_refs']!=self.refs or not first['dispatch_ready'] or scope['max_new_submissions']!=1 or scope['later_segments_authorized']:raise ValueError('current text/scope changed')
  expected={'FULL_SCRIPT.json':x['background_full_script'],'FULL_MODEL_CURRENT_PERFORMANCE.json':self.accepted('current_performance')['output'],'CONTRACT_SPEC.json':x['contract_spec'],'CURRENT_INTERACTION_COMPILED.json':c,'FIRST_SAMPLE.json':first,'FULL_SOURCE_REVIEW.json':review['output'],'INDEPENDENT_PERFORMANCE_GATE.json':control.read(self.root/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json'),'ASSET_FEEDBACK.json':asset,'USER_SCOPE.json':scope}
  for n,v in expected.items():
   if control.read(folder/n)!=v:raise ValueError('handoff changed: '+n)
  hp=self.previous/'receipt.human_review.json';tail=validate_approved_tail(hp,expected_tail_path=Path(asset['path']));prior=control.read(self.previous/'receipt.json')
  if prior['content_status']!='approved' or tail['sha256']!=asset['sha256']:raise ValueError('predecessor not approved')
  for q in [prior,snapshot]:
   if q['task_id']!=scope['previous_task_id'] or q['video_sha256']!=scope['previous_video_sha256'] or q['last_frame_sha256']!=asset['sha256'] or q['last_frame_source']!='generation_service_original' or q['logical_task_id']!=LOGICAL or q['plan_snapshot']['script_content_sha256']!=scope['script_sha256']:raise ValueError('predecessor source changed')
  sources={n:{'path':str(folder/n),'sha256':sha(folder/n)} for n in [*expected,'HANDOFF.json']}
  for p in [Path(__file__).resolve(),Path(media_base.__file__).resolve(),PROJECT/'src/content_factory/seedance_client.py',PROJECT/'src/content_factory/creative_legal_short_seedance_execution_v1.py',PROJECT/'src/content_factory/media_review_policy.py',hp,self.root/'PREDECESSOR_CANDIDATE_SNAPSHOT.json',self.previous/'PLAN.json',Path(prior['video_path']),Path(asset['path']),self.root/'CALL_LEDGER.json',self.root/'SETUP.json']:
   sources[str(p.relative_to(PROJECT))]={'path':str(p),'sha256':sha(p)}
  return {'schema':'reusable_legal_dialogue_segment/v1','logical_task_id':LOGICAL,'segment_id':self.settings['segment_id'],'shot_id':self.settings['contract_spec']['interaction_id'],'script_content_sha256':scope['script_sha256'],'sources':sources,'authorization':scope,'predecessor_user_statement':control.read(hp)['user_statement'],'predecessor_task_id':prior['task_id'],'provider':'ark_api','model':MODEL,'resolution':'480p','ratio':'9:16','duration_seconds':first['duration_seconds'],'generate_audio':True,'return_last_frame':True,'image_role':'first_frame','first_frame':tail,'opening_frame_source':'preceding_human_approved_service_original_tail','prompt':self.prompt(),'source_refs':self.refs,'fit_scaled':False,'budget_reset':False,'later_segments_authorized':False,'text_qualified_not_current_video_approved':True}
 def media(self,operation):
  media_base.OUT=self.out;media_base.ROOT=self.root;media_base.PREVIOUS_MEDIA=self.previous;media_base.SID=self.settings['segment_id'];media_base.media_plan=self.media_plan;media_base.write_text_new=write_text
  return media_base.media(operation)

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('run_dir');ap.add_argument('stage',choices=['prepare','performance','review','finish','status','media_prepare','media_submit','media_query']);a=ap.parse_args();op=Exchange(a.run_dir)
 result=op.media(a.stage) if a.stage.startswith('media_') else op.prepare() if a.stage=='prepare' else op.summary() if a.stage=='status' else op.finish() if a.stage=='finish' else op.dispatch(a.stage)
 print(json.dumps(result,ensure_ascii=False),flush=True)
