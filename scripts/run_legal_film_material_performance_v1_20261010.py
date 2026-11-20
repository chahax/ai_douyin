"""One source-bound material exchange; current writer, complete-source review."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from src.content_factory import creative_film_material_exchange_v1 as contract
from jsonschema import Draft202012Validator
ROOT=PROJECT/'data/production_revisions/legal_film_material_exchange_20261010/round_01'
PREVIOUS=PROJECT/'data/production_revisions/legal_film_director_sample_20261010/round_03'
SOURCE=PROJECT/'data/production_revisions/legal_natural_interaction_20261010/round_05/REVIEWED_CANDIDATE'
PREVIOUS_MEDIA=PROJECT/'data/video_generation/legal_film_director_sample_20261010/opening_v1'
OUT=ROOT/'DELIVERABLE_material'
REFS=['B1.S04','B1.S05','B1.S06','B1.S07']
WRITER_LABEL='film_material_exchange_r1'; REVIEW_LABEL='film_material_full_source_review_r1'
def write_text(p,s):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists() and p.read_text(encoding='utf-8')!=s:raise ValueError('immutable text changed')
 if not p.exists():p.write_text(s,encoding='utf-8')
def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  ledger=control.read(PREVIOUS/'CALL_LEDGER.json'); rows=ledger['calls']
  if [q['ordinal'] for q in rows]!=[390,391]:raise ValueError('exact391 predecessor required')
  receipts=[control.read(PREVIOUS/q['receipt']) for q in rows]
  if any(r['status']!='contract_valid' or type(r['response_metadata']['total_tokens']) is not int or control.sha_file(PREVIOUS/q['receipt'])!=q['receipt_sha256'] for q,r in zip(rows,receipts)):raise ValueError('predecessor invalid or unknown')
  s=control.read(SOURCE/'FULL_SCRIPT.json'); prior=control.read(PREVIOUS/'INPUT.json')
  if control.digest(s)!=contract.SOURCE_SHA:raise ValueError('exact380 source required')
  video=control.read(PREVIOUS_MEDIA/'receipt.json'); plan=control.read(PREVIOUS_MEDIA/'PLAN.json')
  if video['task_id']!='cgt-20261010170430-j94sb' or video['technical_status']!='succeeded' or video['last_frame_source']!='generation_service_original':raise ValueError('exact saved previous provider output required')
  if control.sha_file(Path(video['video_path']))!=video['video_sha256'] or control.sha_file(Path(video['last_frame']))!=video['last_frame_sha256']:raise ValueError('previous provider bytes changed')
  previous_handoff=control.read(PREVIOUS/'DELIVERABLE_opening/HANDOFF.json')
  if previous_handoff['source_sha256']!=contract.SOURCE_SHA or previous_handoff['sample_source_refs']!=['B1.S01','B1.S02','B1.S03']:raise ValueError('prior current coverage invalid')
  scope={'schema':'film_single_material_scope/v1','user_statement':'继续','authorization_basis':'continue current legal production; current next text authorized; video requires explicit previous candidate approval','script_sha256':contract.SOURCE_SHA,'script_ordinal':380,'human_script_adoption_recorded':False,'max_new_submissions':1,'requires_previous_human_approval':True,'previous_task_id':video['task_id'],'previous_video_sha256':video['video_sha256'],'first_frame_source':'generation_service_original','batch_authorized':False,'later_segments_authorized':False,'publish_authorized':False,'automatic_retry':False,'budget_reset':False}
  brief={'method_source':'docs/FILM_SKILL_ADAPTATION_20261010.md; established20expressionstandards','current_change':'小林先确认离开是公司决定，看到申请的个人原因后发现材料写成自己的意愿，将问题转为质问责任归属','zhou_action':'承认是公司决定，把谈话推进到看材料；只用当前原句和一次递材料行动','xiaolin_action':'接收公司立场，看到原因栏后向周姐核实为何写成本人意思；当前只提出问题，未进入后续拒签','observation':'跟随小林理解变化；材料到位和看清提供刺激，重点留在他抬问周姐这一关系上，机位保持同侧空间','cut_condition':'材料已到小林近桌沿、原因已被看清、原反问完整发生并被周姐接收；不因说话者轮换就必切','physical':'一次将纸和笔顺桌面由周姐侧送到小林近桌沿，周姐手收回；小林不碰笔；不得停在桌中间、再推远或第二次推','freedom':'正常普通话交谈，允许动作与不冲突的话重叠；用对对方采取的行动指导表演，不逐肌肉或逐字手势摆演；不把角色冻结','limits':'不新增台词、签字、公司统一格式压力、拒签或离开；不增加第三人或换办公室'}
  asset={'path':video['last_frame'],'sha256':video['last_frame_sha256'],'role':'first_frame','source':'generation_service_original','source_task_id':video['task_id'],'source_video_sha256':video['video_sha256'],'human_approval_required_for_dispatch':True,'state_basis':'previous planned ending; actual pose/content not inspected by assistant'}
  x={'background_full_script':s,'current_interaction':{'source_refs':REFS,'source_catalog':{k:contract.catalog(s)[k] for k in REFS},'end':'未签纸笔留小林近桌沿，小林未碰笔，两人仍坐着；当前质问完整结束，没有后续答复'},'current_initial_state':{'folder':'open','paper':'zhou_side','pen':'zhou_side','paper_signed':False,'xiaolin_pen_touched':False,'zhou_position':'seated','xiaolin_position':'seated','badge':'already_worn'},'reference_fulltext':prior['reference_fulltext'],'film_method_current_brief':brief,'selected_asset_feedback':asset,'scope':scope,'previous_current_coverage':{'source_sha256':previous_handoff['source_sha256'],'source_refs':previous_handoff['sample_source_refs'],'compiled_sha256':previous_handoff['compiled_sha256'],'handoff':str(PREVIOUS/'DELIVERABLE_opening/HANDOFF.json')},'current_authoring_task':'提交当前S04-S07完整新演法，承接起态、因果和同侧空间；不是复述前段或预演后续'}
  for n,v in [('INPUT.json',x),('USER_SCOPE.json',scope),('WRITER_SCHEMA.json',contract.schema(s))]:control.write(ROOT/n,v,True)
  inherited=deepcopy(ledger['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(rows),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(rows),parent_ledger_sha256=control.sha_file(PREVIOUS/'CALL_LEDGER.json'))
  paths=[PREVIOUS/'ANCHOR.json',PREVIOUS/'CALL_LEDGER.json',*[PREVIOUS/q['receipt'] for q in rows],*[PREVIOUS/'DELIVERABLE_opening'/n for n in ['HANDOFF.json','CURRENT_INTERACTION_COMPILED.json','FIRST_SAMPLE.json']],*[SOURCE/n for n in ['FULL_SCRIPT.json','FULL_TEXT_REVIEW.json','CURRENT_BRIEF.json','INDEPENDENT_EDITORIAL_GATE.json','HANDOFF.json']],PROJECT/'docs/FILM_SKILL_ADAPTATION_20261010.md',PROJECT/'docs/CREATIVE_EXPRESSION_STANDARDS_20261007.md',PREVIOUS_MEDIA/'PLAN.json',Path(video['video_path']),Path(video['last_frame'])]
  control.write(ROOT/'ANCHOR.json',{'inherited':inherited,'models':ledger['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in paths},'automatic_retry':False,'budget_reset':False,'previous_mutable_receipt_not_hashed':'explicit human approval can update receipt; immutable provider bytes, task ID and plan bound; video dispatcher must independently validate approval','complete_film_claimed':False},True)
 runtime().prepare();return summary()
def runtime():
 a=control.read(ROOT/'ANCHOR.json'); paths=[Path(__file__).resolve(),PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'src/content_factory/creative_film_material_exchange_v1.py',PROJECT/'src/content_factory/creative_natural_scene_performance_v3.py',PROJECT/'src/content_factory/creative_natural_scene_performance_v2.py',PROJECT/'src/content_factory/creative_natural_scene_performance_v1.py',PROJECT/'src/content_factory/creative_legal_short_director_performance_v1.py',*[ROOT/n for n in ['ANCHOR.json','INPUT.json','USER_SCOPE.json','WRITER_SCHEMA.json']]]+[Path(p) for p in a['parent_files']]
 return control.ContinuationRuntime(PROJECT,ROOT,paths,a['inherited'],a['models'],inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)
def summary():
 s=runtime().summary(); s['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations']; s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s
def accepted(label):
 rt=runtime(); l=control.read(rt.ledger); rt.check(l); rows=[r for r in l['calls'] if r['label']==label]
 if len(rows)!=1:raise ValueError('one original response required, no automatic dispatch')
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('original response invalid or unknown')
 return r
def compiled():return contract.compile_contract(accepted(WRITER_LABEL)['output'],control.read(ROOT/'INPUT.json')['background_full_script'])
def candidate():return contract.pack_first(compiled())
def review_schema():
 text={'type':'string','minLength':1};refs={'type':'array','minItems':1,'items':{'enum':REFS}}
 issue={'type':'object','additionalProperties':False,'required':['problem','required_revision','evidence_refs'],'properties':{'problem':text,'required_revision':text,'evidence_refs':refs}}
 p={'full_source_read':{'const':True},'current_interaction_valid':{'type':'boolean'},'exact_dialogue_and_scope_preserved':{'type':'boolean'},'natural_exchange_assessment':text,'causal_physical_assessment':text,'evidence_refs':refs,'issues':{'type':'array','items':issue},'suggestions':{'type':'array','items':text},'assessment':text}
 return {'type':'object','additionalProperties':False,'required':list(p),'properties':p}
def dispatch(stage):
 prepare();x=control.read(ROOT/'INPUT.json');s=x['background_full_script'];models=control.read(ROOT/'ANCHOR.json')['models']
 if stage=='performance':
  schema=control.read(ROOT/'WRITER_SCHEMA.json');label=WRITER_LABEL;role='writer';cap=2400
  payload={k:deepcopy(x[k]) for k in ['current_interaction','current_initial_state','film_method_current_brief','reference_fulltext','selected_asset_feedback']}
  rule='MiniMax表演导演。提交当前S04-S07完整六字段新演法，依据film_method_current_brief，不交补丁。局部创作只处理周姐承认公司决定并催看材料、一次推纸笔到小林近桌沿、小林看到个人原因后完整发问。原对白由编译器各插一次，演法不引用或改写任何发言；用当前催看/当前读字反问指代，不新增发言。角色目的指向对方，刺激必须先发生再有理解变化；纸到位才能读，压力由失去工作扩展到材料写成自己意愿。一次推到小林近桌沿，周姐手收回，小林不碰笔；动作可与合适对白重叠，不把纸推到桌中间或越推越远。观察主要跟随小林理解与质问，同时保持周姐为明确对手；保持同侧会议室空间，完整质问与受问者接收后才结束。正常普通话、不压语速、不逐肌肉安排、不持续强制凝视或冻结。不得加入后续公司统一格式、拒签、签字和离开。post_pause_seconds自行选择0至1.5秒当前反问后必要空间，不额外加操作。continuous_performance最多320字，两intent各80字，camera160字，delivery100字。只提交工具对象不写分析。'
  def validator(v):
   Draft202012Validator(schema).validate(v);c=contract.compile_contract(v,s);first=contract.pack_first(c)
   if not first['dispatch_ready']:raise ValueError('complete material exchange exceeds native limit; no speed fitting')
   contract.render_prompt(first,s)
   return {'source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'complete_current_interaction':True,'complete_B1':False,'first_source_refs':first['source_refs'],'first_duration_seconds':first['duration_seconds'],'quality_passed':False}
 elif stage=='review':
  c=compiled();first=candidate();schema=review_schema();label=REVIEW_LABEL;role='director';cap=4200
  payload=deepcopy(x);payload.update(full_model_current_performance=accepted(WRITER_LABEL)['output'],compiled_current_interaction=c,actual_first_sample=first,actual_first_prompt=contract.render_prompt(first,s))
  rule='DeepSeek同源完整正文及当前材料回合审查。读取完整380正文、R01、当前S04-S07、新演法、前段已交接覆盖、编译和实际提示词。当前演法只含周姐公司立场与催看、一次推纸笔到小林近桌沿、小林读个人原因发问并未碰笔。核对两原句逐字各一次、起态承接、纸先到位再读/反应、动作对白合理重叠、终点近桌沿、理解变化和观察/切出条件、自然普通话与无提速。必修引用当前S04-S07真实证据；不要求复演S01-S03或提前演B2。肌肉冻结、重复推、先反应后刺激、未来发言或动作是当前必修；角色安静听、不抢话并不当然僵硬。正常语速与排时只是规划，原始尾帧/真实表演未由助手视觉审查，不能声称实际自然度或声画通过。建议与未知放suggestions，不改正文或手工回填演法。只提交完整工具复审。'
  def validator(v):
   Draft202012Validator(schema).validate(v)
   return {'source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'full_source_read':True,'needs_revision':bool(v['issues']) or not v['current_interaction_valid'] or not v['exact_dialogue_and_scope_preserved'],'actual_media_quality_passed':False}
 else:raise ValueError('explicit stage required')
 req={'role':role,'model':models[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},'input_provenance':{'operator_version':'film_material_exchange/v1','source_script_sha256':control.digest(s),'full_script_in_actual_messages':stage=='review','current_actor_request_excludes_future_story':stage=='performance','reference_fulltext_in_actual_messages':True,'reference_fulltext_sha256':control.digest(x['reference_fulltext']),'current_interaction_refs':REFS,'old_acting_prose_in_actual_messages':False,'film_current_method_brief_in_actual_messages':True,'film_current_method_brief_sha256':control.digest(x['film_method_current_brief']),'new_script_adoption_invented':False}}
 control.write(ROOT/'request_previews'/f'{stage}.json',req,True);r=runtime().dispatch(label,req,validator)
 if stage=='performance' and r['status']=='contract_valid':
  control.write(ROOT/'FULL_MODEL_CURRENT_PERFORMANCE.json',r['output'],True);control.write(ROOT/'CURRENT_INTERACTION_COMPILED.json',compiled(),True);control.write(ROOT/'FIRST_SAMPLE.json',candidate(),True);write_text(ROOT/'ACTUAL_FIRST_PROMPT.txt',contract.render_prompt(candidate(),s)+'\n')
 return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':summary()}
def finish():
 x=control.read(ROOT/'INPUT.json');s=x['background_full_script'];d=accepted(WRITER_LABEL);r=accepted(REVIEW_LABEL);c=compiled();first=candidate();gate=control.read(ROOT/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json')
 if r['validation']['needs_revision'] or gate['source_sha256']!=control.digest(s) or gate['compiled_sha256']!=control.digest(c) or not gate['text_sample_qualified'] or gate['unresolved_mandatory_findings']:raise ValueError('current review and independent gate unresolved')
 coverage=x['previous_current_coverage']['source_refs']+first['source_refs']
 if coverage!=[f'B1.S{i:02}' for i in range(1,8)]:raise ValueError('complete B1 text source coverage invalid')
 for n,v in [('FULL_SCRIPT.json',s),('FULL_MODEL_CURRENT_PERFORMANCE.json',d['output']),('CURRENT_INTERACTION_COMPILED.json',c),('FIRST_SAMPLE.json',first),('FULL_SOURCE_REVIEW.json',r['output']),('INDEPENDENT_PERFORMANCE_GATE.json',gate),('ASSET_FEEDBACK.json',x['selected_asset_feedback']),('USER_SCOPE.json',x['scope'])]:control.write(OUT/n,v,True)
 control.write(OUT/'HANDOFF.json',{'status':'reviewed_current_material_exchange','source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'performance_ordinal':d['ordinal'],'review_ordinal':r['ordinal'],'complete_current_interaction':True,'complete_B1':False,'combined_B1_text_source_coverage':coverage,'combined_B1_text_coverage_complete':True,'whole_film_director_or_performance_complete':False,'human_script_adoption_recorded':False,'human_media_quality_approved':False,'sample_source_refs':REFS,'requires_previous_candidate_explicit_human_approval':True,'spend':summary()},True)
 body=['# 材料到位与发现个人原因：完整当前表演','','MiniMax完整新演法及同源全文复审，真实表演待人工审核。只覆盖S04-S07；与前段交接合计覆盖B1文本，不表示B1媒体或整片通过。','']
 for k,v in d['output'].items():body += [k+'：'+str(v),'']
 for row in c['schedule']:body += [row['source_ref']+' '+row['speaker']+'：'+row['original_text'],'']
 write_text(OUT/'CURRENT_EXCHANGE_READABLE.md','\n'.join(body)+'\n');write_text(OUT/'ACTUAL_FIRST_PROMPT.txt',contract.render_prompt(first,s)+'\n')
 return {'handoff':str(OUT/'CURRENT_EXCHANGE_READABLE.md'),'first_duration_seconds':first['duration_seconds'],'combined_B1_text_coverage_complete':True,'spend':summary()}
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','performance','review','finish','status']);a=ap.parse_args();print(json.dumps(prepare() if a.stage=='prepare' else summary() if a.stage=='status' else finish() if a.stage=='finish' else dispatch(a.stage),ensure_ascii=False),flush=True)
