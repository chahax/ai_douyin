"""Source-specific SH06 operation constraints, never repair a model output."""
from copy import deepcopy
VERSION='s7_sh06_source_event_policy/v1'

def restrict_schema(schema,inp):
 result=deepcopy(schema)
 if inp['shot_id']!='SH06':return result
 raw=inp['context']['raw_linear_script'];b=raw['beats'][5]
 if b['id']!='B06' or len(b['steps'])!=2 or any(x['kind']!='action' for x in b['steps']):raise ValueError('policy source changed')
 if not all(s in b['steps'][0]['text'] for s in ('看了一眼','挎包','又看回','客户明细单')) or not all(s in b['steps'][1]['text'] for s in ('右手','收回','结算单')):raise ValueError('source no longer supports policy')
 actions=result['properties']['actions']['prefixItems'];base=actions[0]['properties']['events']['items']
 ops=[None,{'kind':'gaze','actor':'C02','target':'','value':'at_P01_on_E09_backrest'},{'kind':'gaze','actor':'C02','target':'','value':'at_E02_P03_Y_and_P05'}]
 req=next(s for b in inp['direction']['beats'] for s in b['shots'] if s['shot_id']=='SH06')['performance_requirements'];window=[q['id'] for q in req if q['subject']=='C02' and q['relation']=='after']
 if len(window)!=1:raise ValueError('source-bound listener window required')
 def event(op,ids):
  v=deepcopy(base);v['properties']['subject']={'const':'C02'};v['properties']['operation']={'const':op};v['properties']['satisfies']={'const':ids};return v
 actions[0]['properties']['events']={'type':'array','minItems':3,'maxItems':3,'prefixItems':[event(op,window if i==0 else []) for i,op in enumerate(ops)],'items':False}
 actions[1]['properties']['events']={'type':'array','minItems':1,'maxItems':1,'prefixItems':[event(None,[])],'items':False}
 return result
