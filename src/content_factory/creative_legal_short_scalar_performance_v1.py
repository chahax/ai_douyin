"""Keyed original-source objects on wire; unchanged canonical performance values."""
from copy import deepcopy
import re
from jsonschema import Draft202012Validator
from src.content_factory import creative_legal_short_director_performance_v1 as base
VERSION='legal_keyed_beat_performance/v2'
def key(ref):return ref.replace('.','_')
def schema(script,beat):
 canon=base.performance_schema(script,beat)
 props={'beat_id':deepcopy(canon['properties']['beat_id']),'start_state':base.state_schema(),'end_state':base.state_schema()}
 catalog=base.catalog(script)
 for row in canon['properties']['rows']['prefixItems']:
  ref=row['properties']['source_ref']['const'];r=deepcopy(row);del r['properties']['source_ref'];r['required'].remove('source_ref')
  changes={'type':'object','additionalProperties':False,'properties':{f:base.obj({'from':{'enum':values},'to':{'enum':values}}) for f,values in base.STATE_VALUES.items()}}
  if catalog[ref]['kind']=='dialogue':
   changes['maxProperties']=0
   n=len(re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]','',catalog[ref]['text']))/5
   r['properties']['active_seconds']={'type':'number','minimum':n,'maximum':12}
  r['properties']['state_changes']=changes;props[key(ref)]=r
 return base.obj(props)
def expand(raw,script,beat):
 Draft202012Validator(schema(script,beat)).validate(raw)
 result={k:deepcopy(raw[k]) for k in ('beat_id','start_state','end_state')};rows=[]
 for ref in base.own_refs(script,beat):
  row=deepcopy(raw[key(ref)]);changes=row['state_changes'];row['state_changes']=[{'field':f,'from':v['from'],'to':v['to']} for f,v in changes.items()];row['source_ref']=ref;rows.append(row)
 result['rows']=rows
 Draft202012Validator(base.performance_schema(script,beat)).validate(result)
 return result
