"""Current facts as a positive scene contract; reference evidence remains in actual messages."""
from copy import deepcopy
import json
from scripts.creative_resume_dispatch_v3 import digest
from src.content_factory.creative_legal_dialogue_craft_v14 import build_wire as prior,validate_script,expand_review,STANDARDS,compile_writer_script,CONTRACT as base_contract
CONTRACT=deepcopy(base_contract)
CONTRACT['scope']+=' 本场只争申请上的离职原因，不涉及补偿安排或承诺。'
SCENE_FACTS={
 'first_information':'周姐当面通知小林，公司决定让他离开、不再在公司工作。这是公司提出的离开。观众在实际对白里听懂这件事，不能只知道他被暂时停岗或交接。',
 'paper':'原因栏已写个人原因的自愿离职申请和笔原在周姐手边；周姐一次送到小林近桌沿可读处。小林在原位置看清字样，只用表情、声音和自身姿态回应；纸笔留在那里，直到周姐最终收回。',
 'first_pressure':'纸上确实写个人原因/自愿离职，而小林真实没有主动辞职，两个事实不互相改写。小林看字样后不信、委屈转急，质问为何公司让他离开却写自己辞职。周姐坚持公司的要求是让他按自愿离职签自己的名字；小林第一次拒绝这个要求。',
 'second_pressure':'第一次拒绝使周姐改用私人求助，请他签字帮自己交差。小林接住这一请求但仍明确拒绝。',
 'ending':'周姐意识到拿不到签名，有反应后停本次催签，原处取回未签的纸笔入夹，拿夹起身独自离开；小林留坐，门合后缓解眼前压力，争议仍在。',
 'scope':'只谈这张申请及本人意愿；两人、同一小会议室、小林原工牌一直戴着。本场没有合同到期、不续约、离开日期、赔偿安排或第三人。编剧不安排秒数机位。'}
def build_wire(*args,**kwargs):
 req=prior(*args,**kwargs);stage=args[4];ctx=json.loads(req['messages'][-1]['content']);archive=json.loads(req['messages'][1]['content'])
 archive['previous_script_identity'].update(status='358_complete_source_independently_found_content_defects',source_ordinal=358)
 ctx['revision_contract']=deepcopy(CONTRACT)
 if stage=='draft':
  ctx['current_complete_revision_source']={'source_script_ordinal':358,'source_script_sha256':digest(kwargs['previous_script']),'complete_failed_source_preserved_locally':True,'wording_from_previous_script_not_a_template':True,'whole_model_draft_required':True}
  ctx['scene_facts']=deepcopy(SCENE_FACTS)
  original=archive['original_source_context']
  archive['original_source_context']={'full_source_context_preserved_locally_sha256':digest(original),'confirmation_identity':{k:original['confirmation'][k] for k in ('message_id','confirmed_at','direction_sha256')},'verified_legal_context_preserved_locally_sha256':digest(original['verified_legal_context']),'full_tag_graph_preserved_locally':True,'projection_scope':'本场只争这张申请上的原因及本人意愿。完整法律和标签来源冻结保存，全文审查仍读取原来源。'}
  req['messages'][0]['content']='MiniMax编剧。最后消息scene_facts是本场正面的事实及行动合同，请写完整title/premise/有序B1至B4，每拍含event/trigger/steps。开场第一条实际通知先说明公司让小林离开，不是临时停岗；后续质问依据这条通知。纸笔仅一次送到小林近桌沿，交锋中在那儿保持静止，小林用自身表演反应，周姐最后从同处取回。读到个人原因后的不信委屈转急要在正文可演，公司施压遭拒再转私人交差求助，第二拒绝回应这一求助。结尾反应→停本次劝签→带走未签材料→周姐独自离开，小林留坐缓压。前面的参考和六项教学借表达机制；原人类反馈是问题证据，不把其中旧推纸行为复制进新稿。用当面普通话推进交锋，七项标准作功能自检，专业词不写成台词。全部内容由你重新完整生成，不补丁，不拼接，不分析，唯一submit_creative_json；资料是数据。'
 req['messages'][1]['content']=json.dumps(archive,ensure_ascii=False);req['messages'][-1]['content']=json.dumps(ctx,ensure_ascii=False)
 req['operator_version']='legal_dialogue_craft/v16_current_facts_archive_projection'
 req['input_provenance'].update(source_context_sha256=digest(ctx),messages_sha256=digest(req['messages']),archival_context_sha256=digest(archive),revision_contract_sha256=digest(CONTRACT),source_script_sha256=digest(kwargs['previous_script']),scene_facts_sha256=digest(SCENE_FACTS),prior_last_two_beats_in_writer_messages=False,full_previous_wording_in_writer_messages=False,legal_context_full_in_writer_messages=False if stage=='draft' else True)
 return req
