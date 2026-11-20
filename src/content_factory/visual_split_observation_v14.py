"""Explicit target-only people/furniture observations for static first frames.

No desired count, source room, guide or actor reference is supplied. The only
normalization wraps one already-valid flat box for an explicitly counted single
instance; native unknowns, quantities and coordinates are never inferred.
"""
from copy import deepcopy
from pathlib import Path

SCOPE='split_target_only/v14'
VERSION='split_people_furniture_observation/v14'
PROMPT_VERSION='target-only-people-furniture-split-v14'
PEOPLE_PROMPT='''Observe ONLY this actual target image and count visible human depictions,
including partially visible people and duplicated/floating heads. Return a nonnegative
integer if countable; 0 means no visible human depiction. null means the actual image
genuinely prevents a reliable count. Do not infer offscreen people from a story.
You have no desired count, scene description or reference. Give visible evidence.
Do not describe body pose, age, faces, clothing, furniture, camera or approval.
Return ONLY JSON with people_count and evidence conforming to the schema.'''
FURNITURE_PROMPT='''Observe ONLY this actual target image. Count VISIBLE physical furniture
instances, not all objects that might exist elsewhere in the room. A kind entirely
outside this image has VISIBLE count=0; that does not assert it is absent from the room.
Return count=null only if something actually visible is too unclear to classify/count.
Never use null for a whole kind record. Every requested kind must be a complete object
with count, regions, evidence. For an absent-from-view kind use count=0, regions=[], and
brief visible evidence. For an uncertain visible kind use count=null and explain why.
Each integer count must have exactly that many instance regions, using NESTED arrays:
regions is a list of [left,top,right,bottom] boxes; a single instance still needs a list
containing its one box. Coordinates are normalized integer corners 0..1000.
Count partially cropped/occluded identifiable furniture once. Bed frame, mattress and
headboard are parts of ONE bed; bedding is not another bed. Chair/table legs, seats and
backs are parts, not more furniture. Classify each physical instance once: table is a
freestanding surface with its own legs/base; counter is a fixed/built-in worktop, not
a table merely used for work. Cabinet includes wardrobe; its internal shelves are not
separate shelf instances; shelf is a standalone open unit. Stool has no chair back.
Stove is the cooking installation, not loose cookware. Light means a whole fixture,
not each face of its housing. Ignore furniture pictures/reflections, loose props,
doors, windows, walls and bedding. Do not report people, pose, faces or clothing.
You are NOT given a layout guide, source-room image, desired category or permitted
quantity. Observe actual pixels only; do not compare against a plan or grant approval.
Return ONLY JSON with object_observations, all requested kinds, and complete records.'''


def _v():
    from . import visual_asset_review_v3 as v
    return v


def enabled(expectation):
    value=expectation.get('furniture_observation_scope')
    if value is None:return False
    if value!=SCOPE or expectation.get('kind')!='place' or _v().layout_inventory(expectation) is None:
        raise ValueError('split_observation_scope_requires_place_inventory')
    return True


def people_schema():return deepcopy(_v().COUNT_RECHECK_SCHEMA)


def furniture_schema(inventory):
    # The legacy v12 schema remains frozen and is used only as a structural
    # definition. No permitted quantity is present in this furniture-only schema.
    value=_v().blind_schema(dict(kind='place',locate_rois=[],layout_object_inventory=inventory))['properties']['object_observations']
    return dict(type='object',properties=dict(object_observations=deepcopy(value)),required=['object_observations'],additionalProperties=False)


def people_answer(value):
    v=_v();v._keys(value,('people_count','evidence'),'people-only observation')
    count=value['people_count'];evidence=value['evidence']
    if ((count is not None and (type(count) is not int or not 0<=count<=100)) or
        not isinstance(evidence,list) or not evidence or any(not isinstance(x,str) or not x.strip() for x in evidence)):
        raise v.ReviewProtocolError('invalid people-only observation')
    return deepcopy(value)


def normalize(value,inventory):
    v=_v();v._keys(value,('object_observations',),'furniture-only observation')
    raw=value['object_observations'];v._keys(raw,inventory,'furniture-only kinds')
    result=deepcopy(raw);operations=[]
    for kind,item in result.items():
        v._keys(item,('count','regions','evidence'),'furniture-only '+kind)
        region=item['regions']
        if item['count']==1 and type(item['count']) is int and isinstance(region,list) and len(region)==4 and all(type(n) is int for n in region):
            v._box(region) # No clipping, swapping, scaling, rounding or guessed coordinates.
            item['regions']=[deepcopy(region)]
            operations.append(dict(operation='wrap_single_valid_ltrb',kind=kind,before=deepcopy(region),after=deepcopy(item['regions'])))
    v.validate_object_observations(result,inventory)
    return result,operations


