"""Current full source -> whole direction -> B1 acting -> reviewed first sample.
Old batch authorizations, source records and failure budgets remain unchanged.
"""
from pathlib import Path
from copy import deepcopy
import argparse, json, math, re, subprocess, sys
from datetime import datetime, timezone
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_json_document_transport_v1 as document_transport
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from src.content_factory import creative_legal_current_direction_performance_v3 as contract
from src.content_factory.creative_stage_contracts import persist,digest
from src.content_factory.creative_legal_short_seedance_execution_v1 import sha,reference,read,reserve_media_attempt
from src.content_factory.seedance_client import SeedanceClient,SeedanceConfig
from src.content_factory.media_review_policy import mark_saved_candidate
ROOT=PROJECT/'data/production_revisions/legal_current_production_20261010/round_06'
TEXT=PROJECT/'data/production_revisions/legal_dialogue_refinement_20261009/round_20'
OUT=PROJECT/'data/video_generation/legal_current_362_20261010/opening_v1'
LOGICAL='legal_trend_text_trial_20261008_adopted_r8'
MODEL='doubao-seedance-2-0-mini-260615'
PARENT=PROJECT/'data/production_revisions/legal_current_production_20261010/round_05'
SID='CURRENT362_OPEN01'
SCOPE={'schema':'current_legal_sample_scope/v1','source':'current_conversation_human_message','user_statement':'生成视频看看',
 'script_sha256':'c8d00326ae50379eb7fa978d65d7e2b4c06b6ff786aadc1704aa74226ab1a1ac','draft_ordinal':362,'text_review_ordinal':364,
 'interpretation':'try the complete current script by producing one first sample segment; retain default human approval before tail continuation',
 'max_new_video_submissions':1,'automatic_retry':False,'publishing_authorized':False,'batch_continuation_authorized':False,
 'human_creative_quality_approved':False,'budget_reset':False,'no_subtitles':True,'max_film_seconds':180}

