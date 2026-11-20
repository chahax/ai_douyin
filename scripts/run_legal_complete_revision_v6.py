"""Reusable complete current-facts script revision and full-source review; no media."""
from pathlib import Path
from copy import deepcopy
import argparse,json,re,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts import run_legal_natural_dialogue_revision_v5_20261010 as baseline
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts.run_confirmed_legal_script_trial_v4 import render_script
from src.content_factory.creative_legal_dialogue_craft_v14 import compile_writer_script
from src.content_factory.creative_trend_bridge import validate_complete_story
from src.content_factory.creative_current_brief_projection_v1 import project_current_brief,verify_writer_request
from jsonschema import Draft202012Validator
from src.content_factory.creative_legal_current_facts_gate_v3 import check_current_scene_facts

def editorial_requirements(gate):
 raw=gate['unresolved_mandatory_findings']
 if isinstance(raw,list):
  rows=raw
 elif type(raw) is int and raw>=0:
  rows=[q for q in gate.get('findings',[]) if str(q.get('classification','')).startswith('mandatory')]
  if len(rows)!=raw:raise ValueError('mandatory count does not match actual findings')
 else:raise ValueError('mandatory findings must be an evidenced list or legacy count')
 if not gate.get('text_candidate_qualified') and not rows:raise ValueError('rejected source requires actual revision findings')
 out=[]
 for q in rows:
  refs=q.get('evidence_refs') or [q.get('evidence_ref')]
  evidence=q.get('evidence') or q.get('evidence_text')
  problem=q.get('problem')
  required=q.get('required_revision')
  if not q.get('id',q.get('code')) or not refs or not all(isinstance(r,str) and r for r in refs) or not all(isinstance(v,str) and v for v in [evidence,problem,required]):raise ValueError('revision finding missing concrete evidence/problem/instruction')
  out.append({'code':q.get('id',q.get('code')),'evidence_refs':refs,'evidence_text':evidence,'problem':problem,'required_revision':required})
 return out

