"""Complete fresh revision for independently evidenced defects missed by review349."""
import json
from scripts.creative_resume_dispatch_v3 import digest
from src.content_factory.creative_legal_dialogue_craft_v6 import build_wire as prior,validate_script,expand_review,STANDARDS,CONTRACT
TARGETS={
 'paper_state':'纸已由周姐一次送到小林近桌沿可读处，小林在原位置读字和交锋；纸笔直到周姐取回才再次移动。小林的反应通过表情、视线、声音或自身姿态表现，不通过操作纸笔。',
 'strategy_cause':'公司要求后，小林以对白或有意义的非言语反应表示不接受；周姐因此从公司要求换成私人求助，再由小林回应该请求并坚持。摘要中的两次选择在正文有依据，不强制某个词或多一轮台词。',
 'emotional_turn':'读到个人原因是第一刺激，写出不信、委屈转急切的一个可演主反应及质问方式；听公司要求后抗辩，私人求助后转坚定。情绪由交锋推进，不只写在event，不强制哭或叠加生理动作。'}
def build_wire(*args,**kwargs):
 req=prior(*args,**kwargs);ctx=json.loads(req['messages'][-1]['content']);ctx['current_complete_revision_targets']=TARGETS
 req['messages'][-1]['content']=json.dumps(ctx,ensure_ascii=False)
 req['messages'][0]['content']+=' 本轮优先使current_complete_revision_targets在完整正文及摘要一致兑现；保留已改善的直白交锋，不扩写旧流程解释。' if args[4]=='draft' else ' 当前必须逐字检查current_complete_revision_targets对应的纸状态、策略改变原因与情绪正文，不把读纸操作自动当合理，不以摘要情绪标签证明表演。仍据实判断，不预设通过或失败。'
 req['operator_version']='legal_dialogue_craft/v7_evidenced_state_and_turn_revision'
 req['input_provenance'].update(source_context_sha256=digest(ctx),messages_sha256=digest(req['messages']),current_revision_targets_sha256=digest(TARGETS),review349_conclusions_changed=False)
 return req
