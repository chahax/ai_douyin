"""Full model rewrite and independent whole review for natural interaction.
No video authorization, no automatic retries, and no frozen-source mutation.
"""
from pathlib import Path
from copy import deepcopy
import argparse,json,re,sys
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts.run_confirmed_legal_script_trial_v4 import render_script
from src.content_factory.creative_legal_dialogue_craft_v14 import compile_writer_script
from src.content_factory.creative_trend_bridge import validate_complete_story
from jsonschema import Draft202012Validator
from src.content_factory.creative_current_brief_projection_v1 import project_current_brief,verify_writer_request
ROOT=PROJECT/'data/production_revisions/legal_natural_interaction_20261010/round_05'
PARENT=PROJECT/'data/production_revisions/legal_natural_interaction_20261010/round_04'
SOURCE=PROJECT/'data/production_revisions/legal_dialogue_refinement_20261009/round_20'
VIDEO=PROJECT/'data/video_generation/legal_current_362_20261010/opening_v1'
USER='语速有点过快了，可以说话和动作表情一起的这样也可以减少整体时长，这个剧本这么感觉不专业，和看电视上的完全不一样'
def current_brief(source_script):
 return {'brief_id':'legal_resignation_current_facts_20261010','source_identity':{'source_id':'legal_source_script_362_and_current_human_feedback','sha256':control.digest(source_script)},
  'characters':[{'character_id':'xiaolin','name':'小林（虚构劳动者）','role':'被公司要求离开的员工，想让对方回答为什么把公司决定写成自己辞职，拒绝违背真实意愿签字'},{'character_id':'zhou','name':'周姐（虚构人事主管）','role':'代表公司办理离开手续，想拿到签名；公司催办失败后换成个人交差请求'}],
  'scenes':[{'scene_id':'meeting_room','description':'现有同一小会议室，两人隔桌坐着，周姐一侧有文件夹，门在她离开动线上'}],
  'facts':[{'fact_id':'F1','text':'公司要求小林离开，小林没有提出辞职。周姐在本场面先明确说出公司的决定。','participant_ids':['xiaolin','zhou']},{'fact_id':'F2','text':'自愿离职申请的原因栏已经写好个人原因，要求小林在这张申请上签名。不是空白表，不要求另写申请。','participant_ids':['xiaolin','zhou']},{'fact_id':'F3','text':'先公司办理立场劝签；小林发现原因与真实决定冲突、质问后拒绝。周姐公司办法受阻，才改为请他体谅自己、帮交差的私人请求。小林回应请求仍不签。','participant_ids':['xiaolin','zhou']},{'fact_id':'F4','text':'纸和笔只一次由周姐面前沿桌面送到小林面前靠桌沿；到位后留在那里，没有反复推向中间或推回。小林不拿笔签字。','participant_ids':['xiaolin','zhou']},{'fact_id':'F5','text':'第二次拒绝让周姐停劝，从小林面前取回未签的纸笔收入文件夹。周姐拿文件夹独自出门，小林留坐，门关后短呼一口气，争议未结束。','participant_ids':['xiaolin','zhou']},{'fact_id':'F6','text':'不增加第三人、别的场景、新道具、新劳动争议事实、合同期限、入职年份、离开日期、公司后续承诺或旁白；不作普遍赔偿或违法结论。','participant_ids':[]}],
  'initial_state':{'scene_id':'meeting_room','character_states':[{'character_id':'xiaolin','state':'坐在桌边，工牌已戴好，尚未听到周姐当面宣布决定'},{'character_id':'zhou','state':'坐在对面，准备办理公司要求离开的手续'}],'prop_states':[{'prop_id':'application','state':'面朝上放在周姐面前，原因栏已写个人原因，签名栏空白','holder_character_id':None},{'prop_id':'pen','state':'在申请旁，没有人持笔','holder_character_id':None},{'prop_id':'folder','state':'在周姐一侧，最后用来收回纸笔','holder_character_id':None}]},
  'event_chain':[{'event_id':'B1','summary':'周姐明确通知公司要求离开，随后催看材料时将纸笔一次送到小林近桌沿；小林边听边试图理解，低头看清原因栏','participant_ids':['xiaolin','zhou'],'fact_ids':['F1','F2','F4'],'scene_id':'meeting_room'},{'event_id':'B2','summary':'个人原因字样刺激小林质问，周姐以公司办理立场回避或推进；小林回应具体说法并拒签','participant_ids':['xiaolin','zhou'],'fact_ids':['F1','F2','F3'],'scene_id':'meeting_room'},{'event_id':'B3','summary':'公司劝签碰壁，周姐改求私人交差帮助；小林承认她的难处却不为公司决定写个人辞职，再次拒绝','participant_ids':['xiaolin','zhou'],'fact_ids':['F3'],'scene_id':'meeting_room'},{'event_id':'B4','summary':'因第二次拒绝，周姐停止劝签、收未签纸笔入夹独自离开；小林留坐，门关后释放紧绷','participant_ids':['xiaolin','zhou'],'fact_ids':['F4','F5'],'scene_id':'meeting_room'}],
  'ending':{'after_event_id':'B4','summary':'只有周姐带未签纸笔离开，小林仍坐着。门关后才短呼一口气，问题没有解决，拒签只完成本次选择。','participant_ids':['xiaolin','zhou'],'scene_id':'meeting_room'},
  'constraints':{'allowed_character_ids':['xiaolin','zhou'],'allowed_scene_ids':['meeting_room'],'max_duration_seconds':180,'dialogue_language':'普通话自然日常交谈，语速正常','subtitles':False}}