def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  ledger=control.read(PARENT/'CALL_LEDGER.json');rows=ledger['calls']
  if [r['ordinal'] for r in rows]!=[368]:raise ValueError('exact known368 missing-tool interface response required')
  receipts=[]
  for row in rows:
   p=PARENT/row['receipt']
   if sha(p)!=row['receipt_sha256']:raise ValueError('parent receipt changed')
   r=control.read(p)
   if r['status'] not in ['contract_valid','contract_rejected','interface_rejected'] or type(r['response_metadata']['total_tokens']) is not int:raise ValueError('unknown parent result/usage')
   if r['status']=='interface_rejected' and r.get('failure',{}).get('response_received') is not True:raise ValueError('unknown interface outcome cannot continue')
   receipts.append(r)
  s=control.read(TEXT/'DELIVERABLE/FULL_SCRIPT.json');g=control.read(TEXT/'TEXT_EDITORIAL_GATE.json')
  if digest(s)!=SCOPE['script_sha256'] or g['script_sha256']!=digest(s) or g['unresolved_mandatory_findings']:raise ValueError('source editorial issues unresolved')
  text_review=control.read(TEXT/'call_364_craft_review_r20.json')
  if text_review['validation']['needs_revision'] or not text_review['validation']['full_review_complete']:raise ValueError('whole text not ready')
  old=control.read(PROJECT/'data/production_revisions/legal_short_remake_20261009/round_04/INPUT.json')
  asset=deepcopy(old['asset_feedback'])
  if sha(asset['path'])!=asset['sha256']:raise ValueError('approved native asset changed')
  asset['archived_source_prompt_sha256']=digest(asset.pop('source_prompt'));asset['new_source_sha256']=digest(s);asset['prior_scope_is_not_new_batch_authorization']=True
  # Only immutable source metadata is used by the text model; no media inspection.
  asset['source_prompt_metadata_used_for_identity_and_space_only']=True
  asset['director_visual_inspection_claimed']=False
  payload={'previous_complete_director':control.read(PARENT/'ADOPTED_DIRECTION_RAW.json'),'previous_complete_B1_performance':control.read(PARENT/'INPUT.json')['previous_complete_B1_performance'],'previous_interface_failure':receipts[0]['failure'],'B1_repair_findings':['B1_S05.active_seconds=2.5低于完整原句15个发音字/5=3.0秒','导演B1.S01.before要求1秒，但367给0，当前按约定满足','before必须无声，不写发出第一音；S02说完后的1.5秒反应只after一次，不在active重复','每项演法只描述当前刺激与可见反应，避免五指准备、工牌晃动等无叙事操作；不重复初态和协议文字'],'director_repair_findings':['366全部创意原样保留；旧v2每拍最多3个窗口并非叙事需求，B4实际4个窗口需保留。当前总11个仍满足原总12限制'], 'full_script':s,'full_text_review':control.read(TEXT/'DELIVERABLE/FULL_TEXT_REVIEW.json'),
   'reference_fulltext':old['reference_fulltext'],'writer_expression_criteria':old['writer_expression_criteria'],
   'legal_context':control.read(TEXT/'LEGAL_CONTEXT.json'),'current_human_video_instruction':SCOPE,
   'asset_feedback':asset,'source_state_config':contract.CURRENT_SOURCE_CONFIG,
   'production_priorities':['公司决定离开在开场完整明说，听者反应可读','看见个人原因后由不信转委屈急切，周姐有公司立场及私情请求两级阻力','语速自然稍快，约4.5到5个发音字每秒，不为凑时长停顿','纸笔一次从周姐侧推到小林近桌沿，不能越推越远或重复推','只有两人，同会议室，无字幕；最后周姐独自离开、小林留坐；争议未解决']}
  control.write(ROOT/'INPUT.json',payload,True);control.write(ROOT/'USER_SCOPE.json',SCOPE,True)
  inherited=deepcopy(ledger['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(rows),
   reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),
   calls_with_known_usage=inherited['calls_with_known_usage']+len(rows),parent_ledger_sha256=sha(PARENT/'CALL_LEDGER.json'))
  files=[TEXT/'CALL_LEDGER.json',TEXT/'AUTHORIZATION.json',TEXT/'ANCHOR.json',TEXT/'TEXT_EDITORIAL_GATE.json',
   TEXT/'DELIVERABLE/FULL_SCRIPT.json',TEXT/'DELIVERABLE/RAW_MODEL_SCRIPT.json',TEXT/'DELIVERABLE/FULL_TEXT_REVIEW.json',TEXT/'DELIVERABLE/HANDOFF.json',TEXT/'LEGAL_CONTEXT.json',
   TEXT/'call_364_craft_review_r20.json',PARENT/rows[0]['receipt'],PARENT/'CALL_LEDGER.json',PARENT/'ANCHOR.json',PARENT/'AUTHORIZATION.json',PROJECT/'scripts/run_legal_current_production_v5_20261010.py',PROJECT/'src/content_factory/creative_legal_current_direction_performance_v3.py',PARENT/'ADOPTED_DIRECTION_RAW.json',PARENT/'DIRECTOR_SOURCE_QUALIFICATION.json',PROJECT/'data/production_revisions/legal_short_remake_20261009/round_04/INPUT.json',Path(asset['path']),Path(asset['path']).parent/'receipt.human_review.json']
  contract.expand_direction(control.read(PARENT/'ADOPTED_DIRECTION_RAW.json'),s)
  control.write(ROOT/'ADOPTED_DIRECTION_RAW.json',control.read(PARENT/'ADOPTED_DIRECTION_RAW.json'),True)
  control.write(ROOT/'DIRECTOR_SOURCE_QUALIFICATION.json',control.read(PARENT/'DIRECTOR_SOURCE_QUALIFICATION.json'),True)
  control.write(ROOT/'ANCHOR.json',{'schema':'current_legal_production/v1','inherited':inherited,'models':ledger['model_configs'],
   'parent_files':{str(p):sha(p) for p in files},'automatic_retry':False,'budget_reset':False,'old_frozen_governance_unchanged':True,
   'parent_full_integrity_check_completed_this_turn':True,'parent_verified_effective_calls':368,'parent_verified_effective_reported_tokens':6214679,'previous_complete_planning_repair_source':366,'mechanical_source_assignment_compiled_locally':True},True)
 runtime().prepare()
 return summary()

