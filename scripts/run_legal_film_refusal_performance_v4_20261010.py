"""Complete next two-turn performance and same-source full review; no retry."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts import run_legal_film_material_performance_v2_20261010 as previous_text
from scripts import run_legal_film_refusal_performance_v2_20261010 as rejected_text
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from src.content_factory import creative_film_dialogue_exchange_v1 as contract
from src.content_factory.media_review_policy import validate_approved_tail
from jsonschema import Draft202012Validator
ROOT=PROJECT/'data/production_revisions/legal_film_refusal_exchange_20261010/round_04'
PREVIOUS=rejected_text.ROOT
SOURCE=previous_text.SOURCE
PREVIOUS_MEDIA=PROJECT/'data/video_generation/legal_film_material_exchange_20261010/material_v2'
OUT=ROOT/'DELIVERABLE_refusal'
REFS=['B2.S01','B2.S02']
WRITER_LABEL='film_refusal_current_performance_r4';REVIEW_LABEL='film_refusal_full_source_review_r4'
write_text=previous_text.write_text


def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  rejected_text.runtime().check(control.read(PREVIOUS/'CALL_LEDGER.json'))
  ledger=control.read(PREVIOUS/'CALL_LEDGER.json');rows=ledger['calls']
  if [q['ordinal'] for q in rows]!=[397,398]:raise ValueError('exact398 reviewed parent required')
  receipts=[control.read(PREVIOUS/q['receipt']) for q in rows];d,r=receipts
  if any(v['status']!='contract_valid' or type(v['response_metadata']['total_tokens']) is not int or control.sha_file(PREVIOUS/q['receipt'])!=q['receipt_sha256'] for q,v in zip(rows,receipts)) or not r['validation']['needs_revision'] or not r['output']['issues']:raise ValueError('specific full review revision evidence required')
  x=deepcopy(control.read(PREVIOUS/'INPUT.json'));s=x['background_full_script'];spec=x['contract_spec']
  validate_approved_tail(PREVIOUS_MEDIA/'receipt.human_review.json',expected_tail_path=Path(x['selected_asset_feedback']['path']))
  x['rejected_current_performance']=d['output'];x['specific_revision_findings']=deepcopy(r['output']['issues'])
  x['independent_review_clarification']={'window_fact':'原稿和编译已有答复后1.2秒，不能称未留窗口；应修窗口内不再动作的冻结措辞','scope_fact':'当前坚定语气、适量具体表情与自然视线变化本身不超出源；只限缩密集逐项肌肉排演与固定冻结，不禁止所有具体响应','revision_focus':'保留功能驱动的少量可见响应，让关系变化可拍，不把演员只写成抽象心理词，也不列九项眉眼嘴角肩线下颌的步骤'}
  x['specific_revision_targets']=['完整重写六字段，以人物对对方采取的行动、注意对象与对方接收变化组织连续互动，删除逐项眉眼下颌肩线等肌肉清单；不把静止身体当自然接收','普通话与说话方式只写表演方向，不出现编译器、插入、字段或工具等实现说明；不引用原句，当前原句由固定正文提供','保留当前两句、无新道具操作、同侧空间及正常语速；小林接到答复仍可自然反应，不预演下一句反驳']
  for n,v in [('INPUT.json',x),('CONTRACT_SPEC.json',spec),('USER_SCOPE.json',x['scope']),('WRITER_SCHEMA.json',contract.schema(s,spec)),('PREDECESSOR_APPROVED_SNAPSHOT.json',control.read(PREVIOUS/'PREDECESSOR_APPROVED_SNAPSHOT.json'))]:control.write(ROOT/n,v,True)
  inherited=deepcopy(ledger['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(rows),reported_tokens=inherited['reported_tokens']+sum(v['response_metadata']['total_tokens'] for v in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(rows),parent_ledger_sha256=control.sha_file(PREVIOUS/'CALL_LEDGER.json'))
  paths=[PREVIOUS/n for n in ['ANCHOR.json','CALL_LEDGER.json','INPUT.json','CONTRACT_SPEC.json','USER_SCOPE.json','WRITER_SCHEMA.json','PREDECESSOR_APPROVED_SNAPSHOT.json']]+[PREVIOUS/q['receipt'] for q in rows]+[Path(p) for p in control.read(PREVIOUS/'ANCHOR.json')['parent_files']]+[PROJECT/'scripts/run_legal_film_refusal_performance_v2_20261010.py',PROJECT/'scripts/run_legal_film_refusal_performance_v3_20261010.py',PROJECT/'data/production_revisions/legal_film_refusal_exchange_20261010/round_03/ANCHOR.json',PROJECT/'data/production_revisions/legal_film_refusal_exchange_20261010/round_03/CALL_LEDGER.json']
  control.write(ROOT/'ANCHOR.json',{'inherited':inherited,'models':ledger['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in paths},'automatic_retry':False,'budget_reset':False,'mutable_predecessor_receipt_not_hashed':True,'complete_film_claimed':False,'revision_of_ordinal':397,'review_findings_ordinal':398,'revision_reason':'complete model current performance revision after specific muscle-list and freeze findings'},True)
 runtime().prepare();return summary()


def runtime():
 a=control.read(ROOT/'ANCHOR.json');paths=[Path(__file__).resolve(),PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'src/content_factory/creative_film_dialogue_exchange_v1.py',PROJECT/'src/content_factory/creative_film_material_exchange_v1.py',PROJECT/'src/content_factory/creative_natural_scene_performance_v1.py',PROJECT/'src/content_factory/creative_legal_short_director_performance_v1.py',*[ROOT/n for n in ['ANCHOR.json','INPUT.json','CONTRACT_SPEC.json','USER_SCOPE.json','WRITER_SCHEMA.json','PREDECESSOR_APPROVED_SNAPSHOT.json']]]+[Path(p) for p in a['parent_files']]
 return control.ContinuationRuntime(PROJECT,ROOT,paths,a['inherited'],a['models'],inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)
def summary():
 s=runtime().summary();s['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s

def accepted(label):
 rt=runtime();l=control.read(rt.ledger);rt.check(l);rows=[r for r in l['calls'] if r['label']==label]
 if len(rows)!=1:raise ValueError('one original response required, no automatic retry')
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('original response invalid or unknown')
 return r

def compiled():
 x=control.read(ROOT/'INPUT.json');return contract.compile_contract(accepted(WRITER_LABEL)['output'],x['background_full_script'],x['contract_spec'])
def candidate():return contract.pack_first(compiled())
def prompt():
 x=control.read(ROOT/'INPUT.json');return contract.render_prompt(candidate(),x['background_full_script'],x['contract_spec'])
def review_schema():
 text={'type':'string','minLength':1};refs={'type':'array','minItems':1,'items':{'enum':REFS}}
 issue={'type':'object','additionalProperties':False,'required':['problem','required_revision','evidence_refs'],'properties':{'problem':text,'required_revision':text,'evidence_refs':refs}}
 p={'full_source_read':{'const':True},'current_interaction_valid':{'type':'boolean'},'exact_dialogue_and_scope_preserved':{'type':'boolean'},'natural_exchange_assessment':text,'causal_physical_assessment':text,'evidence_refs':refs,'issues':{'type':'array','items':issue},'suggestions':{'type':'array','items':text},'assessment':text}
 return {'type':'object','additionalProperties':False,'required':list(p),'properties':p}

def dispatch(stage):
 prepare();x=control.read(ROOT/'INPUT.json');s=x['background_full_script'];spec=x['contract_spec'];models=control.read(ROOT/'ANCHOR.json')['models']
 if stage=='performance':
  schema=control.read(ROOT/'WRITER_SCHEMA.json');label=WRITER_LABEL;role='writer';cap=2400
  payload={k:deepcopy(x[k]) for k in ['current_interaction','current_initial_state','film_method_current_brief','reference_fulltext','selected_asset_feedback','rejected_current_performance','specific_revision_findings','specific_revision_targets','independent_review_clarification']}
  rule='MiniMax表演导演。依据rejected_current_performance完整原稿、specific_revision_findings及targets完整重写六字段，不交补丁、不写分析。原稿逐项排眉眼嘴角下颌并写不再动作，全文审查要求返修。结合independent_review_clarification，不把398推断误当已验证缺窗口或禁止所有具体表情；当前少量事实驱动的表情、视线和合理语气可以保留，只删除密集清单与强制冻结。连续表演围绕小林把异议送给周姐、周姐如何接收并以格式回应、小林如何接到答复组织；用人物行动、注意对象和接收变化，不写肌肉清单，不冻结身体，不用预先摆好的表情替代听说。演法只用当前拒绝与当前格式答复功能指代，不引用原对白；delivery只写说话方式，不写编译器、插入、字段或工具等实现说明。依据当前互动、电影方法与R01完成关系表演。只处理小林明确拒签和周姐以公司统一格式回应，两原句由编译器各插一次，演法不引用或改写发言，不新增对白或朗读指令。小林看清原因的刺激已在前段发生，当前把异议送给周姐；周姐完整接收拒签后回应，拒绝与回应的听说反应可以自然同时发生。目的面向对手，观察服务理解与关系变化，答复完整被小林接收后结束，不按说话者轮换强制切镜。不逐肌肉、逐字音量或手势排演，不冻结人物，不催语速。纸笔已在小林近桌沿，双方原座位，文件夹打开工牌已戴；当前没有新道具移动，不能再递推、拿笔、开夹或入座。不得预演后续反驳格式、流程压力、责任追问、求情、收纸或出门。post_pause_seconds自行选择0至1.5秒答复后的必要空间，不额外加操作。按schema长度输出完整六字段。'
  def validator(v):
   Draft202012Validator(schema).validate(v);c=contract.compile_contract(v,s,spec);first=contract.pack_first(c)
   if not first['dispatch_ready']:raise ValueError('complete current interaction exceeds native limit; no speed fitting')
   contract.render_prompt(first,s,spec)
   return {'source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'complete_current_interaction':True,'complete_B2':False,'first_source_refs':first['source_refs'],'first_duration_seconds':first['duration_seconds'],'quality_passed':False}
 elif stage=='review':
  c=compiled();first=candidate();schema=review_schema();label=REVIEW_LABEL;role='director';cap=4200
  payload=deepcopy(x);payload.update(full_model_current_performance=accepted(WRITER_LABEL)['output'],compiled_current_interaction=c,actual_first_sample=first,actual_first_prompt=prompt())
  rule='DeepSeek同源完整正文及当前拒签/格式答复回合审查。读取完整380、R01、电影方法、原始当前完整演法、编译与实际提示词。当前只含B2.S01-S02，小林明确拒签和周姐格式答复；不要要求重新演前段看原因/递纸或提前演下一句。核对原对白逐字各一次、从已看清材料转为拒签的因果、周姐先听再回应、小林接收答复后才结束、同空间和纸笔不移动、正常语速与自然互动。机械逐字/肌肉演法、持续冻结凝视、过早结束或新增操作/发言是当前必修；角色安静听和自然转视线不是当然僵硬。必修引用当前两源，建议和实际声画未知放suggestions；文本规划不是实测，不能声称实际自然度/语言/口型通过。只提交完整工具复审，不手改或回填演法。'
  def validator(v):
   Draft202012Validator(schema).validate(v)
   return {'source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'full_source_read':True,'needs_revision':bool(v['issues']) or not v['current_interaction_valid'] or not v['exact_dialogue_and_scope_preserved'],'actual_media_quality_passed':False}
 else:raise ValueError('explicit stage required')
 req={'role':role,'model':models[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},'input_provenance':{'operator_version':'film_refusal_exchange/v4_clarified_complete_revision','source_script_sha256':control.digest(s),'full_script_in_actual_messages':stage=='review','current_actor_request_excludes_future_story':stage=='performance','reference_fulltext_in_actual_messages':True,'reference_fulltext_sha256':control.digest(x['reference_fulltext']),'current_interaction_refs':REFS,'old_global_acting_prose_in_actual_messages':False,'film_current_method_brief_in_actual_messages':True,'film_current_method_brief_sha256':control.digest(x['film_method_current_brief']),'new_script_adoption_invented':False,'rejected_complete_performance_in_actual_messages':stage=='performance'}}
 control.write(ROOT/'request_previews'/f'{stage}.json',req,True);r=runtime().dispatch(label,req,validator)
 if stage=='performance' and r['status']=='contract_valid':
  control.write(ROOT/'FULL_MODEL_CURRENT_PERFORMANCE.json',r['output'],True);control.write(ROOT/'CURRENT_INTERACTION_COMPILED.json',compiled(),True);control.write(ROOT/'FIRST_SAMPLE.json',candidate(),True);write_text(ROOT/'ACTUAL_FIRST_PROMPT.txt',prompt()+'\n')
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
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','performance','review','finish','status']);a=ap.parse_args();print(json.dumps(prepare() if a.stage=='prepare' else summary() if a.stage=='status' else finish() if a.stage=='finish' else dispatch(a.stage),ensure_ascii=False),flush=True)
