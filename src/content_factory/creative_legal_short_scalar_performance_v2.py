"""Keyed original-source objects on wire; unchanged canonical performance values."""
from copy import deepcopy
import re
from jsonschema import Draft202012Validator
from src.content_factory import creative_legal_short_director_performance_v1 as base
VERSION='legal_short_source_transition_performance/v2'
TRANSITIONS={
 'B1.S03':{'paper_location':('zhou_table_side','table_middle'),'pen_location':('zhou_table_side','table_middle')},
 'B3.S01':{'xiaolin_hands':('table_edge','knees_tense')},
 'B4.S01':{'paper_location':('table_middle','zhou_folder'),'paper_facing':('face_up','inside_folder'),'pen_location':('table_middle','zhou_folder'),'folder_location':('zhou_table_side','zhou_carried'),'zhou_position':('seated_opposite','standing')},
 'B4.S03':{'zhou_position':('standing','outside_room')},
 'B4.S04':{'xiaolin_hands':('knees_tense','knees_relaxed')}}
def key(ref):return ref.replace('.','_')
def schema(script,beat):
 canon=base.performance_schema(script,beat)
 props={'beat_id':deepcopy(canon['properties']['beat_id']),'start_state':base.state_schema(),'end_state':base.state_schema()}
 catalog=base.catalog(script)
 for row in canon['properties']['rows']['prefixItems']:
  ref=row['properties']['source_ref']['const'];r=deepcopy(row);del r['properties']['source_ref'];r['required'].remove('source_ref')
  changes=base.obj({f:base.obj({'from':{'const':values[0]},'to':{'const':values[1]}}) for f,values in TRANSITIONS.get(ref,{}).items()})
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
