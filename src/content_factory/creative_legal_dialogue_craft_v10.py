"""Recreate the ending from its causal purpose, isolating the failed prose template."""
from copy import deepcopy
import json
from scripts.creative_resume_dispatch_v3 import digest
from src.content_factory.creative_legal_dialogue_craft_v9 import (
 build_wire as prior,validate_script,expand_review,STANDARDS,CONTRACT,compile_writer_script,
)
def build_wire(*args,**kwargs):
 req=prior(*args,**kwargs)
 ctx=json.loads(req['messages'][-1]['content'])
 archive=json.loads(req['messages'][1]['content'])
 archive['previous_script_identity']['status']='complete_candidate_353_ending_target_not_resolved'
 if args[4]=='draft':
  current=ctx['current_complete_revision_source']
  previous=current.pop('previous_valid_complete_script')
  current.update(previous_title=previous['title'],previous_first_three_beats=deepcopy(previous['beats'][:3]),previous_fulltext_frozen_locally=True,failed_B4_prose_explicitly_omitted=True,ending_facts='周姐未拿到签名，取回未签材料独自离开；小林留坐，门合后缓过眼前压力，事情未解决。',scope='完整重写标题梗概四拍，前三拍作为已清楚的交锋依据；B4从人物当前目的重新创作，旧失败结尾只在本地保留，不沿旧句同义替换。')
  ending_feedback=archive['actual_human_feedback'].get('ending_feedback',{})
  if 'quoted_ending' in ending_feedback:
   quote=ending_feedback.pop('quoted_ending')
   ending_feedback['quoted_ending_preserved_locally_sha256']=digest(quote)
   ending_feedback['quoted_failed_ending_omitted_from_writer_not_a_template']=True
  req['messages'][0]['content']=req['messages'][0]['content'].replace('本轮当前完整正文见最后消息current_complete_revision_source','本轮前三拍依据与结尾事实见最后消息current_complete_revision_source')
  req['messages'][0]['content']+=' 本次旧B4正文显式隔离，只给前三拍交锋依据与结尾事实。小林最后拒绝之后，周姐此时想得到什么、被拒后为什么改变眼前行动，须在可演正文成立；退出的话承接这一次没有拿到签字的具体情况。不是仅改trigger或给结束句同义换词，仍由你完整重新提交全部正文。'
 ctx['current_complete_revision_targets']['ending_closure']='在steps中落实最后拒绝对周姐的作用与她暂止劝签的选择，退出的话或行动承接未拿到签名的当前情况。只写trigger判断不算正文兑现；无需增加催签轮次、表情模板、请示电话或最终处置。小林仅释放眼前压力，争议仍未解决。'
 req['messages'][1]['content']=json.dumps(archive,ensure_ascii=False)
 req['messages'][-1]['content']=json.dumps(ctx,ensure_ascii=False)
 req['operator_version']='legal_dialogue_craft/v10_failed_ending_template_isolation'
 req['input_provenance'].update(source_context_sha256=digest(ctx),user_feedback_sha256=digest(archive['actual_human_feedback']),frozen_full_user_feedback_sha256=digest(kwargs['feedback']),archival_context_sha256=digest(archive),messages_sha256=digest(req['messages']),current_revision_targets_sha256=digest(ctx['current_complete_revision_targets']),current_valid_complete_script_in_writer_messages=False,prior_first_three_beats_in_writer_messages=args[4]=='draft',failed_ending_prose_in_writer_messages=False,source_omission_is_explicit_not_silent=True)
 return req
