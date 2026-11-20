"""Bound target-only disambiguation of one cross-labelled furniture instance.

Overlap only selects an observation to inspect. It never chooses a category or
uses a planned count. Same-class instances (including two beds) are never merged.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

VERSION='target_furniture_taxonomy/v1'
SPLIT_VERSION='target_furniture_taxonomy/v2'
PAIRS=(('table','counter'),)
PROMPT='''Inspect ONLY this actual target-image crop. There is no layout guide,
source-room image, permitted quantity or desired category. Two overlapping annotations
may describe the same furniture, or separate objects occluding each other. Determine
whether they refer to exactly one physical instance. Count the physical instances
represented by those annotations, not incidental background objects. A table is a
freestanding horizontal surface with its own legs/base. A counter is a built-in or
fixed worktop; an ordinary four-legged table does not become a counter merely because
someone could work on it. Choose one unique visible physical category if supported.
Do not assign two categories to one object, invent a fixed attachment, or guess from
intended function. If distinct instances are visible, keep them distinct and return
unique_category=unknown. If the crop cannot establish identity/count/category, use
null or unknown. Give specific visible evidence. Do not judge acceptance or layout.
Return ONLY the supplied JSON. Candidate annotation categories: table, counter.'''
SCHEMA=dict(type='object',properties=dict(
    same_physical_instance={'type':['boolean','null']},
    visible_instance_count={'type':['integer','null'],'minimum':0,'maximum':100},
    unique_category={'type':'string','enum':['table','counter','unknown']},
    evidence={'type':'string','minLength':1}),
    required=['same_physical_instance','visible_instance_count','unique_category','evidence'],additionalProperties=False)


def _v():
    from . import visual_asset_review_v3 as v
    return v


def candidate(observations):
    """At most one strongly overlapping cross-category pair; no same-kind merge."""
    found=[]
    for a,b in PAIRS:
        if a not in observations or b not in observations:continue
        if observations[a]['count'] is None or observations[b]['count'] is None:continue
        for i,x in enumerate(observations[a]['regions']):
            for j,y in enumerate(observations[b]['regions']):
                overlap=max(0,min(x[2],y[2])-max(x[0],y[0]))*max(0,min(x[3],y[3])-max(x[1],y[1]))
                union=(x[2]-x[0])*(x[3]-x[1])+(y[2]-y[0])*(y[3]-y[1])-overlap
                if union and overlap/union>=.8:
                    found.append((overlap/union,a,b,i,j,x,y))
    if not found:return None
    _,a,b,i,j,x,y=max(found,key=lambda r:(r[0],-r[3],-r[4]))
    box=[min(x[0],y[0]),min(x[1],y[1]),max(x[2],y[2]),max(x[3],y[3])]
    pad=max(40,round(max(box[2]-box[0],box[3]-box[1])*.12))
    roi=[max(0,box[0]-pad),max(0,box[1]-pad),min(1000,box[2]+pad),min(1000,box[3]+pad)]
    return dict(annotations=[dict(kind=a,index=i,region=deepcopy(x)),dict(kind=b,index=j,region=deepcopy(y))],roi=roi)


def answer(value):
    v=_v();v._keys(value,('same_physical_instance','visible_instance_count','unique_category','evidence'),'furniture taxonomy')
    same=value['same_physical_instance'];count=value['visible_instance_count'];category=value['unique_category']
    if ((same is not None and type(same) is not bool) or
        (count is not None and (type(count) is not int or not 0<=count<=100)) or
        category not in ('table','counter','unknown') or
        not isinstance(value['evidence'],str) or not value['evidence'].strip()):raise v.ReviewProtocolError('invalid furniture taxonomy response')
    if ((same is True and count not in (1,None)) or
        (same is False and (category!='unknown' or count in (0,1))) or
        (same is None and category!='unknown') or
        (category!='unknown' and (same is not True or count!=1))):raise v.ReviewProtocolError('inconsistent furniture taxonomy response')
    return deepcopy(value)


def apply(original,selection,observed):
    """Replay only the independently observed scope; never inspect allowed counts."""
    value=deepcopy(original);observed=answer(observed)
    if observed['same_physical_instance'] is False:return value
    entries=selection['annotations']
    if observed['same_physical_instance'] is True and observed['visible_instance_count']==1 and observed['unique_category']!='unknown':
        category=observed['unique_category']
        for item in entries:
            field=value[item['kind']];field['regions'].pop(item['index']);field['count']-=1
        chosen=next(item for item in entries if item['kind']==category)
        value[category]['regions'].append(deepcopy(chosen['region']));value[category]['count']+=1
    else:
        for item in entries:value[item['kind']]['count']=None
    for item in entries:value[item['kind']]['evidence']+=' Target-only taxonomy ROI: '+observed['evidence']
    return value


def payload(target,selection):
    v=_v();roi=v.pixel_box(selection['roi'],target)
    crop=v._png(dict(binding=target,region=roi));crop_sha=hashlib.sha256(crop).hexdigest()
    return dict(prompt=PROMPT,images=[dict(role='target_furniture_crop',binding=deepcopy(target),region=roi,png_sha256=crop_sha)],schema=deepcopy(SCHEMA)),crop


def _artifact(path):
    v=_v();return dict(path=str(Path(path).resolve()),sha256=v.file_sha(path))


def recheck(original,target,infer,folder,*,observation_scope=None):
    v=_v();selected=candidate(original)
    if selected is None:return deepcopy(original),None
    if folder is None:raise v.ReviewProtocolError('furniture taxonomy requires persistent evidence')
    folder=Path(folder);request,crop=payload(target,selected)
    path=folder/'FURNITURE_TAXONOMY_0.png'
    if path.exists() and path.read_bytes()!=crop:raise v.ReviewProtocolError('frozen furniture taxonomy crop changed')
    if not path.exists():path.write_bytes(crop)
    native=v._native_call(infer,request,folder,'FURNITURE_TAXONOMY_0')
    observed=answer(v._parse_content(native['text']));corrected=apply(original,selected,observed)
    proof=dict(schema=SPLIT_VERSION if observation_scope is not None else VERSION,target=deepcopy(target),selection=selected,answer=observed,
        original_sha256=v.digest(original),corrected_sha256=v.digest(corrected),
        artifacts={key:_artifact(folder/name) for key,name in dict(
            blind_request='FURNITURE_REQUEST.json' if observation_scope is not None else 'BLIND_REQUEST.json',
            blind_native='FURNITURE_NATIVE.json' if observation_scope is not None else 'BLIND_NATIVE.json',
            request='FURNITURE_TAXONOMY_0_REQUEST.json',native='FURNITURE_TAXONOMY_0_NATIVE.json',
            crop='FURNITURE_TAXONOMY_0.png').items()})
    return corrected,proof


def finish_proof(proof,folder):
    if proof is not None:proof['artifacts']['primary_native']=_artifact(Path(folder)/'MODEL_NATIVE.json')
    return proof


def verify(result):
    """Re-read raw/crop pixels and replay the only allowed count transformation."""
    v=_v();proof=result.get('object_taxonomy_recheck');original=result.get('object_observations_original')
    if proof is None:
        if original is not None:raise v.ReviewProtocolError('furniture taxonomy original requires bound proof')
        return
    if not isinstance(proof,dict) or proof.get('schema') not in (VERSION,SPLIT_VERSION):raise v.ReviewProtocolError('invalid furniture taxonomy proof')
    target=proof['target']
    if v.image_binding(target['path'])!=target or result.get('target_sha256')!=target['sha256']:
        raise v.ReviewProtocolError('furniture taxonomy target changed')
    inventory=result['layout_object_inventory'];v.validate_object_observations(original,inventory)
    if proof['original_sha256']!=v.digest(original) or candidate(original)!=proof['selection']:
        raise v.ReviewProtocolError('furniture taxonomy source selection changed')
    artifacts=proof['artifacts'];v._keys(artifacts,('blind_request','blind_native','request','native','crop','primary_native'),'furniture taxonomy artifacts')
    for item in artifacts.values():
        if v.file_sha(item['path'])!=item['sha256']:raise v.ReviewProtocolError('furniture taxonomy artifact changed')
    blind_request=v._read(artifacts['blind_request']['path'])
    if proof['schema']==VERSION:
        if (blind_request['images']!=[dict(role='observed_image',binding=target)] or
            blind_request['prompt']!=v.BLIND_PROMPT+v.FURNITURE_PROMPT or
            blind_request['schema']!=v.blind_schema(dict(kind='place',layout_object_inventory=inventory,locate_rois=[])) or
            v._parse_content(v._read(artifacts['blind_native']['path'])['text']).get('object_observations')!=original):
            raise v.ReviewProtocolError('furniture taxonomy original blind observation changed')
    else:
        from . import visual_split_observation_v14 as split
        normalized=split.verify(result);scope=result.get('split_observation',{}).get('artifacts',{})
        if (normalized!=original or artifacts['blind_request']!=scope.get('furniture_request') or
            artifacts['blind_native']!=scope.get('furniture_native')):raise v.ReviewProtocolError('split taxonomy furniture source changed')
    request,crop=payload(target,proof['selection'])
    if v._read(artifacts['request']['path'])!=request or Path(artifacts['crop']['path']).read_bytes()!=crop:
        raise v.ReviewProtocolError('furniture taxonomy ROI request or original pixels changed')
    observed=answer(v._parse_content(v._read(artifacts['native']['path'])['text']))
    corrected=apply(original,proof['selection'],observed)
    if (observed!=proof['answer'] or proof['corrected_sha256']!=v.digest(corrected) or
        result.get('object_observations')!=corrected):raise v.ReviewProtocolError('furniture taxonomy correction changed')
    primary=v._parse_content(v._read(artifacts['primary_native']['path'])['text'])
    before=primary['checks']['layout'];after=result['checks'].get('layout')
    if ((before is False and after is not False) or (before is None and after is True)):
        raise v.ReviewProtocolError('taxonomy cannot upgrade primary layout false or null')
    if result.get('primary_checks_before_inventory',{}).get('layout') is not before:
        raise v.ReviewProtocolError('taxonomy primary layout evidence changed')

