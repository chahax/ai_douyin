"""Explicit intact-container relations, separate from effective holders.

Removing contents requires a separate action contract, never a duplicate transfer.
"""
from copy import deepcopy
from .contracts import digest,catalog


def validate(parents,owners):
    if not set(parents)<=owners.keys() or not set(parents.values())<=owners.keys():raise ValueError('container_unknown_prop')
    for child,parent in parents.items():
        if child not in owners or parent not in owners:raise ValueError('container_unknown_prop')
        seen={child};cursor=parent
        while True:
            if cursor in seen:raise ValueError('container_cycle')
            seen.add(cursor)
            if owners[cursor]!=owners[child]:raise ValueError('container_owner_mismatch')
            if cursor not in parents:break
            cursor=parents[cursor]


def descendants(parents,container):
    result=set();front=[container]
    while front:
        current=front.pop()
        for child,parent in parents.items():
            if parent==current and child not in result:
                result.add(child);front.append(child)
    return result


def refine_containment(handoff,proposals,source,review):
    """Source-reviewed enrichment; existing owner values and original stay intact."""
    if (review.get('verdict')!='accepted' or review.get('handoff_sha256')!=digest(handoff)
        or review.get('source_sha256')!=digest(source) or review.get('proposals_sha256')!=digest(proposals)):
        raise ValueError('containment_unreviewed_or_changed')
    result=deepcopy(handoff);parents=result['state'].setdefault('containers',{})
    evidence=catalog(source);seen=set()
    for row in proposals:
        if set(row)!={'child','container','source_ids'}:raise ValueError('containment_field_scope')
        child=row['child']
        if child in seen or child in parents:raise ValueError('containment_overwrite')
        if not row['source_ids'] or not set(row['source_ids'])<=evidence.keys():raise ValueError('containment_source_missing')
        seen.add(child);parents[child]=row['container']
    if not seen:raise ValueError('empty_containment_revision')
    validate(parents,result['state']['props'])
    result.setdefault('relation_revisions',[]).append({'parent_handoff_sha256':digest(handoff),
        'proposals':deepcopy(proposals),'source_sha256':digest(source),'review_sha256':digest(review)})
    return result
