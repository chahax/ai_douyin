"""Lossless request schema factoring; enum members and constraints stay intact."""
from collections import Counter
from copy import deepcopy
import hashlib,json


def compact_enums(schema):
    counts=Counter();values={}
    def key(node):
        if isinstance(node,dict) and 'enum' in node and '$ref' not in node:
            encoded=json.dumps(node,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            if len(encoded.encode('utf-8'))>=160:return encoded
        return None
    def scan(node):
        k=key(node)
        if k is not None:counts[k]+=1;values[k]=node;return
        if isinstance(node,dict):
            for v in node.values():scan(v)
        elif isinstance(node,list):
            for v in node:scan(v)
    scan(schema)
    selected={k:'shared_enum_'+hashlib.sha256(k.encode()).hexdigest()[:16] for k,n in counts.items() if n>1}
    if any(name in schema.get('$defs',{}) for name in selected.values()):raise ValueError('schema_projection_definition_collision')
    def rewrite(node):
        k=key(node)
        if k in selected:return {'$ref':'#/$defs/'+selected[k]}
        if isinstance(node,dict):return {k:rewrite(v) for k,v in node.items()}
        if isinstance(node,list):return [rewrite(v) for v in node]
        return deepcopy(node)
    result=rewrite(schema)
    if selected:result.setdefault('$defs',{}).update({name:deepcopy(values[k]) for k,name in selected.items()})
    return result
