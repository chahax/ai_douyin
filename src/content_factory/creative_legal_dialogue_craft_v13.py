"""Minimal authoring transport shape; canonical ordered full-script acceptance is unchanged."""
from copy import deepcopy
import json
from scripts.creative_resume_dispatch_v3 import digest
from src.content_factory.creative_legal_dialogue_craft_v12 import build_wire as prior,validate_script,expand_review,STANDARDS,CONTRACT as base_contract,compile_writer_script
CONTRACT=deepcopy(base_contract)
CONTRACT['factual_scope']='公司主动要求小林离开，小林没有主动辞职；提供原因栏已写个人原因的自愿离职申请。不得新增合同到期、不续约、离开日期或让小林另写申请，这些不在已确认故事中。'
def build_wire(*args,**kwargs):
 req=prior(*args,**kwargs);ctx=json.loads(req['messages'][-1]['content'])
 ctx['revision_contract']=deepcopy(CONTRACT)
 if args[4]=='draft':
  schema=deepcopy(req['structured_schema']);beats=schema['properties']['beats'];beats.pop('prefixItems')
  beats['items']['properties']['id']={'type':'string','enum':['B1','B2','B3','B4']}
  req['structured_schema']=schema
  ctx['complete_output_contract']={'root_fields':['title','premise','beats'],'beats':'有序B1/B2/B3/B4四个完整对象，每拍自己的steps放在该拍内部；不输出根级steps/item。','factual_scope':CONTRACT['factual_scope']}
 req['messages'][-1]['content']=json.dumps(ctx,ensure_ascii=False)
 req['operator_version']='legal_dialogue_craft/v13_simple_transport_ordered_local_acceptance'
 req['input_provenance'].update(source_context_sha256=digest(ctx),messages_sha256=digest(req['messages']),revision_contract_sha256=digest(CONTRACT),transport_schema_sha256=digest(req['structured_schema']),local_ordered_complete_schema_unchanged=True)
 return req
