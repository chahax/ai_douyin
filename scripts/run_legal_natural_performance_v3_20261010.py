"""One model-authored complete B1, full-source review, immutable repair scope."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from src.content_factory import creative_natural_scene_performance_v2 as contract
from jsonschema import Draft202012Validator
ROOT=PROJECT/'data/production_revisions/legal_natural_performance_20261010/round_03'
PREVIOUS=PROJECT/'data/production_revisions/legal_natural_performance_20261010/round_02'
PARENT=PROJECT/'data/production_revisions/legal_natural_interaction_20261010/round_05'
SOURCE=PARENT/'REVIEWED_CANDIDATE'
OLD=PROJECT/'data/production_revisions/legal_current_production_20261010/round_10'
VIDEO=PROJECT/'data/video_generation/legal_current_362_20261010/opening_v1'
FEEDBACK=PROJECT/'data/qa/legal_natural_performance_20261010/HUMAN_FEEDBACK_AND_REQUEST_EVIDENCE.json'
OUT=ROOT/'DELIVERABLE_opening'
def write_text(p,s):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists() and p.read_text(encoding='utf-8')!=s:raise ValueError('immutable readable output changed')
 if not p.exists():p.write_text(s,encoding='utf-8')
def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  ledger=control.read(PREVIOUS/'CALL_LEDGER.json')
  if [q['ordinal'] for q in ledger['calls']]!=[383]:raise ValueError('known exact383 rejected receipt required')
  receipts=[control.read(PREVIOUS/q['receipt']) for q in ledger['calls']]
  for row,r in zip(ledger['calls'],receipts):
   if control.sha_file(PREVIOUS/row['receipt'])!=row['receipt_sha256'] or r['status']!='contract_rejected' or type(r['response_metadata']['total_tokens']) is not int:raise ValueError('parent response or usage changed')
  source=control.read(SOURCE/'FULL_SCRIPT.json');gate=control.read(SOURCE/'INDEPENDENT_EDITORIAL_GATE.json')
  if control.digest(source)!=contract.SOURCE_SHA or gate['unresolved_mandatory_findings'] or not gate['text_candidate_qualified']:raise ValueError('current source380 unqualified')
  asset=deepcopy(control.read(OLD/'INPUT.json')['asset_feedback']);asset['new_source_sha256']=contract.SOURCE_SHA
  scope={'schema':'natural_single_repair_scope/v1','user_statements':['别人说很诡异好僵硬的感觉这个你有感觉可以解决一下吗','感觉都有'],'authorization_basis':'当前样片修复请求及AGENTS.md按反馈修复并重生成当前段','original_sample_task_id':'cgt-20261010140842-lzc58','original_sample_video_sha256':control.read(VIDEO/'receipt.json')['video_sha256'],'script_sha256':contract.SOURCE_SHA,'script_ordinal':380,'script_review_ordinal':381,'human_script_adoption_recorded':False,'max_new_submissions':1,'batch_authorized':False,'later_segments_authorized':False,'publish_authorized':False,'automatic_retry':False,'budget_reset':False,'reference_identity_environment_only':True}
  x={'full_current_script':source,'current_brief':control.read(SOURCE/'CURRENT_BRIEF.json'),'reference_fulltext':control.read(PARENT/'INPUT.json')['reference_fulltext'],'human_feedback':control.read(FEEDBACK),'selected_asset_feedback':asset,'source_catalog':contract.catalog(source),'scope':scope,'known_request_risks':['旧首样小林追问被切去下一段，首样只有通知停顿推纸','重复起态、每句半秒和肌肉/不活动指令锁死表演','旧稍快语速，本次正常交谈而不加速压时'],'boundary':'原实际观感来自用户；没有看听媒体，服务端原因未知。380候选未伪记人工采用。'}
  x['failed_contract_identity_only']={'ordinal':383,'native_output_sha256':control.digest(receipts[0]['output']),'old_prose_not_replayed':True};x['rejected_contract_findings']=['数组变item对象：本次模型不再维护数组、源编号或物理状态，固定映射由本地负责','原句不要写进表演说明，原话由编译器插入；不重新说或解释原句','正常交談而不偏快，不让身体定在那里或盯死；不要提前下一单元的话和行动']
  for n,v in [('INPUT.json',x),('USER_SCOPE.json',scope),('WRITER_SCHEMA.json',contract.schema(source))]:control.write(ROOT/n,v,True)
  inherited=deepcopy(ledger['starting_spend']);inherited.update(calls_started=inherited['calls_started']+1,reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+1,parent_ledger_sha256=control.sha_file(PREVIOUS/'CALL_LEDGER.json'))
  paths=[PARENT/'ANCHOR.json',PARENT/'CALL_LEDGER.json',PARENT/'INPUT.json',*[PREVIOUS/q['receipt'] for q in ledger['calls']],PREVIOUS/'ANCHOR.json',PREVIOUS/'CALL_LEDGER.json',PREVIOUS/'INPUT.json',PREVIOUS/'WRITER_SCHEMA.json',PROJECT/'scripts/run_legal_natural_performance_v2_20261010.py',*[SOURCE/n for n in ['FULL_SCRIPT.json','FULL_TEXT_REVIEW.json','CURRENT_BRIEF.json','INDEPENDENT_EDITORIAL_GATE.json','HANDOFF.json']],FEEDBACK,OLD/'INPUT.json',OLD/'USER_SCOPE.json',VIDEO/'PROMPT.txt',VIDEO/'receipt.json']
  control.write(ROOT/'ANCHOR.json',{'schema':'natural_performance_continuation/v3_native_object_transport','inherited':inherited,'models':ledger['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in paths},'automatic_retry':False,'budget_reset':False},True)
 runtime().prepare();return summary()
def runtime():
 a=control.read(ROOT/'ANCHOR.json');own=[Path(__file__).resolve(),PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'src/content_factory/creative_natural_scene_performance_v2.py',PROJECT/'src/content_factory/creative_natural_scene_performance_v1.py',PROJECT/'src/content_factory/creative_legal_short_director_performance_v1.py',*[ROOT/n for n in ['ANCHOR.json','INPUT.json','USER_SCOPE.json','WRITER_SCHEMA.json']]]
 return control.ContinuationRuntime(PROJECT,ROOT,own+[Path(p) for p in a['parent_files']],a['inherited'],a['models'],inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)
def summary():
 s=runtime().summary();s['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s
def accepted(label):
 rt=runtime();l=control.read(rt.ledger);rt.check(l);rows=[q for q in l['calls'] if q['label']==label]
 if len(rows)!=1:raise ValueError('one original response required; no automatic dispatch')
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('original response invalid or unknown')
 return r
def compiled():return contract.compile_contract(accepted('natural_direction_B1_r1')['output'],control.read(ROOT/'INPUT.json')['full_current_script'])
def candidate():return contract.pack_first(compiled())
def review_schema(s):
 text={'type':'string','minLength':1};refs={'type':'array','minItems':1,'items':{'enum':list(contract.catalog(s))+['direction.B1','direction.B2','direction.B3','direction.B4']}}
 issue={'type':'object','additionalProperties':False,'required':['problem','required_revision','evidence_refs'],'properties':{'problem':text,'required_revision':text,'evidence_refs':refs}}
 p={'full_review_complete':{'const':True},'story_invariants_preserved':{'type':'boolean'},'B1_performance_valid':{'type':'boolean'},'natural_exchange_assessment':text,'causal_physical_assessment':text,'sampling_scope_assessment':text,'evidence_refs':refs,'issues':{'type':'array','items':issue},'suggestions':{'type':'array','items':text},'assessment':text}
 return {'type':'object','additionalProperties':False,'required':list(p),'properties':p}
def dispatch(stage):
 prepare();x=control.read(ROOT/'INPUT.json');s=x['full_current_script'];models=control.read(ROOT/'ANCHOR.json')['models']
 if stage=='performance':
  payload=deepcopy(x);schema=control.read(ROOT/'WRITER_SCHEMA.json')
  rule='MiniMax剧情导演。阅读全文与R01，仅借表达机制。只用submit_creative_json提交完整新合同，不改原对白，不交补丁。direction写B1-B4的观察对象/新增信息/切镜理由。opening_exchange只写开夹、公司通知、小林当场反驳；material_offer只写周姐承认公司决定并催看材料、句末把纸笔送到小林手边一次；reading_discovery只写纸到位后小林读原因栏并质疑、不碰笔。这三个固定回合的编号、对白、动作前提、重叠和状态由本地编译维护，不需要你输出数组或来源路径。用言语行动、角色目的、潜台词和对手反馈指导连续表演，让人边听边理解、边说边做相关动作。不要逐个指令控制眉眼嘴唇，不固定眼神/上身/手势；保留真实的人体活动，只有纸笔剧情起终态必须固定。周姐是惯常办手续却需要拿到签字，小林原本以为会解释安排，听到被要求离开才追问；说话是为了对方回应，不朗诵主题。正常日常语速和自然换气，不偏快，不贴尾音抢说。表演字段不能复制原对白，也不加别的实际发言，不提前下一回合对白或未来质问/劝签/出门。单元post_pause_seconds只表示确有必要的回合后短消化，通常0；不是每句话必须停顿。每单元原对白按3.3字/秒规划不压时，全B1可超过15秒。只交Schema对象。'
  label='natural_direction_B1_r1';role='writer';cap=6500
  def validator(v):
   c=contract.compile_contract(v,s);first=contract.pack_first(c)
   if c['needs_revision'] or not first['dispatch_ready']:raise ValueError('intact natural exchange exceeds service limit; never scale')
   contract.render_prompt(first,s)
   return {'complete_B1':True,'source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'first_source_refs':first['source_refs'],'first_duration_seconds':first['duration_seconds'],'whole_film_performance_complete':False,'quality_passed':False}
 elif stage=='review':
  c=compiled();first=candidate();schema=review_schema(s);payload={**deepcopy(x),'full_direction_and_B1_contract':accepted('natural_direction_B1_r1')['output'],'complete_B1_compilation':c,'actual_first_sample':first,'actual_first_sample_prompt':contract.render_prompt(first,s),'review_scope':'全文四拍和粗导演+完整B1+首样；B2-B4实际表演未建，不当本次B1失败，也不声称整片交接完成'}
  rule='DeepSeek全文源核对/自然表演文本审查。阅读全文、粗导演、完整B1和实际首样。核对人物目标/应答变化、正常语速、话中反应、连续活动和完整通知+小林回应。检查开夹通知可并行、纸一次到小林近桌沿、通知先完、到纸再读、S07持续状态、起终态、对白逐字一次/未来隔离。不要求额外催签，不伪称人工采用。后三拍表演未建是范围说明，不是B1必修；真实脸/眼神/动作/声音/口型/观众感觉不能由文字验证。issues只列真实矛盾缺失或语义物理错误，引用当前具体来源；审美增强/实测未知放suggestions。只用submit_creative_json输出完整复审，不修改原稿。'
  label='natural_B1_full_source_review_r1';role='director';cap=5500
  def validator(v):
   Draft202012Validator(schema).validate(v)
   return {'full_review_complete':True,'source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'needs_revision':bool(v['issues']) or not v['story_invariants_preserved'] or not v['B1_performance_valid'],'actual_media_quality_passed':False}
 else:raise ValueError('explicit text stage required')
 req={'role':role,'model':models[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},'input_provenance':{'operator_version':'natural_performance/v3_native_object_transport','source_script_sha256':control.digest(s),'full_script_in_actual_messages':True,'reference_fulltext_in_actual_messages':True,'reference_fulltext_sha256':control.digest(x['reference_fulltext']),'selected_asset_feedback_in_actual_messages':True,'old362_performance_prose_in_actual_messages':False,'rejected383_contract_body_in_actual_messages':False,'native_schema_contains_arrays':False,'current_fact_projection_only':True,'source_context_sha256':control.digest(payload),'human_content_adoption_invented':False}}
 control.write(ROOT/'request_previews'/f'{stage}.json',req,True);r=runtime().dispatch(label,req,validator)
 if stage=='performance' and r['status']=='contract_valid':
  control.write(ROOT/'FULL_DIRECTION_AND_B1_MODEL.json',r['output'],True);control.write(ROOT/'COMPLETE_B1_COMPILED.json',compiled(),True);control.write(ROOT/'FIRST_SAMPLE.json',candidate(),True);write_text(ROOT/'ACTUAL_FIRST_PROMPT.txt',contract.render_prompt(candidate(),s)+'\n')
 return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':summary()}
def finish():
 x=control.read(ROOT/'INPUT.json');s=x['full_current_script'];d=accepted('natural_direction_B1_r1');r=accepted('natural_B1_full_source_review_r1');c=compiled();first=candidate();gate=control.read(ROOT/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json')
 if r['validation']['needs_revision'] or gate.get('compiled_sha256')!=control.digest(c) or gate.get('source_sha256')!=control.digest(s) or gate.get('unresolved_mandatory_findings')!=[] or not gate.get('text_sample_qualified'):raise ValueError('same-source review/editorial gate unresolved')
 for n,v in [('FULL_SCRIPT.json',s),('WHOLE_FILM_DIRECTION.json',d['output']['direction']),('FULL_MODEL_CONTRACT.json',d['output']),('COMPLETE_B1_COMPILED.json',c),('FIRST_SAMPLE.json',first),('FULL_SOURCE_REVIEW.json',r['output']),('INDEPENDENT_PERFORMANCE_GATE.json',gate),('ASSET_FEEDBACK.json',x['selected_asset_feedback']),('USER_SCOPE.json',x['scope'])]:control.write(OUT/n,v,True)
 control.write(OUT/'HANDOFF.json',{'status':'complete_reviewed_B1_ready_for_one_repair_sample','source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'performance_ordinal':d['ordinal'],'review_ordinal':r['ordinal'],'whole_film_performance_complete':False,'unbuilt_beats':['B2','B3','B4'],'human_script_adoption_recorded':False,'human_media_quality_approved':False,'sample_source_refs':first['source_refs'],'spend':summary()},True)
 body=['# 自然表演修复：整片粗导演与完整B1','','380全文保持；完整B1已生成复审，B2–B4实际表演未建。秒数是规划，真实演技口型待人工审核。','']
 for bid,direction in d['output']['direction'].items():body+=['## '+bid,'','观察：'+direction['observation'],'新增信息：'+direction['information_change'],'切镜理由：'+direction['cut_reason'],'']
 sources=contract.catalog(s)
 for u in c['semantic_units']:
  body+=['## '+u['unit_id']+f" / {u['start']:.2f}–{u['end']:.2f}秒",'',u['continuous_performance'],'周姐目的：'+u['zhou_intent'],'小林目的：'+u['xiaolin_intent'],'机位：'+u['camera'],'说话方式：'+u['delivery'],'']
  for ref in u['source_refs']:body+=[ref+' '+sources[ref]['speaker']+'：'+sources[ref]['text']]
  body+=['']
 write_text(OUT/'DIRECTOR_AND_COMPLETE_B1.md','\n'.join(body)+'\n');write_text(OUT/'ACTUAL_FIRST_PROMPT.txt',contract.render_prompt(first,s)+'\n')
 return {'handoff':str(OUT/'DIRECTOR_AND_COMPLETE_B1.md'),'first_duration_seconds':first['duration_seconds'],'first_source_refs':first['source_refs'],'whole_film_performance_complete':False,'spend':summary()}
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','performance','review','finish','status']);a=ap.parse_args()
 print(json.dumps(prepare() if a.stage=='prepare' else summary() if a.stage=='status' else finish() if a.stage=='finish' else dispatch(a.stage),ensure_ascii=False),flush=True)
