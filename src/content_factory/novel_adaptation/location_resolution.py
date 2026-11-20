"""Explicit, source-reviewed opening localization; never infer unknown from OFFSCREEN alone."""
from copy import deepcopy
from . import contracts as c


def resolve(design,handoff,proposals,source,review):
    bindings={'design_sha256':c.digest(design),'handoff_sha256':c.digest(handoff),
              'source_sha256':c.digest(source),'proposals_sha256':c.digest(proposals)}
    if review.get('verdict')!='accepted' or any(review.get(k)!=v for k,v in bindings.items()):
        raise ValueError('location_resolution_unreviewed_or_stale')
    if not proposals:raise ValueError('empty_location_resolution')
    result=deepcopy(design);next_handoff=deepcopy(handoff);seen=set()
    evidence=c.catalog(source);places={p['id'] for p in design['places']}
    props={p['id']:p for p in result['props']}
    for row in proposals:
        if set(row)!={'prop','place','source_ids','prior_location_was_unresolved','reason'}:
            raise ValueError('location_resolution_field_scope')
        prop=row['prop']
        if prop in seen or prop not in props:raise ValueError('location_resolution_identity')
        seen.add(prop)
        if row['prior_location_was_unresolved'] is not True or not row['reason'].strip():
            raise ValueError('explicit_unknown_review_required')
        if props[prop]['owner']!='__OFFSCREEN__' or handoff['state']['props'].get(prop)!='__OFFSCREEN__':
            raise ValueError('known_location_cannot_be_reset')
        if row['place'] not in places or row['place']=='__OFFSCREEN__':raise ValueError('resolution_place_unknown')
        if prop in handoff['state'].get('containers',{}) or prop in handoff['state'].get('containers',{}).values():
            raise ValueError('contained_resolution_requires_group_review')
        if handoff['state'].get('prop_status',{}).get(prop,'present')!='present':raise ValueError('resolution_cannot_create_prop')
        if not row['source_ids'] or not set(row['source_ids'])<=evidence.keys():raise ValueError('resolution_source_unknown')
        props[prop]['owner']=row['place'];next_handoff['state']['props'][prop]=row['place']
    amendment={**bindings,'review_sha256':c.digest(review),'proposals':deepcopy(proposals),
        'prior_state_sha256':c.digest(handoff['state']),
        'meaning':'new episode opening knowledge resolution, not a performed transfer or revised prior screenplay'}
    next_handoff.setdefault('opening_resolutions',[]).append(amendment)
    result.setdefault('opening_resolutions',[]).append(deepcopy(amendment))
    return result,next_handoff
