"""A single qualified full review on unchanged whole writer output; no content rewrite."""
from copy import deepcopy
import json
from scripts.creative_resume_dispatch_v3 import digest
from src.content_factory.creative_legal_dialogue_craft_v19 import build_wire as prior,validate_script,expand_review,STANDARDS,CONTRACT as base_contract,compile_writer_script
CONTRACT=deepcopy(base_contract)
CONTRACT['review_qualification']+=' 通知判语义明确而非指定词组；公司+小林+在此工作结束已足以说明公司决定，追问辞退性质或不信不等于通知缺失。暂停填写不指定材料归属；只有当前真的提出留表才与带走有冲突，不能从今天先不写推断留给对方。全文实际回收与持有动作也作为依据，不逐字追溯。'
def build_wire(*args,**kwargs):
 if args[4]!='review':raise ValueError('v20 one qualified same-source full review only; no writer dispatch')
 req=prior(*args,**kwargs);ctx=json.loads(req['messages'][-1]['content']);a=json.loads(req['messages'][1]['content'])
 a['previous_script_identity'].update(status='362_unchanged_complete_source_single_review_qualification',source_ordinal=362)
 ctx['revision_contract']=deepcopy(CONTRACT)
 ctx['current_review_objection_qualification']={'previous_review_ordinal':363,'not_an_instruction_to_pass':True,'semantic_first_information':'判断公司、对象、工作结束三项能否从当前通知理解。辞退性质的追问不自动否定通知，语义可追溯不等于逐字复述。旧结束语缺对象的事实不得外推到已给工作对象的新句。','material_ownership':'区分暂停写/签与把纸留给小林的指令。看当前实际回收带走动作；旧361留表措辞不在当前文本，不能继承旧矛盾。','whole_review':'保留全稿所有标准、情绪及物理检查；真有新缺陷给当前引用和功能损失，不预设零问题、不改稿。'}
 req['messages'][0]['content']+=' 按current_review_objection_qualification完整复核，不继承旧363结论，不把更直白的审美偏好升成必修。自然表达允许，不能仅因含到此为止或先不写判缺失/留表。真实缺陷照列，已有检查结果放satisfied，不修改源。'
 req['messages'][1]['content']=json.dumps(a,ensure_ascii=False);req['messages'][-1]['content']=json.dumps(ctx,ensure_ascii=False)
 req['operator_version']='legal_dialogue_craft/v20_single_qualified_same_source_full_review'
 req['input_provenance'].update(source_context_sha256=digest(ctx),archival_context_sha256=digest(a),messages_sha256=digest(req['messages']),revision_contract_sha256=digest(CONTRACT),review_qualification_sha256=digest(ctx['current_review_objection_qualification']))
 return req
