"""Preserve the exact local validation schema in the model's document contract."""
from copy import deepcopy
from scripts import step_index_physical_adapter_v5 as base
from src.content_factory.creative_stage_contracts import digest
VERSION='step_index_full_validation_schema_adapter_v6'

def __getattr__(name):return getattr(base,name)

def build_local_schema(local_input):
    if local_input.get('schema')!=base.INPUT:base.fail('STEP_PHYSICAL_INPUT','输入须来自build_local_input')
    result=deepcopy(base._local_schema(local_input['context'],local_input['direction'],local_input['shot_id'],digest(local_input)))
    result['description']=base.RULES
    return result