class Revision:
 def __init__(self,root):self.root=Path(root).resolve();self.settings=control.read(self.root/'SETUP.json')
 def prepare(self):
  if not (self.root/'ANCHOR.json').exists():
   parent=PROJECT/self.settings['parent_text_directory'];l=control.read(parent/'CALL_LEDGER.json');verify_files({str(PROJECT/p):h for p,h in l['source_manifest'].items()})
   receipts=[]
   for q in l['calls']:
    p=parent/q['receipt'];r=control.read(p)
    if control.sha_file(p)!=q['receipt_sha256'] or r['status']!='contract_valid' or type(r['response_metadata']['total_tokens']) is not int:raise ValueError('unresolved parent response; reconcile original')
    receipts.append(r)
   inherited=deepcopy(l['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(receipts),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(receipts),parent_ledger_sha256=control.sha_file(parent/'CALL_LEDGER.json'))
   source=PROJECT/self.settings['source_directory'];s=control.read(source/'REVIEWED_CANDIDATE/FULL_SCRIPT.json');old=control.read(source/'INPUT.json');brief=baseline.current_brief(s);brief['source_identity']['source_id']='current_legal_source_and_explicit_human_spoken_dialogue_feedback'
   projection=project_current_brief(brief,{'schema':'current_revision_context/v1'});d={'schema':'current_revision_direction/v1','current_brief_identity':projection['identity'],'characters':[{'name':q['name']} for q in brief['characters']]}
   media=PROJECT/self.settings['feedback_media_directory'];mr=control.read(media/'receipt.json')
   feedback={'schema':'human_spoken_dialogue_feedback/v1','user_statement':self.settings['user_statement'],'source_script_sha256':control.digest(s),'source_video_task_id':mr['task_id'],'source_video_sha256':mr['video_sha256'],'reported_issue':'两句对白仍像AI写的，不像当面交谈','voice_judgment_source':'human_feedback_only','assistant_viewed_or_listened':False,'formal_binary_media_rejection_invented':False,'new_video_authorized':False}
   x={'source_direction':d,'current_projection':projection,'reference_fulltext':old['reference_fulltext'],'feedback':feedback,'draft_to_replace_not_facts':s,'spoken_language_revision_criteria':self.settings['criteria'],'legal_expression_boundaries':old['legal_expression_boundaries']}
   for n,v in [('CURRENT_BRIEF.json',brief),('INPUT_PROJECTION.json',projection),('INPUT.json',x),('USER_FEEDBACK.json',feedback),('WRITER_SCHEMA.json',control.read(source/'WRITER_SCHEMA.json'))]:control.write(self.root/n,v,True)
   revision_files=[]
   if self.settings.get('previous_revision_directory'):
    prior=PROJECT/self.settings['previous_revision_directory'];pl=control.read(prior/'CALL_LEDGER.json');row=[q for q in pl['calls'] if q['label']=='full_review']
    if len(row)!=1:raise ValueError('one previous complete review required')
    pr=control.read(prior/row[0]['receipt']);gate=control.read(prior/'INDEPENDENT_EDITORIAL_GATE.json');failed=control.read(prior/'FULL_MODEL_SCRIPT.json')
    if pr['validation']['script_sha256']!=control.digest(failed) or gate['script_sha256']!=control.digest(failed) or gate['text_candidate_qualified']:raise ValueError('evidenced rejected complete source required')
    x['draft_to_replace_not_facts']=failed;x['previous_full_review']=pr['output'];x['independent_editorial_revision']=gate
    control.write(self.root/'INPUT.json',x)
    revision_files=[prior/'FULL_MODEL_SCRIPT.json',prior/'INDEPENDENT_EDITORIAL_GATE.json',prior/row[0]['receipt']]
   files={str(PROJECT/p):h for p,h in l['source_manifest'].items()}
   for p in [parent/'CALL_LEDGER.json',*[parent/q['receipt'] for q in l['calls']],source/'REVIEWED_CANDIDATE/FULL_SCRIPT.json',source/'INPUT.json',source/'WRITER_SCHEMA.json',*revision_files,Path(baseline.__file__).resolve(),media/'PLAN.json',media/'PROMPT.txt',Path(mr['video_path'])]:files[str(p)]=control.sha_file(p)
   control.write(self.root/'ANCHOR.json',{'inherited':inherited,'models':l['model_configs'],'parent_files':files,'automatic_retry':False,'media_authorized':False,'budget_reset':False,'old_governance_migrated':False},True)
  self.runtime().prepare();return self.summary()
 def runtime(self):
  a=control.read(self.root/'ANCHOR.json');own=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_legal_current_facts_gate_v3.py',PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'src/content_factory/creative_trend_bridge.py',PROJECT/'src/content_factory/creative_current_brief_projection_v1.py',PROJECT/'scripts/run_confirmed_legal_script_trial_v4.py',*[self.root/n for n in ['SETUP.json','INPUT.json','USER_FEEDBACK.json','CURRENT_BRIEF.json','INPUT_PROJECTION.json','WRITER_SCHEMA.json','ANCHOR.json']],*sorted((PROJECT/'src/content_factory').glob('creative_legal_dialogue_craft_v*.py'))]
  return control.ContinuationRuntime(PROJECT,self.root,own+[Path(p) for p in a['parent_files']],a['inherited'],a['models'],inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)
 def summary(self):
  s=self.runtime().summary();s['unknown_token_reservations']+=control.read(self.root/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s
 def accepted(self,label):
  rt=self.runtime();l=control.read(rt.ledger);rt.check(l);rows=[q for q in l['calls'] if q['label']==label]
  if len(rows)!=1:raise ValueError('one original result required; no automatic retry')
  r=rt.effective_receipt(rows[0])
  if r['status']!='contract_valid':raise ValueError('original result invalid or unknown')
  return r
 def script(self):return compile_writer_script(self.accepted('complete_draft')['output'],control.read(self.root/'INPUT.json')['source_direction'])
 def dispatch(self,stage):
  self.prepare();x=control.read(self.root/'INPUT.json');m=control.read(self.root/'ANCHOR.json')['models'];payload=deepcopy(x);payload['authoring']=payload.pop('current_projection')['writer_context'];payload.pop('source_direction');verify_writer_request(payload['authoring'],x['current_projection'])
  if stage=='draft':
   payload={k:deepcopy(payload[k]) for k in ['authoring','reference_fulltext','feedback','spoken_language_revision_criteria','legal_expression_boundaries']}
   payload['evidenced_revision_findings']=editorial_requirements(x['independent_editorial_revision'])
   schema=control.read(self.root/'WRITER_SCHEMA.json');role='writer';label='complete_draft';cap=4500
   rule='你是影视编剧。只依据authoring.current_brief，重新写出这个两人辞职谈话的完整四拍剧本。本轮writer只收确认事实、R01表达参考、真实用户反馈和已核实问题；历史失败稿仅留档，不在这里改句补丁。人物此刻在当面办一件具体的事：周姐要拿到小林在个人原因申请上的签名，小林不愿把公司让他走写成自己辞职。让话轮成为言语行动：催签、追问原因、拒绝、私人求助、再次拒绝；后一回应针对前一要求，别几次解释同一道理。生活化普通话，听得懂的短句，有情绪但不朗诵道理；不写公文隐喻、概念对举或每句话都要漂亮，不用抽象手续难办概括公司诉求。公司在一拍已明确决定让他走，后面不再追问决定是谁做的或用对方说不出口证明事实。二拍拒签后周姐才转个人帮忙请求，不新增截止时点、薪资、赔偿、社保、法律后果或后续承诺。动作只保留事件需要的行为与反应：纸笔一次送到小林近桌沿，不碰笔不签，最后周姐从同处收回独自走，小林坐着，门关后呼气，争议未解。R01只借刺激反应、行动有目的和余味机制，不照搬剧情。按schema提交完整title/premise/beats，四拍B1至B4和event/trigger/steps，不分析；每句dialogue独立、action不藏发言，不列逐秒肌肉动作。'
   rule+=' B1第一项先是周姐明确通知公司让小林离开的dialogue，催看材料时才一次递纸。B2面对公司催签说法有一次实质拒签，不再三次完整复述签字归属；B3周姐转个人交差请求、小林明确拒绝，B4仅用收纸笔、周姐独自离开、小林留坐呼气收束，不新加未来承诺。'
   def validator(v):
    Draft202012Validator(schema).validate(v);s=compile_writer_script(v,x['source_direction'])
    for b in s['beats']:
     for q in b['steps']:
      if q['kind']=='action' and re.search(r'(?:说|道)[“\"]',q['text']):raise ValueError('dialogue hidden in action')
    return {**validate_complete_story(s,x['source_direction']),'script_sha256':control.digest(s),'full_model_script':True,'creative_text_changed_locally':False,'local_current_fact_findings':check_current_scene_facts(s),'creative_quality_passed':False}
  elif stage=='review':
   s=self.script();schema=baseline.review_schema(s);schema['properties']['human_spoken_language_feedback_addressed']={'type':'boolean'};schema['required'].append('human_spoken_language_feedback_addressed');payload.update(full_current_script=s,source_catalog=baseline.evidence(s));role='director';label='full_review';cap=5500
   rule='DeepSeek同源全文审查，完整读取新稿每拍每句、当前事实和R01，重点检查真实用户对白反馈，不只核对来源、状态与时序。spoken_language_revision_criteria作为本轮采用要求：关键冲突中的谁让谁做什么和拒绝什么能直接听懂；公司催签诉求和公司口径可辨；对方上一句话使下一句产生新的具体回应，避免概念对概念、纸落字落/事情变事情等主题警句连排。口语是否自然属于文本候选判断，最终观感仍待用户，不能声称已获得观众或视频质量通过。若仍保留被用户指出的核心表达方式，需明确列当前新稿证据为issues，不以结构通过代替反馈解决；同义重复只在实际回应新压力时成立。不要强制每句更口语或新增金句，不把合理角色公务语气一律当错误。完整核对公司要求离开、已写个人原因、先公司催签再私人求助、两次拒签及结尾因果；纸笔一次递出同处取回、只周姐走小林留坐；不得新增未经确认劳动争议事实、法律后果或公司承诺。不手改正文，完整提交复审。实际表演语言口型未知只能放suggestions。'
   rule+=' 核对independent_editorial_revision所列当前具体问题是否修复，上一复审给的台词例句不代表当前事实，尤其B1已明确公司决定之后不再要求追问谁要走。不要把日常说法或正常人事公务口吻逐词判错；以本次具体上下文、应答和因果举证，审美建议不扩大成硬禁词。'
   def validator(v):
    Draft202012Validator(schema).validate(v);return {'full_review_complete':True,'script_sha256':control.digest(s),'needs_revision':bool(v['issues']) or not v['story_invariants_preserved'] or not v['human_spoken_language_feedback_addressed'],'creative_quality_passed':False}
  else:raise ValueError('explicit draft/review required')
  req={'role':role,'model':m[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},'input_provenance':{'operator_version':'complete_legal_spoken_revision/v6_evidenced_findings_projection','full_current_facts_in_actual_messages':True,'previous_complete_script_in_actual_messages':stage=='review','rejected_full_dialogue_excluded_from_writer':stage=='draft','new_full_script_in_actual_messages':stage=='review','reference_fulltext_in_actual_messages':True,'reference_fulltext_sha256':control.digest(x['reference_fulltext']),'human_feedback_in_actual_messages':True,'spoken_language_criteria_in_actual_messages':True,'current_brief_projection_checked':True,'creative_text_changed_locally':False,'evidenced_findings_are_objects':True,'new_media_authorized':False}}
  control.write(self.root/'request_previews'/f'{stage}.json',req,True);r=self.runtime().dispatch(label,req,validator)
  if stage=='draft' and r['status']=='contract_valid':
   control.write(self.root/'FULL_MODEL_SCRIPT.json',self.script(),True);baseline.write_readable(self.root/'FULL_SCRIPT_DRAFT.md',render_script(self.script(),'完整MiniMax返修新稿；待全文复审及用户核对，新视频0。'))
  return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':self.summary()}
 def finish(self):
  s=self.script();d=self.accepted('complete_draft');r=self.accepted('full_review');gate=control.read(self.root/'INDEPENDENT_EDITORIAL_GATE.json')
  if d['validation']['local_current_fact_findings'] or r['validation']['needs_revision'] or gate['script_sha256']!=control.digest(s) or not gate['text_candidate_qualified'] or gate['unresolved_mandatory_findings']:raise ValueError('full current review unresolved')
  out=self.root/'REVIEWED_CANDIDATE'
  for n,v in [('FULL_SCRIPT.json',s),('RAW_MODEL_SCRIPT.json',d['output']),('FULL_TEXT_REVIEW.json',r['output']),('USER_FEEDBACK.json',control.read(self.root/'USER_FEEDBACK.json')),('CURRENT_BRIEF.json',control.read(self.root/'CURRENT_BRIEF.json')),('INDEPENDENT_EDITORIAL_GATE.json',gate)]:control.write(out/n,v,True)
  baseline.write_readable(out/'FULL_SCRIPT.md',render_script(s,'MiniMax完整新稿已完成DeepSeek全文复审；待用户核对，新导演/表演待重建、新视频0。'))
  control.write(out/'HANDOFF.json',{'status':'complete_reviewed_text_awaiting_human_content_confirmation','draft_ordinal':d['ordinal'],'review_ordinal':r['ordinal'],'script_sha256':control.digest(s),'raw_creative_sha256':control.digest(d['output']),'creative_text_changed_locally':False,'old_director_performance_and_video_invalidated_for_new_script':True,'new_director_and_performance_built':False,'human_quality_approved':False,'video_calls':0,'spend':self.summary()},True)
  return {'candidate':str(out/'FULL_SCRIPT.md'),'draft_ordinal':d['ordinal'],'review_ordinal':r['ordinal'],'spend':self.summary()}
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('run_dir');ap.add_argument('stage',choices=['prepare','draft','review','finish','status']);a=ap.parse_args();op=Revision(a.run_dir)
 print(json.dumps(op.prepare() if a.stage=='prepare' else op.summary() if a.stage=='status' else op.finish() if a.stage=='finish' else op.dispatch(a.stage),ensure_ascii=False),flush=True)
