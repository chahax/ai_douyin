"""Inline Pydantic schema references without changing validation semantics."""
from copy import deepcopy
def inline_schema(schema):
    definitions=schema.get('$defs',{})
    def walk(v,stack=()):
        if isinstance(v,list):return [walk(x,stack) for x in v]
        if not isinstance(v,dict):return v
        if '$ref' in v:
            key=v['$ref'].removeprefix('#/$defs/')
            if key not in definitions or key in stack:raise ValueError('unsupported_schema_ref')
            merged=deepcopy(definitions[key]);merged.update({k:x for k,x in v.items() if k!='$ref'})
            return walk(merged,(*stack,key))
        return {k:walk(x,stack) for k,x in v.items() if k!='$defs'}
    return walk(schema)