def _payload(target,prompt,schema,role):
    return dict(prompt=prompt,images=[dict(role=role,binding=deepcopy(target))],schema=schema)


def _artifact(path):return dict(path=str(Path(path).resolve()),sha256=_v().file_sha(path))


def observe(prepared,infer,folder):
    v=_v()
    if folder is None:raise v.ReviewProtocolError('split observation requires persistent native evidence')
    folder=Path(folder);target=prepared['target'];inventory=v.layout_inventory(prepared['expectation'])
    people=v._native_call(infer,_payload(target,PEOPLE_PROMPT,people_schema(),'target_people'),folder,'PEOPLE')
    human=people_answer(v._parse_content(people['text']))
    furniture=v._native_call(infer,_payload(target,FURNITURE_PROMPT,furniture_schema(inventory),'target_furniture'),folder,'FURNITURE')
    normalized,operations=normalize(v._parse_content(furniture['text']),inventory)
    audit=dict(schema=VERSION,raw_native_sha256=v.digest(furniture),normalized_sha256=v.digest(normalized),operations=operations)
    path=folder/'FURNITURE_NORMALIZATION.json'
    if path.exists() and v._read(path)!=audit:raise v.ReviewProtocolError('frozen furniture normalization changed')
    if not path.exists():v._write(path,audit)
    scope=dict(schema=VERSION,target=deepcopy(target),normalized_sha256=v.digest(normalized),
        artifacts={key:_artifact(folder/name) for key,name in dict(people_request='PEOPLE_REQUEST.json',people_native='PEOPLE_NATIVE.json',
            furniture_request='FURNITURE_REQUEST.json',furniture_native='FURNITURE_NATIVE.json',normalization='FURNITURE_NORMALIZATION.json').items()})
    blind=dict(observations=dict(people_count=human['people_count'],age_band='unknown',orientation='unknown',framing='unknown',pose_view='unknown'),
        rois=dict.fromkeys(v.ROI_NAMES),evidence=human['evidence'],object_observations=normalized)
    return blind,scope


def verify(result):
    """Always replay raw-only normalization, including during H3 qualification."""
    v=_v();scope=result.get('split_observation')
    if scope is None:
        if result.get('furniture_observation_scope')==SCOPE and result.get('decision')!='unavailable':
            raise v.ReviewProtocolError('declared split observation requires native proof')
        return None
    if not isinstance(scope,dict) or scope.get('schema')!=VERSION:raise v.ReviewProtocolError('invalid split observation proof')
    target=scope['target']
    if v.image_binding(target['path'])!=target or result.get('target_sha256')!=target['sha256']:
        raise v.ReviewProtocolError('split observation target changed')
    inventory=result['layout_object_inventory'];artifacts=scope['artifacts']
    v._keys(artifacts,('people_request','people_native','furniture_request','furniture_native','normalization'),'split observation artifacts')
    for item in artifacts.values():
        if v.file_sha(item['path'])!=item['sha256']:raise v.ReviewProtocolError('split observation native artifact changed')
    if (v._read(artifacts['people_request']['path'])!=_payload(target,PEOPLE_PROMPT,people_schema(),'target_people') or
        v._read(artifacts['furniture_request']['path'])!=_payload(target,FURNITURE_PROMPT,furniture_schema(inventory),'target_furniture')):
        raise v.ReviewProtocolError('split observation request changed or contains a reference')
    human=people_answer(v._parse_content(v._read(artifacts['people_native']['path'])['text']))
    if result.get('observations',{}).get('people_count')!=human['people_count']:
        raise v.ReviewProtocolError('split people count changed')
    native=v._read(artifacts['furniture_native']['path']);normalized,operations=normalize(v._parse_content(native['text']),inventory)
    audit=dict(schema=VERSION,raw_native_sha256=v.digest(native),normalized_sha256=v.digest(normalized),operations=operations)
    if v._read(artifacts['normalization']['path'])!=audit or scope['normalized_sha256']!=v.digest(normalized):
        raise v.ReviewProtocolError('split furniture normalization changed')
    current=result.get('object_observations_original') if result.get('object_taxonomy_recheck') is not None else result.get('object_observations')
    if current!=normalized:raise v.ReviewProtocolError('split furniture facts changed after observation')
    return normalized