def runtime():
 a=control.read(ROOT/'ANCHOR.json')
 own=[Path(__file__).resolve(),PROJECT/'scripts/creative_json_document_transport_v1.py',PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'src/content_factory/creative_legal_current_direction_performance_v3.py',PROJECT/'src/content_factory/creative_legal_current_direction_performance_v1.py',ROOT/'ADOPTED_DIRECTION_RAW.json',ROOT/'DIRECTOR_SOURCE_QUALIFICATION.json',ROOT/'INPUT.json',ROOT/'USER_SCOPE.json',ROOT/'ANCHOR.json']
 return control.ContinuationRuntime(PROJECT,ROOT,own+[Path(p) for p in a['parent_files']],a['inherited'],a['models'],
  inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)

def summary():
 s=runtime().summary();s['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s

def accepted(label):
 if label=='director_r1':
  rt=runtime();rt.check(control.read(rt.ledger));return {'ordinal':366,'output':control.read(ROOT/'ADOPTED_DIRECTION_RAW.json'),'status':'original_response_requalified_unchanged'}
 rt=runtime();l=control.read(rt.ledger);rt.check(l);rows=[c for c in l['calls'] if c['label']==label]
 if len(rows)!=1:raise ValueError('exact stage receipt required')
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('failed/unknown stage: inspect original receipt, no automatic replay')
 if r['request'].get('output_transport'):
  decoded=document_transport.extract_original_inner(r['response_text'],r['request']['inner_document_schema'])
  if decoded['document']!=r['document_output']:raise ValueError('inner raw document differs')
  r=deepcopy(r);r['raw_tool_output']=r['output'];r['output']=deepcopy(r['document_output'])
 return r

def direction():return contract.expand_direction(accepted('director_r1')['output'],control.read(ROOT/'INPUT.json')['full_script'])
def performance():return contract.expand_performance(accepted('performance_B1_r1')['output'],control.read(ROOT/'INPUT.json')['full_script'],'B1')
def compiled():return contract.compile_prefix(control.read(ROOT/'INPUT.json')['full_script'],direction(),[performance()])

def review_schema(context):
 cat=contract.evidence_catalog(context);ref=contract.arr({'enum':list(cat)},1,6)
 return contract.obj({'source_preserved':{'type':'boolean'},'whole_direction_analysis':contract.text(),'opening_timing_and_reactions':contract.text(),
  'opening_evidence_refs':ref,'remaining_performance_is_unbuilt':{'const':True},
  'issues':contract.arr(contract.obj({'problem':contract.text(),'required_revision':contract.text(),'evidence_refs':ref})),
  'suggestions':contract.arr(contract.text()),'assessment':contract.text()})

def validate_review(v,ctx):
 from jsonschema import Draft202012Validator
 Draft202012Validator(review_schema(ctx)).validate(v)
 cat=contract.evidence_catalog(ctx);e=[cat[i] for i in v['opening_evidence_refs']]
 if not any(x['path'].startswith('script.beats.0.') for x in e) or not any(x['path'].startswith('compiled.schedule.') for x in e):raise ValueError('must cite current source and actual opening timing')
 return {'full_current_script_and_direction_read':True,'actual_performance_review_scope':['B1'],'unbuilt_beats':['B2','B3','B4'],'needs_revision':bool(v['issues']) or not v['source_preserved'],'creative_quality_passed':False}

def dispatch(stage):
 prepare();x=control.read(ROOT/'INPUT.json');s=x['full_script'];models=control.read(ROOT/'ANCHOR.json')['models']
 if stage=='director':raise ValueError('complete366 response reused unchanged; no new director submit')
 if False:
  schema=contract.direction_schema(s);payload={'read_only_complete_source':x,'source_ref_catalog':contract.catalog(s),'task':'生成完整整片导演安排，四拍各一个镜头。每镜一套连续构图，人物两张脸及有关桌面可读，不添加景别切换。根B1到B4各完整拍对象，机械步骤归属由本地推导，原稿不改。reaction_windows每拍至少一项，只给关键刺激后的必要反应下限。仅确定观察、新增信息、刺激反应、切镜理由和粗状态，不细排秒数。'}
  rule='MiniMax整片导演，只通过submit_creative_json提交完整文档。当前正文19步11句权威，原参考借表达机制。根B1/B2/B3/B4键只填写创作观察字段与reaction_windows；shot_id/beat_id/source_refs/initial_state由本地编译，不在你的输出中。修复previous_complete_director列出的三个缺陷，提交完整整片新安排。纸笔到小林近桌沿的源动作不改。粗状态由source_state_config本地推导。每拍一个连续机位，两张脸都可见；开场小林用侧前脸，不用背身；B4室内固定角度可见纸笔桌面、门和小林留坐，禁止镜内切换。拍间切镜必须新增观察理由，不让台词外的操作填时。重点普通话自然稍快和听者脸的刺激后变化；反应下限0.5到1.5秒即可，关键可2秒。正文和已选人物环境不重写，不加入第三人。资产图实际给视频模型，文本阶段只有元数据，不声称看过像素。'
  validator=lambda v:contract.validate_direction(contract.expand_direction(v,s),s);label='director_r1';role='writer';cap=6000
 elif stage=='B1':
  acting_source={k:deepcopy(x[k]) for k in ['full_script','reference_fulltext','writer_expression_criteria','current_human_video_instruction','asset_feedback','production_priorities']}
  acting_source['previous_complete_B1_performance']=x['previous_complete_B1_performance'];acting_source['B1_repair_findings']=x['B1_repair_findings']
  d=direction();schema=contract.performance_schema(s,'B1');payload={'read_only_complete_source':acting_source,'whole_direction':d,'current_beat':s['beats'][0],'source_ref_catalog':{k:v for k,v in contract.catalog(s).items() if k.startswith('B1.')},'required_timing_bounds':{c_key:{'minimum_active_seconds':contract.spoken_seconds(src) if src['kind']=='dialogue' else 0,'reaction_windows':[w for w in d['reaction_windows'] if w['source_ref']==ref]} for ref,src in contract.catalog(s).items() if ref.startswith('B1.') for c_key in [contract.key(ref)]},'task':'完整返修第一拍，上一整拍367不可手动修改，提交完整新五源演法与秒数。B1_S05活跃至少3秒；B1_S01 before至少1秒。每项只写20到80字可见表演，不堆协议文字，不复述对白。前窗不发音，中窗说完整句、包含句中听者变化，后窗才演话音落地的反应；S02话后1.5秒只after一次。S01是初态建立约0.5-1秒，不演旧片入座摘戴工牌；S02约9-10秒说完整第一句，听者随工作到此为止从正常等待变僵住，留1秒左右反应；S03纸笔2秒左右一次推到近手沿，到位停手。希望前三个完整源步骤合计<=15秒做首段，但不要挤压对白或反应；后两句顺序下一段。自然稍快普通话约4.5-5字/秒。全B1各源before/active/after细排；无多余手部/道具操作、无新增或重复原动作。'}
  rule='MiniMax局部表演导演，只提交submit_creative_json完整当前拍。每个B1_S01键仅6项时间和演法；秒数可小数，before/after0秒写不占额外时间。人物动作只能当前action的active演一次，前后仅眼神表情呼吸，台词来源由本地编译器插一次。不要复述台词，不加别的对白，描述两人声音情绪和听者反应而不朗读解说。当前句完整说完，必须<=5个发音字/秒，稍快而自然，不拉长无意义停顿。单源总时长<=15秒。先建立起态再明确公司决定，受压反应可读，再推纸一次到手一掌宽；小林不碰笔不签字，周姐不反复挪纸。不得预演看个人原因/拒签/收夹/出门。'
  validator=lambda v:{'compiled_prefix':contract.compile_prefix(s,d,[contract.expand_performance(v,s,'B1')]),'creative_quality_passed':False};label='performance_B1_r1';role='writer';cap=5000
 elif stage=='review':
  ctx={'script':s,'director':direction(),'compiled':compiled()};schema=review_schema(ctx);payload={'read_only_complete_source':x,'current_production':ctx,'evidence_catalog':[{'id':k,**v} for k,v in contract.evidence_catalog(ctx).items()],'review_scope':'读完整当前正文和整片导演，实际逐步秒数仅B1。不能声称B2-B4表演已建。检查当前第一拍对白/动作顺序、语速和反应下限、纸笔到小林手边，不新增动作。对比完整source_preserved，不让导演改变拒签收束。只真正矛盾列issues，审美增强suggestions。'}
  rule='DeepSeek文本审查：只提交submit_creative_json。审查完整当前正文和全片方向；当前实际表演仅B1，剩余三拍未建，明确remaining_performance_is_unbuilt=true。引用opening_evidence_refs须同时有script.beats.0与compiled.schedule来源；不检查视频像素，不假定秒数实测。旧314/316描述不得套进当前362；纸笔必须一次到小林近桌沿，起态工牌脖子。零issues不等于人审质量通过。'
  validator=lambda v:validate_review(v,ctx);label='production_opening_review_r1';role='director';cap=6500
 else:raise ValueError('explicit stage required')
 req={'role':role,'model':models[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],
  'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},
  'input_provenance':{'script_sha256':digest(s),'reference_fulltext_sha256':digest(x['reference_fulltext']),'reference_fulltext_in_actual_messages':True,'asset_sha256':x['asset_feedback']['sha256'],'operator_version':contract.VERSION,'server_strict_generation_claimed':False}}
 if stage=='B1':
  req['messages']=document_transport.build_messages(req['messages'],schema);req['structured_schema']=document_transport.build_envelope_schema();req['output_transport']=document_transport.VERSION;req['inner_document_schema']=schema
  req['input_provenance']['role_context_projection']='full script and full R01 preserved; unrelated full legal packet and duplicate old complete director omitted from actor request; archive unchanged'
 control.write(ROOT/'request_previews'/f'{label}.json',req,True)
 r=runtime().dispatch(label,req,validator)
 control.write(ROOT/'STATUS.json',{'stage':stage,'ordinal':r['ordinal'],'status':r['status'],'spend':summary(),'new_media_calls':0,'quality_passed':False})
 return {'ordinal':r['ordinal'],'status':r['status'],'validation_error':r.get('validation_error'),'failure':r.get('failure'),'spend':summary()}

def finish():
 x=control.read(ROOT/'INPUT.json');s=x['full_script'];d=direction();p=performance();c=compiled();r=accepted('production_opening_review_r1')
 if r['validation']['needs_revision']:raise ValueError('current opening production review unresolved')
 folder=ROOT/'DELIVERABLE_opening'
 for name,val in [('FULL_SCRIPT.json',s),('WHOLE_FILM_DIRECTION.json',d),('B1_PERFORMANCE.json',p),('COMPILED_PREFIX.json',c),('OPENING_PRODUCTION_REVIEW.json',r['output']),('ASSET_FEEDBACK.json',x['asset_feedback']),('USER_SCOPE.json',SCOPE)]:control.write(folder/name,val,True)
 rows=[];seconds=0
 for row in c['schedule']:
  length=row['end']-row['start']
  if rows and seconds+length>15+1e-6:break
  rows.append(deepcopy(row));seconds+=length
 if not any(row['source_kind']=='dialogue' for row in rows):raise ValueError('first sample must contain opening notice; avoid a silent staging-only sample')
 duration=max(4,math.ceil(round(seconds,6)));shot=next(q for q in d['shots'] if q['shot_id']==rows[0]['shot_id'])
 if duration>15:raise ValueError('source step exceeds service limit')
 definition={'segment_id':SID,'source_refs':[r['source_ref'] for r in rows],'rows':rows,'framing':shot['framing'],'source_seconds':round(seconds,6),'duration_seconds':duration,'time_scale':duration/seconds}
 prompt=render_prompt(definition)
 control.write(folder/'OPENING_SEGMENT.json',definition,True)
 control.write(folder/'PRODUCTION_HANDOFF.json',{'status':'whole_direction_and_reviewed_B1_ready','script_sha256':digest(s),'compiled_sha256':digest(c),'review_ordinal':r['ordinal'],'complete_film_performance':False,'unbuilt_beats':['B2','B3','B4'],'sample_source_refs':definition['source_refs'],'spend':summary(),'human_quality_approved':False},True)
 body=['# 当前稿362：整片导演与第一拍实际表演','',d['emotional_arc'],'',d['causal_chain'],'',d['ending_intent'],'','完整导演已建；实际表演只建第一拍，后三拍待续。秒数是规划，不是实际音画通过。','']
 for shot in d['shots']:body+=['## '+shot['shot_id']+' / '+shot['beat_id'],'','新增信息：'+shot['new_information'],'观察：'+shot['observation_target'],'刺激与反应：'+shot['stimulus_and_response'],'构图：'+shot['framing'],'切镜理由：'+shot['cut_reason'],'']
 for row in c['schedule']:body += ['## '+row['source_ref']+f" {row['start']:.2f}–{row['end']:.2f}秒",'',row['original_text'],f"前 {row['active_start']-row['start']:.2f}s："+row['before_performance'],f"中 {row['active_end']-row['active_start']:.2f}s："+row['active_performance'],f"后 {row['end']-row['active_end']:.2f}s："+row['after_performance'],'']
 write_text_new(folder/'DIRECTOR_AND_B1.md','\n'.join(body));write_text_new(folder/'ACTUAL_OPENING_PROMPT.md','# 当前首段实际提示词\n\n'+prompt+'\n')
 return {'delivery':str(folder),'duration_seconds':duration,'source_refs':definition['source_refs'],'full_performance_complete':False,'spend':summary()}

def write_text_new(path,body):
 path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists() and path.read_text(encoding='utf-8')!=body:raise ValueError('immutable readable artifact changed')
 if not path.exists():path.write_text(body,encoding='utf-8')

def render_prompt(d):
 lines=[f"{d['duration_seconds']}秒竖屏9:16写实职场剧情。同一小会议室，一个连续镜头。",
  '图片1参考同一位男员工小林、同一位女人事周姐的脸、年龄、发型和衣服，以及深色会议桌、玻璃隔断和门；只有这两个人。',
  '参考图只用于身份环境，按新起态重新构图：两人已经面对面坐好，工牌已戴在小林胸前，文件夹、未签的自愿离职申请和笔都在周姐面前。不要演摘戴工牌或入座。',
  '构图：'+d['framing'],
  '清晰自然普通话，语速稍快而有情绪。只有标注的说话人开口，对方倾听不跟读。动作说明不朗读，无旁白、配乐、字幕、标题和姓名标签。']
 clock=0
 for row in d['rows']:
  for phase,seconds,text in [('before',row['active_start']-row['start'],row['before_performance']),('active',row['active_end']-row['active_start'],row['active_performance']),('after',row['end']-row['active_end'],row['after_performance'])]:
   if seconds<=1e-9:continue
   end=clock+seconds*d['time_scale']
   if any(s['text'].rstrip('。！？') in text for s in contract.catalog(control.read(ROOT/'INPUT.json')['full_script']).values() if s['kind']=='dialogue'):raise ValueError('dialogue repeated in acting prose')
   cue=(row['speaker'].split('（')[0]+'对白："'+row['original_text']+'"。' if phase=='active' and row['source_kind']=='dialogue' else '无声动作与反应：')
   lines.append(f'{clock:.2f}–{end:.2f}秒：'+cue+text);clock=end
 lines.append('纸和笔只按本段步骤移动一次，到位就停。截止本段时间表，不提前读纸、拒签或离场。小林不碰笔、不签名。')
 prompt='\n'.join(lines)
 speeches=[r['original_text'] for r in d['rows'] if r['source_kind']=='dialogue']
 if any(prompt.count(t)!=1 for t in speeches):raise ValueError('current speech must appear exactly once')
 return prompt

def media_plan(client):
 folder=ROOT/'DELIVERABLE_opening';d=read(folder/'OPENING_SEGMENT.json');x=read(ROOT/'INPUT.json');asset=x['asset_feedback']
 rt=runtime();rt.check(control.read(rt.ledger));review=accepted('production_opening_review_r1')
 if review['validation']['needs_revision']:raise ValueError('reviewed current opening unresolved')
 expected={'FULL_SCRIPT.json':x['full_script'],'WHOLE_FILM_DIRECTION.json':direction(),'B1_PERFORMANCE.json':performance(),'COMPILED_PREFIX.json':compiled(),'OPENING_PRODUCTION_REVIEW.json':review['output'],'ASSET_FEEDBACK.json':asset,'USER_SCOPE.json':SCOPE}
 for name,value in expected.items():
  if read(folder/name)!=value:raise ValueError('delivery differs from current accepted source: '+name)
 schedule=expected['COMPILED_PREFIX.json']['schedule'];rows=d['rows'];seconds=sum(r['end']-r['start'] for r in rows)
 shot=next(q for q in expected['WHOLE_FILM_DIRECTION.json']['shots'] if q['shot_id']==rows[0]['shot_id'])
 if (rows!=schedule[:len(rows)] or d['source_refs']!=[r['source_ref'] for r in rows]
   or d['framing']!=shot['framing'] or d['source_seconds']!=round(seconds,6)
   or d['duration_seconds']!=max(4,math.ceil(round(seconds,6))) or d['time_scale']!=d['duration_seconds']/seconds
   or d['duration_seconds']>15 or not any(r['source_kind']=='dialogue' for r in rows)):
  raise ValueError('current first sample projection changed')
 handoff=read(folder/'PRODUCTION_HANDOFF.json')
 if handoff['script_sha256']!=SCOPE['script_sha256'] or handoff['human_quality_approved']:raise ValueError('sample scope changed')
 refs={name:{'path':str(folder/name),'sha256':sha(folder/name)} for name in ['FULL_SCRIPT.json','WHOLE_FILM_DIRECTION.json','B1_PERFORMANCE.json','COMPILED_PREFIX.json','OPENING_PRODUCTION_REVIEW.json','ASSET_FEEDBACK.json','USER_SCOPE.json','PRODUCTION_HANDOFF.json','OPENING_SEGMENT.json']}
 return {'schema':'current_legal_seedance_opening/v1','logical_task_id':LOGICAL,'segment_id':SID,'shot_id':d['rows'][0]['shot_id'],
  'script_content_sha256':SCOPE['script_sha256'],'sources':refs,'authorization':SCOPE,'provider':'ark_api','model':MODEL,'resolution':'480p','ratio':'9:16',
  'duration_seconds':d['duration_seconds'],'generate_audio':True,'return_last_frame':True,'image_role':'reference_image',
  'reference_image':{'path':asset['path'],'sha256':asset['sha256'],'source':'previous_human_approved_service_original'},
  'prompt':render_prompt(d),'source_refs':d['source_refs'],'budget_reset':False,'later_segments_authorized':False}

def request_for(client,plan):
 from src.content_factory.seedance_client import SeedanceReference
 ref=reference(Path(plan['reference_image']['path']));ref=SeedanceReference('image',ref.source,'reference_image')
 return client.build_task_payload(plan['prompt'],duration=plan['duration_seconds'],ratio='9:16',resolution='480p',generate_audio=True,return_last_frame=True,watermark=False,seed=20261010,references=[ref],task_type='reference')

def validate_saved_metadata(probe,plan):
 videos=[q for q in probe['streams'] if q['codec_type']=='video'];audios=[q for q in probe['streams'] if q['codec_type']=='audio']
 if len(videos)!=1 or len(audios)!=1:raise ValueError('expected exactly one video and one native audio stream')
 actual=float(probe['format']['duration'])
 if abs(actual-plan['duration_seconds'])>.5:raise ValueError('saved duration differs from planned native segment')
 v=videos[0];w,h=v['width'],v['height']
 if not 448<=min(w,h)<=512 or w>=h or abs(w/h-9/16)>.03:raise ValueError('saved resolution or aspect ratio differs from 480p vertical sample')
 return {'duration_seconds':actual,'native_audio_present':True,'resolution':[w,h],'content_inspected':False}

def media(operation):
 OUT.mkdir(parents=True,exist_ok=True);pp=OUT/'PLAN.json';rp=OUT/'receipt.json';lock=OUT/'.execution.lock'
 with lock.open('x',encoding='utf-8') as f:f.write('exclusive current sample execution')
 try:
  with SeedanceClient(SeedanceConfig.from_env('ark_api',require_key=True)) as client:
   if client.config.model!=MODEL:raise ValueError('configured model differs; no automatic switch')
   if operation=='media_prepare':
    if rp.exists():raise ValueError('existing submission; query original ID')
    plan=media_plan(client);control.write(pp,plan,True);req=request_for(client,plan)
    control.write(OUT/'REQUEST.preview.json',req,True);write_text_new(OUT/'PROMPT.txt',plan['prompt']+'\n')
    return {'status':'prepared','new_paid_calls':0,'duration_seconds':plan['duration_seconds'],'source_refs':plan['source_refs']}
   if operation=='media_submit':
    if rp.exists():raise ValueError('existing receipt; query original ID, never repeat submit')
    plan=read(pp)
    if media_plan(client)!=plan or sha(plan['reference_image']['path'])!=plan['reference_image']['sha256']:raise ValueError('current source/asset binding changed')
    verify_files({r['path']:r['sha256'] for r in plan['sources'].values()})
    req=request_for(client,plan)
    if req!=read(OUT/'REQUEST.preview.json'):raise ValueError('request preview changed')
    r={'schema':'current_legal_seedance_opening_receipt/v1','status':'submitting','technical_status':'running','content_status':'not_available',
     'logical_task_id':LOGICAL,'segment_id':SID,'shot_id':plan['shot_id'],'provider':'ark_api','model':MODEL,'plan':str(pp),'plan_sha256':sha(pp),
     'plan_snapshot':plan,'source_bindings':plan['sources'],'request_sha256':digest(req),'created_at':control.now(),'new_submissions':1,'automatic_retry':False}
    control.write(rp,r,True)
    try:reserve_media_attempt(pp,plan,rp)
    except Exception as exc:
     r.update(status='blocked_before_submit',technical_status='not_submitted',new_submissions=0,error=str(exc));persist(rp,r);raise
    try:
     created=client.create_task(req)
     if not created.get('id'):raise ValueError('missing task ID; submission outcome unknown')
    except Exception as exc:
     code=getattr(exc,'status_code',None);known=isinstance(code,int) and 400<=code<500
     r.update(status='request_rejected' if known else 'submit_outcome_unknown',technical_status='failed' if known else 'unknown',http_status=code,error=str(exc));persist(rp,r);raise
    r.update(task_id=created['id'],created=created,status='submitted');persist(rp,r)
   elif operation=='media_query':
    r=read(rp)
    if not r.get('task_id'):raise ValueError('no task ID; reconcile, never resubmit')
   else:raise ValueError('explicit media operation required')
   if r.get('technical_status')=='succeeded':
    if sha(r['video_path'])!=r['video_sha256'] or (r.get('last_frame') and sha(r['last_frame'])!=r['last_frame_sha256']):raise ValueError('saved output changed')
    return {k:r[k] for k in ['technical_status','content_status','task_id','video_path']}
   t=client.get_task(r['task_id']);r.update(latest_response=t,last_queried_at=control.now(),status=t['status']);persist(rp,r)
   if t['status'] in ['failed','expired','cancelled']:r.update(technical_status='failed',final=t);persist(rp,r)
   elif t['status']=='succeeded':
    stage='video_download'
    try:
     video=client.download_video(t,OUT/(SID+'.mp4'))
     if not video.stat().st_size:raise ValueError('empty video output')
     r.update(final=t,provider_task_status='succeeded',video_path=str(video),video_sha256=sha(video),video_bytes=video.stat().st_size)
     persist(rp,r);stage='technical_probe'
     probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(video)],text=True,encoding='utf-8'))
     validate_saved_metadata(probe,r['plan_snapshot']);r['metadata']=probe;persist(rp,r)
     stage='tail_download'
     if t.get('content',{}).get('last_frame_url'):
      tail=client.download_last_frame(t,OUT/(SID+'.provider_last.png'))
      if not tail.stat().st_size:raise ValueError('empty original tail output')
      r.update(last_frame=str(tail),last_frame_sha256=sha(tail),last_frame_source='generation_service_original',tail_status='saved_unapproved')
     else:r.update(last_frame=None,last_frame_sha256=None,tail_status='not_returned; continuation blocked')
     r.update(completed_at=control.now(),human_decision=None,next_segment_dispatch_allowed=False,assistant_content_inspected=False)
     r.pop('artifact_error',None);r.pop('failure_stage',None)
     mark_saved_candidate(r);persist(rp,r)
    except Exception as exc:
     r.update(status='artifact_save_pending',provider_task_status='succeeded',failure_stage=stage,artifact_error=str(exc));persist(rp,r);raise
   return {k:r.get(k) for k in ['technical_status','content_status','status','task_id','video_path','tail_status']}
 finally:lock.unlink()

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','director','B1','review','finish','status','media_prepare','media_submit','media_query']);a=ap.parse_args()
 result=media(a.stage) if a.stage.startswith('media_') else prepare() if a.stage=='prepare' else summary() if a.stage=='status' else finish() if a.stage=='finish' else dispatch(a.stage)
 print(json.dumps(result,ensure_ascii=False),flush=True)
