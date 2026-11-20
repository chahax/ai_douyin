"""Compact room comparison; target-only observations remain separate facts."""
from copy import deepcopy
import json

SCOPE='compact_room/v18'
VERSION='room_compare/v18'
CHECKS=('layout','view','consistency','artifact_free')
PROMPT='''Compare the actual TARGET room with its approved SOURCE room and the
current-camera geometry GUIDE. The GUIDE is an art-production blockout, not a photo.
Judge four things only:
layout: visible fixed furnishings/openings have compatible physical relationships;
view: TARGET follows the current GUIDE camera/partial framing, allowing occlusion;
consistency: visible room finishes/furnishings and supplied spatial staging agree;
artifact_free: no visible duplicate furniture, collage or broken room geometry.
Do not infer hidden geometry. Ordinary lighting differences are not a new room.
An independently observed human count is context only, not a request to recount or
describe people. Do not restate the whole scene, source story or action sequence.
For each check return true, false or null, plus exactly ONE short concrete sentence
for that check. null means genuinely not judgeable; false is an observed mismatch.
Each evidence sentence must be at most 180 characters. Do not repeat sentences.
Return exactly the two JSON fields checks and evidence, each with the four named
keys. No other observations, regions, commentary, approval decision or narration.'''


def enabled(expectation):
    value=expectation.get('room_comparison_scope')
    if value is None:return False
    if value!=SCOPE or expectation.get('kind')!='place':raise ValueError('compact_room_scope_requires_place')
    return True


def schema():
    fields={k:dict(type=['boolean','null']) for k in CHECKS}
    evidence={k:dict(type='string',minLength=1,maxLength=180) for k in CHECKS}
    return dict(type='object',properties=dict(
        checks=dict(type='object',properties=fields,required=list(CHECKS),additionalProperties=False),
        evidence=dict(type='object',properties=evidence,required=list(CHECKS),additionalProperties=False)),
        required=['checks','evidence'],additionalProperties=False)


def contract():return dict(version=VERSION,prompt=PROMPT,schema=schema())


def payload(prepared,blind):
    if not enabled(prepared['expectation']) or not prepared.get('reference') or not prepared.get('layout_guide'):
        raise ValueError('compact_room_requires_source_and_actual_guide')
    exp=prepared['expectation']
    semantic=dict(environment_context=deepcopy(exp.get('environment_context') or {}),
        room_description=exp.get('composition_place',{}).get('description',''),
        independently_observed_people_count=blind['observations']['people_count'])
    if exp.get('spatial_staging') is not None:
        value=exp['spatial_staging']
        if not isinstance(value,str) or len(value)>400:raise ValueError('compact_room_spatial_staging_invalid')
        semantic['spatial_staging']=value
    return dict(prompt=PROMPT+'\nROOM_DATA:\n'+json.dumps(semantic,ensure_ascii=False),schema=schema(),
        images=[dict(role='target',binding=prepared['target']),dict(role='reference',binding=prepared['reference']),
                dict(role='layout_guide',binding=prepared['layout_guide'])])


def observation(raw,blind):
    from . import visual_asset_review_v3 as v
    v._keys(raw,('checks','evidence'),'compact room comparison')
    v._keys(raw['checks'],CHECKS,'compact room checks');v._keys(raw['evidence'],CHECKS,'compact room evidence')
    if any(type(x) is not bool and x is not None for x in raw['checks'].values()):raise v.ReviewProtocolError('compact room checks must be bool/null')
    if any(not isinstance(x,str) or not x.strip() or len(x)>180 for x in raw['evidence'].values()):
        raise v.ReviewProtocolError('compact room evidence must be 1..180 characters per check')
    issues=[]
    for key,value in raw['checks'].items():
        if value is not True:issues.append(dict(kind='view' if key=='view' else 'artifact' if key=='artifact_free' else 'layout',
            severity='blocking' if value is False else 'uncertain',evidence=raw['evidence'][key],target_region=None,reference_region=None))
    return dict(checks=deepcopy(raw['checks']),observations={k:v for k,v in blind['observations'].items() if k!='pose_view'},
        issues=issues,rois=deepcopy(blind['rois']),reference_rois=dict.fromkeys(v.ROI_NAMES),evidence=list(raw['evidence'].values()))


def verify_result(result):
    proof=result.get('room_comparison')
    if proof is None:
        if (result.get('room_comparison_scope')==SCOPE or result.get('prompt_version')==VERSION) and result.get('decision')!='unavailable':
            raise ValueError('compact_room_native_proof_required')
        return
    from pathlib import Path
    from . import visual_asset_review_v3 as v
    if proof.get('schema')!=VERSION:raise ValueError('compact_room_proof_schema_changed')
    for name in ('request','native'):
        item=proof[name]
        if v.file_sha(item['path'])!=item['sha256']:raise ValueError('compact_room_native_proof_changed')
    request=v._read(proof['request']['path']);native=v._read(proof['native']['path'])
    v._unchanged(proof['prepared'])
    if request!=payload(proof['prepared'],proof['blind']):raise ValueError('compact_room_request_changed')
    raw=v._parse_content(native['text']);answer=observation(raw,proof['blind'])
    # Inventory/other conservative gates may make a true primary false, never
    # upgrade a primary false/null. Keep the exact primary verdict available.
    primary=result.get('primary_checks_before_inventory',result['checks'])
    for key,value in answer['checks'].items():
        if value is not True and (primary.get(key)!=value or result['checks'].get(key) is True):
            raise ValueError('compact_room_primary_verdict_upgraded')
    if result.get('target_sha256')!=proof['prepared']['target']['sha256']:raise ValueError('compact_room_target_changed')
