"""Explicit, reviewed episode state handoff; never reset returning actors or props."""
from copy import deepcopy
from .contracts import digest,catalog
from . import contracts as c
from .scenes import initial_state,opening_schema,bind_opening


def reference_delta_schema(allowed_ids):
    """Only references used in this scene may enter the evidence ledger."""
    return c.obj(used_source_ids=c.refs(allowed_ids,minimum=0))


def stage_reference_delta(previous,source,packet,candidate,selected,allowed_ids):
    if previous['source_sha256']!=digest(source) or packet['source_sha256']!=digest(source):
        raise ValueError('reference_source_changed')
    errors=c.schema_issues(selected,reference_delta_schema(allowed_ids),'reference_delta')
    if errors:raise c.ContractError(errors)
    evidence=catalog(source)
    if not set(allowed_ids)<=evidence.keys():raise ValueError('unknown_delta_evidence')
    return {'previous_sha256':digest(previous),'source_sha256':digest(source),'packet_sha256':digest(packet),
        'candidate_sha256':digest(candidate),'selected_ids':deepcopy(selected['used_source_ids']),
        'additions':{key:deepcopy(evidence[key]) for key in selected['used_source_ids'] if key not in previous['evidence']},
        'status':'pending_review','scope':'source_evidence_index_not_freeform_state_summary'}


def commit_reference_delta(previous,source,packet,candidate,delta,review):
    for key,value in [('previous_sha256',previous),('source_sha256',source),('packet_sha256',packet),('candidate_sha256',candidate)]:
        if delta[key]!=digest(value):raise ValueError('stale_reference_delta:'+key)
    if (review.get('verdict')!='accepted' or review.get('reviewer')!='primary_assistant'
        or review.get('delta_sha256')!=digest(delta) or review.get('open_issues')!=[]):
        raise ValueError('reference_delta_not_reviewed')
    expected={key:deepcopy(catalog(source)[key]) for key in delta['selected_ids'] if key not in previous['evidence']}
    if expected!=delta['additions']:raise ValueError('source_reference_rewritten')
    result=deepcopy(previous);result['evidence'].update(expected)
    result.setdefault('history',[]).append({'delta_sha256':digest(delta),'review_sha256':digest(review)})
    # Omitting an irrelevant item from a request must never erase the archive.
    return result


def qualify_information(state,episode_id):
    result=deepcopy(state)
    for history in result.get("information",{}).values():
        for event in history:
            if "origin_episode" not in event:
                event["id"]=episode_id+":"+event["id"]
                event["origin_episode"]=episode_id
    return result


def registry(entities,design):
    return {
        "people":{e["id"]:{"kind":e["kind"],"display_name":e["display_name"]}
                  for e in entities["entities"] if e["kind"]=="character"},
        "places":{p["id"]:deepcopy(p) for p in design["places"]},
        "props":{p["id"]:{k:deepcopy(v) for k,v in p.items() if k!="owner"} for p in design["props"]},
        "presentation":deepcopy(design.get('presentation_labels',{}))}


def export_handoff(candidate,entities,source,review,*,book_id,episode_id,timeline_id):
    if not all((book_id,episode_id,timeline_id)):raise ValueError("handoff_identity_required")
    if review.get("verdict") not in ("accepted_text_pilot","accepted"):
        raise ValueError("episode_not_reviewed")
    if review.get("candidate_sha256")!=digest(candidate) or review.get("source_sha256")!=digest(source):
        raise ValueError("review_stale")
    if "end_state" not in candidate:raise ValueError("episode_without_end_state")
    return {"book_id":book_id,"episode_id":episode_id,"timeline_id":timeline_id,
        "candidate_sha256":digest(candidate),"source_sha256":digest(source),
        "review_sha256":digest(review),"scope":"reviewed_text_state_only",
        "registry":registry(entities,candidate["design"]),
        "visual_design":deepcopy(candidate['design'].get('visual_design',[])),
        "state":qualify_information(candidate["end_state"],episode_id)}


def inherit_design(raw,handoff):
    """The model proposes additions; returning assets and style are program copies."""
    result=deepcopy(raw)
    for kind in ('places','props'):
        old=handoff['registry'][kind]
        ids=[row['id'] for row in raw[kind]]
        if len(ids)!=len(set(ids)) or set(ids)&old.keys():raise ValueError('continuation_asset_redefinition:'+kind)
        if '__OFFSCREEN__' in ids:raise ValueError('reserved_offscreen_id')
        result[kind]=deepcopy(list(old.values()))+result[kind]
    for prop in result['props']:
        if prop['id'] in handoff['state']['props']:prop['owner']=handoff['state']['props'][prop['id']]
    result['presentation_labels']=deepcopy(handoff['registry'].get('presentation',{}))
    result['containers']=deepcopy(handoff['state'].get('containers',{}))
    old_recipes=handoff['state'].get('recipes',{})
    if any(r['id'] in old_recipes for r in raw.get('recipes',[])):
        raise ValueError('continuation_recipe_redefinition')
    if set(raw.get('planned_props',[]))&handoff['state']['props'].keys():
        raise ValueError('continuation_prop_status_redefinition')
    if old_recipes or raw.get('recipes'):
        result['recipes']=deepcopy(list(old_recipes.values()))+deepcopy(raw.get('recipes',[]))
    if handoff['state'].get('prop_status'):
        result['initial_prop_status']=deepcopy(handoff['state']['prop_status'])
    if handoff['state'].get('recipes_completed'):
        result['recipes_completed']=deepcopy(handoff['state']['recipes_completed'])
    result['visual_design']=deepcopy(handoff.get('visual_design',[]))+result.get('visual_design',[])
    return result


