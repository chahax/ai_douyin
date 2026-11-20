"""Only acting/timing on model wire; source-derived coarse states compiled locally.
No action, speech or acting prose is added or repaired by this transformer.
"""
from copy import deepcopy
from jsonschema import Draft202012Validator
from src.content_factory import creative_legal_short_director_performance_v1 as base
from src.content_factory.creative_legal_short_scalar_performance_v2 import TRANSITIONS, key
VERSION='legal_short_local_state_compiler/v3'
SOURCE_SHA='2904da9d662dd3cf7c8411bf7cf4d9f763a3f7d3df35809fa064a46b893101ca'

def schema(script,beat):
 if base.digest(script)!=SOURCE_SHA:raise ValueError('state compiler belongs to exact reviewed14-step script; rederive for changed source')
 from src.content_factory.creative_legal_short_scalar_performance_v2 import schema as old_schema
 wire=old_schema(script,beat);wire['properties'].pop('start_state');wire['properties'].pop('end_state');wire['required'].remove('start_state');wire['required'].remove('end_state')
 for ref in base.own_refs(script,beat):
  p=wire['properties'][key(ref)];p['properties'].pop('state_changes');p['required'].remove('state_changes')
 return wire

def expand(raw,script,beat):
 Draft202012Validator(schema(script,beat)).validate(raw)
 state=deepcopy(base.INITIAL)
 for ref in base.catalog(script):
  if ref.startswith(beat+'.'):break
  for field,(before,after) in TRANSITIONS.get(ref,{}).items():
   if state[field]!=before:raise ValueError('derived prior source state invalid')
   state[field]=after
 result={'beat_id':beat,'start_state':deepcopy(state),'rows':[]}
 for ref in base.own_refs(script,beat):
  row=deepcopy(raw[key(ref)]);row['source_ref']=ref;row['state_changes']=[{'field':f,'from':a,'to':b} for f,(a,b) in TRANSITIONS.get(ref,{}).items()]
  state=base.apply_changes(state,row);result['rows'].append(row)
 result['end_state']=state
 Draft202012Validator(base.performance_schema(script,beat)).validate(result)
 return result
