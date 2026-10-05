"""Context-bound evidence ID transport, following existing evidence_ids_v1.

The model selects full source leaves. Projection copies their actual complete
values; it never creates conclusions or edits performances. Business/source
validation remains unchanged after expansion.
"""
from copy import deepcopy
import re
from jsonschema import Draft202012Validator
from scripts import creative_review_wire_v18 as base
from scripts import creative_compact_review_transport_v8 as compact
VERSION='creative_review_source_ids/v19'

def id_pattern(values):
    values=list(values)
    if not values:raise ValueError('empty evidence ID set')
    prefixes={v.rsplit('-',1)[0]+'-' for v in values}
    if len(prefixes)!=1:raise ValueError('context-bound IDs required')
    def trie(words):
        if words==['']:return ''
        groups={}
        for w in words:groups.setdefault(w[0],[]).append(w[1:])
        tails={}
        for ch,rest in groups.items():tails.setdefault(trie(sorted(set(rest))),[]).append(ch)
        parts=[]
        for tail,chars in tails.items():
            chars=sorted(chars);head=chars[0] if len(chars)==1 else '['+''.join(chars)+']'
            parts.append(head+tail)
        return parts[0] if len(parts)==1 else '(?:'+'|'.join(parts)+')'
    digits=[v.rsplit('-',1)[1] for v in values]
    if any(len(d)!=4 or not d.isdigit() for d in digits):raise ValueError('four-digit catalog IDs required')
    return '^'+re.escape(next(iter(prefixes)))+trie(sorted(set(digits)))+'$'

def catalog(ctx):
    values=base.scalar_leaves(ctx);prefix='E'+compact.context_digest(ctx)[:12]+'-'
    # Duplicate prompts and unrelated reference navigation are not proof leaves.
    roots=('creative_brief.','brief.','script.','shots.','state_plan.','raw_linear_script.','execution_script.','execution_bindings.','whole_film_direction.','declared_performance_window_checks.','static_visual_manifest.')
    paths=[p for p in sorted(values) if p.startswith(roots) and not p.endswith('.prompt')]
    return {prefix+str(i+1).zfill(4):{'path':p,'quote':values[p]} for i,p in enumerate(paths)}

def schema(ctx):
    result=deepcopy(base.relation_schema(ctx));entries=catalog(ctx);result['properties']['schema']={'const':VERSION}
    result['$defs']={'EvidenceID':{'type':'string','pattern':id_pattern(entries)}};buckets={}
    refs=[result['properties']['issues']['items']['properties']['evidence_refs']]
    refs +=[c['prefixItems'][2] for row in result['properties']['coverage']['prefixItems'] for c in row['prefixItems'][1:]]
    for ref in refs:
        ref['items']={'$ref':'#/$defs/EvidenceID'}
        ref['description']='Each array item is exactly one source directory ID string, never path/quote.'
        for rule in ref.get('allOf',[]):
            path_rule=rule['contains']['prefixItems'][0]
            allowed=tuple(k for k,v in entries.items() if Draft202012Validator(path_rule).is_valid(v['path']))
            if not allowed:raise ValueError('catalog lacks a required source relation')
            if allowed not in buckets:
                name='SourceSet'+str(len(buckets)+1);buckets[allowed]=name;result['$defs'][name]={'type':'string','pattern':id_pattern(allowed)}
            rule['contains']={'$ref':'#/$defs/'+buckets[allowed]}
    return result

def expand(raw,ctx):
    if raw.get('schema')!=VERSION:raise ValueError('wrong evidence ID protocol')
    entries=catalog(ctx);out=deepcopy(raw);out['schema']=compact.VERSION
    lists=[i['evidence_refs'] for i in out['issues']]+[c[2] for row in out['coverage'] for c in row[1:]]
    for refs in lists:
        if not isinstance(refs,list) or any(not isinstance(k,str) or k not in entries for k in refs):raise ValueError('unknown/stale evidence ID or wrong type')
        refs[:]=[[entries[k]['path'],entries[k]['quote']] for k in refs]
    return out

def diagnostics(value,ctx):return base.diagnostics(value,ctx)
def validate_repair_preserves_conclusions(original,corrected):return base.validate_repair_preserves_conclusions(original,corrected)
def format_addendum(ctx):
    return '本次唯一引用外观覆盖此前path/quote说明：evidence_refs每项只写证据目录的ID字符串。ID选择完整真实叶子，目录excerpt仅导航；全文上下文完整保留。不要返回path或quote，程序按本次上下文冻结目录展开后继续完整旧验收。目录选择不代表语义通过。schema填写'+VERSION+'，coverage仍按完整当前镜数逐行七列、每检查四列，其余内容/理由/结论保护不变。'
