"""Reversible display projection; source labels and identities are never edited."""
import re
from collections import Counter
from copy import deepcopy
from . import contracts as c


def display_names(plan,entities):
    original={e['id']:e['display_name'] for e in entities['entities']}
    for p in plan['places']:original.setdefault(p['id'],p.get('display_name',p['id']))
    for p in plan['props']:original.setdefault(p['id'],p.get('display_name',p.get('kind',p['id'])))
    original.update(plan.get('presentation_labels',{}))
    projected={k:re.sub(r'(?:\s*[（(][^（）()]*[）)])+\s*$','',v).strip() or v for k,v in original.items()}
    counts=Counter(projected.values())
    # Qualifiers that distinguish two identities must remain visible.
    return {k:(original[k] if counts[v]>1 else v) for k,v in projected.items()}


def label_schema(prop_ids,source):
    return c.obj(labels=c.array(c.obj(id=c.choices(prop_ids),label={'type':'string','minLength':1,'maxLength':20},
        source_ids=c.refs(c.catalog(source))),1))


def apply_labels(plan,proposal,prop_ids,source,expected_sha):
    if c.digest(plan)!=expected_sha:raise ValueError('stale_label_design')
    errors=c.schema_issues(proposal,label_schema(prop_ids,source),'presentation')
    if errors:raise c.ContractError(errors)
    ids=[r['id'] for r in proposal['labels']]
    if len(ids)!=len(set(ids)) or set(ids)!=set(prop_ids):raise ValueError('label_scope_coverage')
    if not set(ids)<={r['id'] for r in plan['props']}:raise ValueError('label_must_be_prop')
    result=deepcopy(plan)
    labels=result.setdefault('presentation_labels',{})
    for row in proposal['labels']:
        if row['id'] in labels:raise ValueError('label_already_versioned')
        labels[row['id']]=row['label']
    if len(set(labels.values()))!=len(labels):raise ValueError('ambiguous_prop_labels')
    return result