def prepare():
 if not (ROOT/'ANCHOR.json').exists():
  anchor=control.read(PARENT/'ANCHOR.json');ledger=control.read(PARENT/'CALL_LEDGER.json')
  if [q['ordinal'] for q in ledger['calls']]!=[378,379]:raise ValueError('exact378/379 known receipts required')
  prior=[control.read(PARENT/q['receipt']) for q in ledger['calls']]
  for row,receipt in zip(ledger['calls'],prior):
   if control.sha_file(PARENT/row['receipt'])!=row['receipt_sha256'] or receipt['status']!='contract_valid' or type(receipt['response_metadata']['total_tokens']) is not int:raise ValueError('known parent response changed')
  s=control.read(SOURCE/'DELIVERABLE/FULL_SCRIPT.json');archive_direction=control.read(SOURCE/'DIRECTION.json')
  old=control.read(PARENT/'INPUT.json');receipt=control.read(VIDEO/'receipt.json')
  if receipt['task_id']!='cgt-20261010140842-lzc58' or control.sha_file(receipt['video_path'])!=receipt['video_sha256']:raise ValueError('user feedback video identity differs')
  feedback={'schema':'natural_interaction_human_feedback/v1','user_statement':USER,'source_script_ordinal':362,'source_script_sha256':control.digest(s),'source_video_task_id':receipt['task_id'],'source_video_sha256':receipt['video_sha256'],'video_human_approval':False,'source_of_actual_fast_speech_judgment':'human_feedback_only','assistant_viewed_or_listened':False,'must_fix':['normal conversational delivery, remove faster directive','source-authorized speech/actions/listener expression can overlap','natural responsive dialogue and character tactics instead of explanatory monologues'],'formal_binary_review_not_invented':True,'new_media_authorized':False}
  brief=current_brief(s)
  projection=project_current_brief(brief,archive_direction)
  d={'schema':'current_revision_direction/v1','current_brief_identity':projection['identity'],'characters':[{'name':c['name']} for c in brief['characters']]}
  x={'source_direction':d,'current_projection':projection,'reference_fulltext':old['reference_fulltext'],'feedback':feedback,
     'functional_revision_goals':old['functional_revision_goals'],
     'legal_expression_boundaries':['只展示本次虚构事件和当事人的选择，不作裁判、赔偿金额或拒签必胜结论','法律研究内容与元数据提案不是本次剧情事实，角色不说法律免责声明，不新增旁白'],
     'prior_findings':['此前真实请求同时携带旧咖啡社保剧情提案和当前确认事实，造成相互矛盾；本次实际创作输入已完全移除旧提案正文','当前要解决自然应答与并行行为，不新增事件或道具，不复制旧整稿台词']}
  x['draft_to_replace_not_facts']=control.read(PARENT/'FULL_MODEL_SCRIPT.json')
  x['independent_editorial_revision']=control.read(PARENT/'INDEPENDENT_EDITORIAL_GATE.json')
  if x['independent_editorial_revision']['script_sha256']!=control.digest(x['draft_to_replace_not_facts']):raise ValueError('same-source editorial issues required')
  control.write(ROOT/'CURRENT_BRIEF.json',brief,True)
  control.write(ROOT/'INPUT_PROJECTION.json',projection,True)
  control.write(ROOT/'INPUT.json',x,True);control.write(ROOT/'USER_FEEDBACK.json',feedback,True)
  original=PROJECT/'data/production_revisions/legal_dialogue_refinement_20261009/round_19/call_362_craft_draft_r19.json'
  control.write(ROOT/'WRITER_SCHEMA.json',control.read(original)['request']['structured_schema'],True)
  files=[*[PARENT/q['receipt'] for q in ledger['calls']],PARENT/'FULL_MODEL_SCRIPT.json',PARENT/'INDEPENDENT_EDITORIAL_GATE.json',PROJECT/'scripts/run_legal_natural_dialogue_revision_v4_20261010.py',PARENT/'INPUT_PROJECTION.json',PARENT/'ACTUAL_REQUEST_PROJECTION_CHECK.json',PROJECT/'scripts/run_legal_natural_dialogue_revision_v2_20261010.py',PROJECT/'scripts/run_legal_natural_dialogue_revision_v1_20261010.py',PROJECT/'data/production_revisions/legal_natural_interaction_20261010/round_01/ANCHOR.json',PROJECT/'data/production_revisions/legal_natural_interaction_20261010/round_01/CALL_LEDGER.json',PROJECT/'data/production_revisions/legal_natural_interaction_20261010/round_01/request_previews/draft.json',PARENT/'ANCHOR.json',PARENT/'CALL_LEDGER.json',PARENT/'INPUT.json',SOURCE/'DELIVERABLE/FULL_SCRIPT.json',SOURCE/'DIRECTION.json',SOURCE/'LEGAL_CONTEXT.json',VIDEO/'PROMPT.txt',Path(receipt['video_path']),original]
  inherited=deepcopy(ledger['starting_spend']);inherited.update(calls_started=inherited['calls_started']+2,reported_tokens=inherited['reported_tokens']+sum(q['response_metadata']['total_tokens'] for q in prior),calls_with_known_usage=inherited['calls_with_known_usage']+2,parent_ledger_sha256=control.sha_file(PARENT/'CALL_LEDGER.json'))
  control.write(ROOT/'ANCHOR.json',{'schema':'natural_legal_complete_revision/v5_current_fact_full_revision','inherited':inherited,'models':ledger['model_configs'],'parent_files':{str(p):control.sha_file(p) for p in files},'automatic_retry':False,'media_authorized':False,'budget_reset':False,'old_governance_migrated':False},True)
 runtime().prepare();return summary()
