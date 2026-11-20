"""Source identity belongs to deterministic compilation, creative text to the model."""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from scripts.creative_resume_dispatch_v3 import digest
from src.content_factory.creative_legal_dialogue_craft_v7 import build_wire as prior,validate_script,expand_review,STANDARDS,CONTRACT
from src.content_factory.creative_trend_bridge import complete_story_schema

def model_content_schema(bound_schema):
 out=deepcopy(bound_schema);out['properties'].pop('selected_candidate_id');out['required'].remove('selected_candidate_id');return out

def compile_writer_script(raw,direction):
 bound=complete_story_schema(direction)
 Draft202012Validator(model_content_schema(bound)).validate(raw)
 out=deepcopy(raw);out['selected_candidate_id']=bound['properties']['selected_candidate_id']['const']
 return out

def build_wire(*args,**kwargs):
 req=prior(*args,**kwargs);ctx=json.loads(req['messages'][-1]['content'])
 ctx['current_complete_revision_targets']['departure_state']='两人交锋时均坐着，周姐可用语气或身体靠前求助；收纸笔入夹、拿夹起身以后才独自出门。小林留坐，门合上后短暂释放。'
 if args[4]=='draft':
  req['structured_schema']=model_content_schema(req['structured_schema'])
  ctx['source_identity_owner']='本地编译器绑定已确认选题身份；模型仅返回title、premise、beats完整创作内容，不返回selected_candidate_id。'
  req['messages'][0]['content']+=' 只生成完整创作内容三项title/premise/beats；来源身份由本地绑定，不输出任何来源ID。'
 req['messages'][-1]['content']=json.dumps(ctx,ensure_ascii=False)
 req['operator_version']='legal_dialogue_craft/v8_compiler_owned_source_identity'
 req['input_provenance'].update(source_context_sha256=digest(ctx),messages_sha256=digest(req['messages']),source_identity_owned_by_deterministic_compiler=True,current_revision_targets_sha256=digest(ctx['current_complete_revision_targets']))
 return req
