"""Complete source rewrite and full review from latest human feedback; no media submits."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_legal_short_director_performance_v4_20261009 as parent
from scripts import run_legal_plain_script_revision_v4_20261009 as fixed
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v4 import FIXED_INPUTS,render_script
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_legal_conflict_feedback_v1 import build_wire,validate_exact_wording,REVISION_CONTRACT
from src.content_factory.creative_complete_review_ids_v1 import expand
from src.content_factory.creative_trend_bridge import validate_complete_story
ROOT=PROJECT/'data/production_revisions/legal_conflict_feedback_20261009/round_01'
MEDIA=PROJECT/'data/video_generation/legal_short_remake_20261009/batch_v1'
USER_STATEMENT='今天不签手续就停在这这段还是太AI味了，然后合同推的时候都往桌子中间推都越来越远了，然后语速可以加快一点也不住于一分半才这么点话，然后看到是个人原因的时候小林可以情绪扩散一下，人事也可以再公司角度回复，视频平淡的原因应该再这里'
def record_feedback():
 from src.content_factory.media_review_policy import record_user_media_decision
 target=MEDIA/'human_feedback_conflict_20261009';receipt=MEDIA/'ASSEMBLY_RECEIPT.json';review_path=MEDIA/'ASSEMBLY_RECEIPT.human_review.json'
 if not review_path.exists():control.write(target/'ORIGINAL_TECHNICAL_ASSEMBLY_RECEIPT.json',control.read(receipt),True)
 review=record_user_media_decision(receipt,'rejected',USER_STATEMENT)
 feedback={'schema':'legal_short_human_conflict_feedback/v1','decision_source':'explicit_user_statement','user_statement':USER_STATEMENT,'video_path':review['original_video'],'video_sha256':review['original_video_sha256'],'human_review':str(review_path),'whole_film_status':'rejected_requires_revision','not_all_segments_individually_rejected':True,'assistant_content_inspected':False,'media_calls':0,
 'verified_request_causes':[
 {'source':'FULL_SCRIPT316/ACTUAL_PROMPTS.SHORT01,SHORT02,SHORT04','fact':'递纸调纸退纸均table_middle，目标没有区分。实际越来越远是用户观察，服务机制仍未知。'},
 {'source':'COMPILED_PERFORMANCE','fact':'85对白字符、92.2秒编译，最后一拍33秒。真实语速未测听。'},
 {'source':'FULL_SCRIPT316.B2.S02/S03','fact':'质疑个人原因后人事只催签，没有公司立场回答；情绪扩散缺有来有回刺激。'}],
 'revision_contract':REVISION_CONTRACT,'old_receipts_and_media_preserved':True,'old_budget_reset':False}
 control.write(target/'USER_FEEDBACK.json',feedback,True)
 return target/'USER_FEEDBACK.json'
def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  feedback=record_feedback();rt=parent.runtime();l=control.read(rt.ledger);rt.check(l);receipts=[rt.effective_receipt(c) for c in l['calls']]
  if [r['ordinal'] for r in receipts]!=[327,328,329]:raise ValueError('exact329 parent required')
  for n in FIXED_INPUTS:control.write(ROOT/n,control.read(fixed.ROOT/n),True)
  control.write(ROOT/'HUMAN_REVISION_REQUEST.json',control.read(feedback),True);control.write(ROOT/'PREVIOUS_COMPLETE_SCRIPT.json',parent.sources()['full_script'],True)
  inherited=deepcopy(l['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(receipts),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(receipts),parent_ledger_sha256=control.sha_file(rt.ledger))
  files=list(dict.fromkeys(rt.sources+[rt.ledger]+[rt.root/c['receipt'] for c in l['calls']]+[feedback]))
  control.write(ROOT/'ANCHOR.json',{'schema':'legal_conflict_feedback_revision/v1','inherited':inherited,'models':l['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in files},'media_authorized':False,'automatic_retry':False,'budget_reset':False},True)
 return runtime().prepare()
def runtime():
 a=control.read(ROOT/'ANCHOR.json');own=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_legal_conflict_feedback_v1.py',ROOT/'ANCHOR.json',ROOT/'HUMAN_REVISION_REQUEST.json',ROOT/'PREVIOUS_COMPLETE_SCRIPT.json']+[ROOT/n for n in FIXED_INPUTS]
 return control.ContinuationRuntime(PROJECT,ROOT,list(dict.fromkeys(own+[Path(p) for p in a['parent_files']])),a['inherited'],a['models'],inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)
def summary():
 s=runtime().summary();s['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s
def accepted(label):
 rt=runtime();l=control.read(rt.ledger);rt.check(l);rows=[c for c in l['calls'] if c['label']==label]
 if len(rows)!=1:raise ValueError('exact current receipt required '+label)
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('source failed/unknown; no repeated dispatch')
 return r
def dispatch(stage):
 prepare();script=accepted('conflict_draft_r1')['output'] if stage=='review' else None
 p,f,g,s,d,c=[control.read(ROOT/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
 req=build_wire(p,f,g,s,stage,now=control.now(),direction=d,confirmation=c,feedback=control.read(ROOT/'HUMAN_REVISION_REQUEST.json'),previous_script=control.read(ROOT/'PREVIOUS_COMPLETE_SCRIPT.json'),script=script)
 control.write(ROOT/f'request_previews/{stage}_r1.json',req,True);ctx=json.loads(req['messages'][1]['content'])
 def validate(v):return {**validate_complete_story(v,d),**validate_exact_wording(v)} if stage=='draft' else expand(v,script,ctx['emotional_brief'])[2]
 r=runtime().dispatch(f'conflict_{stage}_r1',req,validate)
 if r['status']=='contract_valid':
  v=r['output']
  if stage=='review':v,e,_=expand(v,script,ctx['emotional_brief']);control.write(ROOT/'FULL_REVIEW_EVIDENCE.json',e,True)
  control.write(ROOT/f'{stage.upper()}_r1.json',v,True)
  if stage=='draft':write_new(ROOT/'FULL_SCRIPT_r1.md',render_script(v,'MiniMax完整返修稿，等待全文复审和用户核对；未生成新视频。'))
 control.write(ROOT/'STATUS.json',{'stage':stage,'ordinal':r['ordinal'],'receipt_status':r['status'],'spend':summary(),'new_media_calls':0,'creative_quality_passed':False})
 return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':summary()}
def finish():
 draft=accepted('conflict_draft_r1');review=accepted('conflict_review_r1')
 if review['validation']['needs_revision'] or review['validation']['emotion_checkpoint']!='needs_content_confirmation':raise ValueError('unresolved mandatory whole review')
 script=draft['output'];out=ROOT/'DELIVERABLE_conflict_r1'
 for n,v in [('FULL_SCRIPT.json',script),('FULL_TEXT_REVIEW.json',control.read(ROOT/'REVIEW_r1.json')),('HUMAN_FEEDBACK.json',control.read(ROOT/'HUMAN_REVISION_REQUEST.json'))]:control.write(out/n,v,True)
 write_new(out/'FULL_SCRIPT.md',render_script(script,'MiniMax完整新稿已完成DeepSeek全文复审；待用户核对。新导演表演尚未生成，未生成新视频。'))
 speech=[s['text'] for b in script['beats'] for s in b['steps'] if s['kind']=='dialogue']
 control.write(out/'HANDOFF.json',{'status':'complete_reviewed_text_awaiting_human_content_confirmation','script_sha256':control.digest(script),'draft_ordinal':draft['ordinal'],'review_ordinal':review['ordinal'],'speech_count':len(speech),'spoken_characters':sum(len(s) for s in speech),'old_director_performance_and_media_invalidated_for_new_source':True,'human_content_approved':False,'creative_quality_passed':False,'media_calls':0,'spend':summary()},True)
 return {'delivery':str(out),'speech_count':len(speech),'spoken_characters':sum(len(s) for s in speech),'spend':summary()}
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','draft','review','finish','status']);stage=ap.parse_args().stage
 print(json.dumps(prepare() if stage=='prepare' else summary() if stage=='status' else finish() if stage=='finish' else dispatch(stage),ensure_ascii=False),flush=True)

