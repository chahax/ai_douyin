"""Film-method current opening, complete model new version; frozen prior untouched."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from src.content_factory import creative_natural_scene_performance_v3 as contract
from jsonschema import Draft202012Validator
ROOT=PROJECT/'data/production_revisions/legal_film_director_sample_20261010/round_01'
PREVIOUS=PROJECT/'data/production_revisions/legal_natural_performance_20261010/round_06'
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
  if [q['ordinal'] for q in rows]!=[387,388]:raise ValueError('exact predecessor387/388 required')
  receipts=[control.read(PREVIOUS/q['receipt']) for q in rows]
  if any(r['status']!='contract_valid' or type(r['response_metadata']['total_tokens']) is not int or control.sha_file(PREVIOUS/q['receipt'])!=q['receipt_sha256'] for q,r in zip(rows,receipts)):raise ValueError('predecessor response unknown or changed')
  prior=control.read(PREVIOUS/'INPUT.json');s=control.read(SOURCE/'FULL_SCRIPT.json')
  if control.digest(s)!=contract.SOURCE_SHA:raise ValueError('exact380 source required')
  old_plan=control.read(PROJECT/'data/video_generation/legal_natural_performance_20261010/opening_v1/PLAN.json')
  old_receipt=control.read(PROJECT/'data/video_generation/legal_natural_performance_20261010/opening_v1/receipt.json')
  if old_receipt['task_id']!='cgt-20261010161836-wb6zj' or old_receipt['technical_status']!='succeeded':raise ValueError('exact prior sample required')
  scope={'schema':'film_single_opening_scope/v1','user_statements':['交接下然后用新的生成一段刚刚的视频'],'authorization_basis':'explicit one current opening regeneration with film directing methods','original_sample_task_id':old_receipt['task_id'],'original_sample_video_sha256':old_receipt['video_sha256'],'script_sha256':contract.SOURCE_SHA,'script_ordinal':380,'script_review_ordinal':381,'human_script_adoption_recorded':False,'max_new_submissions':1,'batch_authorized':False,'later_segments_authorized':False,'publish_authorized':False,'automatic_retry':False,'budget_reset':False,'reference_identity_environment_only':True,'unapproved_prior_tail_used':False}
  brief={'method_source':'docs/FILM_SKILL_ADAPTATION_20261010.md; comfy-director; prior20expressionstandards',
   'current_dramatic_change':'周姐试图让小林接下当面通知；小林当场反问，将单向宣布转成要求解释。只表达本次变化。',
   'zhou_action':'向小林传达公司决定并争取他接受这次通知；面向真实的对手，不朗读文件',
   'xiaolin_action':'听清离开是公司决定后，用当前原反问要求周姐解释；本人没有提出辞职',
   'camera_observer':'以小林接收决定并反问为重点，周姐仍是明确受问对象；同侧空间和双方位置可理解',
   'cut_condition':'当前反问完整发生，给受问者接收到这一问的短空间才结束；镜头变化须服务理解变化，可选择不切镜',
   'acting_freedom':'正常普通话交谈，开夹与通知自然重叠；演法不用对白引语，不逐眉眼肩膝摆动作，不持续强制凝视',
   'visual_continuity':'沿用同一人物、服装和会议室参考，只按新起态；不另造光源或戏剧性换色，不额外改变道具位置'}
  x={'background_full_script':s,'current_brief':control.read(SOURCE/'CURRENT_BRIEF.json'),'current_interaction':{'source_refs':REFS,'source_catalog':{k:contract.catalog(s)[k] for k in REFS},'end':'小林当前反问完整说完，周姐只接收，不新增发言或操作；纸笔仍在周姐一侧。'},'reference_fulltext':prior['reference_fulltext'],'human_feedback':prior['human_feedback'],'selected_asset_feedback':prior['selected_asset_feedback'],'scope':scope,'film_method_current_brief':brief,'previous_sample_identity':{'task_id':old_receipt['task_id'],'video_sha256':old_receipt['video_sha256'],'previous_prose_not_replayed':True},'current_authoring_task':'模型提交当前S01-S03完整新导演表演；全片导演不在本次交付范围'}
  wire=contract.schema(s)
  for field,limit in [('continuous_performance',200),('zhou_intent',80),('xiaolin_intent',80),('camera',160),('delivery',100)]:wire['properties'][field]['maxLength']=limit
  for n,v in [('INPUT.json',x),('USER_SCOPE.json',scope),('WRITER_SCHEMA.json',wire)]:control.write(ROOT/n,v,True)
  inherited=deepcopy(ledger['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(rows),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(rows),parent_ledger_sha256=control.sha_file(PREVIOUS/'CALL_LEDGER.json'))
  paths=[PREVIOUS/'ANCHOR.json',PREVIOUS/'CALL_LEDGER.json',PREVIOUS/'INPUT.json',PREVIOUS/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json',*[PREVIOUS/q['receipt'] for q in rows],PROJECT/'scripts/run_legal_natural_performance_v6_20261010.py',*[SOURCE/n for n in ['FULL_SCRIPT.json','FULL_TEXT_REVIEW.json','CURRENT_BRIEF.json','INDEPENDENT_EDITORIAL_GATE.json','HANDOFF.json']],PROJECT/'docs/FILM_SKILL_ADAPTATION_20261010.md',PROJECT/'docs/CREATIVE_EXPRESSION_STANDARDS_20261007.md',Path('C:/Users/c/.codex/skills/comfy-director/SKILL.md'),PROJECT/'data/video_generation/legal_natural_performance_20261010/opening_v1/PLAN.json',PROJECT/'data/video_generation/legal_natural_performance_20261010/opening_v1/receipt.json']
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
  schema=control.read(ROOT/'WRITER_SCHEMA.json');label='natural_opening_exchange_r1';role='writer';cap=2400
  payload={'current_interaction':deepcopy(x['current_interaction']),'current_initial_state':{'scene':'同一小会议室，女人事周姐与男员工小林已经隔桌坐着，工牌已戴小林胸前','folder':'合着，在周姐侧','paper_pen':'未签，留周姐侧'},'film_method_current_brief':x['film_method_current_brief'],'reference_fulltext':x['reference_fulltext'],'reference_use':'借实际刺激使听者改变理解、关系变化引导观察的表达机制，不照搬剧情','human_feedback':['按本次电影方法加强人物与画面，交接后重生成同一开场','正常说话，听与答像真实互动，不靠加速压时'],'selected_reference_identity':{'path':x['selected_asset_feedback']['path'],'sha256':x['selected_asset_feedback']['sha256'],'scope':'仅身份服装及同一会议室参考；按当前起态'}}
  if list(payload['current_interaction']['source_catalog'])!=REFS or 'background_full_script' in payload or 'current_brief' in payload:raise ValueError('current-only authoring projection failed')
  rule='MiniMax表演导演。根据当前原文和film_method_current_brief提交完整六字段新稿，原对白固定由编译器插入。只写周姐开夹并通知、小林听清后完整反问这一个回合。角色意图写要对对方采取什么行动，连续演法体现刺激导致理解与交往变化；摄影说明主要观察谁、为何，以及完整反问和受问者接收到反问之后才结束的条件，机位保持同侧空间。不能在演法引用或改写任何发言，不加发言；用当前通知/当前反问指代。人物正常交谈，开夹可与通知重叠，给演员自然活动，不逐肌肉安排，不僵死或持续凝视，不提速，不预演后续故事。纸笔始终周姐侧。光线和空间遵循已选参考，不重新造景。post_pause_seconds为本次反问后的必要短承载，0到1.5秒中自行选择；不生成新回应或操作。continuous_performance最多200字，两个intent各80字，camera160字，delivery100字。只提交完整工具对象，不写分析。'
  def validator(v):
   Draft202012Validator(schema).validate(v);c=contract.compile_contract(v,s);first=contract.pack_first(c)
   if not first['dispatch_ready']:raise ValueError('complete current exchange exceeds native limit')
   contract.render_prompt(first,s)
   return {'source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'complete_current_interaction':True,'complete_B1':False,'first_source_refs':first['source_refs'],'first_duration_seconds':first['duration_seconds'],'quality_passed':False}
 elif stage=='review':
  c=compiled();first=candidate();schema=review_schema();label='natural_opening_full_source_review_r1';role='director';cap=4200
  payload.update(full_model_current_performance=accepted('natural_opening_exchange_r1')['output'],compiled_current_interaction=c,actual_first_sample=first,actual_first_prompt=contract.render_prompt(first,s))
  rule='DeepSeek完整背景阅读及本次电影方法当前交互全文审查。阅读完整原稿/R01/当前3步和实际原生模型表演、编译与提示词，核对只含开夹/公司通知/小林没提辞职回应；纸笔仍周姐側未送，未演催看、读字或后续拒签。检查原对白逐字各一次、当前信息时序、完整通知与回应、人物目标/对手反馈、自然连续活动和正常语速；每条必修引用当前S01-S03，不泛泛要求后续戏提前发生。不要求单样完成整B1或整片，这是明确当前scope，不能声称全部导演已建。核对本次角色行动目的、策略回应、主要观察与切出条件是否具体；缺失当前方法要求、肌肉僵死、机械卡住、不许活动、未来发言或动作是本次必修；真实脸/眼神/身体/声音/口型改善无法由文字确认。建议与实际未知放suggestions，issues只放当前真实不合格，不能改正文。只用submit_creative_json交完整复审。'
  def validator(v):
   Draft202012Validator(schema).validate(v)
   return {'source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'full_source_read':True,'needs_revision':bool(v['issues']) or not v['current_interaction_valid'] or not v['exact_dialogue_and_scope_preserved'],'actual_media_quality_passed':False}
 else:raise ValueError('explicit stage required')
 req={'role':role,'model':models[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},'input_provenance':{'operator_version':'film_current_interaction/v1','source_script_sha256':control.digest(s),'full_script_in_actual_messages':stage=='review','current_actor_request_excludes_future_story':stage=='performance','reference_fulltext_in_actual_messages':True,'reference_fulltext_sha256':control.digest(x['reference_fulltext']),'current_interaction_refs':REFS,'old_global_acting_prose_in_actual_messages':False,'prior_acting_prose_in_actual_messages':False,'film_current_method_brief_in_actual_messages':True,'film_current_method_brief_sha256':control.digest(x['film_method_current_brief']),'new_script_adoption_invented':False}}
 control.write(ROOT/'request_previews'/f'{stage}.json',req,True);r=runtime().dispatch(label,req,validator)
 if stage=='performance' and r['status']=='contract_valid':
  control.write(ROOT/'FULL_MODEL_CURRENT_PERFORMANCE.json',r['output'],True);control.write(ROOT/'CURRENT_INTERACTION_COMPILED.json',compiled(),True);control.write(ROOT/'FIRST_SAMPLE.json',candidate(),True);write_text(ROOT/'ACTUAL_FIRST_PROMPT.txt',contract.render_prompt(candidate(),s)+'\n')
 return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':summary()}
def finish():
 x=control.read(ROOT/'INPUT.json');s=x['background_full_script'];d=accepted('natural_opening_exchange_r1');r=accepted('natural_opening_full_source_review_r1');c=compiled();first=candidate();gate=control.read(ROOT/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json')
 if r['validation']['needs_revision'] or gate['source_sha256']!=control.digest(s) or gate['compiled_sha256']!=control.digest(c) or not gate['text_sample_qualified'] or gate['unresolved_mandatory_findings']:raise ValueError('current full-source review and independent gate unresolved')
 for n,v in [('FULL_SCRIPT.json',s),('FULL_MODEL_CURRENT_PERFORMANCE.json',d['output']),('CURRENT_INTERACTION_COMPILED.json',c),('FIRST_SAMPLE.json',first),('FULL_SOURCE_REVIEW.json',r['output']),('INDEPENDENT_PERFORMANCE_GATE.json',gate),('ASSET_FEEDBACK.json',x['selected_asset_feedback']),('USER_SCOPE.json',x['scope'])]:control.write(OUT/n,v,True)
 control.write(OUT/'HANDOFF.json',{'status':'reviewed_film_method_current_exchange_for_one_replacement_sample','source_sha256':control.digest(s),'compiled_sha256':control.digest(c),'performance_ordinal':d['ordinal'],'review_ordinal':r['ordinal'],'complete_B1':False,'whole_film_director_or_performance_complete':False,'human_script_adoption_recorded':False,'human_media_quality_approved':False,'sample_source_refs':REFS,'spend':summary()},True)
 body=['# 通知与当场回应：完整当前表演','','本次新电影方法只交接当前开场；完整B1/全片导演未交付。新演法由MiniMax完整生成，真实表演与口型待人工审核。','']
 for k,v in d['output'].items():body += [k+'：'+str(v),'']
 for row in c['schedule']:body += [row['source_ref']+' '+row['speaker']+'：'+row['original_text'],'']
 write_text(OUT/'CURRENT_EXCHANGE_READABLE.md','\n'.join(body)+'\n');write_text(OUT/'ACTUAL_FIRST_PROMPT.txt',contract.render_prompt(first,s)+'\n')
 return {'handoff':str(OUT/'CURRENT_EXCHANGE_READABLE.md'),'first_duration_seconds':first['duration_seconds'],'complete_B1':False,'spend':summary()}
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','performance','review','finish','status']);a=ap.parse_args();print(json.dumps(prepare() if a.stage=='prepare' else summary() if a.stage=='status' else finish() if a.stage=='finish' else dispatch(a.stage),ensure_ascii=False),flush=True)
