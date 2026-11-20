"""Lossless request-only deduplication; authoritative runtime state remains unchanged."""
from copy import deepcopy
from . import contracts as c


def relevance_schema(needs,allowed_ids):
    """Select original evidence addresses; there is no paraphrase field."""
    if not needs or len(set(needs))!=len(needs):raise ValueError('invalid_context_needs')
    return c.obj(**{need:c.refs(allowed_ids,minimum=0) for need in needs})


def relevant_packet(source,needs,allowed_ids,selection,*,target_id):
    errors=c.schema_issues(selection,relevance_schema(needs,allowed_ids),'relevance')
    if errors:raise c.ContractError(errors)
    catalog=c.catalog(source)
    if not set(allowed_ids)<=catalog.keys():raise ValueError('unknown_source_evidence')
    ids=list(dict.fromkeys(key for need in needs for key in selection[need]))
    return {'target_id':target_id,'source_sha256':c.digest(source),'needs':deepcopy(selection),
        'evidence':{key:deepcopy(catalog[key]) for key in ids},
        'empty_means':'not retrieved for this request, not proof of nonexistence',
        'semantic_status':'awaiting_review','qualifiers_preserved_verbatim':True}


def encode_state(state,design,*,compact_events=False):
    result=deepcopy(state);catalog={}
    if 'information' in state:
        refs={}
        for person,rows in state['information'].items():
            refs[person]=[]
            for row in rows:
                key=row['id']
                if key in catalog and catalog[key]!=row:raise ValueError('information_id_conflict')
                catalog[key]=deepcopy(row);refs[person].append(key)
        result['information']=refs;result['information_event_catalog']=catalog
        if compact_events:
            groups={}
            for row in catalog.values():
                fields=tuple(sorted(row));groups.setdefault(fields,[]).append([deepcopy(row[k]) for k in fields])
            result['information_event_groups']=[{'fields':list(fields),'rows':rows} for fields,rows in groups.items()]
            del result['information_event_catalog']
    if 'recipes' in state and state['recipes']=={r['id']:r for r in design.get('recipes',[])}:
        del result['recipes'];result['recipes_source']='design.recipes'
    return result


def decode_state(encoded,design):
    result=deepcopy(encoded)
    if 'information_event_groups' in result:
        catalog={}
        for group in result.pop('information_event_groups'):
            fields=group['fields']
            if len(fields)!=len(set(fields)):raise ValueError('duplicate_information_column')
            for values in group['rows']:
                if len(values)!=len(fields):raise ValueError('information_row_length')
                row=dict(zip(fields,values));key=row['id']
                if key in catalog:raise ValueError('duplicate_information_id')
                catalog[key]=row
        result['information_event_catalog']=catalog
    if 'information_event_catalog' in result:
        catalog=result.pop('information_event_catalog')
        result['information']={person:[deepcopy(catalog[key]) for key in ids] for person,ids in result['information'].items()}
    if result.pop('recipes_source',None)=='design.recipes':result['recipes']={r['id']:deepcopy(r) for r in design['recipes']}
    return result
