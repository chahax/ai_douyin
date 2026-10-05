"""Typed full joint-review rows and string-only source quotations."""
from copy import deepcopy
from scripts import creative_review_wire_v10 as base
from scripts import creative_compact_review_transport_v8 as compact
VERSION='creative_review_wire/v12'

def schema(ctx):
    result=deepcopy(base.schema(ctx))
    text={'type':'string','minLength':1}
    pair={'type':'array','minItems':2,'maxItems':2,'prefixItems':[deepcopy(text),deepcopy(text)],'items':False}
    refs={'type':'array','items':pair,'description':'Every quote is a NONEMPTY STRING, including numeric source values: ["execution_bindings.0.start","0.0"], never an unquoted number. Reference actual scalar leaves only.'}
    check={'type':'array','minItems':4,'maxItems':4,'prefixItems':[{'enum':['pass','fail','not_applicable']},deepcopy(text),refs,{'type':'array','uniqueItems':True,'items':deepcopy(text)}],'items':False}
    rows=[{'type':'array','minItems':7,'maxItems':7,'prefixItems':[{'const':rid}]+[deepcopy(check) for _ in range(6)],'items':False} for rid in compact._rows(ctx)]
    result['properties']['coverage']={'type':'array','minItems':len(rows),'maxItems':len(rows),'prefixItems':rows,'items':False}
    result['properties']['issues']['items']['properties']['evidence_refs']=deepcopy(refs)
    return result

def format_addendum(ctx):
    return base.format_addendum(ctx)+'\n所有证据quote即使引用数值仍须是非空字符串，逐字来自该叶子的字符串表示。每行七列、每检查四列，已编码工具Schema固定位置和各项类型。suggestions仅location/proposal/reason。'
