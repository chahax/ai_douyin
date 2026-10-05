"""Explicit simultaneous operations for the registered three-note bundle only."""
from copy import deepcopy
from jsonschema import Draft202012Validator
from scripts import creative_compact_local_contract_v2 as single
from scripts import creative_compact_local_contract_v1 as prior
VERSION='synchronous_registered_note_bundle/v3'
MEMBERS={'P03_Y','P03_P','P03_B'}

def batch_schema(inp):
    chars=[c['id'] for c in inp['context']['static_visual_manifest']['characters']]
    return {'type':'array','minItems':3,'maxItems':3,'items':{'type':'object','properties':{'kind':{'enum':['take','place']},'actor':{'enum':chars},'target':{'enum':sorted(MEMBERS)},'value':{'type':'string','minLength':1}},'required':['kind','actor','target','value'],'additionalProperties':False}}

def build_schema(inp):
    result=single.build_schema(inp)
    group=result['properties']['actions']['items']['properties']['groups']['items']
    group['properties']['operation']['anyOf'].append(batch_schema(inp))
    result['description']+=' 同叠三色便利贴可用三项operation数组表示同一事件同步取或同步放；成员齐全、同人物、同kind。取与放仍前后两个事件，不允许同组先取后放。'
    return result

def validate_batch(operations,ref,inp):
    if {x['target'] for x in operations}!=MEMBERS or len(operations)!=3:raise ValueError('batch must contain exactly the three registered note members')
    if len({x['kind'] for x in operations})!=1 or len({x['actor'] for x in operations})!=1:raise ValueError('batch must have one actor and one simultaneous kind')
    if {p['id'] for p in inp['context']['static_visual_manifest']['props']} & MEMBERS != MEMBERS:raise ValueError('all note members must be registered')
    source=prior.base._raw_sources(inp['context'])[ref]['text']
    if not all(word in source for word in ('便利贴','浅黄','浅粉','浅蓝')):raise ValueError('batch requires the original complete three-note action')
    if operations[0]['kind']=='take' and len({x['value'] for x in operations})!=1:raise ValueError('whole bundle must be taken into the same holding position')
    if operations[0]['kind']=='place':
        faces=[x['value'].split(':') for x in operations]
        if any(len(x)!=3 or x[0]!='surface' for x in faces) or len({x[1] for x in faces})!=1:raise ValueError('whole bundle must be placed on the same registered support')

def derive_local(doc,inp):
    Draft202012Validator(build_schema(inp)).validate(doc)
    projected=deepcopy(doc)
    for action in projected['actions']:
        for group in action['groups']:
            op=group.pop('operation')
            if isinstance(op,list):validate_batch(op,action['source_step_ref'],inp);ops=op
            else:ops=[] if op is None else [op]
            group['operations']=[[x[k] for k in ('kind','actor','target','value')] for x in ops]
    return prior.derive_local(projected,inp)