def runtime():
 a=control.read(ROOT/'ANCHOR.json')
 deps=sorted((PROJECT/'src/content_factory').glob('creative_legal_dialogue_craft_v*.py'))
 own=[Path(__file__).resolve(),PROJECT/'scripts/creative_resume_dispatch_v3.py',PROJECT/'src/content_factory/creative_trend_bridge.py',PROJECT/'src/content_factory/creative_current_brief_projection_v1.py',PROJECT/'scripts/run_confirmed_legal_script_trial_v4.py',ROOT/'INPUT.json',ROOT/'USER_FEEDBACK.json',ROOT/'CURRENT_BRIEF.json',ROOT/'INPUT_PROJECTION.json',ROOT/'WRITER_SCHEMA.json',ROOT/'ANCHOR.json']+deps
 return control.ContinuationRuntime(PROJECT,ROOT,own+[Path(p) for p in a['parent_files']],a['inherited'],a['models'],inherited_guard=lambda:verify_files(a['parent_files']),quota_state=None,shared_lock=identity.SHARED_LOCK)
def summary():
 v=runtime().summary();v['unknown_token_reservations']+=control.read(ROOT/'ANCHOR.json')['inherited']['unknown_token_reservations'];v.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160]);return v
def accepted(label):
 rt=runtime();l=control.read(rt.ledger);rt.check(l);rows=[q for q in l['calls'] if q['label']==label]
 if len(rows)!=1:raise ValueError('exact original response required; no automatic dispatch')
 r=rt.effective_receipt(rows[0])
 if r['status']!='contract_valid':raise ValueError('original response rejected or unknown')
 return r
def script():return compile_writer_script(accepted('complete_natural_draft_r1')['output'],control.read(ROOT/'INPUT.json')['source_direction'])
def evidence(s):return {f"{b['id']}.S{i+1:02}":q for b in s['beats'] for i,q in enumerate(b['steps'])}
def review_schema(s):
 ref={'type':'array','minItems':1,'maxItems':len(evidence(s)),'items':{'enum':list(evidence(s))}}
 finding={'type':'object','additionalProperties':False,'required':['problem','required_revision','evidence_refs'],'properties':{'problem':{'type':'string','minLength':1},'required_revision':{'type':'string','minLength':1},'evidence_refs':ref}}
 fields={'full_review_complete':{'const':True},'story_invariants_preserved':{'type':'boolean'},'dialogue_and_character_tactics':{'type':'string','minLength':1},'causal_and_physical_assessment':{'type':'string','minLength':1},'parallel_interaction_assessment':{'type':'string','minLength':1},'evidence_refs':ref,'issues':{'type':'array','items':finding},'suggestions':{'type':'array','items':{'type':'string'}},'assessment':{'type':'string','minLength':1}}
 return {'type':'object','additionalProperties':False,'required':list(fields),'properties':fields}
