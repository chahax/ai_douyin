"""Separate identity, source facts, visual choices, and screen continuity.

Evidence validity is deliberately not called semantic acceptance. Models select
source IDs; the program owns the original text and its checksum.
"""
from copy import deepcopy
from dataclasses import dataclass
from jsonschema import Draft202012Validator
from ..corpus_screenplay_v1 import digest
from ..story_first_contract_v5 import paragraphs


def obj(**fields):
    return {'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}


def array(item, minimum=0):
    return {'type':'array','items':item,'minItems':minimum}


TEXT={'type':'string','minLength':1}
def choices(values):
    return {'type':'string','enum':list(values)}


def refs(values, minimum=1):
    return {**array(choices(values), minimum),'uniqueItems':True}


@dataclass(frozen=True)
class Issue:
    owner: str
    path: str
    code: str
    message: str


class ContractError(ValueError):
    def __init__(self, issues):
        self.issues=issues
        super().__init__('; '.join(f'{i.path}: {i.code}' for i in issues))


def pointer(parts):
    return '/'+'/'.join(str(p).replace('~','~0').replace('/','~1') for p in parts)


def catalog(source):
    return {p['id']:{**p,'text_sha256':digest(p['text'])} for p in paragraphs(source)}


def indexed_chapters(source):
    """Add paragraph addresses once; preserve every original line and separator."""
    result=[]
    for chapter in source['chapters']:
        lines=[]
        for n,line in enumerate(chapter['text'].splitlines(keepends=True),1):
            lines.append((f'[CH{chapter["index"]}-P{n:03}] ' if line.strip() else '')+line)
        result.append({'index':chapter['index'],'title':chapter.get('title',''),
            'text_with_paragraph_ids':''.join(lines)})
    return result


def entity_schema(source):
    ids=list(catalog(source))
    return obj(entities=array(obj(id=TEXT,kind=choices(['character','character_group','organization','place','prop','prop_type']),
        display_name=TEXT,source_ids=refs(ids)),1))


def fact_schema(source,entities,kind):
    if kind not in ('character','environment','event'):raise ValueError('unknown_fact_kind')
    return obj(facts=array(obj(id=TEXT,entity_ids=refs([e['id'] for e in entities['entities']]),
        statement=TEXT,temporal_scope=choices(['current','past','original_future','plan','unspecified']),
        certainty=choices(['explicit','inferred','unknown']),source_ids=refs(catalog(source))),1))


def visual_schema(entities):
    return obj(choices=array(obj(id=TEXT,entity_ids=refs([e['id'] for e in entities['entities']]),
        aspect=choices(['palette','lighting','layout','wardrobe','appearance','camera']),
        description=TEXT)))


def schema_issues(raw,schema,owner):
    return [Issue(owner,pointer(e.absolute_path),'schema',e.message)
            for e in sorted(Draft202012Validator(schema).iter_errors(raw),key=lambda e:str(list(e.path)))]


def duplicate_issues(rows,owner,root):
    seen=set();issues=[]
    for n,row in enumerate(rows):
        if row['id'] in seen:issues.append(Issue(owner,f'/{root}/{n}/id','duplicate_id',row['id']))
        seen.add(row['id'])
    return issues


def validate_entities(raw,source,previous=None):
    issues=schema_issues(raw,entity_schema(source),'identity')
    if issues:raise ContractError(issues)
    issues+=duplicate_issues(raw['entities'],'identity','entities')
    prior={e['id']:e for e in (previous or {'entities':[]})['entities']}
    # The program supplies original paragraphs; names are labels, not quotes.
    # Whether an ID denotes the right person is a separate semantic decision.
    for n,row in enumerate(raw['entities']):
        if row['id'] in prior and row['kind']!=prior[row['id']]['kind']:
            issues.append(Issue('identity',f'/entities/{n}/kind','identity_kind_changed','Existing ID cannot change kind'))
    if issues:raise ContractError(issues)
    return deepcopy(raw)


def validate_facts(raw,source,entities,kind):
    issues=schema_issues(raw,fact_schema(source,entities,kind),kind)
    if not issues:issues+=duplicate_issues(raw['facts'],kind,'facts')
    if issues:raise ContractError(issues)
    return deepcopy(raw)


def bind_evidence(raw,source):
    """Attach original paragraphs verbatim; no model-copying quote task."""
    sources=catalog(source)
    return {'candidate':deepcopy(raw),'candidate_sha256':digest(raw),'source_sha256':digest(source),
            'evidence':{key:sources[key] for key in sorted({s for f in raw['facts'] for s in f['source_ids']})},
            'semantic_status':'unreviewed'}


def build_scene_packet(entities, banks, visual, entity_ids, fact_ids, source, previous_state):
    """Select explicit dependencies. Unknown or missing facts block this packet only."""
    people={e['id']:e for e in entities['entities']}
    allfacts={};issues=[]
    for kind,bank in banks.items():
        for fact in bank['facts']:
            if fact['id'] in allfacts:issues.append(Issue(kind,'/facts','cross_bank_id_collision',fact['id']))
            allfacts[fact['id']]={**fact,'category':kind}
    if len(set(entity_ids))!=len(entity_ids) or len(set(fact_ids))!=len(fact_ids):
        issues.append(Issue('packet','/dependencies','duplicate_dependency','IDs must be unique'))
    for id in entity_ids:
        if id not in people:issues.append(Issue('packet','/entity_ids','unknown_entity',id))
    for id in fact_ids:
        if id not in allfacts:issues.append(Issue('packet','/fact_ids','unknown_fact',id))
        elif allfacts[id]['certainty']!='explicit':
            issues.append(Issue('source_fact','/fact_ids','unconfirmed_dependency',id))
        elif not set(allfacts[id]['entity_ids'])<=set(entity_ids):
            issues.append(Issue('packet','/entity_ids','missing_fact_entity',id))
    if issues:raise ContractError(issues)
    facts=[allfacts[id] for id in fact_ids]
    bound=bind_evidence({'facts':facts},source)
    return {'entities':[deepcopy(people[id]) for id in entity_ids], 'facts':deepcopy(facts),
        'evidence':bound['evidence'],'source_sha256':bound['source_sha256'],
        'visual_choices':[deepcopy(v) for v in visual['choices'] if set(v['entity_ids'])<=set(entity_ids)],
        'previous_state':deepcopy(previous_state),'semantic_status':'unreviewed'}


def apply_record_patches(artifact,patches,allowed_ids,expected_sha256,validate):
    """CAS + exact record scope; return a new artifact, never mutate the old one."""
    if digest(artifact)!=expected_sha256:raise ValueError('stale_patch_candidate')
    root=next((k for k in ('entities','facts','choices','beats') if k in artifact),None)
    if root is None:raise ValueError('unknown_record_collection')
    ids={r['id'] for r in artifact[root]};seen=set();replacements={}
    for patch in patches:
        id=patch['id']
        if id not in ids or id not in allowed_ids:raise ValueError('patch_outside_authorized_records')
        if id in seen or patch['replacement']['id']!=id:raise ValueError('patch_identity_changed')
        if digest(next(r for r in artifact[root] if r['id']==id))!=patch['before_sha256']:
            raise ValueError('stale_record_patch')
        replacements[id]=deepcopy(patch['replacement']);seen.add(id)
    result=deepcopy(artifact)
    result[root]=[replacements.get(r['id'],r) for r in result[root]]
    validate(result)
    return result


def append_records(artifact, records, allowed_new_ids, expected_sha256, validate):
    """Explicit additions are separate from replacement; old rows cannot change."""
    if digest(artifact)!=expected_sha256:raise ValueError('stale_patch_candidate')
    root=next((k for k in ('entities','facts','choices') if k in artifact),None)
    if root is None:raise ValueError('unknown_record_collection')
    old={r['id'] for r in artifact[root]};new=[r['id'] for r in records]
    if len(new)!=len(set(new)) or set(new)&old or not set(new)<=set(allowed_new_ids):
        raise ValueError('addition_identity_collision_or_scope')
    result=deepcopy(artifact);result[root].extend(deepcopy(records));validate(result)
    return result


def validate_screen_presence(scene, previous_end, characters, places):
    """Screen locations are adaptation state, separate from source residence facts.

    Every change in a continuing timeline needs a named entry/exit event; cuts
    cannot silently reset actors. Different timelines use separate previous_end.
    """
    issues=[];state=deepcopy(previous_end or {})
    if scene['place_id'] not in places:
        issues.append(Issue('continuity','/place_id','unknown_place',scene['place_id']))
    if len(scene['end_cast'])!=len(set(scene['end_cast'])):
        issues.append(Issue('continuity','/end_cast','duplicate_actor','end_cast must be unique'))
    for who,place in state.items():
        if who not in characters or place not in places:
            issues.append(Issue('continuity','/previous_end','unknown_entity',who))
    for who,place in scene['initial_locations'].items():
        if who not in characters or place not in places:
            issues.append(Issue('continuity','/initial_locations','unknown_entity',who));continue
        if who in state and state[who]!=place:
            issues.append(Issue('continuity','/initial_locations','silent_location_reset',who))
        elif who not in state:state[who]=place
    for n,event in enumerate(scene['transitions']):
        who=event['person'];src=event['from'];dest=event['to']
        if who not in characters or src not in places or dest not in places:
            issues.append(Issue('continuity',f'/transitions/{n}','unknown_entity',who));continue
        if state.get(who)!=src or src==dest or not event['action'].strip():
            issues.append(Issue('continuity',f'/transitions/{n}','unexplained_transition',who));continue
        state[who]=dest
    expected={who for who,place in state.items() if place==scene['place_id']}
    if expected!=set(scene['end_cast']):
        issues.append(Issue('continuity','/end_cast','cast_location_mismatch',
            f'missing={sorted(expected-set(scene["end_cast"]))}; unexpected={sorted(set(scene["end_cast"])-expected)}'))
    if issues:raise ContractError(issues)
    return state
