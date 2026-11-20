"""Source-required transitions, independent of draft state self-reporting."""
from . import contracts as c
from .containers import descendants
from copy import deepcopy


def select_reviewed_events(proposal,source,decisions):
    """Select independently upheld obligations; never rewrite a native event."""
    if decisions.get('proposal_sha256')!=c.digest(proposal) or decisions.get('source_sha256')!=c.digest(source):
        raise ValueError('event_decisions_stale')
    rows=proposal['events'];ids=[r['id'] for r in rows];verdicts=decisions['verdicts']
    if len(ids)!=len(set(ids)) or set(ids)!=set(verdicts):raise ValueError('event_decision_coverage')
    if any(v not in ('source_required','design_only','rejected') for v in verdicts.values()):
        raise ValueError('event_decision_unresolved')
    return {'events':[deepcopy(r) for r in rows if verdicts[r['id']]=='source_required']}


def event_schema(source,design,entities,target_chapters):
    people=[r['id'] for r in entities['entities'] if r['kind']=='character']
    places=[p['id'] for p in design['places']]
    evidence=c.refs([id for id,row in c.catalog(source).items() if row['chapter'] in target_chapters])
    common={'id':c.TEXT,'scene_id':c.choices([s['id'] for s in design['scenes']]),'source_ids':evidence}
    return c.obj(events=c.array({'oneOf':[
        c.obj(**common,kind=c.choices(['transfer']),prop=c.choices([p['id'] for p in design['props']]),
              origin=c.choices(people+places),destination=c.choices(people+places)),
        c.obj(**common,kind=c.choices(['leave','enter']),people=c.refs(people),place=c.choices(places)),
        *([c.obj(**common,kind=c.choices(['transform']),recipe=c.choices([r['id'] for r in design['recipes']]))] if design.get('recipes') else [])]}))


def validate_requirements(candidate,contract,*,transition_effects=None):
    """Called only after independent source review of the event contract.

    A draft that reports internally consistent states still fails when a required
    source event was never enacted in its assigned scene.
    """
    by_id={s['id']:s for s in candidate['scenes']};errors=[]
    for event in contract['events']:
        scene=by_id.get(event['scene_id'])
        if scene is None:
            errors.append(c.Issue('source_event',event['id'],'required_scene_missing',event['scene_id']));continue
        if event['kind']=='transform':
            matches=[t for b in scene['beats'] for t in b.get('transforms',[]) if t['recipe']==event['recipe']]
            if len(matches)!=1:errors.append(c.Issue('source_event',event['id'],'required_transform_not_once',str(len(matches))))
        elif event['kind']=='transfer':
            dynamic=any(b.get('unpacks') or b.get('packs') or b.get('transforms') for b in scene['beats'])
            if dynamic and transition_effects is None:raise ValueError('dynamic_source_gate_requires_execution_effects')
            parents=candidate.get('containers',candidate.get('design',{}).get('containers',{}))
            matches=([t for t in transition_effects if t['scene_id']==event['scene_id'] and all(t[k]==event[k] for k in ('prop','origin','destination'))] if transition_effects is not None else [t for b in scene['beats'] for t in b.get('transfers',[])
                     if all(t[k]==event[k] for k in ('origin','destination'))
                     and (t['prop']==event['prop'] or event['prop'] in descendants(parents,t['prop']))])
            if len(matches)!=1:errors.append(c.Issue('source_event',event['id'],'required_transfer_not_once',str(len(matches))))
        else:
            for who in event['people']:
                matches=[m for b in scene['beats'] for m in b.get('moves',[]) if m['person']==who
                    and ((m['origin']==event['place'] and m['destination']!=event['place']) if event['kind']=='leave'
                         else (m['destination']==event['place'] and m['origin']!=event['place']))]
                if not matches:errors.append(c.Issue('source_event',event['id'],'required_'+event['kind']+'_missing',who))
    if errors:raise c.ContractError(errors)
    return True


def require_review(contract,source,review):
    if review.get('verdict')!='accepted' or review.get('source_sha256')!=c.digest(source) or review.get('contract_sha256')!=c.digest(contract):
        raise ValueError('source_event_contract_unreviewed_or_changed')