def dispatch(stage):
 prepare();x=control.read(ROOT/'INPUT.json');m=control.read(ROOT/'ANCHOR.json')['models']
 if stage=='draft':
  schema=control.read(ROOT/'WRITER_SCHEMA.json')
  payload={'authoring':deepcopy(x['current_projection']['writer_context']),'reference_fulltext':x['reference_fulltext'],'feedback':x['feedback'],'functional_revision_goals':x['functional_revision_goals'],'legal_expression_boundaries':x['legal_expression_boundaries'],'draft_to_replace_not_facts':x['draft_to_replace_not_facts'],'independent_editorial_revision':x['independent_editorial_revision']}
  verify_writer_request(payload['authoring'],x['current_projection'])
  rule='MiniMax编剧。只以authoring.current_brief作为本次剧情事实，根据independent_editorial_revision，重新提交同一两人辞职场面的完整新稿。draft_to_replace_not_facts是被拒的完整稿，不是事实来源；其中有期限等错误须删除，不能照抄。优先解决重复追问：周姐已明确公司决定后，小林不再问是谁要走。看到个人原因后先质问，周姐以统一表格回避时，下一句要真正顶住这个理由，令她公司办法失效；她才转个人请求。允许短暂动作与情绪打断连说，别把每轮写成解释三遍主题。让每句对白成为人物对对方采取的行动：推动签名、绕开问题、逼对方回答、求情、守住自己的立场。对方上一句话改变下一句话的说法；不要反复解释主题或替角色解说法律。小林看到原因栏时由不相信转为委屈急切，他在说话中盯住对方争取回答；周姐起初按公司办理习惯推进，碰壁后才私人请求，不写成纯口号坏人。日常普通话交谈，有口语停连，精简空档而不加速。每句话独立dialogue项，action不能藏实际发言；催看表时可同时送纸，但公司决定先说清、纸到位后才读字。动作写人物的目标和变化，不写微动作清单或逐秒。仅参考功能性目标，不必增加重复催签。私人求助后的回答对准她当前求助，不写连续三句普遍道理。完整R01只借表达机制，不照搬剧情。只用submit_creative_json返回完整title/premise/beats，有序四拍B1-B4和各拍event/trigger/steps；不交补丁、不分析。'
  label='complete_natural_draft_r1';role='writer';cap=4500
  def validator(v):
   Draft202012Validator(schema).validate(v);c=compile_writer_script(v,x['source_direction'])
   for beat in c['beats']:
    for step in beat['steps']:
     if step['kind']=='action' and re.search(r'(?:说|道)[“\"]',step['text']):raise ValueError('spoken line hidden in action; all dialogue must have its own source')
   return {**validate_complete_story(c,x['source_direction']),'full_model_script':True,'script_sha256':control.digest(c),'creative_content_changed_locally':False,'creative_quality_passed':False}
 elif stage=='review':
  s=script();schema=review_schema(s);payload={'authoring':deepcopy(x['current_projection']['writer_context']),'reference_fulltext':x['reference_fulltext'],'feedback':x['feedback'],'functional_revision_goals':x['functional_revision_goals'],'legal_expression_boundaries':x['legal_expression_boundaries'],'full_current_script':s,'source_catalog':evidence(s),'prior_editorial_required_changes':x['independent_editorial_revision']['unresolved_mandatory_findings']}
  verify_writer_request(payload['authoring'],x['current_projection'])
  rule='DeepSeek全文文本审查。只通过submit_creative_json输出完整审查。完整当前新稿每拍逐句阅读，以authoring.current_brief核对当前剧情事实，不能用旧提案代替；检查每项事实/起态/四个事件及结尾、双方目标与策略换招、自然应答、情绪刺激反应、并行动作可行性、纸笔一次递出和从同处未签取回、只周姐离开小林留坐。是否符合用户反馈必须引用当前新稿，不把旧问题自动套进新稿。真实矛盾/导致观众无法理解的缺失列issues；审美增强/实际视频未知列suggestions，不能强制再塞泛结束语或字数规则。全文复审不验证真实语速、演技或观众感受，不改源稿。'
  label='complete_natural_review_r1';role='director';cap=5500
  def validator(v):
   Draft202012Validator(schema).validate(v)
   return {'full_review_complete':v['full_review_complete'],'script_sha256':control.digest(s),'needs_revision':bool(v['issues']) or not v['story_invariants_preserved'],'creative_quality_passed':False}
 else:raise ValueError('explicit stage required')
 req={'role':role,'model':m[role]['model'],'messages':[{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],'structured_schema':schema,'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},'input_provenance':{'operator_version':'natural_legal_complete_revision/v5_current_fact_full_revision','reference_fulltext_sha256':control.digest(x['reference_fulltext']),'reference_fulltext_in_actual_messages':True,'feedback_sha256':control.digest(x['feedback']),'previous_complete_script_in_actual_messages':stage=='draft','previous_draft_is_rejected_not_factual_authority':True,'archived_direction_body_in_actual_messages':False,'full_legal_research_in_actual_messages':False,'current_brief_identity':x['current_projection']['identity'],'current_brief_projection_exactly_checked':True,'source_context_sha256':control.digest(payload),'new_video_authorized':False,'server_strict_generation_claimed':False}}
 control.write(ROOT/'request_previews'/f'{stage}.json',req,True)
 r=runtime().dispatch(label,req,validator)
 if stage=='draft' and r['status']=='contract_valid':
  control.write(ROOT/'FULL_MODEL_SCRIPT.json',script(),True)
  write_readable(ROOT/'FULL_SCRIPT_DRAFT.md',render_script(script(),'完整MiniMax新稿；待全文复审和用户内容核对。旧视频不续段。'))
 control.write(ROOT/'STATUS.json',{'stage':stage,'ordinal':r['ordinal'],'status':r['status'],'spend':summary(),'new_media_calls':0,'quality_passed':False})
 return {'ordinal':r['ordinal'],'status':r['status'],'validation':r.get('validation'),'failure':r.get('failure'),'validation_error':r.get('validation_error'),'spend':summary()}
def write_readable(p,s):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists() and p.read_text(encoding='utf-8')!=s:raise ValueError('immutable readable text changed')
 if not p.exists():p.write_text(s,encoding='utf-8')
def finish():
 s=script();d=accepted('complete_natural_draft_r1');r=accepted('complete_natural_review_r1')
 if r['validation']['needs_revision']:raise ValueError('whole review unresolved; cannot label candidate ready')
 gate=control.read(ROOT/'INDEPENDENT_EDITORIAL_GATE.json')
 if gate.get('script_sha256')!=control.digest(s) or gate.get('text_candidate_qualified') is not True or gate.get('unresolved_mandatory_findings')!=[]:raise ValueError('independent current-source editorial gate unresolved')
 out=ROOT/'REVIEWED_CANDIDATE'
 for name,val in [('FULL_SCRIPT.json',s),('RAW_MODEL_SCRIPT.json',d['output']),('FULL_TEXT_REVIEW.json',r['output']),('USER_FEEDBACK.json',control.read(ROOT/'USER_FEEDBACK.json')),('INDEPENDENT_EDITORIAL_GATE.json',gate),('CURRENT_BRIEF.json',control.read(ROOT/'CURRENT_BRIEF.json'))]:control.write(out/name,val,True)
 write_readable(out/'FULL_SCRIPT.md',render_script(s,'MiniMax完整新稿已完成DeepSeek全文复审；待用户内容核对。并行表演与新视频未完成，创作质量未批准。'))
 control.write(out/'HANDOFF.json',{'status':'complete_reviewed_text_awaiting_human_content_confirmation','draft_ordinal':d['ordinal'],'review_ordinal':r['ordinal'],'script_sha256':control.digest(s),'raw_creative_sha256':control.digest(d['output']),'creative_text_changed_locally':False,'old_director_performance_and_video_invalidated_for_new_script':True,'new_director_and_performance_built':False,'human_quality_approved':False,'video_calls':0,'spend':summary()},True)
 return {'candidate':str(out/'FULL_SCRIPT.md'),'draft_ordinal':d['ordinal'],'review_ordinal':r['ordinal'],'spend':summary()}
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','draft','review','finish','status']);a=ap.parse_args()
 print(json.dumps(prepare() if a.stage=='prepare' else summary() if a.stage=='status' else finish() if a.stage=='finish' else dispatch(a.stage),ensure_ascii=False),flush=True)
