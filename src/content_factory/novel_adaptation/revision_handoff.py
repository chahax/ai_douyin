"""CAS prose revisions invalidate derived continuity, including same-text rebinding."""
from copy import deepcopy
from . import contracts as c, prose_patch

def revise(original,plan,edits,source,registry):
    text=prose_patch.apply(original['screenplay'],plan,edits)
    return {'title':original.get('title',''),'screenplay':text,
        'source_sha256':c.digest(source),'registry_sha256':c.digest(registry),
        'parent_sha256':c.digest(original),'legacy_continuity_sha256':c.digest(original.get('continuity')),
        'continuity_status':'invalidated','continuity':None}

def attach(candidate,summary,source,registry):
    if candidate['source_sha256']!=c.digest(source) or candidate['registry_sha256']!=c.digest(registry):
        raise ValueError('changed_dependencies')
    if not isinstance(summary,str) or not summary.strip():raise ValueError('empty_continuity')
    return {'screenplay_sha256':c.digest(candidate['screenplay']),'source_sha256':c.digest(source),
        'registry_sha256':c.digest(registry),'summary':summary,'status':'awaiting_primary_review'}

def release(candidate,handoff,source,registry,review):
    if (handoff['screenplay_sha256']!=c.digest(candidate['screenplay']) or handoff['source_sha256']!=c.digest(source)
        or handoff['registry_sha256']!=c.digest(registry) or candidate['source_sha256']!=c.digest(source)
        or candidate['registry_sha256']!=c.digest(registry)):
        raise ValueError('stale_handoff')
    if (review.get('reviewer')!='primary_assistant' or review.get('verdict')!='approved'
        or review.get('open_issues')!=[] or review.get('candidate_sha256')!=c.digest(candidate)
        or review.get('handoff_sha256')!=c.digest(handoff)):
        raise ValueError('unreviewed_or_stale_pair')
    return {**deepcopy(handoff),'status':'released','review_sha256':c.digest(review)}