def opening_delta_schema(design,entities,handoff):
    schema=opening_schema(design,entities)
    for field,old in [('locations',handoff['state']['locations']),('owners',handoff['state']['props'])]:
        target=schema['properties'][field]
        for key in old:
            target['properties'].pop(key,None)
            if key in target['required']:target['required'].remove(key)
    return schema


def bind_opening_delta(design,entities,handoff,delta):
    errors=c.schema_issues(delta,opening_delta_schema(design,entities,handoff),'opening_delta')
    if errors:raise c.ContractError(errors)
    opening={'locations':{**deepcopy(handoff['state']['locations']),**delta['locations']},
             'owners':{**deepcopy(handoff['state']['props']),**delta['owners']}}
    return bind_opening(design,opening,entities)


def continue_state(handoff,expected_sha256,design,entities,*,book_id,episode_id,timeline_id):
    if digest(handoff)!=expected_sha256:raise ValueError("handoff_changed")
    if handoff["book_id"]!=book_id or handoff["timeline_id"]!=timeline_id:
        raise ValueError("book_or_timeline_mismatch")
    if handoff["episode_id"]==episode_id:raise ValueError("episode_replay")
    current=registry(entities,design)
    for kind,old in handoff["registry"].items():
        for key,value in old.items():
            if current[kind].get(key)!=value:raise ValueError("returning_registry_changed:"+kind+":"+key)
    result=initial_state(design,entities)
    # An incompatible opening must be explicitly staged, not silently overwritten.
    for kind in ("locations","props"):
        for key,value in handoff["state"][kind].items():
            if result[kind].get(key)!=value:raise ValueError("opening_state_reset:"+kind+":"+key)
    if result.get('containers',{})!=handoff['state'].get('containers',{}):raise ValueError('opening_container_reset')
    for prop in handoff['state']['props']:
        if result.get('prop_status',{}).get(prop,'present')!=handoff['state'].get('prop_status',{}).get(prop,'present'):
            raise ValueError('opening_lifecycle_reset:prop_status:'+prop)
    for field in ('prop_status','recipes'):
        for key,value in handoff['state'].get(field,{}).items():
            if result.get(field,{}).get(key)!=value:raise ValueError('opening_lifecycle_reset:'+field+':'+key)
    if result.get('recipes_completed',[])!=handoff['state'].get('recipes_completed',[]):
        raise ValueError('opening_recipe_history_reset')
    result["information"]=deepcopy(handoff["state"].get("information",{}))
    return result


def refine_registry(handoff,expected_sha256,proposals,source,review):
    """Version descriptive metadata only; source-reviewed, no identity/state edits."""
    if digest(handoff)!=expected_sha256:raise ValueError("handoff_changed")
    if (review.get("verdict")!="accepted" or review.get("proposals_sha256")!=digest(proposals)
        or review.get("source_sha256")!=digest(source) or review.get("handoff_sha256")!=expected_sha256):
        raise ValueError("registry_revision_unreviewed_or_changed")
    if not proposals:raise ValueError("empty_registry_revision")
    evidence=catalog(source);result=deepcopy(handoff);seen=set()
    for row in proposals:
        if set(row)!={"kind","id","before_sha256","description","source_ids"}:
            raise ValueError("registry_revision_field_scope")
        kind,key=row["kind"],row["id"]
        if kind not in ("props","places") or (kind,key) in seen:raise ValueError("registry_revision_scope")
        seen.add((kind,key))
        old=handoff["registry"][kind].get(key)
        if old is None or digest(old)!=row["before_sha256"]:raise ValueError("registry_record_changed")
        if not isinstance(row["description"],str) or not row["description"].strip():raise ValueError("empty_description")
        if not row["source_ids"] or not set(row["source_ids"])<=evidence.keys():raise ValueError("registry_source_missing")
        result["registry"][kind][key]["description"]=row["description"]
    result.setdefault("registry_revisions",[]).append({"parent_handoff_sha256":expected_sha256,
        "proposals":deepcopy(proposals),"source_sha256":digest(source),"review_sha256":digest(review)})
    return result


def description_span(record,expected_sha256,start,end,replacement):
    if digest(record)!=expected_sha256:raise ValueError("registry_record_changed")
    text=record["description"]
    if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text):
        raise ValueError("invalid_description_span")
    if not isinstance(replacement,str) or not replacement.strip():raise ValueError("empty_span_replacement")
    return text[:start]+replacement+text[end:]
