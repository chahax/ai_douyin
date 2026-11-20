"""A source-bound ending revision; all creative text stays model-authored."""
from copy import deepcopy
import json
from scripts.creative_resume_dispatch_v3 import digest
from src.content_factory.creative_legal_dialogue_craft_v8 import (
 build_wire as prior, validate_script, expand_review, STANDARDS,
 CONTRACT as prior_contract, compile_writer_script,
)
CONTRACT=deepcopy(prior_contract)
CONTRACT['B4']='私人求助再次遭拒后，周姐有可读的承受、判断或语气变化，决定这次停止催签；她收回未签纸笔入夹，拿夹起身独自出门。退出话与行动承接当次未拿到签名，不像手续办妥。小林留坐，门合后缓过眼前压力，争议未解决。'
ENDING_TARGET='私人求助失败→周姐判断继续劝签无果并暂时结束→未签材料带走→门合、小林眼前压力解除。通过实际正文体现转变，允许沉默或行动作答，不指定叹气苦笑、不加第三轮催签或最终公司处置，也不以泛泛以后再说代替当前结果。'
def build_wire(*args,**kwargs):
 req=prior(*args,**kwargs)
 ctx=json.loads(req['messages'][-1]['content'])
 archive=json.loads(req['messages'][1]['content'])
 archive['previous_script_identity']['status']='reviewed_complete_source_requiring_ending_revision_not_human_adopted'
 req['messages'][1]['content']=json.dumps(archive,ensure_ascii=False)
 ctx['revision_contract']=deepcopy(CONTRACT)
 ctx['current_complete_revision_targets']['ending_closure']=ENDING_TARGET
 ctx['ending_review_qualification']='检查言语行为中的退出动机、话轮衔接、反应可演性和释放范围。自然省略可由道具与人物目标恢复即成立，不因没有指定停顿或没说明下一步判失败；必修须给当前全文实际引用和功能损失，审美建议分列，不预设通过。'
 if args[4]=='draft':
  source=deepcopy(kwargs['previous_script'])
  ctx['current_complete_revision_source']={'source_script_sha256':digest(source),'previous_valid_complete_script':source,'source_status':'complete_text_user_requested_ending_revision_not_human_adopted','scope':'围绕最后拒绝到停止劝签的衔接修整完整标题梗概四拍；保留前面已清楚的交锋，不复用更早的错误稿。全部字段由模型完整提交，不交补丁。'}
  req['messages'][0]['content']+=' 本轮当前完整正文见最后消息current_complete_revision_source，主要返修结尾，保留前面已清楚的两层压力与拒绝。不预写固定台词，不凑反应动作。完整稿的event/trigger/steps与梗概共同承接周姐停止劝签的选择；无需新增处罚、公司最终结果、电话或第三人。'
 else:
  req['messages'][0]['content']+=' 本轮必须在七项标准中具体检查ending_closure：私人求助失败后停止劝签的可读转变、未签材料被带走的局部结果，以及门合后释放的范围。审查当前完整script，不拿旧352零问题作新稿放行；退出不要求说明全部后续，也不能凭梗概标签替代正文因果。仍只返回原三块审查对象，不增加新字段。'
 req['messages'][-1]['content']=json.dumps(ctx,ensure_ascii=False)
 req['operator_version']='legal_dialogue_craft/v9_source_bound_ending_closure'
 req['input_provenance'].update(source_context_sha256=digest(ctx),archival_context_sha256=digest(archive),messages_sha256=digest(req['messages']),revision_contract_sha256=digest(CONTRACT),current_revision_targets_sha256=digest(ctx['current_complete_revision_targets']),current_valid_complete_script_in_writer_messages=args[4]=='draft',current_valid_script_sha256=digest(kwargs['previous_script']),historical_failed_script_in_actual_messages=False,ending_check_uses_existing_seven_criteria=True)
 return req
