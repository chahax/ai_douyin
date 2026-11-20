"""Single source ownership on wire; deterministic grouping, no performance patch."""
from copy import deepcopy
from jsonschema import Draft202012Validator
from src.content_factory import creative_legal_director_performance_v1 as base
VERSION='legal_director_assignment/v2'
def schema(script):
 s=base.direction_schema(script)
 del s['properties']['shots']['items']['properties']['source_refs']
 s['properties']['shots']['items']['required'].remove('source_refs')
 rows=[base.obj({'source_ref':{'const':r},'shot_id':base.text()}) for r in base.catalog(script)]
 s['properties']['source_assignments']={'type':'array','prefixItems':rows,'items':False,'minItems':len(rows),'maxItems':len(rows)}
 s['required'].append('source_assignments');return s
def expand(raw,script):
 Draft202012Validator(schema(script)).validate(raw)
 value=deepcopy(raw);assign=value.pop('source_assignments');shotids=[s['shot_id'] for s in value['shots']]
 if len(set(shotids))!=len(shotids) or set(a['shot_id'] for a in assign)!=set(shotids):raise ValueError('unknown/orphan/duplicate shot assignment')
 for shot in value['shots']:shot['source_refs']=[a['source_ref'] for a in assign if a['shot_id']==shot['shot_id']]
 base.validate_direction(value,script)
 return value
