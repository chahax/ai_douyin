"""Complete MiniMax rewrites and small evidence-bound DeepSeek reviews; immutable rounds."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_legal_dialogue_refinement_v5_20261009 as second
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v4 import FIXED_INPUTS,render_script
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_legal_dialogue_craft_v6 import build_wire,validate_script,expand_review,STANDARDS,CONTRACT
from src.content_factory.creative_trend_bridge import validate_complete_story
BASE=PROJECT/'data/production_revisions/legal_dialogue_refinement_20261009'
def root(n):
 if type(n)is not int or n<1 or n>20:raise ValueError('round1..20 only; no automatic retry loop')
 return BASE/f'round_{n:02}'
def prepare(n):
 dst=root(n)
 if n<6:raise ValueError('v6 only new explicit rounds starting6; old rounds immutable')
 if not (dst/'ANCHOR.json').exists():
  rt=second.runtime(5) if n==6 else runtime(n-1)
  l=control.read(rt.ledger);rt.check(l);rs=[rt.effective_receipt(c) for c in l['calls']]
  if not rs:raise ValueError('parent actual receipts missing')
  for r in rs:
   if r['status'] not in ('contract_valid','contract_rejected','interface_rejected') or type(r.get('response_metadata',{}).get('total_tokens')) is not int:raise ValueError('unknown parent outcome/usage; preserve and reconcile')
   if r['status']=='interface_rejected' and r.get('failure',{}).get('response_received') is not True:raise ValueError('unknown parent failure')
  draft=[r for r in rs if r['request']['role']=='writer' and (r['status']=='contract_valid' or (n==6 and r['ordinal']==347 and r['status']=='contract_rejected' and isinstance(r.get('output'),dict)))];
  if n==6:
   if len(draft)!=1:raise ValueError('exact known full rejected source required')
   validate_complete_story(draft[0]['output'],control.read(rt.root/'DIRECTION.json'))
  if len(draft)!=1:raise ValueError('exact complete valid parent writer required')
  if n==6 and [r['ordinal'] for r in rs]!=[347]:raise ValueError('exact347 known receipt required; no unknown/replay')
  parent=rt.root
  for name in FIXED_INPUTS:control.write(dst/name,control.read(parent/name),True)
  feedback={
   'schema':'legal_dialogue_refinement_human_scope/v1','source':'explicit_current_user_request',
   'user_statement':'你调试着，可以用专业的语言或语文专业术语尝试管控下。你可以尝试持续优化',
   'prior_user_statements':[control.read(PROJECT/p)['user_statement'] for p in [
    'data/video_generation/legal_short_remake_20261009/batch_v1/human_feedback_conflict_20261009/USER_FEEDBACK.json',
    'data/video_generation/legal_trend_20261008/remaining_batch_v1/human_feedback_20261009/PLAIN_LANGUAGE_AND_ENDING_FEEDBACK.json']],
   'professional_terms_are_functional_criteria_not_required_dialogue':True,'human_source_adoption':False,'media_authorized':False,'automatic_retry':False}
  control.write(dst/'HUMAN_REVISION_REQUEST.json',feedback,True)
  control.write(dst/'PREVIOUS_COMPLETE_SCRIPT.json',draft[0]['output'],True)
  reviews=[r for r in rs if r['request']['role']=='director']
  previous=control.read(parent/'REVIEW.json') if reviews and reviews[-1]['status']=='contract_valid' else {'valid_full_review':False,'received_failures':[{'ordinal':r['ordinal'],'status':r['status'],'failure':r.get('failure'),'validation_error':r.get('validation_error')} for r in reviews]}
  control.write(dst/'PREVIOUS_COMPLETE_REVIEW.json',previous,True)
  control.write(dst/'DIALOGUE_CRAFT_STANDARDS.json',{'standards':STANDARDS,'contract':CONTRACT},True)
  inherited=deepcopy(l['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(rs),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in rs),calls_with_known_usage=inherited['calls_with_known_usage']+len(rs),parent_ledger_sha256=control.sha_file(rt.ledger))
  files=list(dict.fromkeys(rt.sources+[rt.ledger]+[rt.root/c['receipt'] for c in l['calls']]))
  control.write(dst/'ANCHOR.json',{'schema':'legal_dialogue_refinement/v1','round':n,'inherited':inherited,'models':l['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in files},'media_authorized':False,'automatic_retry':False,'budget_reset':False,'old_governance_migrated':False,'parent_source_347_contract_rejected_not_adopted':n==6},True)
 runtime(n).prepare()
 return summary(n)
def runtime(n):
 dst=root(n);a=control.read(dst/'ANCHOR.json')
 own=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_legal_dialogue_craft_v6.py']+[dst/f for f in FIXED_INPUTS+('ANCHOR.json','HUMAN_REVISION_REQUEST.json','PREVIOUS_COMPLETE_SCRIPT.json','PREVIOUS_COMPLETE_REVIEW.json','DIALOGUE_CRAFT_STANDARDS.json')]
 return control.ContinuationRuntime(PROJECT,dst,list(dict.fromkeys(own+[Path(p) for p in a['parent_files']])),a['inherited'],a['models'],inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)
def summary(n):
 s=runtime(n).summary();s['unknown_token_reservations']+=control.read(root(n)/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s
def accepted(n,label):
 rt=runtime(n);l=control.read(rt.ledger);rt.check(l);cs=[c for c in l['calls'] if c['label']==label]
 if len(cs)!=1:raise ValueError('exact existing receipt required')
 r=rt.effective_receipt(cs[0])
 if r['status']!='contract_valid':raise ValueError('source rejected/unknown; no repeat dispatch')
 return r
def wire(n,stage,script=None):
 dst=root(n);p,f,g,s,d,c=[control.read(dst/x) for x in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
 return build_wire(p,f,g,s,stage,now=control.now(),direction=d,confirmation=c,feedback=control.read(dst/'HUMAN_REVISION_REQUEST.json'),previous_script=control.read(dst/'PREVIOUS_COMPLETE_SCRIPT.json'),previous_review=control.read(dst/'PREVIOUS_COMPLETE_REVIEW.json'),script=script)
def dispatch(n,stage):
 prepare(n);rt=runtime(n);dst=root(n);label=f'craft_{stage}_r{n:02}';l=control.read(rt.ledger)
 if any(c['label']==label for c in l['calls']):raise ValueError('stage already dispatched; inspect original receipt, do not regenerate timestamp and replay')
 script=accepted(n,f'craft_draft_r{n:02}')['output'] if stage=='review' else None
 req=wire(n,stage,script);control.write(dst/f'request_previews/{stage}.json',req,True)
 ctx=json.loads(req['messages'][-1]['content']);d=control.read(dst/'DIRECTION.json')
 def validate(v):return {**validate_complete_story(v,d),**validate_script(v)} if stage=='draft' else expand_review(v,script,ctx['emotional_brief'])[2]
 r=rt.dispatch(label,req,validate)
 if r['status']=='contract_valid':
  v=r['output']
  if stage=='review':v,e,_=expand_review(v,script,ctx['emotional_brief']);control.write(dst/'FULL_REVIEW_EVIDENCE.json',e,True)
  control.write(dst/f'{stage.upper()}.json',v,True)
  if stage=='draft':write_new(dst/'FULL_SCRIPT_DRAFT.md',render_script(v,'完整模型稿，待专业全文审查；不是正式采用稿，新媒体0。'))
 control.write(dst/'STATUS.json',{'stage':stage,'ordinal':r['ordinal'],'receipt_status':r['status'],'spend':summary(n),'new_media_calls':0,'creative_quality_passed':False})
 return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':summary(n)}
def finish(n):
 dst=root(n);draft=accepted(n,f'craft_draft_r{n:02}');review=accepted(n,f'craft_review_r{n:02}')
 if review['validation']['needs_revision'] or review['validation']['emotion_checkpoint']!='needs_content_confirmation':raise ValueError('unresolved mandatory review or uncertainty; no final delivery')
 script=draft['output'];out=dst/'DELIVERABLE';effective=control.read(dst/'REVIEW.json')
 for name,value in [('FULL_SCRIPT.json',script),('FULL_TEXT_REVIEW.json',effective),('HUMAN_FEEDBACK.json',control.read(dst/'HUMAN_REVISION_REQUEST.json'))]:control.write(out/name,value,True)
 write_new(out/'FULL_SCRIPT.md',render_script(script,'MiniMax完整新稿已完成DeepSeek情绪及专业对白全文审查；待用户内容核对。新导演与表演未完成，新视频0。'))
 rows=effective['dialogue_craft_review']['criteria'];lines=['# 专业对白全文审查','', '完整原稿引用展开不改变模型结论；有效文本审查不等于人工创作质量通过。','']
 for row in rows:
  lines+=['## '+STANDARDS[row['criterion']]['term'],'',row['finding']+'：'+row['reason'],'']
  for ref in row['evidence_refs']:lines+=['原文 '+ref['path']+'：'+ref['quote'],'']
 write_new(out/'DIALOGUE_CRAFT_REVIEW.md','\n'.join(lines))
 ds=[s['text'] for b in script['beats'] for s in b['steps'] if s['kind']=='dialogue']
 control.write(out/'HANDOFF.json',{'status':'complete_reviewed_text_awaiting_human_content_confirmation','script_sha256':control.digest(script),'draft_ordinal':draft['ordinal'],'review_ordinal':review['ordinal'],'speech_count':len(ds),'dialogue_characters_including_punctuation':sum(map(len,ds)),'professional_review_complete':True,'old_director_performance_and_media_invalidated_for_new_source':True,'human_content_approved':False,'creative_quality_passed':False,'media_calls':0,'spend':summary(n)},True)
 return {'delivery':str(out),'speech_count':len(ds),'dialogue_characters_including_punctuation':sum(map(len,ds)),'spend':summary(n)}
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','draft','review','finish','status']);ap.add_argument('--round',type=int,default=6);args=ap.parse_args();n=args.round
 print(json.dumps(prepare(n) if args.stage=='prepare' else summary(n) if args.stage=='status' else finish(n) if args.stage=='finish' else dispatch(n,args.stage),ensure_ascii=False),flush=True)
