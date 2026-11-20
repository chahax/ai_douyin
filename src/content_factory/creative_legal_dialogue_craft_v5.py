"""Fresh complete authoring from confirmed facts without failed dialogue priming.

Old scripts remain frozen and identity-bound locally. Reference, teaching and
human feedback still enter actual requests. Review remains a full-source gate.
"""
import json
from scripts.creative_resume_dispatch_v3 import digest
from src.content_factory.creative_legal_dialogue_craft_v4 import build_wire as prior,validate_script,expand_review,STANDARDS,CONTRACT

def build_wire(*args,**kwargs):
 req=prior(*args,**kwargs);archive=json.loads(req['messages'][1]['content'])
 previous=archive.pop('previous_complete_script')
 archive['previous_script_identity']={'sha256':digest(previous),'status':'historical_failed_complete_text_preserved_locally','consumed_as_dialogue_template':False}
 archive['role']='完整参考、教学、实际人类反馈与原来源资料。历史错稿保留在本地，仅携带SHA；本次从当前事实重新创作完整正文。当前要求见最后一条任务消息。'
 req['messages'][1]['content']=json.dumps(archive,ensure_ascii=False)
 req['operator_version']='legal_dialogue_craft/v5_fresh_complete_authoring'
 pr=req['input_provenance'];pr.update(archival_context_sha256=digest(archive),messages_sha256=digest(req['messages']),historical_failed_script_in_actual_messages=False,complete_source_output_required=True,source_omission_is_explicit_not_silent=True)
 return req
