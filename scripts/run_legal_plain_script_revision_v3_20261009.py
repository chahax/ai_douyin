"""Source-bound second complete rewrite after actual full review; no auto retry."""
from pathlib import Path
from copy import deepcopy
import json
import sys
import argparse
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts import run_legal_plain_script_revision_v2_20261009 as prior
from scripts.run_confirmed_legal_script_trial_v4 import FIXED_INPUTS,render_script
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_legal_plain_revision_v2 import build_wire,validate_plain_dialogue
from src.content_factory.creative_trend_bridge import validate_complete_story
from src.content_factory.creative_complete_review_ids_v1 import expand
ROOT=PROJECT/'data/production_revisions/legal_plain_revision_20261009/round_03'
DIAGNOSIS={
 'schema':'legal_plain_full_source_diagnosis/v1','complete_review_ordinal':313,'complete_draft_ordinal':312,
 'original_review_preserved':True,
 'qualified_review_wording':['ISS-01原句是对得上吗，不是字面出现对不上；问题是重复比对式表达。','ISS-02旧要求没有字面禁用省事；问题是省心式套话的同义替代与重复劝签。','ISS-03没有字面核对，真正问题是拒签后的再次解释。','ISS-05新稿未摘戴工牌；反复描写工牌是叙事注意力问题，不冒充真实生成失败。'],
 'proposal_boundaries':'工资、档案被卡等是审查自行给的备选，未经事实验证，不加入新稿；不把每条建议逐一加戏。',
 'additional_source_findings':[
  {'path':'script.beats.0.steps.0.text / script.beats.7.steps.3.text','finding':'水杯在工位，结尾出现在会议室，正文无携带或另一杯起态。直接删掉无叙事作用的水杯，不新增搬杯操作。'},
  {'path':'script.beats.4.steps.0.text / script.beats.5.steps.2.text','finding':'周姐已经离开笔杆，之后却仍写推笔的手悬空。不要用未来反应覆写之前手部状态；减少重复推笔。'}],
 'complete_rewrite_goal':'直接从两人已坐定的同一间办公室开始。不拍工位日常、起身领路、进门。纸和笔开场交代；工牌正常佩戴只作身份起态，之后不做动作。',
 'plain_causal_spine':'公司让小林离开；要求签个人原因辞职；小林犹疑并问原因；周姐有一次具体劝签，小林明确拒绝；周姐收回未签纸，独自离开，小林留坐。',
 'word_budget':'尽量四个完整事件拍，核心对白约六到八句。每句推动新信息或回应前句，拒签后不再解释同一个区别。长度服务故事，不硬锁秒数。',
 'emotion':'保留突然被要求离开的吃惊、落笔前的迟疑、对方劝签后的挣扎、拒签后的静默与放松。不要以动作填满静默。',
 'manual_script_patch':False,'media_calls':0}

