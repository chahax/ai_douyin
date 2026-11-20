"""Second complete rewrite with repaired source-bound review contract; old calls retained."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_legal_conflict_feedback_revision_v5_20261009 as prior
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v4 import FIXED_INPUTS,render_script
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_legal_conflict_feedback_v6 import build_wire,validate_current_script
from src.content_factory.creative_complete_review_ids_v1 import expand
from src.content_factory.creative_trend_bridge import validate_complete_story
ROOT=PROJECT/'data/production_revisions/legal_conflict_feedback_20261009/round_06'
def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  rt=prior.runtime();l=control.read(rt.ledger);rt.check(l);rs=[rt.effective_receipt(c) for c in l['calls']]
  if [r['ordinal'] for r in rs]!=[335,336]:raise ValueError('exact335 whole source and336 received invalid review required')
  for n in FIXED_INPUTS:control.write(ROOT/n,control.read(prior.ROOT/n),True)
  control.write(ROOT/'HUMAN_REVISION_REQUEST.json',control.read(prior.ROOT/'HUMAN_REVISION_REQUEST.json'),True)
  control.write(ROOT/'PREVIOUS_COMPLETE_SCRIPT.json',rs[0]['output'],True)
  control.write(ROOT/'PREVIOUS_COMPLETE_REVIEW.json',rs[1]['output'],True)
  control.write(ROOT/'PREVIOUS_REVIEW_VALIDATION.json',{'ordinal':336,'status':rs[1]['status'],'failure':rs[1]['failure'],'validation_error':rs[1]['validation_error'],'reason':'DeepSeek added suggestions_note beyond exact tool schema. Original full response preserved; no field stripped. Current55-character speech too bureaucratic, requires complete writer rewrite before new full review.','valid_full_review':False},True)
  inherited=deepcopy(l['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(rs),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in rs),calls_with_known_usage=inherited['calls_with_known_usage']+len(rs),parent_ledger_sha256=control.sha_file(rt.ledger))
  files=list(dict.fromkeys(rt.sources+[rt.ledger]+[rt.root/c['receipt'] for c in l['calls']]))
  control.write(ROOT/'ANCHOR.json',{'schema':'legal_conflict_feedback_revision/v6','inherited':inherited,'models':l['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in files},'media_authorized':False,'automatic_retry':False,'budget_reset':False},True)
 return runtime().prepare()
def runtime():
 a=control.read(ROOT/'ANCHOR.json');own=[Path(__file__).resolve()]+[PROJECT/'src/content_factory'/n for n in ['creative_legal_conflict_feedback_v1.py','creative_legal_conflict_feedback_v2.py','creative_legal_conflict_feedback_v3.py','creative_legal_conflict_feedback_v4.py','creative_legal_conflict_feedback_v5.py','creative_legal_conflict_feedback_v6.py','creative_complete_review_ids_v1.py']]+[ROOT/n for n in FIXED_INPUTS+('ANCHOR.json','HUMAN_REVISION_REQUEST.json','PREVIOUS_COMPLETE_SCRIPT.json','PREVIOUS_COMPLETE_REVIEW.json','PREVIOUS_REVIEW_VALIDATION.json')]
 return control.ContinuationRuntime(PROJECT,ROOT,list(dict.fromkeys(own+[Path(p) for p in a['parent_files']])),a['inherited'],a['models'],inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)
def summary():
 s=runtime().summary();s['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s
def accepted(label):
 rt=runtime();l=control.read(rt.ledger);rt.check(l);rows=[c for c in l['calls'] if c['label']==label]
 if len(rows)!=1:raise ValueError('exact current receipt required '+label)
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('source failed/unknown; no repeated dispatch')
 return r
def wire(stage,script=None):
 p,f,g,s,d,c=[control.read(ROOT/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
 return build_wire(p,f,g,s,stage,now=control.now(),direction=d,confirmation=c,feedback=control.read(ROOT/'HUMAN_REVISION_REQUEST.json'),previous_script=control.read(ROOT/'PREVIOUS_COMPLETE_SCRIPT.json'),previous_review=control.read(ROOT/'PREVIOUS_COMPLETE_REVIEW.json'),script=script)
def dispatch(stage):
 prepare();script=accepted('conflict_draft_r6')['output'] if stage=='review' else None;req=wire(stage,script)
 control.write(ROOT/f'request_previews/{stage}_r6.json',req,True);ctx=json.loads(req['messages'][1]['content']);d=control.read(ROOT/'DIRECTION.json')
 def validate(v):return {**validate_complete_story(v,d),**validate_current_script(v)} if stage=='draft' else expand(v,script,ctx['emotional_brief'])[2]
 r=runtime().dispatch(f'conflict_{stage}_r6',req,validate)
 if r['status']=='contract_valid':
  v=r['output']
  if stage=='review':v,e,_=expand(v,script,ctx['emotional_brief']);control.write(ROOT/'FULL_REVIEW_EVIDENCE.json',e,True)
  control.write(ROOT/f'{stage.upper()}_r6.json',v,True)
  if stage=='draft':write_new(ROOT/'FULL_SCRIPT_r6.md',render_script(v,'MiniMax完整短句返修稿，待全文复审与用户内容核对；新媒体0。'))
 control.write(ROOT/'STATUS.json',{'stage':stage,'ordinal':r['ordinal'],'receipt_status':r['status'],'spend':summary(),'new_media_calls':0,'creative_quality_passed':False})
 return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':summary()}
def finish():
 draft=accepted('conflict_draft_r6');review=accepted('conflict_review_r6')
 if review['validation']['needs_revision'] or review['validation']['emotion_checkpoint']!='needs_content_confirmation':raise ValueError('unresolved mandatory whole review')
 script=draft['output'];out=ROOT/'DELIVERABLE_conflict_r6'
 for n,v in [('FULL_SCRIPT.json',script),('FULL_TEXT_REVIEW.json',control.read(ROOT/'REVIEW_r6.json')),('HUMAN_FEEDBACK.json',control.read(ROOT/'HUMAN_REVISION_REQUEST.json'))]:control.write(out/n,v,True)
 write_new(out/'FULL_SCRIPT.md',render_script(script,'MiniMax完整新稿已完成DeepSeek全文复审；待用户核对。导演/表演待重建，新视频0。'))
 speech=[s['text'] for b in script['beats'] for s in b['steps'] if s['kind']=='dialogue']
 control.write(out/'HANDOFF.json',{'status':'complete_reviewed_text_awaiting_human_content_confirmation','script_sha256':control.digest(script),'draft_ordinal':draft['ordinal'],'review_ordinal':review['ordinal'],'speech_count':len(speech),'spoken_characters':sum(len(s) for s in speech),'old_director_performance_and_media_invalidated_for_new_source':True,'human_content_approved':False,'creative_quality_passed':False,'media_calls':0,'spend':summary()},True)
 return {'delivery':str(out),'speech_count':len(speech),'spoken_characters':sum(len(s) for s in speech),'spend':summary()}
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','draft','review','finish','status']);s=ap.parse_args().stage
 print(json.dumps(prepare() if s=='prepare' else summary() if s=='status' else finish() if s=='finish' else dispatch(s),ensure_ascii=False),flush=True)

