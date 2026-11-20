"""Full model rewrite and independent whole review for natural interaction.
No video authorization, no automatic retries, and no frozen-source mutation.
"""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts.run_confirmed_legal_script_trial_v4 import render_script
from src.content_factory.creative_legal_dialogue_craft_v14 import compile_writer_script
from src.content_factory.creative_trend_bridge import validate_complete_story
from jsonschema import Draft202012Validator
ROOT=PROJECT/'data/production_revisions/legal_natural_interaction_20261010/round_01'
PARENT=PROJECT/'data/production_revisions/legal_current_production_20261010/round_10'
SOURCE=PROJECT/'data/production_revisions/legal_dialogue_refinement_20261009/round_20'
VIDEO=PROJECT/'data/video_generation/legal_current_362_20261010/opening_v1'
USER='语速有点过快了，可以说话和动作表情一起的这样也可以减少整体时长，这个剧本这么感觉不专业，和看电视上的完全不一样'
def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  anchor=control.read(PARENT/'ANCHOR.json');ledger=control.read(PARENT/'CALL_LEDGER.json')
  if ledger['calls'] or anchor['inherited']['calls_started']!=374 or anchor['inherited']['reported_tokens']!=6315744:raise ValueError('exact374 accounted parent required')
  s=control.read(SOURCE/'DELIVERABLE/FULL_SCRIPT.json');d=control.read(SOURCE/'DIRECTION.json')
  old=control.read(PARENT/'INPUT.json');receipt=control.read(VIDEO/'receipt.json')
  if receipt['task_id']!='cgt-20261010140842-lzc58' or control.sha_file(receipt['video_path'])!=receipt['video_sha256']:raise ValueError('user feedback video identity differs')
  feedback={'schema':'natural_interaction_human_feedback/v1','user_statement':USER,'source_script_ordinal':362,'source_script_sha256':control.digest(s),'source_video_task_id':receipt['task_id'],'source_video_sha256':receipt['video_sha256'],'video_human_approval':False,'source_of_actual_fast_speech_judgment':'human_feedback_only','assistant_viewed_or_listened':False,'must_fix':['normal conversational delivery, remove faster directive','source-authorized speech/actions/listener expression can overlap','natural responsive dialogue and character tactics instead of explanatory monologues'],'formal_binary_review_not_invented':True,'new_media_authorized':False}
  x={'previous_complete_script':s,'source_direction':d,'reference_fulltext':old['reference_fulltext'],'legal_context':control.read(SOURCE/'LEGAL_CONTEXT.json'),'feedback':feedback,
   'story_invariants':['仅小林与周姐、同一小会议室；小林工牌已戴好','公司先明确通知要求小林离开，小林未主动辞职','表上原因写个人原因，签的是小林自己自愿离职；不把公司决定改成主动意愿','先以公司手续催签，被质问拒绝后改以私人交差求助，再被拒','纸笔只一次送至小林近桌沿，始终未签；最后周姐从同处取回入夹、独自离开，小林留坐；争议未解','无新增第三人、场景、赔偿/违法结论、到期事实、离开日期或公司后续承诺'],
   'functional_revision_goals':['对白是对对方采取行动：催办、避答、逼问、求情、划界；每轮回应对方刚说的话而改变策略','周姐想尽快拿到签名，小林想弄清公司要求离开为何写个人原因；让目标受阻形成情绪而不依赖表情清单','开场长句拆为自然短应答，避免一口气交代四个信息；别把同一拒绝换同义词重复当升级','公司立场和私人请求两轮区别明确，结尾停劝要由第二次拒绝促成，不重复两个泛泛结束语','动作和对白可并行但在完整新原动作中明确先后条件：公司决定说清后，催看材料时可顺势递纸；纸到位后才读字，关键信息后的消化仍留空间','普通话日常交谈，不指定稍快，不写逐秒、皱眉次数或手指位置；总体尽量三分钟内，靠精简无效信息与空档而非赶台词']}
  control.write(ROOT/'INPUT.json',x,True);control.write(ROOT/'USER_FEEDBACK.json',feedback,True)
  original=PROJECT/'data/production_revisions/legal_dialogue_refinement_20261009/round_19/call_362_craft_draft_r19.json'
  control.write(ROOT/'WRITER_SCHEMA.json',control.read(original)['request']['structured_schema'],True)
  files=[PARENT/'ANCHOR.json',PARENT/'CALL_LEDGER.json',PARENT/'INPUT.json',SOURCE/'DELIVERABLE/FULL_SCRIPT.json',SOURCE/'DIRECTION.json',SOURCE/'LEGAL_CONTEXT.json',VIDEO/'PROMPT.txt',Path(receipt['video_path']),original]
  control.write(ROOT/'ANCHOR.json',{'schema':'natural_legal_complete_revision/v1','inherited':deepcopy(anchor['inherited']),'models':ledger['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in files},'automatic_retry':False,'media_authorized':False,'budget_reset':False,'old_governance_migrated':False},True)
 runtime().prepare();return summary()
def runtime():
 a=control.read(ROOT/'ANCHOR.json')
 deps=sorted((PROJECT/'src/content_factory').glob('creative_legal_dialogue_craft_v*.py'))
 own=[Path(__file__).resolve(),PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'src/content_factory/creative_trend_bridge.py',PROJECT/'scripts/run_confirmed_legal_script_trial_v4.py',ROOT/'INPUT.json',ROOT/'USER_FEEDBACK.json',ROOT/'WRITER_SCHEMA.json',ROOT/'ANCHOR.json']+deps
 return control.ContinuationRuntime(PROJECT,ROOT,own+[Path(p) for p in a['parent_files']],a['inherited'],a['models'],inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)
def summary():
 v=runtime().summary();v['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];v.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return v
def accepted(label):
 rt=runtime();l=control.read(rt.ledger);rt.check(l);rows=[q for q in l['calls'] if q['label']==label]
 if len(rows)!=1:raise ValueError('exact original response required; no automatic dispatch')
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('original response rejected or unknown')
 return r
def script():return compile_writer_script(accepted('complete_natural_draft_r1')['output'],control.read(ROOT/'INPUT.json')['source_direction'])
def evidence(s):return {f"{b['id']}.S{i+1:02}":q for b in s['beats'] for i,q in enumerate(b['steps'])}
def review_schema(s):
 ref={'type':'array','minItems':1,'maxItems':len(evidence(s)),'items':{'enum':list(evidence(s))}}
 finding={'type':'object','additionalProperties':False,'required':['problem','required_revision','evidence_refs'],'properties':{'problem':{'type':'string','minLength':1},'required_revision':{'type':'string','minLength':1},'evidence_refs':ref}}
 fields={'full_review_complete':{'const':True},'story_invariants_preserved':{'type':'boolean'},'dialogue_and_character_tactics':{'type':'string','minLength':1},'causal_and_physical_assessment':{'type':'string','minLength':1},'parallel_interaction_assessment':{'type':'string','minLength':1},'evidence_refs':ref,'issues':{'type':'array','items':finding},'suggestions':{'type':'array','items':{'type':'string'}},'assessment':{'type':'string','minLength':1}}
 return {'type':'object','additionalProperties':False,'required':list(fields),'properties':fields}
def dispatch(stage):
 prepare();x=control.read(ROOT/'INPUT.json');m=control.read(ROOT/'ANCHOR.json')['models']
 if stage=='draft':
  schema=control.read(ROOT/'WRITER_SCHEMA.json');payload=x
  rule='MiniMax编剧。根据用户新反馈完整重写同一辞职剧情，保留story_invariants而不保留旧句式。以functional_revision_goals组织自然现场应答、对方反应导致策略换招、真实目标与潜台词。专业术语用于内部判断，不能让角色说成影评或普法。原动作中明确可同时发生的说话和送纸，重要信息先听见才反应、纸到位后才读字。不要逐秒表演和手指细节。已有参考全文借表达机制，不搬参考剧情。工具submit_creative_json返回完整title/premise/beats四拍B1-B4，每拍完整event/trigger/steps；不交单句补丁，不拼旧稿，不分析。'
  label='complete_natural_draft_r1';role='writer';cap=4500
  def validator(v):
   Draft202012Validator(schema).validate(v);c=compile_writer_script(v,x['source_direction'])
   return {**validate_complete_story(c,x['source_direction']),'full_model_script':True,'script_sha256':control.digest(c),'creative_content_changed_locally':False,'creative_quality_passed':False}
 elif stage=='review':
  s=script();schema=review_schema(s);payload={k:x[k] for k in ['reference_fulltext','legal_context','feedback','story_invariants','functional_revision_goals']};payload.update(full_current_script=s,source_catalog=evidence(s))
  rule='DeepSeek全文文本审查。只通过submit_creative_json输出完整审查。完整当前新稿每拍逐句阅读，核对既定故事事实、双方目标与策略换招、自然应答、情绪刺激反应、并行动作可行性、纸笔一次递出和从同处未签取回、只周姐离开小林留坐。是否符合用户反馈必须引用当前新稿，不把旧问题自动套进新稿。真实矛盾/导致观众无法理解的缺失列issues；审美增强/实际视频未知列suggestions，不能强制再塞泛结束语或字数规则。全文复审不验证真实语速、演技或观众感受，不改源稿。'
  label='complete_natural_review_r1';role='director';cap=5500
  def validator(v):
   Draft202012Validator(schema).validate(v)
   return {'full_review_complete':v['full_review_complete'],'script_sha256':control.digest(s),'needs_revision':bool(v['issues']) or not v['story_invariants_preserved'],'creative_quality_passed':False}
 else:raise ValueError('explicit stage required')
 req={'role':role,'model':m[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.5 if stage=='draft' else .2,'thinking':'disabled'},'input_provenance':{'operator_version':'natural_legal_complete_revision/v1','reference_fulltext_sha256':control.digest(x['reference_fulltext']),'reference_fulltext_in_actual_messages':True,'feedback_sha256':control.digest(x['feedback']),'previous_complete_script_in_actual_messages':stage=='draft','source_context_sha256':control.digest(payload),'new_video_authorized':False,'server_strict_generation_claimed':False}}
 control.write(ROOT/'request_previews'/f'{stage}.json',req,True)
 r=runtime().dispatch(label,req,validator)
 if stage=='draft' and r['status']=='contract_valid':
  control.write(ROOT/'FULL_MODEL_SCRIPT.json',script(),True)
  write_readable(ROOT/'FULL_SCRIPT_DRAFT.md',render_script(script(),'完整MiniMax新稿；待全文复审和用户内容核对。旧视频不续段。'))
 control.write(ROOT/'STATUS.json',{'stage':stage,'ordinal':r['ordinal'],'status':r['status'],'spend':summary(),'new_media_calls':0,'quality_passed':False})
 return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':summary()}
def write_readable(p,s):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists() and p.read_text(encoding='utf-8')!=s:raise ValueError('immutable readable text changed')
 if not p.exists():p.write_text(s,encoding='utf-8')
def finish():
 s=script();d=accepted('complete_natural_draft_r1');r=accepted('complete_natural_review_r1')
 if r['validation']['needs_revision']:raise ValueError('whole review unresolved; cannot label candidate ready')
 out=ROOT/'REVIEWED_CANDIDATE'
 for name,val in [('FULL_SCRIPT.json',s),('RAW_MODEL_SCRIPT.json',d['output']),('FULL_TEXT_REVIEW.json',r['output']),('USER_FEEDBACK.json',control.read(ROOT/'USER_FEEDBACK.json'))]:control.write(out/name,val,True)
 write_readable(out/'FULL_SCRIPT.md',render_script(s,'MiniMax完整新稿已完成DeepSeek全文复审；待用户内容核对。并行表演与新视频未完成，创作质量未批准。'))
 control.write(out/'HANDOFF.json',{'status':'complete_reviewed_text_awaiting_human_content_confirmation','draft_ordinal':d['ordinal'],'review_ordinal':r['ordinal'],'script_sha256':control.digest(s),'raw_creative_sha256':control.digest(d['output']),'creative_text_changed_locally':False,'old_director_performance_and_video_invalidated_for_new_script':True,'new_director_and_performance_built':False,'human_quality_approved':False,'video_calls':0,'spend':summary()},True)
 return {'candidate':str(out/'FULL_SCRIPT.md'),'draft_ordinal':d['ordinal'],'review_ordinal':r['ordinal'],'spend':summary()}
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','draft','review','finish','status']);a=ap.parse_args()
 print(json.dumps(prepare() if a.stage=='prepare' else summary() if a.stage=='status' else finish() if a.stage=='finish' else dispatch(a.stage),ensure_ascii=False),flush=True)
