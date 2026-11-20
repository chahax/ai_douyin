"""Independent same-source full review of unchanged performance399; no retry."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import run_legal_film_refusal_performance_v4_20261010 as parent
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from src.content_factory import creative_film_dialogue_exchange_v1 as contract
from src.content_factory.media_review_policy import validate_approved_tail
from jsonschema import Draft202012Validator
ROOT=PROJECT/'data/production_revisions/legal_film_refusal_exchange_20261010/round_05'
PREVIOUS=parent.ROOT
SOURCE=parent.SOURCE
PREVIOUS_MEDIA=parent.PREVIOUS_MEDIA
OUT=ROOT/'DELIVERABLE_refusal'
REFS=parent.REFS
WRITER_LABEL=parent.WRITER_LABEL
REVIEW_LABEL='film_refusal_same_source_evidence_review_r5'
write_text=parent.write_text
DISPUTE=PREVIOUS/'REVIEW_EVIDENCE_DISPUTE.json'

def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  parent.runtime().check(control.read(PREVIOUS/'CALL_LEDGER.json'))
  ledger=control.read(PREVIOUS/'CALL_LEDGER.json');rows=ledger['calls']
  if [q['ordinal'] for q in rows]!=[399,400]:raise ValueError('exact399/400 parent required')
  receipts=[control.read(PREVIOUS/q['receipt']) for q in rows];d,r=receipts
  if any(v['status']!='contract_valid' or type(v['response_metadata']['total_tokens']) is not int or control.sha_file(PREVIOUS/q['receipt'])!=q['receipt_sha256'] for q,v in zip(rows,receipts)) or not r['validation']['needs_revision']:raise ValueError('preserved original review required')
  dispute=control.read(DISPUTE)
  verify_files({v['path']:v['file_sha256'] for v in dispute['source_bindings'].values()})
  if not dispute['new_same_source_full_review_required'] or dispute['model_performance_rewritten'] or dispute['disputed_review_ordinal']!=400:raise ValueError('exact independent evidence adjudication required')
  x=deepcopy(control.read(PREVIOUS/'INPUT.json'))
  for k in ['rejected_current_performance','specific_revision_findings','specific_revision_targets']:x.pop(k,None)
  x['unchanged_performance_ordinal']=399;x['disputed_full_review']=r['output'];x['independent_evidence_dispute']=dispute
  validate_approved_tail(PREVIOUS_MEDIA/'receipt.human_review.json',expected_tail_path=Path(x['selected_asset_feedback']['path']))
  for n,v in [('INPUT.json',x),('CONTRACT_SPEC.json',x['contract_spec']),('USER_SCOPE.json',x['scope']),('PREDECESSOR_APPROVED_SNAPSHOT.json',control.read(PREVIOUS/'PREDECESSOR_APPROVED_SNAPSHOT.json'))]:control.write(ROOT/n,v,True)
  inherited=deepcopy(ledger['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(rows),reported_tokens=inherited['reported_tokens']+sum(v['response_metadata']['total_tokens'] for v in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(rows),parent_ledger_sha256=control.sha_file(PREVIOUS/'CALL_LEDGER.json'))
  paths=[PREVIOUS/n for n in ['ANCHOR.json','CALL_LEDGER.json','INPUT.json','CONTRACT_SPEC.json','USER_SCOPE.json','PREDECESSOR_APPROVED_SNAPSHOT.json','FULL_MODEL_CURRENT_PERFORMANCE.json','CURRENT_INTERACTION_COMPILED.json','FIRST_SAMPLE.json','ACTUAL_FIRST_PROMPT.txt','REVIEW_EVIDENCE_DISPUTE.json']]+[PREVIOUS/q['receipt'] for q in rows]+[Path(p) for p in control.read(PREVIOUS/'ANCHOR.json')['parent_files']]+[Path(parent.__file__).resolve()]
  control.write(ROOT/'ANCHOR.json',{'inherited':inherited,'models':ledger['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in paths},'automatic_retry':False,'budget_reset':False,'mutable_predecessor_receipt_not_hashed':True,'complete_film_claimed':False,'unchanged_performance_ordinal':399,'preserved_disputed_review_ordinal':400,'reason':'new independent same-source review of concrete mandatory-evidence dispute; no model performance modification'},True)
 runtime().prepare();return summary()

def runtime():
 a=control.read(ROOT/'ANCHOR.json');paths=[Path(__file__).resolve(),PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'src/content_factory/creative_film_dialogue_exchange_v1.py',*[ROOT/n for n in ['ANCHOR.json','INPUT.json','CONTRACT_SPEC.json','USER_SCOPE.json','PREDECESSOR_APPROVED_SNAPSHOT.json']]]+[Path(p) for p in a['parent_files']]
 return control.ContinuationRuntime(PROJECT,ROOT,paths,a['inherited'],a['models'],inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)
def summary():
 s=runtime().summary();s['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s

def accepted(label):
 if label==WRITER_LABEL:return parent.accepted(label)
 rt=runtime();l=control.read(rt.ledger);rt.check(l);rows=[r for r in l['calls'] if r['label']==label]
 if len(rows)!=1:raise ValueError('one original response required, no automatic retry')
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('original response invalid or unknown')
 return r

def compiled():return parent.compiled()
def candidate():return parent.candidate()
def prompt():return parent.prompt()
def review_schema():return parent.review_schema()

def dispatch(stage):
 if stage!='review':raise ValueError('review-only unchanged performance')
 prepare();x=control.read(ROOT/'INPUT.json');s=x['background_full_script'];c=compiled();first=candidate();schema=review_schema();models=control.read(ROOT/'ANCHOR.json')['models']
 payload=deepcopy(x);payload.update(full_model_current_performance=accepted(WRITER_LABEL)['output'],compiled_current_interaction=c,actual_first_sample=first,actual_first_prompt=prompt())
 rule='DeepSeek独立同源全文复审。完整读取380正文、R01、当前原始399六字段、编译及实际提示词；399没有更改。disputed_full_review是400原始审查，independent_evidence_dispute是独立证据核对，两者均为待裁定的材料，不是要求你必然通过或否定。核对B2.S01-S02完整原对白各一次、已看清原因到拒签、周姐先听后以格式答复、小林接收后收束、同空间不移动纸笔、正常语速。对每个必修需指出当前实际指令与源或合同的矛盾。适量由对方答复引起的可见随动不自动等于逐字密集肌肉清单；注视交谈对象不自动等于身体冻结；已有1秒接收窗口不能称不存在。明确要求不再动作、逐肌肉固定顺序或实际时序冲突才是证实必修。仍可独立发现其他真实错误并列issues，不能因独立证据核对而强制空issues。自然微动是否最终被视频模型演机械、真实凝视是否僵硬均未实测，这类未证实风险放suggestions。保持简洁、不要求新增前序或未来动作与对白。仅审查完整原稿，不写补丁，不替用户判断视频或口型通过。提交完整工具结果。'
 def validator(v):
  Draft202012Validator(schema).validate(v)
  return {'source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'full_source_read':True,'needs_revision':bool(v['issues']) or not v['current_interaction_valid'] or not v['exact_dialogue_and_scope_preserved'],'actual_media_quality_passed':False,'unchanged_performance_ordinal':399,'preserved_disputed_review_ordinal':400}
 req={'role':'director','model':models['director']['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':4200,'temperature':.4,'thinking':'disabled'},'input_provenance':{'operator_version':'film_refusal_exchange/v5_independent_same_source_evidence_review','source_script_sha256':control.digest(s),'full_script_in_actual_messages':True,'reference_fulltext_in_actual_messages':True,'reference_fulltext_sha256':control.digest(x['reference_fulltext']),'current_interaction_refs':REFS,'unchanged_performance_ordinal':399,'unchanged_performance_sha256':control.digest(accepted(WRITER_LABEL)['output']),'complete_disputed_review_in_actual_messages':True,'independent_evidence_dispute_in_actual_messages':True,'new_script_adoption_invented':False,'old_global_acting_prose_in_actual_messages':False}}
 control.write(ROOT/'request_previews/review.json',req,True);r=runtime().dispatch(REVIEW_LABEL,req,validator)
 return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':summary()}

def finish():
 x=control.read(ROOT/'INPUT.json');s=x['background_full_script'];d=accepted(WRITER_LABEL);r=accepted(REVIEW_LABEL);c=compiled();first=candidate();gate=control.read(ROOT/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json')
 if r['validation']['needs_revision'] or gate['source_sha256']!=control.digest(s) or gate['compiled_sha256']!=control.digest(c) or not gate['text_sample_qualified'] or gate['unresolved_mandatory_findings']:raise ValueError('current review and independent gate unresolved')
 for n,v in [('FULL_SCRIPT.json',s),('CONTRACT_SPEC.json',x['contract_spec']),('FULL_MODEL_CURRENT_PERFORMANCE.json',d['output']),('CURRENT_INTERACTION_COMPILED.json',c),('FIRST_SAMPLE.json',first),('FULL_SOURCE_REVIEW.json',r['output']),('INDEPENDENT_PERFORMANCE_GATE.json',gate),('ASSET_FEEDBACK.json',x['selected_asset_feedback']),('USER_SCOPE.json',x['scope'])]:control.write(OUT/n,v,True)
 control.write(OUT/'HANDOFF.json',{'status':'reviewed_current_refusal_exchange','source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'performance_ordinal':d['ordinal'],'review_ordinal':r['ordinal'],'complete_current_interaction':True,'complete_B2':False,'whole_film_director_or_performance_complete':False,'human_script_adoption_recorded':False,'human_media_quality_approved':False,'sample_source_refs':REFS,'requires_previous_candidate_explicit_human_approval':True,'spend':summary()},True)
 body=['# 明确拒签与公司格式答复：完整当前表演','','只覆盖B2.S01-S02，真实表演待人工审核，不表示完整B2或整片通过。','']
 for k,v in d['output'].items():body += [k+'：'+str(v),'']
 for row in c['schedule']:body += [row['source_ref']+' '+row['speaker']+'：'+row['original_text'],'']
 write_text(OUT/'CURRENT_EXCHANGE_READABLE.md','\n'.join(body)+'\n');write_text(OUT/'ACTUAL_FIRST_PROMPT.txt',prompt()+'\n')
 return {'handoff':str(OUT/'CURRENT_EXCHANGE_READABLE.md'),'first_duration_seconds':first['duration_seconds'],'spend':summary()}

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','review','finish','status']);a=ap.parse_args();print(json.dumps(prepare() if a.stage=='prepare' else summary() if a.stage=='status' else finish() if a.stage=='finish' else dispatch(a.stage),ensure_ascii=False),flush=True)
