"""Independent whole review of exact third draft with source-bound issue qualification."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts import run_legal_plain_script_revision_v4_20261009 as prior
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts.run_confirmed_legal_script_trial_v4 import render_script
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_legal_review_qualification_v1 import schema,validate
ROOT=PROJECT/'data/production_revisions/legal_plain_revision_20261009/round_05'

def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  rt=prior.runtime();ledger=control.read(rt.ledger);rt.check(ledger);receipts=[rt.effective_receipt(c) for c in ledger['calls']]
  if len(receipts)!=2 or any(type(r['response_metadata'].get('total_tokens')) is not int for r in receipts):raise ValueError('exact latest parent required')
  draft=prior.accepted('plain_draft_r3');review=prior.accepted('plain_review_r3')
  if draft['ordinal']!=316 or review['ordinal']!=317:raise ValueError('same current third draft required')
  control.write(ROOT/'FULL_SCRIPT_SOURCE.json',draft['output'],True);control.write(ROOT/'PRIOR_FULL_REVIEW.json',control.read(prior.ROOT/'REVIEW_r3.json'),True)
  control.write(ROOT/'BASE_REVIEW_REQUEST.json',review['request'],True)
  files=list(dict.fromkeys(rt.sources+[rt.ledger]+[rt.root/c['receipt'] for c in ledger['calls']]+[prior.ROOT/'DRAFT_r3.json',prior.ROOT/'REVIEW_r3.json',prior.ROOT/'REVIEW_EVIDENCE_r3.json']))
  inherited=deepcopy(ledger['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(receipts),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(receipts),parent_ledger_sha256=control.sha_file(rt.ledger))
  control.write(ROOT/'ANCHOR.json',{'schema':'legal_plain_whole_review_qualification/v1','inherited':inherited,'models':ledger['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in files},'automatic_retry':False,'media_authorized':False,'same_source_draft_ordinal':316},True)
 return runtime().prepare()

def runtime():
 a=control.read(ROOT/'ANCHOR.json')
 def guard():verify_files(a['parent_files'])
 own=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_legal_review_qualification_v1.py',ROOT/'ANCHOR.json',ROOT/'FULL_SCRIPT_SOURCE.json',ROOT/'PRIOR_FULL_REVIEW.json',ROOT/'BASE_REVIEW_REQUEST.json']
 return control.ContinuationRuntime(PROJECT,ROOT,list(dict.fromkeys(own+[Path(p) for p in a['parent_files']])),a['inherited'],a['models'],inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)

def summary():
 s=runtime().summary();s['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s

def wire():
 req=control.read(ROOT/'BASE_REVIEW_REQUEST.json');ctx=json.loads(req['messages'][1]['content']);script=control.read(ROOT/'FULL_SCRIPT_SOURCE.json');old=control.read(ROOT/'PRIOR_FULL_REVIEW.json')
 if ctx['script']!=script:raise ValueError('exact full source changed')
 ctx['prior_full_review_for_qualification']=old
 ctx['review_acceptance_contract']={
  'must_fix':'当前真正矛盾、核心事件缺失、必须动作不可能、范围违背、法律绝对断言或正文确实重复绕口；须用全片上下文检验。',
  'optional':'还能更美、更强，但当前有完整刺激选择后果；不要求每拍单独完成完整因果循环。',
  'director_stage':'机位、纸上字何时被观众先看见、演员脸和手的观察重点、停顿秒数，由后续导演和表演编译负责。',
  'continuous_beats':'B3末尾停顿后B4紧接收回未签纸，全片未写时间跳过；必须同一拍收纸不是本项目的普遍验收规则。',
  'full_state_chain':'B2指节收紧，B3手收回膝上，B4门合上后松开；判断保持或变化是否需要补新动作，不忽略前拍。',
  'source_scope':'读取完整premise、event、trigger和steps，情节是否成立以正文发生为准；不要求B1就讲完B2才揭示的信息，也不强制观众比人物更早知道。',
  'verdict':'逐条原问题重新判断，真实问题保留；不能因为来源有旧必修就默认全部必修，也不能为了通过删除真问题。'}
 req['messages'][0]['content']='DeepSeek独立全文重审同一完整新稿，真实源与完整参考不变。依据当前已确认故事和review_acceptance_contract检查因果、情绪、对白、物件和动作前提；原问题逐条填写prior_issue_assessments。保留真正当前必修问题，表演观察/秒数建议交导演，审美可选归建议，不强制收纸与拒签同一拍，不强制每拍单独兑现全片目标。公司让走是压力，纸上个人原因触发追问，一次催签后拒签、对方停住收纸、只对方离开，是完整链；仍须判断真实矛盾，不因该说明假通过。法律胜负仍留白。全过程不代写，不修改原稿或原审查；四项情绪须用当前正文证据。只调用submit_creative_json，所有evidence_refs仅{ref_id:目录ID}，基于完整script而非excerpt。逐项资格判断不能漏项；upheld_must_fix必须在本次全文issues列出，其他current_issue_id为null。'
 req['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False);req['structured_schema']=schema(script,ctx['emotional_brief'],old);req['parameters']['max_completion_tokens']=8000
 req['operator_version']='legal_plain_whole_review_qualification/v1';req['input_provenance'].update(source_context_sha256=control.digest(ctx),same_complete_script_sha256=control.digest(script),prior_full_review_sha256=control.digest(old))
 return req

def dispatch():
 prepare();req=wire();ctx=json.loads(req['messages'][1]['content']);script=ctx['script'];old=control.read(ROOT/'PRIOR_FULL_REVIEW.json');brief=ctx['emotional_brief']
 control.write(ROOT/'request_previews/qualified_whole_review_r3.json',req,True)
 r=runtime().dispatch('plain_qualified_review_r3',req,lambda v:validate(v,script,brief,old)[2])
 if r['status']=='contract_valid':
  effective,evidence,_=validate(r['output'],script,brief,old);control.write(ROOT/'FULL_TEXT_REVIEW_QUALIFIED.json',effective,True);control.write(ROOT/'QUALIFICATION_EVIDENCE.json',evidence,True)
 control.write(ROOT/'STATUS.json',{'stage':'independent_qualified_full_review','ordinal':r['ordinal'],'receipt_status':r['status'],'spend':summary(),'media_calls':0,'human_new_script_adopted':None})
 return {'ordinal':r['ordinal'],'status':r['status'],'failure':r.get('failure'),'validation_error':r.get('validation_error'),'validation':r.get('validation'),'spend':summary()}

def finish():
 rt=runtime();ledger=control.read(rt.ledger);rt.check(ledger)
 if len(ledger['calls'])!=1:raise ValueError('one independent review required')
 r=rt.effective_receipt(ledger['calls'][0])
 if r['status']!='contract_valid' or r['validation']['needs_revision'] or r['validation']['emotion_checkpoint']!='needs_content_confirmation':raise ValueError('current qualified full review unresolved')
 script=control.read(ROOT/'FULL_SCRIPT_SOURCE.json');review=control.read(ROOT/'FULL_TEXT_REVIEW_QUALIFIED.json');out=ROOT/'DELIVERABLE_r3'
 if control.digest(script)!='2904da9d662dd3cf7c8411bf7cf4d9f763a3f7d3df35809fa064a46b893101ca':raise ValueError('same third draft changed')
 control.write(out/'FULL_SCRIPT.json',script,True);control.write(out/'FULL_TEXT_REVIEW.json',review,True);control.write(out/'PRIOR_REVIEW_317.json',control.read(ROOT/'PRIOR_FULL_REVIEW.json'),True);control.write(out/'QUALIFICATION_EVIDENCE.json',control.read(ROOT/'QUALIFICATION_EVIDENCE.json'),True)
 write_new(out/'FULL_SCRIPT.md',render_script(script,'完整MiniMax新稿；DeepSeek已全文复审并逐项校准原异议。等待用户采用，尚未生成新视频。'))
 speech=[s['text'] for b in script['beats'] for s in b['steps'] if s['kind']=='dialogue']
 control.write(out/'HANDOFF.json',{'status':'complete_reviewed_text_awaiting_human_adoption','script_sha256':control.digest(script),'draft_ordinal':316,'review_ordinal':r['ordinal'],'prior_full_review_ordinal':317,'original_review_preserved':True,'issues':len(review['full_text_review']['issues']),'beat_count':len(script['beats']),'speech_count':len(speech),'spoken_characters':sum(len(s) for s in speech),'human_new_script_adopted':None,'director_and_performance_recompile_required':True,'reuse_old_timing':False,'media_calls':0,'creative_quality_passed':False,'spend':summary()},True)
 return {'delivery':str(out),'spend':summary()}

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['prepare','review','finish','status']);s=p.parse_args().stage
 print(json.dumps(prepare() if s=='prepare' else summary() if s=='status' else finish() if s=='finish' else dispatch(),ensure_ascii=False),flush=True)
