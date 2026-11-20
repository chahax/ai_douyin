"""Single text validation path; no provider calls, media or deployment effects."""
from .contracts import digest
from .narrative_revision import validate
from .narrative_presence import replay
from .narrative_props import audit_event_structure
from .narrative_timing import schedule
from .performance_patch import inspect
from .uncertainty_review import evaluate as review_uncertainties
from .narrative_patch import value_at

DIMENSIONS=('source_fidelity','identity','visual_design','continuity','timing','pacing')


def validate_semantic_review(bundle, review, identity):
    if review.get('artifact_hashes')!=identity:raise ValueError('stale_semantic_review')
    dimensions=review.get('dimensions',{})
    if set(dimensions)!=set(DIMENSIONS):raise ValueError('semantic_dimension_coverage')
    required={'source_fidelity':{'source','candidate'},'identity':{'packet','candidate'},
              'visual_design':{'design','candidate'},'continuity':{'projection','candidate'},
              'timing':{'candidate'},'pacing':{'candidate'}}
    for key,item in dimensions.items():
        if not item.get('reason','').strip():raise ValueError('semantic_reason_missing')
        if item.get('decision') not in ('accepted','revise','uncertain'):raise ValueError('semantic_decision_invalid')
        evidence=item.get('evidence',[])
        if not required[key]<={e['artifact'] for e in evidence}:raise ValueError('semantic_evidence_coverage')
        for e in evidence:
            if e['artifact'] not in identity:raise ValueError('semantic_evidence_unbound')
            actual=value_at(bundle[e['artifact']],e['path'])
            if digest(actual)!=e['value_sha256']:raise ValueError('semantic_evidence_changed')
    return dimensions


def verify(bundle, *, semantic_review=None, maximum_seconds=240):
    c=bundle['candidate'];source=bundle['source'];packet=bundle['packet'];design=bundle['design']
    if packet['source_sha256']!=digest(source):raise ValueError('packet_source_mismatch')
    if bundle['run_plan']['source_sha256']!=digest(source):raise ValueError('run_source_mismatch')
    if bundle['state']['pending'] is not None or bundle['state']['status'] in ('running','prepared'):
        raise ValueError('unsettled_run_cannot_validate')
    structural=validate(c,source,packet,design,maximum_seconds)
    people=[x['id'] for x in packet['entities'] if x['kind']=='character']
    places=[x['id'] for x in bundle['plan']['places']]
    if set(places)!={x['id'] for x in design['places']}:raise ValueError('design_place_registry_mismatch')
    trace=replay(c,bundle['presence'],people,places,prop_plan=bundle['plan'],prop_projection=bundle['projection'])
    saved_trace={k:v for k,v in bundle['replay'].items() if k!='registry_uncertainties'}
    if trace!=saved_trace:raise ValueError('stored_replay_not_reproducible')
    # The producer appends registry notes after replay. They are review inputs,
    # not engine state; preserve them in the bound uncertainty inventory below.
    notes=bundle['replay'].get('registry_uncertainties',[])
    if not isinstance(notes,list) or any(not isinstance(x,str) or not x.strip() for x in notes):
        raise ValueError('invalid_registry_uncertainties')
    event_audit=audit_event_structure(bundle['presence'],bundle['projection'])
    artifacts={k:bundle[k] for k in ('candidate','plan','presence','projection','replay')}
    uncertainty=review_uncertainties(artifacts,bundle['uncertainty_review'])
    paths=[f'/scenes/{i}/segments/{j}/{field}' for i,s in enumerate(c['scenes'])
           for j,_ in enumerate(s['segments']) for field in ('action','expression','camera','visual_additions')]
    performance=inspect(c,paths);timing=schedule(c,maximum_seconds=maximum_seconds)
    blocked=[]
    if event_audit['issues']:blocked.append('event_structure')
    if uncertainty['open_ids']:blocked.append('open_uncertainties')
    if performance['issues']:blocked.append('performance_process_language')
    if not timing['within_brief']:blocked.append('estimated_duration_exceeds_brief')
    identity={k:digest(bundle[k]) for k in ('source','candidate','packet','design','plan','presence','projection','uncertainty_review')}
    if semantic_review is None:blocked.append('same_version_semantic_review_missing')
    else:
        dimensions=validate_semantic_review(bundle,semantic_review,identity)
        for key,item in dimensions.items():
            if item.get('decision')!='accepted':blocked.append('semantic_'+key)
        if set(semantic_review.get('acknowledged_limit_ids',[]))!=set(uncertainty['retained_limit_ids']):
            blocked.append('limits_not_reviewed')
    return {'artifact_hashes':identity,'status':'text_review_accepted' if not blocked else 'text_validation_incomplete',
            'blocking_reasons':blocked,'structure':structural,'replayed_segments':len(trace['trace']),
            'event_structure':event_audit,'uncertainties':uncertainty,'performance':performance,'schedule':timing,
            'semantic_acceptance':not blocked,'media_ready':False,'production_default_changed':False,
            'limits':['Text review is not measured audio/video acceptance.',
                      'Reviewer evidence and conclusions still require audit; structure does not prove semantic truth.']}
