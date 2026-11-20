"""Replace only approved event rows; plan, source, presence and prose stay fixed."""
from copy import deepcopy
from . import contracts as c,narrative_props


def schema(candidate,plan,people,segment_ids):
    ids=[b['id'] for s in candidate['scenes'] for b in s['segments']]
    if not segment_ids or len(segment_ids)!=len(set(segment_ids)) or not set(segment_ids)<=set(ids):
        raise ValueError('event_row_scope')
    base=narrative_props.body_schema(candidate,plan,{'entities':[{'id':p,'kind':'character'} for p in people]})
    row=deepcopy(base['properties']['segments']['items']);row['properties']['id']=c.choices(segment_ids)
    result=c.obj(segments=c.array(row,len(segment_ids)))
    result['properties']['segments']['maxItems']=len(segment_ids)
    result['properties']['new_uncertainties']=c.array(c.TEXT)
    result['$defs']=base['$defs']
    return result


def apply(candidate,plan,projection,body,people,segment_ids,identity):
    expected={'candidate_sha256':c.digest(candidate),'plan_sha256':c.digest(plan),'projection_sha256':c.digest(projection)}
    if expected!=identity:raise ValueError('event_row_inputs_changed')
    if projection['candidate_sha256']!=expected['candidate_sha256'] or projection['plan_sha256']!=expected['plan_sha256']:
        raise ValueError('event_row_prior_binding')
    errors=c.schema_issues(body,schema(candidate,plan,people,segment_ids),'event_row_patch')
    if errors:raise c.ContractError(errors)
    replacements={r['id']:r for r in body['segments']}
    if len(replacements)!=len(segment_ids) or set(replacements)!=set(segment_ids):raise ValueError('event_row_coverage')
    result=deepcopy(projection)
    result['segments']=[deepcopy(replacements.get(r['id'],r)) for r in projection['segments']]
    for issue in body.get('new_uncertainties',[]):
        if issue not in result['uncertainties']:result['uncertainties'].append(issue)
    return result
