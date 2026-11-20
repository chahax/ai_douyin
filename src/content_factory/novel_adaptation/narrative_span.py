"""Exact source-character scope for long prose fields; adapted from the prior span trial."""
from . import contracts as c
from .narrative_patch import value_at,apply


def target(candidate, target_id, path, original):
    text=value_at(candidate,path)
    if not isinstance(text,str) or not original or text.count(original)!=1:
        raise ValueError('span_not_unique')
    start=text.index(original)
    return {'id':target_id,'path':path,'start':start,'end':start+len(original),
            'original':original,'field_sha256':c.digest(text)}


def schema(targets):
    return c.array(c.obj(id=c.choices([t['id'] for t in targets]),replacement=c.TEXT),len(targets))


def apply_spans(candidate, targets, edits):
    by={t['id']:t for t in targets}
    if len(by)!=len(targets) or len(edits)!=len(targets) or {e['id'] for e in edits}!=set(by):
        raise ValueError('span_scope_mismatch')
    values={e['id']:e['replacement'] for e in edits};patches=[]
    for path in dict.fromkeys(t['path'] for t in targets):
        text=value_at(candidate,path);cursor=0;pieces=[]
        for t in sorted((t for t in targets if t['path']==path),key=lambda t:t['start']):
            if (c.digest(text)!=t['field_sha256'] or type(t['start']) is not int or
                type(t['end']) is not int or not 0<=t['start']<t['end']<=len(text) or
                text[t['start']:t['end']]!=t['original']):raise ValueError('stale_span_target')
            if t['start']<cursor:raise ValueError('overlapping_spans')
            value=values[t['id']]
            if not isinstance(value,str) or not value:raise ValueError('invalid_span_replacement')
            pieces.extend([text[cursor:t['start']],value]);cursor=t['end']
        pieces.append(text[cursor:]);patches.append({'path':path,'value':''.join(pieces)})
    return apply(candidate,{'candidate_sha256':c.digest(candidate),'replacements':patches},
                 [p['path'] for p in patches],c.digest(candidate))