def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  rt=prior.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
  receipts=[rt.effective_receipt(c) for c in ledger['calls']]
  if len(receipts)!=2 or any(type(r['response_metadata'].get('total_tokens')) is not int for r in receipts):raise ValueError('actual current lineage required')
  review=prior.accepted('plain_review_r1');draft=prior.accepted('plain_draft_r1')
  if review['ordinal']!=313 or not review['validation']['needs_revision']:raise ValueError('genuine current whole review required')
  for n in FIXED_INPUTS:control.write(ROOT/n,control.read(prior.ROOT/n),True)
  for n in ('HUMAN_REVISION_REQUEST.json','DRAFT_r1.json','REVIEW_r1.json'):control.write(ROOT/n,control.read(prior.ROOT/n),True)
  control.write(ROOT/'SOURCE_DIAGNOSIS.json',DIAGNOSIS,True)
  files=list(dict.fromkeys(rt.sources+[rt.ledger]+[rt.root/c['receipt'] for c in ledger['calls']]+[prior.ROOT/n for n in ('DRAFT_r1.json','REVIEW_r1.json','REVIEW_EVIDENCE_r1.json')]))
  inherited=deepcopy(ledger['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(receipts),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(receipts),parent_ledger_sha256=control.sha_file(rt.ledger))
  control.write(ROOT/'ANCHOR.json',{'schema':'legal_plain_complete_revision/v3','inherited':inherited,'models':ledger['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in files},'automatic_retry':False,'media_authorized':False},True)
 return runtime().prepare()

def runtime():
 a=control.read(ROOT/'ANCHOR.json')
 def guard():verify_files(a['parent_files'])
 own=[Path(__file__).resolve(),ROOT/'ANCHOR.json',ROOT/'SOURCE_DIAGNOSIS.json']+[ROOT/n for n in FIXED_INPUTS+('HUMAN_REVISION_REQUEST.json','DRAFT_r1.json','REVIEW_r1.json')]
 return control.ContinuationRuntime(PROJECT,ROOT,list(dict.fromkeys(own+[Path(p) for p in a['parent_files']])),a['inherited'],a['models'],inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)

def summary():
 s=runtime().summary();s['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s

def accepted(label):
 rt=runtime();l=control.read(rt.ledger);rt.check(l);rows=[c for c in l['calls'] if c['label']==label]
 if len(rows)!=1:raise ValueError('exact source call required')
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('source rejected or unknown')
 return r

def wire(stage,script=None):
 p,f,g,s,d,c=[control.read(ROOT/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
 revision={'previous_complete_script':control.read(ROOT/'DRAFT_r1.json'),'complete_review':control.read(ROOT/'REVIEW_r1.json'),'source_diagnosis':control.read(ROOT/'SOURCE_DIAGNOSIS.json')}
 req=build_wire(p,f,g,s,stage,now=control.now(),direction=d,confirmation=c,feedback=control.read(ROOT/'HUMAN_REVISION_REQUEST.json'),script=script,revision=revision if stage=='draft' else None)
 ctx=json.loads(req['messages'][1]['content']);ctx['complete_source_diagnosis']=control.read(ROOT/'SOURCE_DIAGNOSIS.json')
 if stage=='draft':
  req['messages'][0]['content']+=' 此次是减少重复与过场的完整重写，不逐条照审查proposal加动作。直接从同一间办公室已坐定谈起，尽量四拍、六到八句核心对白。角色读到个人原因后直接问为什么，拒签只说一次，让对方的停顿和收纸兑现后果。工牌不再成为动作；删除水杯与工位支线，不拍两人进门或一起走。纸笔开场给清楚起态，笔只递一次收一次，无推完又悬手。只准周姐独自出门，小林始终留坐。'
 else:
  ctx['review_source_qualification']='历史审查仅是返修来源，不把省事/对得上等误称当前已列字面禁词；检查当前真正重复绕口和因果/状态问题。备选威胁不成为必须剧情。新稿动作和原稿不同，以当前全文为准。'
 req['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False)
 req['operator_version']='legal_plain_complete_revision/v3'
 req['input_provenance'].update(source_context_sha256=control.digest(ctx),source_diagnosis_sha256=control.digest(ctx['complete_source_diagnosis']))
 return req

def dispatch(stage):
 prepare();script=accepted('plain_draft_r2')['output'] if stage=='review' else None;req=wire(stage,script)
 control.write(ROOT/f'request_previews/{stage}_r2.json',req,True)
 ctx=json.loads(req['messages'][1]['content']);d=control.read(ROOT/'DIRECTION.json')
 def validate(v):return {**validate_complete_story(v,d),**validate_plain_dialogue(v)} if stage=='draft' else expand(v,script,ctx['emotional_brief'])[2]
 r=runtime().dispatch(f'plain_{stage}_r2',req,validate)
 if r['status']=='contract_valid':
  v=r['output']
  if stage=='review':v,e,_=expand(v,script,ctx['emotional_brief']);control.write(ROOT/'REVIEW_EVIDENCE_r2.json',e,True)
  control.write(ROOT/f'{stage.upper()}_r2.json',v,True)
  if stage=='draft':write_new(ROOT/'FULL_SCRIPT_r2.md',render_script(v,'完整MiniMax第二稿，等待全文复审与用户采用。'))
 control.write(ROOT/'STATUS.json',{'stage':stage,'ordinal':r['ordinal'],'receipt_status':r['status'],'spend':summary(),'media_calls':0,'human_new_script_adopted':None})
 return {'ordinal':r['ordinal'],'status':r['status'],'failure':r.get('failure'),'validation_error':r.get('validation_error'),'validation':r.get('validation'),'spend':summary()}

def finish():
 draft=accepted('plain_draft_r2');review=accepted('plain_review_r2')
 if review['validation']['needs_revision'] or review['validation']['emotion_checkpoint']!='needs_content_confirmation':raise ValueError('unresolved current full review')
 script=draft['output'];out=ROOT/'DELIVERABLE_r2'
 control.write(out/'FULL_SCRIPT.json',script,True);control.write(out/'FULL_TEXT_REVIEW.json',control.read(ROOT/'REVIEW_r2.json'),True)
 write_new(out/'FULL_SCRIPT.md',render_script(script,'完整新稿已完成DeepSeek全文复审；等待用户采用。尚未生成新视频。'))
 speech=[x['text'] for b in script['beats'] for x in b['steps'] if x['kind']=='dialogue']
 control.write(out/'HANDOFF.json',{'status':'complete_reviewed_text_awaiting_human_adoption','script_sha256':control.digest(script),'draft_ordinal':draft['ordinal'],'review_ordinal':review['ordinal'],'issues':0,'beat_count':len(script['beats']),'speech_count':len(speech),'spoken_characters':sum(len(x) for x in speech),'human_new_script_adopted':None,'director_and_performance_recompile_required':True,'reuse_old_timing':False,'media_calls':0,'creative_quality_passed':False,'spend':summary()},True)
 return {'delivery':str(out),'spend':summary()}

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');a=argparse.ArgumentParser(description=__doc__);a.add_argument('stage',choices=['prepare','draft','review','finish','status']);stage=a.parse_args().stage
 print(json.dumps(prepare() if stage=='prepare' else summary() if stage=='status' else finish() if stage=='finish' else dispatch(stage),ensure_ascii=False),flush=True)
