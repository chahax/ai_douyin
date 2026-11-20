"""A complete current opening exchange, no whole-B1 or whole-film claim."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from src.content_factory import creative_natural_scene_performance_v3 as contract
from jsonschema import Draft202012Validator
ROOT=PROJECT/'data/production_revisions/legal_natural_performance_20261010/round_05'
PREVIOUS=PROJECT/'data/production_revisions/legal_natural_performance_20261010/round_04'
SOURCE=PROJECT/'data/production_revisions/legal_natural_interaction_20261010/round_05/REVIEWED_CANDIDATE'
OUT=ROOT/'DELIVERABLE_opening'
REFS=['B1.S01','B1.S02','B1.S03']
def write_text(p,s):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists() and p.read_text(encoding='utf-8')!=s:raise ValueError('immutable readable changed')
 if not p.exists():p.write_text(s,encoding='utf-8')
def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  ledger=control.read(PREVIOUS/'CALL_LEDGER.json');rows=ledger['calls']
  if [q['ordinal'] for q in rows]!=[385]:raise ValueError('known exact385 required')
  receipts=[control.read(PREVIOUS/q['receipt']) for q in rows]
  if receipts[0]['status']!='contract_valid' or type(receipts[0]['response_metadata']['total_tokens']) is not int or control.sha_file(PREVIOUS/rows[0]['receipt'])!=rows[0]['receipt_sha256']:raise ValueError('385 original response changed')
  previous_gate=control.read(PREVIOUS/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json')
  if previous_gate['text_sample_qualified'] or not previous_gate['unresolved_mandatory_findings']:raise ValueError('385 content rejection evidence required')
  prior=control.read(PREVIOUS/'INPUT.json');s=control.read(SOURCE/'FULL_SCRIPT.json')
  if control.digest(s)!=contract.SOURCE_SHA:raise ValueError('exact current source required')
  x={'background_full_script':s,'current_brief':control.read(SOURCE/'CURRENT_BRIEF.json'),'current_interaction':{'source_refs':REFS,'source_catalog':{k:contract.catalog(s)[k] for k in REFS},'end':'小林本次反驳完整说完。纸笔仍在周姐一侧，尚未催看/送纸/读字。'},'reference_fulltext':prior['reference_fulltext'],'human_feedback':prior['human_feedback'],'selected_asset_feedback':prior['selected_asset_feedback'],'scope':prior['scope'],'previous_unqualified_identity':{'ordinal':385,'compiled_sha256':previous_gate['compiled_sha256'],'prose_not_replayed':True},'current_authoring_task':'只写当前通知与回应这一完整交互；背景全文是因果上下文，不是本段动作指令。完整B1与整片导演未完成。'}
  wire=contract.schema(s)
  for field,limit in [('continuous_performance',160),('zhou_intent',80),('xiaolin_intent',80),('camera',80),('delivery',80)]:wire['properties'][field]['maxLength']=limit
  for n,v in [('INPUT.json',x),('USER_SCOPE.json',x['scope']),('WRITER_SCHEMA.json',wire)]:control.write(ROOT/n,v,True)
  inherited=deepcopy(ledger['starting_spend']);inherited.update(calls_started=inherited['calls_started']+1,reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+1,parent_ledger_sha256=control.sha_file(PREVIOUS/'CALL_LEDGER.json'))
  paths=[PREVIOUS/'ANCHOR.json',PREVIOUS/'CALL_LEDGER.json',PREVIOUS/'INPUT.json',PREVIOUS/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json',PREVIOUS/'CURRENT_INTERACTION_COMPILED.json',PREVIOUS/'FULL_MODEL_CURRENT_PERFORMANCE.json',PREVIOUS/rows[0]['receipt'],PROJECT/'scripts/run_legal_natural_performance_v4_20261010.py',*[SOURCE/n for n in ['FULL_SCRIPT.json','FULL_TEXT_REVIEW.json','CURRENT_BRIEF.json','INDEPENDENT_EDITORIAL_GATE.json','HANDOFF.json']]]
  control.write(ROOT/'ANCHOR.json',{'inherited':inherited,'models':ledger['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in paths},'automatic_retry':False,'budget_reset':False,'complete_film_claimed':False},True)
 runtime().prepare();return summary()
def runtime():
 a=control.read(ROOT/'ANCHOR.json');paths=[Path(__file__).resolve(),PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'src/content_factory/creative_natural_scene_performance_v3.py',PROJECT/'src/content_factory/creative_natural_scene_performance_v2.py',PROJECT/'src/content_factory/creative_natural_scene_performance_v1.py',PROJECT/'src/content_factory/creative_legal_short_director_performance_v1.py',*[ROOT/n for n in ['ANCHOR.json','INPUT.json','USER_SCOPE.json','WRITER_SCHEMA.json']]]+[Path(p) for p in a['parent_files']]
 return control.ContinuationRuntime(PROJECT,ROOT,paths,a['inherited'],a['models'],inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)
def summary():
 s=runtime().summary();s['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s
def accepted(label):
 rt=runtime();l=control.read(rt.ledger);rt.check(l);rows=[r for r in l['calls'] if r['label']==label]
 if len(rows)!=1:raise ValueError('one original response required, no automatic dispatch')
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('original response invalid or unknown')
 return r
def compiled():return contract.compile_contract(accepted('natural_opening_exchange_r1')['output'],control.read(ROOT/'INPUT.json')['background_full_script'])
def candidate():return contract.pack_first(compiled())
def review_schema():
 text={'type':'string','minLength':1};refs={'type':'array','minItems':1,'items':{'enum':REFS}}
 issue={'type':'object','additionalProperties':False,'required':['problem','required_revision','evidence_refs'],'properties':{'problem':text,'required_revision':text,'evidence_refs':refs}}
 p={'full_source_read':{'const':True},'current_interaction_valid':{'type':'boolean'},'exact_dialogue_and_scope_preserved':{'type':'boolean'},'natural_exchange_assessment':text,'causal_physical_assessment':text,'evidence_refs':refs,'issues':{'type':'array','items':issue},'suggestions':{'type':'array','items':text},'assessment':text}
 return {'type':'object','additionalProperties':False,'required':list(p),'properties':p}
def dispatch(stage):
 prepare();x=control.read(ROOT/'INPUT.json');s=x['background_full_script'];models=control.read(ROOT/'ANCHOR.json')['models'];payload=deepcopy(x)
 if stage=='performance':
  schema=control.read(ROOT/'WRITER_SCHEMA.json');label='natural_opening_exchange_r1';role='writer';cap=2200
  payload={'current_interaction':deepcopy(x['current_interaction']),'current_initial_state':{'scene':'同一小会议室，周姐与小林已经隔桌坐着，工牌已戴小林胸前','folder':'合着，在周姐侧','paper_pen':'未签，留周姐侧'},'actor_tasks':{'zhou':'习惯按公司要求通知，但要面对小林的反应','xiaolin':'以为将听工作安排，听见公司要自己离开后要一个说法，本人没提过辞职'},'reference_fulltext':x['reference_fulltext'],'reference_use':'只借话中刺激改变听者理解、反应带出回应的机制','human_feedback':['正常说话，不靠加速压时','人物说话与听话可以自然伴随活动，像真实对话'],'selected_reference_identity':{'path':x['selected_asset_feedback']['path'],'sha256':x['selected_asset_feedback']['sha256'],'scope':'仅身份服装及同一会议室参考；按当前起态'}}
  if list(payload['current_interaction']['source_catalog'])!=REFS or 'background_full_script' in payload or 'current_brief' in payload:raise ValueError('current-only authoring projection failed')
  rule='MiniMax表演导演。只交当前一个完整回合的6字段对象。当前演员来源只有3步：周姐开夹时完整通知，小林听懂后回应没提辞职，回应说完本段结束。按人物任务、言语行动、潜台词与对手反馈写简洁连续演法，两人自然活动；写心理与关系变化，不逐一指挥肌肉。原对白会由编译插入，各说一次；表演说明不引用发言或加任何发言。纸笔一直留周姐侧。只写当前演法，不展开后续故事。正常普通话交谈与自然换气，通知使小林意外并产生回应，动作表情与听说自然发生。参考只借机制，当前事实只看current_interaction。continuous_performance最多160字，其他字段最多80字；目的和说话方式简洁明确，不复述同一变化。post_pause_seconds通常0，不每句停。只输出完整对象。'
  def validator(v):
   Draft202012Validator(schema).validate(v);c=contract.compile_contract(v,s);first=contract.pack_first(c)
   if not first['dispatch_ready']:raise ValueError('complete current exchange exceeds native limit')
   contract.render_prompt(first,s)
   return {'source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'complete_current_interaction':True,'complete_B1':False,'first_source_refs':first['source_refs'],'first_duration_seconds':first['duration_seconds'],'quality_passed':False}
 elif stage=='review':
  c=compiled();first=candidate();schema=review_schema();label='natural_opening_full_source_review_r1';role='director';cap=4200
  payload.update(full_model_current_performance=accepted('natural_opening_exchange_r1')['output'],compiled_current_interaction=c,actual_first_sample=first,actual_first_prompt=contract.render_prompt(first,s))
  rule='DeepSeek完整背景阅读及当前交互全文审查。阅读完整原稿/R01/当前3步和实际原生模型表演、编译与提示词，核对只含开夹/公司通知/小林没提辞职回应；纸笔仍周姐側未送，未演催看、读字或后续拒签。检查原对白逐字各一次、当前信息时序、完整通知与回应、人物目标/对手反馈、自然连续活动和正常语速；每条必修引用当前S01-S03，不泛泛要求后续戏提前发生。不要求单样完成整B1或整片，这是明确当前scope，不能声称全部导演已建。肌肉僵死、机械卡住、不许活动、未来发言或动作是本次必修；真实脸/眼神/身体/声音/口型改善无法由文字确认。建议与实际未知放suggestions，issues只放当前真实不合格，不能改正文。只用submit_creative_json交完整复审。'
  def validator(v):
   Draft202012Validator(schema).validate(v)
   return {'source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'full_source_read':True,'needs_revision':bool(v['issues']) or not v['current_interaction_valid'] or not v['exact_dialogue_and_scope_preserved'],'actual_media_quality_passed':False}
 else:raise ValueError('explicit stage required')
 req={'role':role,'model':models[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},'input_provenance':{'operator_version':'natural_current_interaction/v5_scope_projection','source_script_sha256':control.digest(s),'full_script_in_actual_messages':stage=='review','current_actor_request_excludes_future_story':stage=='performance','reference_fulltext_in_actual_messages':True,'reference_fulltext_sha256':control.digest(x['reference_fulltext']),'current_interaction_refs':REFS,'old_acting_prose_in_actual_messages':False,'new_script_adoption_invented':False}}
 control.write(ROOT/'request_previews'/f'{stage}.json',req,True);r=runtime().dispatch(label,req,validator)
 if stage=='performance' and r['status']=='contract_valid':
  control.write(ROOT/'FULL_MODEL_CURRENT_PERFORMANCE.json',r['output'],True);control.write(ROOT/'CURRENT_INTERACTION_COMPILED.json',compiled(),True);control.write(ROOT/'FIRST_SAMPLE.json',candidate(),True);write_text(ROOT/'ACTUAL_FIRST_PROMPT.txt',contract.render_prompt(candidate(),s)+'\n')
 return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':summary()}
def finish():
 x=control.read(ROOT/'INPUT.json');s=x['background_full_script'];d=accepted('natural_opening_exchange_r1');r=accepted('natural_opening_full_source_review_r1');c=compiled();first=candidate();gate=control.read(ROOT/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json')
 if r['validation']['needs_revision'] or gate['source_sha256']!=control.digest(s) or gate['compiled_sha256']!=control.digest(c) or not gate['text_sample_qualified'] or gate['unresolved_mandatory_findings']:raise ValueError('current full-source review and independent gate unresolved')
 for n,v in [('FULL_SCRIPT.json',s),('FULL_MODEL_CURRENT_PERFORMANCE.json',d['output']),('CURRENT_INTERACTION_COMPILED.json',c),('FIRST_SAMPLE.json',first),('FULL_SOURCE_REVIEW.json',r['output']),('INDEPENDENT_PERFORMANCE_GATE.json',gate),('ASSET_FEEDBACK.json',x['selected_asset_feedback']),('USER_SCOPE.json',x['scope'])]:control.write(OUT/n,v,True)
 control.write(OUT/'HANDOFF.json',{'status':'reviewed_complete_current_exchange_for_one_replacement_sample','source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'performance_ordinal':d['ordinal'],'review_ordinal':r['ordinal'],'complete_B1':False,'whole_film_director_or_performance_complete':False,'human_script_adoption_recorded':False,'human_media_quality_approved':False,'sample_source_refs':REFS,'spend':summary()},True)
 body=['# 通知与当场回应：完整当前表演','','本次只修当前样片。完整B1/全片导演未交付，真实表演与口型待人工审核。','']
 for k,v in d['output'].items():body += [k+'：'+str(v),'']
 for row in c['schedule']:body += [row['source_ref']+' '+row['speaker']+'：'+row['original_text'],'']
 write_text(OUT/'CURRENT_EXCHANGE_READABLE.md','\n'.join(body)+'\n');write_text(OUT/'ACTUAL_FIRST_PROMPT.txt',contract.render_prompt(first,s)+'\n')
 return {'handoff':str(OUT/'CURRENT_EXCHANGE_READABLE.md'),'first_duration_seconds':first['duration_seconds'],'complete_B1':False,'spend':summary()}
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','performance','review','finish','status']);a=ap.parse_args();print(json.dumps(prepare() if a.stage=='prepare' else summary() if a.stage=='status' else finish() if a.stage=='finish' else dispatch(a.stage),ensure_ascii=False),flush=True)
