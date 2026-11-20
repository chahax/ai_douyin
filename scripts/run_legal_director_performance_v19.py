"""Explicit new production after actual full-script adoption; no automatic retry."""
from pathlib import Path
from copy import deepcopy
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_legal_director_performance_v18 as previous
from scripts.run_legal_review_qualification_v14 import ScriptTrial as ScriptParent
class Prior:
 root=previous.ROOT
 def runtime(self):return previous.runtime()
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts import run_creative_resume_v10 as identity
from src.content_factory import creative_legal_director_performance_v1 as contract
from src.content_factory import creative_legal_director_assignment_v2 as assignment
from src.content_factory import creative_legal_scalar_performance_v2 as scalar
ROOT=PROJECT/'data/production_revisions/legal_director_performance_20261008/round_05'
PREVIEW=ScriptParent().root/'DELIVERABLE_r8/DIRECTOR_INPUT_PREVIEW.json'
ADOPTION={"schema":"actual_full_script_adoption/v1","source":"current_conversation_user_reply","question_call_id":"call_055c841f8b8740efaac27febf08b3f18","user_statement":"符合，采用正文进入导演与表演","script_sha256":"febb8a7c9d186bc3addc0080e02413a67532bab079486decb15423c66de1d7de","approved_scope":"adopt complete script; create whole-film direction and actual per-beat performance, compile and review text handoff","media_authorized":False,"publishing_authorized":False,"upstream_message_id_supplied":False}
def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  prior=Prior();rt=prior.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
  receipts=[rt.effective_receipt(c) for c in ledger['calls']]
  if any(type(r['response_metadata'].get('total_tokens')) is not int for r in receipts):raise ValueError('parent spend unresolved')
  preview=control.read(PREVIEW)
  if control.digest(preview['full_script'])!=ADOPTION['script_sha256'] or preview['full_text_review']['full_text_review']['issues']:raise ValueError('adopted exact reviewed script required')
  control.write(ROOT/'HUMAN_SCRIPT_ADOPTION.json',ADOPTION,True)
  preview.update(status='actual_script_adopted_text_production',actual_user_full_script_confirmation=ADOPTION,dispatch_allowed=True)
  control.write(ROOT/'INPUT.json',preview,True)
  control.write(ROOT/'ADOPTED_DIRECTION.json',previous.accepted('director_r1')['output'],True)
  control.write(ROOT/'DIRECTION_SOURCE_CHECK.json',control.read(prior.root/'DIRECTOR_SOURCE_CHECK.json'),True)
  files=list(dict.fromkeys(rt.sources+[rt.ledger,PREVIEW,prior.root/'HUMAN_SCRIPT_ADOPTION.json',prior.root/'DIRECTOR_SOURCE_CHECK.json']+[rt.root/c['receipt'] for c in ledger['calls']]))
  inherited=deepcopy(ledger['starting_spend']);inherited.update(calls_started=inherited['calls_started']+len(receipts),reported_tokens=inherited['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),calls_with_known_usage=inherited['calls_with_known_usage']+len(receipts),parent_ledger_sha256=control.sha_file(rt.ledger))
  control.write(ROOT/'ANCHOR.json',{'schema':contract.VERSION,'inherited':inherited,'models':ledger['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in files},'media_authorized':False,'automatic_retry':False},True)
 return runtime().prepare()
def runtime():
 a=control.read(ROOT/'ANCHOR.json')
 def guard():
  verify_files(a['parent_files'])
  if control.read(ROOT/'HUMAN_SCRIPT_ADOPTION.json')!=ADOPTION:raise ValueError('human adoption changed')
 own=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_legal_scalar_performance_v2.py',PROJECT/'tests/test_creative_legal_scalar_performance_v2.py',ROOT/'ADOPTED_DIRECTION.json',ROOT/'DIRECTION_SOURCE_CHECK.json',PROJECT/'src/content_factory/creative_legal_director_assignment_v2.py',PROJECT/'src/content_factory/creative_legal_director_performance_v1.py',PROJECT/'tests/test_creative_legal_director_performance_v1.py',ROOT/'INPUT.json',ROOT/'HUMAN_SCRIPT_ADOPTION.json',ROOT/'ANCHOR.json']
 return control.ContinuationRuntime(PROJECT,ROOT,list(dict.fromkeys(own+[Path(p) for p in a['parent_files']])),a['inherited'],a['models'],inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)
def summary():
 s=runtime().summary();s['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];s.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return s
def accepted(label):
 if label=='director_r1':
  d=control.read(ROOT/'ADOPTED_DIRECTION.json');proof=control.read(ROOT/'DIRECTION_SOURCE_CHECK.json')
  if proof['direction_sha256']!=control.digest(d) or not proof['approved_for_local_text']:raise ValueError('exact checked director required')
  return {'ordinal':304,'output':d,'status':'contract_valid'}
 rt=runtime();l=control.read(rt.ledger);rt.check(l);rows=[c for c in l['calls'] if c['label']==label]
 if len(rows)!=1:raise ValueError('exact call required '+label)
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('current source rejected or unknown '+label)
 if label.startswith('performance_'):
  r=deepcopy(r);r['original_wire_output']=deepcopy(r['output']);r['output']=scalar.expand(r['output'],sources()['full_script'],label.split('_')[1])
 return r

def sources():return control.read(ROOT/'INPUT.json')
def performance_prefix(count):return [accepted(f'performance_B{i+1}_r1')['output'] for i in range(count)]
def wire(role,payload,schema,rule,cap=8000):
 src=sources();models=control.read(ROOT/'ANCHOR.json')['models']
 # Read-only full creative source and full reference are present in every creative/review request.
 source={k:deepcopy(src[k]) for k in ('full_script','reference_fulltext','expression_standards','emotion_goal','creative_brief','verified_legal_context')}
 messages=[{'role':'system','content':rule},{'role':'user','content':json.dumps({'read_only_complete_source':source,**payload},ensure_ascii=False,separators=(',',':'))}]
 return {'role':role,'model':models[role]['model'],'messages':messages,'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},'input_provenance':{'script_sha256':control.digest(src['full_script']),'full_reference_sha256':control.digest(src['reference_fulltext']),'full_reference_in_actual_messages':True,'actual_user_adoption_sha256':control.digest(ADOPTION),'server_strict_generation_claimed':False},'operator_version':contract.VERSION}
def dispatch(stage):
 if stage=='director':raise ValueError('v19 reuses only source-checked304; director revision needs a new version and downstream invalidation')
 prepare();script=sources()['full_script']
 if stage=='director':
  payload={'source_ref_catalog':contract.catalog(script),'previous_complete_direction':previous.accepted('director_r1')['output'],'task':'只提交完整导演安排。保留全部原步骤与顺序；shot按完整步骤分组，不重复对白、不删除动作。每镜新信息、观察主体、刺激反应、构图、切镜理由明确。开场状态满足原动作；四拍至少各一处关键情绪窗口，不把全部动作变成慢镜。时长浮动，长对白完整留时间。资产只定义文字，不生成图片。'}
  req=wire('writer',payload,assignment.schema(script),'你是MiniMax导演。输出唯一工具对象，严格遵守Schema。导演只决定全片情绪/因果/观察和必要反应下限，不细排实际秒数。正文原句和事件不可改；参考只借机制，不抄剧情。角色仅小林与周姐。原文姓名以Schema全称表示。source_assignments每个原步骤唯一归属一个shot_id，按原顺序填写；shots仅镜头描述，不能额外拆出同一个动作的第二镜。镜头总量优先少而必要，不要每个道具操作都切镜。初态位于B1第一个动作开始之前，小林进入房间工牌还在脖子；纸和笔在周姐文件夹内。before/during/after均相对source_ref完整原步骤，during反应与对白同时，不额外重复说话。要求是下限，不是强行固定总时长。资产和空间定义必须适合玻璃会议室，同一房间轴线，不能引入第三个角色。')
  payload_fault={'actual_previous_ordinal':303,'confirmed_faults':['SH10归属只有B4.S04/S05，却在new_information与stimulus_and_response写小林点头，这是B4.S06；不能提前或重复点头。SH11仅桌面近景却归属B4.S06也包含小林点头，必须先能看见点头再观察空桌，或用同框同时显示。','SH05归B2.S01/S02/S03却摘要里写明要求公司把事由写清并今天不动笔，这个原步骤在B2.S05；本镜只确认两种说法不同，未来要求只写全片因果链。','B1.S02窗口观察者为小林，SH02既说拍周姐正脸又随后切回小林；SH03写快速正反打。每个shot_id要明确一个可连续执行构图，不能偷偷把额外切镜藏进framing。用两人中近景同框/单镜平移即可同时读说话与听者；真切镜请新shot_id按完整步骤唯一归属。'],'request':'提交完整新导演稿，源严格按23个编号逐句核对。每镜新增信息/刺激/反应仅本镜实际归属发生的事，避免复述全片台词把后文塞到前镜。只有表情/呼吸可延伸反应，原点头/纸笔/工牌动作不能重复或提前。全片正文不改，无额外角色/台词；不要新增复杂操作。保持11镜或必要更少，每镜连续构图，重要脸和关键道具实际可读。'}
  req['messages'].append({'role':'user','content':json.dumps(payload_fault,ensure_ascii=False)})
  validator=lambda v:{**contract.validate_direction(assignment.expand(v,script),script),'canonical_direction':assignment.expand(v,script),'original_model_document_preserved':True};label='director_r1'
 elif stage.startswith('B'):
  index=[b['id'] for b in script['beats']].index(stage);d=accepted('director_r1')['output'];prior=performance_prefix(index);prefix=contract.compile_prefix(script,d,prior)
  payload={'whole_direction':d,'current_beat':deepcopy(script['beats'][index]),'source_ref_catalog':{r:s for r,s in contract.catalog(script).items() if r.startswith(stage+'.')},'required_start_state':prefix['final_state'],'prior_compiled_performance':prefix,'state_values':contract.STATE_VALUES,'original_action_state_obligations':{r:v for r,v in contract.SOURCE_STATE_OBLIGATIONS.items() if r.startswith(stage+'.')},'task':'为当前整拍提交完整可演表演与实际时间；所有当前原步骤各一次，不改原话。动作只演原步骤，状态变化仅记相应动作实际引起的变化。对白无状态操作。前后留给听者/说话者的脸、呼吸、消化，不能加入新台词、道具动作、离职胜负或第二次工牌操作。'}
  payload['verified_prior_fault']={'ordinal':305,'fault':'B1 rows S03后被拆成多个$text/item对象，active_seconds缺失；本次每源完整键对象，不在本地修坏响应。'} if stage=='B1' else None
  req=wire('writer',payload,scalar.schema(script,stage),'你是MiniMax表演导演。当前采用逐源键对象，如B1_S01；禁止rows数组、$text、item、payload_json。每个原源键对象完整7项，state_changes为字段名到{from,to}的对象；对白为空对象{}，动作仅填写实际变化的字段。before/after仅原位表情眼神呼吸，不做手部/道具动作。逐原步骤填写before/active/after秒数和对应表演。程序唯一插入原句，不重复把对白抄入表演描述，不删缩原句。active对白时间按自然普通话不超过5个发音字符/秒，关键句可更慢；before与after是独立不说话的反应时间，0秒时填写“不占额外时间”。只在active动作发生state_changes，每字段from必须与当前状态一致，to为真实结果；对白变化必须空对象{}。before/after只允许静止姿态内的眼神、表情、呼吸，不能藏道具转移或新增行动。动作可写原动作的手法，但不要反复拿笔、摘戴工牌或额外推纸。满足导演当前反应窗口。状态义务是验收规则，不是新增原剧情。最后收走未签纸笔、周姐离开，小林仍坐；承诺答复尚未兑现。完整开场工牌从脖子到桌角，最后B3戴回，此后不能再拿工牌。',6000)
  validator=lambda v: {'compiled_prefix':contract.compile_prefix(script,d,prior+[scalar.expand(v,script,stage)]),'canonical_performance':scalar.expand(v,script,stage),'creative_quality_passed':False};label=f'performance_{stage}_r1'
 elif stage=='review':
  d=accepted('director_r1')['output'];p=performance_prefix(len(script['beats']));compiled=contract.compile_complete(script,d,p);context={'script':script,'director':d,'compiled':compiled};cat=contract.evidence_catalog(context)
  payload={'current_complete_production':context,'evidence_catalog':cat,'review_boundary':'全文检查剧本是否保留、四拍情绪/因果/道具连续及重要对白前中后排时。真正当前矛盾保留必修，额外美学选择归建议。今日停止催签不是案件胜利；未来答复可以留白。计时估算不是音视频实测。每拍证据包含原稿与当前编译实际表演的标量ID，原值查表无手改。'}
  req=wire('director',payload,contract.review_schema(context),'你是DeepSeek独立完整文本审查。读全片原稿、导演、实际逐拍排时与完整参考，逐拍全覆盖。issues只当前必须改的具体矛盾/严重挤压/源删改；不为增加戏剧性强改已采用正文。存在真实问题不能假通过。coverage证据必须有当前原稿和当前compiled.schedule表演，按目录ID引用；不要生成正文不存在的引用。四项情绪压力、核对选择、催签暂停、仍留白的释放共同判断，给具体理由。',10000)
  def validator(v):return contract.validate_review(v,context)[1]
  label='production_review_r1'
 else:raise ValueError('one explicit stage required')
 control.write(ROOT/'request_previews'/f'{label}.json',req,True)
 actual=json.loads(req['messages'][1]['content'])['read_only_complete_source']
 if actual['full_script']!=script or actual['reference_fulltext']!=sources()['reference_fulltext']:raise ValueError('full actual creative inputs missing')
 r=runtime().dispatch(label,req,validator)
 if r['status']=='contract_valid':control.write(ROOT/(label.upper()+'.json'),r['output'],True)
 control.write(ROOT/'STATUS.json',{'stage':stage,'ordinal':r['ordinal'],'receipt_status':r['status'],'spend':summary(),'media_calls':0,'human_script_adopted':True,'human_director_performance_approval':None})
 return {'ordinal':r['ordinal'],'status':r['status'],'failure':r.get('failure'),'validation_error':r.get('validation_error'),'validation':{k:v for k,v in r.get('validation',{}).items() if k!='compiled_prefix'},'spend':summary()}
def finish():
 script=sources()['full_script'];d=accepted('director_r1')['output'];p=performance_prefix(len(script['beats']));c=contract.compile_complete(script,d,p);context={'script':script,'director':d,'compiled':c};raw=accepted('production_review_r1');review,result=contract.validate_review(raw['output'],context)
 if review['issues'] or not review['story_preserved']:raise ValueError('unresolved actual production review')
 out=ROOT/'DELIVERABLE_d1'
 for name,v in [('FULL_SCRIPT.json',script),('WHOLE_FILM_DIRECTION.json',d),('ACTUAL_BEAT_PERFORMANCES.json',p),('COMPILED_PERFORMANCE.json',c),('FULL_TEXT_REVIEW.json',review),('HUMAN_SCRIPT_ADOPTION.json',ADOPTION)]:control.write(out/name,v,True)
 lines=['# '+script['title']+'：完整导演与表演安排','','正文已获用户采用；导演与表演已完成模型全文审查，等待用户对具体安排的内容确认。尚无图片或视频。','',f"确定性排时：{c['total_duration_seconds']:.2f}秒，{len(c['shots'])}镜。实际声音/口型/表演可读性未验证。",'', '## 全片安排','',d['emotional_arc'],'',d['causal_chain'],'',d['ending_intent'],'',d['spatial_design'],'','## 资产定义','']
 for a in d['assets']:lines += [a['id']+'：'+a['definition']+'；叙事用途：'+a['story_function'],'']
 for s in c['shots']:
  lines += [f"## {s['shot_id']} / {s['beat_id']} / {s['start']:.2f}–{s['end']:.2f}秒",'', '新增信息：'+s['new_information'],'','观察：'+s['observation_target']+'；构图：'+s['framing'],'','刺激与反应：'+s['stimulus_and_response'],'','切镜理由：'+s['cut_reason'],'']
  for r in c['schedule']:
   if r['shot_id']!=s['shot_id']:continue
   lines += [f"**{r['source_ref']} {r['start']:.2f}–{r['end']:.2f}秒**",'',('**'+r['speaker']+'**：' if r['source_kind']=='dialogue' else '原动作：')+r['original_text'],'',f"前窗 {r['active_start']-r['start']:.2f}秒："+r['before_performance'],'',f"主体 {r['active_end']-r['active_start']:.2f}秒："+r['active_performance'],'',f"后窗 {r['end']-r['active_end']:.2f}秒："+r['after_performance'],'']
 lines+=['## 反应窗口与边界','']
 for w in c['reaction_window_checks']:lines += [f"{w['source_ref']} {w['phase']} / {w['observer']}：下限{w['minimum_seconds']}秒，编译实际{w['actual_seconds']}秒；真实可读性待人工视频审核。",'']
 lines+=['## 制作交接','', '下一步先确认当前导演/表演及少量审美样板，再明确图片方案和当前媒体授权。人物与会议室资产优先复用，本法律新片尚无选定实图。付费生成段由视频服务长度限制另编译，观察镜头不能直接等同生成段。普通话及原句完整，长对白不得为了塞入短段而改速或删句。服务提示只投影当前段的有效表演与资产，不发送内部状态JSON。','', '视频成功保存统一 awaiting_human_review；助手不主动抽帧、听看、ASR或媒体审核。批准本段及服务原始尾帧后才能续段，旧片独立九镜特许不继承。','',c['physical_scope'],'', '当前全文审查必修问题：0；不构成真实声画质量通过。']
 path=out/'DIRECTOR_PERFORMANCE_READABLE.md';body='\n'.join(lines)+'\n'
 if path.exists() and path.read_text(encoding='utf-8')!=body:raise ValueError('immutable delivery changed')
 if not path.exists():path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body,encoding='utf-8')
 control.write(out/'PRODUCTION_HANDOFF.json',{'status':'text_handoff_ready_awaiting_human_director_and_aesthetic_confirmation','script_sha256':control.digest(script),'compiled_sha256':control.digest(c),'review_ordinal':raw['ordinal'],'text_handoff_complete':True,'human_script_adopted':True,'human_director_performance_approval':None,'media_calls':0,'actual_images':[],'media_authorized':False,'automatic_retry':False,'creative_quality_passed':False,'spend':summary()},True)
 return {'delivery':str(out),'seconds':c['total_duration_seconds'],'shots':len(c['shots']),'issues':0,'spend':summary()}
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');a=argparse.ArgumentParser();a.add_argument('stage',choices=['prepare','director','B1','B2','B3','B4','review','finish','status']);s=a.parse_args().stage
 print(json.dumps(prepare() if s=='prepare' else summary() if s=='status' else finish() if s=='finish' else dispatch(s),ensure_ascii=False),flush=True)
