"""Same-source full review with contextual qualification; prior issues stay immutable."""
import json
from scripts.creative_resume_dispatch_v3 import digest
from src.content_factory.creative_legal_dialogue_craft_v10 import (
 build_wire as prior,validate_script,expand_review,STANDARDS,CONTRACT,compile_writer_script,
)
QUALIFICATION='退出意义应结合未签材料被收回、两轮拒绝及先不写的语境判断，暂时结束现场谈话不自动等于手续办妥或劳动争议解决；仅措辞略泛可列建议。紧张依据可来自公司压力、急切质问、拒签和人物反应，不强制前段写同部位紧张姿态才允许门合后肩膀放下或呼气。自然省略和身体变化可成立，仍检查真正缺刺激、前提矛盾或误导结果；不得据本资格预设通过，问题必须给当前完整源的实质功能损失。'
def build_wire(*args,**kwargs):
 if args[4]!='review':raise ValueError('v11 only same-source full review; no writer dispatch')
 req=prior(*args,**kwargs);ctx=json.loads(req['messages'][-1]['content'])
 archive=json.loads(req['messages'][1]['content'])
 archive['previous_script_identity'].update(status='complete_354_reused_unchanged_for_full_review',source_ordinal=354)
 req['messages'][1]['content']=json.dumps(archive,ensure_ascii=False)
 ctx['revision_contract']['review_qualification']+=' '+QUALIFICATION
 ctx['ending_review_qualification']+=' '+QUALIFICATION
 req['messages'][0]['content']+=' 本轮完整正文保持不变，仅复核上次意见资格。'+QUALIFICATION+' 逐字全文、四拍覆盖、四项情绪和七项专业标准全部独立重审；不要照旧355结论复制问题，也不为了求零问题忽视真实缺陷。仍只返回原三块Schema对象。'
 req['messages'][-1]['content']=json.dumps(ctx,ensure_ascii=False)
 req['operator_version']='legal_dialogue_review/v11_contextual_mandatory_qualification'
 req['input_provenance'].update(source_context_sha256=digest(ctx),archival_context_sha256=digest(archive),messages_sha256=digest(req['messages']),revision_contract_sha256=digest(ctx['revision_contract']),review_qualification_sha256=digest(QUALIFICATION),same_complete_source_re_review=True,script_sha256=digest(kwargs['script']),previous_review_issues_modified=False)
 return req
