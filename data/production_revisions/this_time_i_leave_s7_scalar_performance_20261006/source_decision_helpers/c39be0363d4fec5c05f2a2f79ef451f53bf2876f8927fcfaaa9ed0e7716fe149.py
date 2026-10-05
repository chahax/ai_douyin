"""Structural source decision for a complete zero-action dialogue plan."""
from copy import deepcopy
from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_local_event_performance_v3 as split
from scripts import step_index_physical_adapter_v5 as physical
from jsonschema import Draft202012Validator


def build(record,inp):
 if record.get('status')!='contract_valid' or record['output']!={'actions':[]}:raise ValueError('actual complete zero-action model plan required')
 prov=record['request']['input_provenance']
 if prov.get('local_input_sha256')!=control.digest(inp) or prov.get('raw_script_sha256')!=control.digest(inp['context']['raw_linear_script']):raise ValueError('source/start-state binding changed')
 Draft202012Validator(split.plan_schema(inp)).validate(record['output'])
 shot=split.focus(inp)['current_shot'];sources=physical._raw_sources(inp['context']);refs=shot['source_step_refs']
 if not refs or any(sources[ref]['kind']!='dialogue' for ref in refs):raise ValueError('zero-action decision only for original dialogue-only shot')
 evidence=[{'path':ref+'.text','quote':sources[ref]['text'],'finding':'本镜完整原对白；没有原action，不为填字段新增动作。'} for ref in refs]
 return {'approved_for_performance_text':True,'plan_sha256':control.digest(record['output']),'evidence':evidence,'evidence_source':'actual original context leaves, not fabricated leaves of empty plan','zero_action_source_proof':{'submitted_actions':[],'original_action_source_refs':[],'original_dialogue_refs':deepcopy(refs),'local_input_sha256':control.digest(inp)},'actual_timing_verified':False,'human_quality_approval':False,'model_output_manually_patched':False}
