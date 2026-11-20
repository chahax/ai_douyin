"""Source-bound short legal remake: whole direction, local performances, compile, full review."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_legal_short_director_performance_v2_20261009 as prior
from scripts import run_legal_plain_script_qualification_v5_20261009 as original_script
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from src.content_factory import creative_legal_short_director_performance_v1 as contract
from src.content_factory import creative_legal_short_director_assignment_v1 as assignment
from src.content_factory import creative_legal_short_scalar_performance_v3 as scalar
from src.content_factory import creative_legal_short_split_review_v1 as review_wire
ROOT=PROJECT/'data/production_revisions/legal_short_remake_20261009/round_03'
FRAME=PROJECT/'data/video_generation/legal_trend_20261008/opening_SH01_v1/SH01.provider_last.png'
OLD=FRAME.parent
AUTH={
 'schema':'legal_short_remake_user_scope/v1',
 'source':'current_conversation_user_statements',
 'user_statements':['时间可以再压缩下尽量3分钟内的剧情可以用同场景的资源不同的剧本再在一次','重做原来的辞职剧情','本次整批生成，最后统一审核'],
 'question_call_ids':['call_9fcac9e8c7654a18ab5e0d198df5d850','call_61f0a83eba2b4aabacd1783b79e84d84'],
 'interpreted_current_script_sha256':'2904da9d662dd3cf7c8411bf7cf4d9f763a3f7d3df35809fa064a46b893101ca',
 'interpretation':'redo original dismissal/voluntary-resignation conflict using reviewed short full draft 316/318 and existing two-person office; no different wage story',
 'max_duration_seconds':180,'aim':'necessary natural dialogue and reactions, prefer around 60-90 seconds; never fill 3 minutes',
 'no_subtitles':True,'reuse_resources':True,'media_authorized':True,
 'batch_service_native_tail_continuation':True,'human_content_approved':False,
 'automatic_retry':False,'publishing_authorized':False,'budget_reset':False}

def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  rt=prior.runtime();l=control.read(rt.ledger);rt.check(l);receipts=[rt.effective_receipt(c) for c in l['calls']]
  if [r['ordinal'] for r in receipts]!=[321]:raise ValueError('exact failed321 parent required')
  control.write(ROOT/'ADOPTED_DIRECTION_WIRE.json',control.read(prior.ROOT/'ADOPTED_DIRECTION_WIRE.json'),True);control.write(ROOT/'PREVIOUS_B1_FAILURE.json',receipts[0],True)
  src=control.read(original_script.ROOT/'FULL_SCRIPT_SOURCE.json')
  if control.digest(src)!=AUTH['interpreted_current_script_sha256']:raise ValueError('full current short source changed')
  ctx=json.loads(control.read(original_script.ROOT/'BASE_REVIEW_REQUEST.json')['messages'][1]['content'])
  asset={'id':'approved_old_opening_native_tail','path':str(FRAME),'sha256':control.sha_file(FRAME),
    'provider':'ark_api','model':'doubao-seedance-2-0-mini-260615','role_for_new_opening':'reference_image',
    'source_prompt':control.read(OLD/'PLAN.json')['prompt'],
    'human_original_approval':control.read(OLD/'CONTINUATION_USER_CONTEXT.json'),
    'scope':'reuse original two-person identities and same office; new first-frame prop/pose state must follow new source',
    'old_state_conflict':'old tail has badge on table and paper face-down; NOT new literal first frame',
    'assistant_pixels_inspected':False,'director_receives':'actual provenance and source prompt metadata; no vision inspection claimed'}
  payload={k:deepcopy(ctx[k]) for k in ['reference_fulltext','writer_expression_criteria','emotional_brief','verified_legal_context','creative_brief','confirmed_case_facts']}
  payload.update(full_script=src,asset_feedback=asset,remake_user_scope=AUTH)
  control.write(ROOT/'INPUT.json',payload,True);control.write(ROOT/'USER_SCOPE.json',AUTH,True)
  inherited=deepcopy(l['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(receipts),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(receipts),parent_ledger_sha256=control.sha_file(rt.ledger))
  files=list(dict.fromkeys(rt.sources+[rt.ledger]+[rt.root/c['receipt'] for c in l['calls']]+[original_script.ROOT/'FULL_TEXT_REVIEW_QUALIFIED.json',original_script.ROOT/'DELIVERABLE_r3/FULL_SCRIPT.json',FRAME,OLD/'CONTINUATION_USER_CONTEXT.json',OLD/'PLAN.json']))
  control.write(ROOT/'ANCHOR.json',{'schema':contract.VERSION,'inherited':inherited,'models':l['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in files},'automatic_retry':False,'budget_reset':False},True)
 return runtime().prepare()

def runtime():
 a=control.read(ROOT/'ANCHOR.json')
 def guard():verify_files(a['parent_files'])
 own=[Path(__file__).resolve(),ROOT/'ANCHOR.json',ROOT/'USER_SCOPE.json',ROOT/'INPUT.json',ROOT/'ADOPTED_DIRECTION_WIRE.json',ROOT/'PREVIOUS_B1_FAILURE.json']+[PROJECT/'src/content_factory'/n for n in ['creative_legal_short_director_performance_v1.py','creative_legal_short_director_assignment_v1.py','creative_legal_short_scalar_performance_v3.py','creative_legal_short_split_review_v1.py']]
 return control.ContinuationRuntime(PROJECT,ROOT,list(dict.fromkeys(own+[Path(p) for p in a['parent_files']])),a['inherited'],a['models'],inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)

def summary():
 s=runtime().summary();s['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s

def sources():return control.read(ROOT/'INPUT.json')
def accepted(label):
 if label=='director_r1':return {'ordinal':319,'output':assignment.expand(control.read(ROOT/'ADOPTED_DIRECTION_WIRE.json'),sources()['full_script']),'status':'contract_valid'}
 rt=runtime();l=control.read(rt.ledger);rt.check(l);rows=[c for c in l['calls'] if c['label']==label]
 if len(rows)!=1:raise ValueError('exact current receipt required '+label)
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('source failed/unknown; do not retry '+label)
 if label=='director_r1':return {**r,'output':assignment.expand(r['output'],sources()['full_script'])}
 if label.startswith('performance_'):return {**r,'output':scalar.expand(r['output'],sources()['full_script'],label.split('_')[1])}
 return r

def prefix(n):return [accepted(f'performance_B{i+1}_r1')['output'] for i in range(n)]

def wire(role,payload,schema,rule,cap):
 src=sources();models=control.read(ROOT/'ANCHOR.json')['models']
 return {'role':role,'model':models[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps({'read_only_complete_source':src,**payload},ensure_ascii=False,separators=(',',':'))}],
  'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},
  'input_provenance':{'script_sha256':control.digest(src['full_script']),'full_reference_sha256':control.digest(src['reference_fulltext']),'full_reference_in_actual_messages':True,'server_strict_generation_claimed':False,'user_scope_sha256':control.digest(AUTH)},'operator_version':contract.VERSION}

def dispatch(stage):
 prepare();script=sources()['full_script']
 if stage=='director':raise ValueError('director319 preserved; no repeat submit')
 if False:
  req=wire('writer',{'source_ref_catalog':contract.catalog(script),'required_initial_state':contract.INITIAL,'state_obligations':contract.SOURCE_STATE_OBLIGATIONS,'task':'全片导演安排，4到6镜；优先四拍各一个连续构图，两人中近景能看见听者脸和纸。每镜只写当前归属步骤实际新增信息，未来情节仅全片因果链可述。少切桌面，不用反复道具动作填时。每拍关键反应下限，拒签前后及周姐被拒后的停顿可读。新开场借旧图身份与办公室，重置道具起态不是摘戴工牌。'},assignment.schema(script),
   'MiniMax全片导演。只输出submit_creative_json。完整原稿不改，五句对白不重复，角色仅小林和周姐，不加入第三人。参考只借表达机制。source_assignments按给定14源次序各唯一shot_id；每镜一个连续构图，不暗藏正反打。导演负责信息、观察、因果和反应下限，不编细排时间。初态严格required_initial_state；工牌一直戴着，纸未签，小林全程坐着，最后仅周姐离开。纸的微小拉正/推回都在table_middle区内，不改变归属权。全片目标自然紧凑且小于180秒，反应窗口最低秒数宜0.5到2秒，重点可稍长，不堆无意义慢动作。资产反馈原图仅参考身份/空间，新稿初态由新首段重建。具体参考像素没有被你看见，不声称视觉核验。',6000)
  validator=lambda v:contract.validate_direction(assignment.expand(v,script),script);label='director_r1'
 elif stage in [b['id'] for b in script['beats']]:
  idx=[b['id'] for b in script['beats']].index(stage);d=accepted('director_r1')['output'];p=prefix(idx);c=contract.compile_prefix(script,d,p)
  req=wire('writer',{'whole_direction':d,'current_beat':script['beats'][idx],'source_ref_catalog':{r:s for r,s in contract.catalog(script).items() if r.startswith(stage+'.')},'required_start_state':c['final_state'],'prior_compiled_performance':c,'state_values':contract.STATE_VALUES,'source_state_obligations':{r:s for r,s in contract.SOURCE_STATE_OBLIGATIONS.items() if r.startswith(stage+'.')},'local_state_compilation':'粗粒度道具与人位置严格从14源正文编译，不再要求生成模型输出状态字段；模型只生成整拍时间和表演，不补写原文动作','verified_failure320':control.read(ROOT/'PREVIOUS_B1_FAILURE.json')['output'] if stage=='B1' else None,'repair_request':'提交当前整拍完整新表演，320/321原响应保留。321把空state_changes写成$text对象；本次道具状态归确定性编译器，不在模型输出协议里。动作源不得开口说话、话落下，不能提前执行后续对白；非言语前后窗不可执行下一步或重复原动作。'},scalar.schema(script,stage),
   'MiniMax局部表演导演。只输出submit_creative_json。当前整拍逐源键完整对象，例如B1_S01，每源只需6项时间和表演。禁止rows/item/$text对象包装。状态字段由确定性编译器从原稿推导，不在你输出中。完整原话由编译器插入一次，表演文本不复述对白、不抄原动作重复一遍，不加新动作或台词。before/after只眼神表情呼吸静止反应，0秒写“不占额外时间”；道具/位置操作只能active且只能当前原动作一次，非对白动作不可开口说话。自然普通话不超过5个发音字每秒，重要句稍慢；active不超过12秒，前后各不超过3秒，单步总长务必不超过15秒，以免跨段拆句。每拍避免过多等待，满足导演反应下限即可，保留关键受压/迟疑/拒签/对方接回的脸部可读性。遵守required_start_state和原动作事实，不输出from/to或start_state/end_state/state_changes。B4收纸笔入夹并站起，随后唯一周姐出门；小林全程坐着，结尾手指放松。工牌全程脖子，不摘戴。不得新增纸上签名或字幕。',5000)
  def validator(v):
   expanded=scalar.expand(v,script,stage)
   if any(r['before_seconds']+r['active_seconds']+r['after_seconds']>15 for r in expanded['rows']):raise ValueError('one complete source step exceeds service15s; revise complete beat')
   return {'compiled_prefix':contract.compile_prefix(script,d,p+[expanded]),'creative_quality_passed':False}
  label=f'performance_{stage}_r1'
 elif stage=='review':
  d=accepted('director_r1')['output'];c=contract.compile_complete(script,d,prefix(4));ctx={'script':script,'director':d,'compiled':c}
  req=wire('director',{'current_complete_production':ctx,'evidence_catalog':review_wire.compact_catalog(ctx),'review_boundary':'核对完整正文保存、当前14源一次、当前因果状态、关键对白前中后估算秒数及<=180。只标真正必须返修的矛盾，不要求案件胜利或增加对白。每拍script/performance目录ID各一组。旧片人物/声音问题需要人审，不能写成已解决。'},review_wire.schema(ctx),
   'DeepSeek独立全文文本审查，读完整script、导演、逐拍编译和R01。逐拍证据同时引用当前原稿和compiled.schedule，目录ID查原值，禁止捏造。五句对白原样保留，不加重复，催签拒签收纸的关系变化是否可理解；初态工牌戴着，全文不摘戴，最后只周姐离开，小林留坐。纸拉正与推回属于table_middle微移动，不能把粗粒度不变误判未发生动作。秒数只是模型规划与确定性编译估计，不是实测。真矛盾列issues，审美增强列suggestions；不得擅改正文。',8500)
  validator=lambda v:review_wire.expand(v,ctx)[1];label='production_review_r1'
 else:raise ValueError('explicit stage required')
 control.write(ROOT/'request_previews'/f'{label}.json',req,True)
 r=runtime().dispatch(label,req,validator)
 if r['status']=='contract_valid':control.write(ROOT/(label.upper()+'.json'),r['output'],True)
 control.write(ROOT/'STATUS.json',{'stage':stage,'ordinal':r['ordinal'],'receipt_status':r['status'],'spend':summary(),'media_calls':0,'content_quality_approved':False})
 return {'ordinal':r['ordinal'],'status':r['status'],'validation_error':r.get('validation_error'),'failure':r.get('failure'),'spend':summary()}

def finish():
 script=sources()['full_script'];d=accepted('director_r1')['output'];p=prefix(4);c=contract.compile_complete(script,d,p);ctx={'script':script,'director':d,'compiled':c};r=accepted('production_review_r1');review,check=review_wire.expand(r['output'],ctx)
 if review['issues'] or not review['story_preserved']:raise ValueError('unresolved current full review')
 out=ROOT/'DELIVERABLE_short'
 for name,v in [('FULL_SCRIPT.json',script),('WHOLE_FILM_DIRECTION.json',d),('ACTUAL_BEAT_PERFORMANCES.json',p),('COMPILED_PERFORMANCE.json',c),('FULL_TEXT_REVIEW.json',review),('USER_SCOPE.json',AUTH),('ASSET_FEEDBACK.json',sources()['asset_feedback'])]:control.write(out/name,v,True)
 lines=['# '+script['title']+'：辞职剧情短版制作交接','',f"编译表演总长 {c['total_duration_seconds']:.2f} 秒；{len(c['shots'])}镜；实际视频时长另核对，最高180秒。",'','五句对白不改。办公室和两人物复用；无字幕，工牌一直戴着，周姐独自离开，小林留坐。','',d['emotional_arc'],'',d['causal_chain'],'',d['ending_intent'],'',d['spatial_design'],'']
 for shot in c['shots']:
  lines += [f"## {shot['shot_id']} / {shot['start']:.2f}–{shot['end']:.2f}秒",'', '新增信息：'+shot['new_information'],'','观察：'+shot['observation_target'],'','构图：'+shot['framing'],'','刺激反应：'+shot['stimulus_and_response'],'','切镜理由：'+shot['cut_reason'],'']
  for row in [x for x in c['schedule'] if x['shot_id']==shot['shot_id']]:
   lines += [f"**{row['source_ref']} {row['start']:.2f}–{row['end']:.2f}秒**",'',('对白 '+row['speaker']+'：' if row['source_kind']=='dialogue' else '原动作：')+row['original_text'],'',f"前 {row['active_start']-row['start']:.2f}s："+row['before_performance'],f"中 {row['active_end']-row['active_start']:.2f}s："+row['active_performance'],f"后 {row['end']-row['active_end']:.2f}s："+row['after_performance'],'']
 lines+=['## 制作边界','','文本全文复审必修0；不证明实际表演或音画通过。旧图为身份/环境参考，不作为不兼容的新首帧；新段服务原生尾帧按本次批量授权相接。无自动重试，视频仅核对接口和保存，完成后统一 awaiting_human_review，不抽帧/听看/ASR、不发布。','']
 control.write(out/'PRODUCTION_HANDOFF.json',{'status':'text_handoff_ready_for_authorized_short_remake','script_sha256':control.digest(script),'compiled_sha256':control.digest(c),'review_ordinal':r['ordinal'],'duration_estimate_seconds':c['total_duration_seconds'],'media_authorized':True,'user_scope_sha256':control.digest(AUTH),'creative_quality_passed':False,'spend':summary()},True)
 body='\n'.join(lines);path=out/'DIRECTOR_PERFORMANCE_READABLE.md'
 if path.exists() and path.read_text(encoding='utf-8')!=body:raise ValueError('immutable human readout changed')
 if not path.exists():path.write_text(body,encoding='utf-8')
 return {'delivery':str(out),'duration_seconds':c['total_duration_seconds'],'shots':len(c['shots']),'spend':summary()}

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','director','B1','B2','B3','B4','review','finish','status']);s=ap.parse_args().stage
 print(json.dumps(prepare() if s=='prepare' else summary() if s=='status' else finish() if s=='finish' else dispatch(s),ensure_ascii=False),flush=True)
