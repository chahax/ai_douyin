"""Apply reviewed field replacements without permitting an implicit full rewrite."""
from copy import deepcopy
from .contracts import digest
from . import contracts as c


def value_at(candidate,path):
    value=candidate
    for token in _tokens(path):value=value[_key(value,token)]
    return value


def proposal_schema(candidate, paths):
    if not paths:
        return c.obj(candidate_sha256=c.choices([digest(candidate)]),
                     replacements={'type':'array','items':False,'maxItems':0})
    def shape(value):
        if isinstance(value,str):return c.TEXT
        if type(value) is int:return {'type':'integer','exclusiveMinimum':0}
        if type(value) is float:return {'type':'number','exclusiveMinimum':0}
        if isinstance(value,list):
            if not value:raise ValueError('empty_list_requires_explicit_schema')
            return c.array(shape(value[0]))
        if isinstance(value,dict):return c.obj(**{k:shape(v) for k,v in value.items()})
        raise ValueError('unsupported_patch_value')
    return c.obj(candidate_sha256=c.choices([digest(candidate)]),replacements=c.array({
        'oneOf':[c.obj(path=c.choices([path]),value=shape(value_at(candidate,path))) for path in paths]},len(paths)))


def body_schema(candidate, paths):
    schema=deepcopy(proposal_schema(candidate,paths))
    del schema['properties']['candidate_sha256']
    schema['required'].remove('candidate_sha256')
    return schema


def bind_body(candidate, body, paths, expected_sha256):
    if digest(candidate)!=expected_sha256:
        raise ValueError('candidate_changed')
    errors=c.schema_issues(body,body_schema(candidate,paths),'patch_body')
    if errors:raise c.ContractError(errors)
    return {'candidate_sha256':expected_sha256,**deepcopy(body)}


def _tokens(path):
    if not isinstance(path,str) or not path.startswith('/') or path=='/':
        raise ValueError('invalid_patch_path')
    tokens=path[1:].split('/')
    for token in tokens:
        if '~' in token.replace('~0','').replace('~1',''):
            raise ValueError('invalid_pointer_escape')
    return [x.replace('~1','/').replace('~0','~') for x in tokens]


def _key(parent, token):
    if isinstance(parent,list):
        if not token.isascii() or not token.isdecimal() or str(int(token))!=token:
            raise ValueError('invalid_array_index')
        index=int(token)
        if index>=len(parent):raise ValueError('patch_target_missing')
        return index
    if not isinstance(parent,dict) or token not in parent:
        raise ValueError('patch_target_missing')
    return token


def apply(candidate, proposal, approved_paths, expected_sha256):
    if digest(candidate)!=expected_sha256:raise ValueError('candidate_changed')
    if set(proposal)!={'candidate_sha256','replacements'} or proposal['candidate_sha256']!=expected_sha256:
        raise ValueError('proposal_candidate_mismatch')
    paths=list(approved_paths)
    tokens=[_tokens(p) for p in paths]
    if len(set(paths))!=len(paths):raise ValueError('duplicate_approved_path')
    for i,a in enumerate(tokens):
        for j,b in enumerate(tokens):
            if i!=j and len(a)<=len(b) and a==b[:len(a)]:raise ValueError('overlapping_patch_scope')
    edits=proposal['replacements']
    if not isinstance(edits,list) or any(not isinstance(e,dict) or set(e)!={'path','value'} for e in edits):
        raise ValueError('invalid_patch_envelope')
    if len(edits)!=len(paths) or {e['path'] for e in edits}!=set(paths):raise ValueError('patch_scope_mismatch')
    result=deepcopy(candidate)
    for edit in edits:
        parts=_tokens(edit['path']);parent=result
        for token in parts[:-1]:parent=parent[_key(parent,token)]
        key=_key(parent,parts[-1])
        if type(parent[key]) is not type(edit['value']):raise ValueError('patch_value_type_changed')
        parent[key]=deepcopy(edit['value'])
    return result
