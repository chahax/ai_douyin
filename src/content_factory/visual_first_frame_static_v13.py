"""Explicit still-time/cropped identity contract; old dynamic shots stay frozen."""
from copy import deepcopy
import hashlib
import io
import json
import math
from pathlib import Path

from PIL import Image
from jsonschema import validate as schema_validate,ValidationError

from . import visual_environment_v4 as environment
from .visual_shot_binding_v3 import fingerprint

CONTRACT='static_start_identity_roi/v13'
SCHEMA='first_frame_static_plan/v13'
GUIDE='first_frame_shot_guide/v13'
CROP='reviewed_identity_head_shoulders/v13'
SHOT_FOV_MIN=12
SHOT_FOV_MAX=110


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def _freeze(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if read(path)!=value:raise ValueError('static_frame_frozen_artifact_changed')
    else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def enabled(config):
    value=config.get('first_frame_contract')
    if value is None:
        if 'first_frame_plan' in config:raise ValueError('static_frame_plan_requires_explicit_contract')
        return False
    if value!=CONTRACT:raise ValueError('unsupported_first_frame_contract')
    if config.get('generation_reference_policy')!='geometry_materials_only/v1':raise ValueError('static_frame_requires_isolated_generation_policy')
    binding=config.get('first_frame_plan')
    if not isinstance(binding,dict) or set(binding)!={'path','sha256'}:raise ValueError('static_frame_plan_binding_required')
    return True


def validate_camera(layout,camera):
    environment.validate_layout(layout)
    camera_schema=deepcopy(environment.layout_schema()['properties']['cameras']['properties']['front'])
    camera_schema['properties']['fov'].update(minimum=SHOT_FOV_MIN,maximum=SHOT_FOV_MAX)
    try:schema_validate(camera,camera_schema)
    except ValidationError as error:raise ValueError('static_frame_camera_schema_invalid') from error
    eye,target=camera['eye'],camera['target'];limits=[layout['room'][k] for k in ('width','depth','height')]
    if any(type(n) not in (int,float) or not math.isfinite(n) for n in eye+target+[camera['fov']]):
        raise ValueError('static_frame_camera_nonfinite')
    if any(not 0<=n<=limit for point in (eye,target) for n,limit in zip(point,limits)):
        raise ValueError('static_frame_camera_outside_room')
    if math.hypot(target[0]-eye[0],target[1]-eye[1])<.3 or not .1<=eye[2]<=limits[2]:
        raise ValueError('static_frame_camera_degenerate')
    for item in layout['objects']:
        if (environment._base(item)-1e-7<=eye[2]<=environment._base(item)+item['size'][2]+1e-7
            and environment._overlap(environment._corners(item),[(eye[0]-.01,eye[1]-.01),(eye[0]+.01,eye[1]-.01),
                (eye[0]+.01,eye[1]+.01),(eye[0]-.01,eye[1]+.01)])):
            raise ValueError('static_frame_camera_inside_object')
    return deepcopy(camera)


def _source_shot(packet,shot):
    found=[item for item in packet.get('shots',[]) if item['id']==shot['id']]
    if len(found)!=1:raise ValueError('static_frame_original_shot_missing_or_duplicate')
    return found[0]


def validate_plan(packet,config):
    if not enabled(config):return None
    binding=config['first_frame_plan']
    if sha(binding['path'])!=binding['sha256']:raise ValueError('static_frame_plan_file_changed')
    value=read(binding['path'])
    if (value.get('schema')!=SCHEMA or value.get('source')!=packet['source']
        or value.get('packet_sha256')!=fingerprint(packet) or sha(packet['source']['path'])!=packet['source']['sha256']):
        raise ValueError('static_frame_source_or_packet_changed')
    if 'camera_conform' in value:
        from .visual_camera_conform_v13 import verify_plan
        verify_plan(value)
    entries=value.get('shots');original={s['id']:s for s in packet.get('shots',[])}
    if (not isinstance(entries,list) or len(entries)!=len(original) or len({e.get('shot_id') for e in entries})!=len(entries)
        or {e.get('shot_id') for e in entries}!=set(original)):
        raise ValueError('static_frame_shot_scope_changed')
    for item in entries:
        if set(item)-{'shot_id','shot_sha256','visible_cast','static_start_prompt','camera_override','camera_design_note'}:
            raise ValueError('static_frame_unknown_shot_plan_fields')
        shot=original[item['shot_id']];text=item.get('static_start_prompt')
        if (item.get('shot_sha256')!=fingerprint(shot) or item.get('visible_cast')!=shot['visible_cast']
            or not isinstance(text,str) or not text.strip() or len(text)>6000
            or any('\u4e00'<=char<='\u9fff' for char in text)):
            raise ValueError('static_frame_shot_cast_or_english_prompt_invalid')
        # Off-screen names must not become image content; their source audio is preserved elsewhere.
        offscreen=set(shot.get('scene_present_cast',[]))|{entity['id'] for entity in packet.get('characters',[])}
        normalized=''.join(c for c in text.casefold() if c.isalnum())
        for identity in offscreen-set(shot['visible_cast']):
            if ''.join(c for c in identity.casefold() if c.isalnum()) in normalized:
                raise ValueError('static_frame_offscreen_identity_in_prompt')
        place=next(p for p in packet['places'] if p['id']==shot['place_id'])
        if not place.get('spatial_layout'):raise ValueError('static_frame_geometry_required')
        if 'camera_override' in item:validate_camera(place['spatial_layout'],item['camera_override'])
    return value


def entry(plan,shot):
    value=validate_plan(plan['packet'],plan['config'])
    if value is None:return None
    original=_source_shot(plan['packet'],shot)
    item=next(e for e in value['shots'] if e['shot_id']==shot['id'])
    return dict(item,source_shot_sha256=fingerprint(original),static_plan=deepcopy(plan['config']['first_frame_plan']))


def camera_for(entity,shot,item):
    view=shot.get('place_view','front')
    if view not in ('front','reverse','side'):raise ValueError('static_frame_perspective_view_required')
    return validate_camera(entity['spatial_layout'],item.get('camera_override',entity['spatial_layout']['cameras'][view]))


def preview_guide(entity,view,camera,path,*,width=736,height=1312):
    """CPU preview only; the actual production guide is separately plan-bound."""
    layout=deepcopy(entity['spatial_layout']);validate_camera(layout,camera);layout['cameras'][view]=deepcopy(camera)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    image=environment._perspective(layout,view,(width,height))
    if path.exists():raise ValueError('static_frame_preview_already_exists')
    image.save(path);return str(path.resolve())


def guide(run,plan,shot,entity,*,width=736,height=1312,create=False):
    if any(type(n) is not int or not 64<=n<=2048 or n%16 for n in (width,height)):
        raise ValueError('static_frame_guide_dimensions_invalid')
    item=entry(plan,shot);camera=camera_for(entity,shot,item);layout=deepcopy(entity['spatial_layout']);view=shot.get('place_view','front')
    binding=dict(schema=GUIDE,static_plan=item['static_plan'],source_shot_sha256=item['source_shot_sha256'],
        binding_sha256=shot['binding_sha256'],layout_sha256=fingerprint(layout),source_place_sha256=fingerprint(entity),renderer=environment.RENDERER,
        camera=camera,width=width,height=height,view=view)
    folder=Path(run).resolve()/'environment_guides'/'static_v13'/fingerprint(binding)[:24]
    path=folder/'guide.png';manifest=folder/'GUIDE.json'
    if create and not manifest.exists():
        if path.exists():raise ValueError('static_frame_orphan_guide')
        folder.mkdir(parents=True,exist_ok=True);layout['cameras'][view]=camera
        environment._perspective(layout,view,(width,height)).save(path)
        _freeze(manifest,dict(binding=binding,path=str(path),sha256=sha(path)))
    value=read(manifest)
    if value.get('binding')!=binding or value.get('path')!=str(path) or value.get('sha256')!=sha(path):
        raise ValueError('static_frame_guide_binding_or_pixels_changed')
    with Image.open(path) as image:
        if image.format!='PNG' or image.size!=(width,height):raise ValueError('static_frame_guide_dimensions_changed')
        image.verify()
    return dict(schema=GUIDE,path=str(path),sha256=value['sha256'],view=view,layout_sha256=binding['layout_sha256'],
        camera=camera,renderer=environment.RENDERER,manifest_path=str(manifest),manifest_sha256=sha(manifest),
        technical_guide=True,production_approved=False,static_plan=item['static_plan'],binding_sha256=shot['binding_sha256'])


def identity_roi(face,size):
    width,height=size
    if (not isinstance(face,dict) or set(face)!={'x','y','width','height'} or any(type(v) is not int for v in face.values())
        or min(face['x'],face['y'])<0 or min(face['width'],face['height'])<1
        or face['x']+face['width']>width or face['y']+face['height']>height):
        raise ValueError('static_frame_approved_face_roi_invalid')
    # One continuous head/shoulders/upper-chest region, not a pose-bearing whole body.
    center=face['x']+face['width']/2;left=max(0,round(center-face['width']*1.25));right=min(width,round(center+face['width']*1.25))
    top=max(0,round(face['y']-face['height']*.25));bottom=min(height,round(face['y']+face['height']*2.25))
    if bottom-top>height*.55 or bottom>height*.58:raise ValueError('static_frame_identity_crop_would_include_body_pose')
    return dict(x=left,y=top,width=right-left,height=bottom-top)


def character_input(run,plan,row,*,create=False):
    from . import visual_asset_pipeline_v3 as pipeline
    req={k:row[k] for k in ('entity_id','kind','view','design_version')}
    current=pipeline._lookup(plan,req)
    if (row.get('kind')!='character' or not current or current['status']!='reviewed'
        or pipeline._asset_identity(current)!=pipeline._asset_identity(row)):
        raise ValueError('static_frame_identity_requires_current_reviewed_front')
    current=pipeline._lookup(plan,{**req,'view':'front'})
    if not current or current['status']!='reviewed':raise ValueError('static_frame_canonical_front_not_reviewed')
    review=pipeline._latest_review({},current)
    if review.get('decision')!='accepted' or review.get('target_sha256')!=current['sha256']:
        raise ValueError('static_frame_identity_review_not_bound')
    source=pipeline._image_path(plan,current)
    with Image.open(source) as image:
        size=list(image.size);face=review.get('rois',{}).get('face');roi=identity_roi(face,size)
        out=io.BytesIO();image.convert('RGB').crop((roi['x'],roi['y'],roi['x']+roi['width'],roi['y']+roi['height'])).save(out,format='PNG');pixels=out.getvalue()
    binding=dict(schema=CROP,source_identity=pipeline._asset_identity(current),shot_reference_identity=pipeline._asset_identity(row),source_path=str(source),source_dimensions=size,
        source_review_sha256=fingerprint(review),source_event_sha256=fingerprint(current.get('review')),
        face_roi=face,pixel_roi=roi,crop_sha256=hashlib.sha256(pixels).hexdigest())
    folder=Path(run).resolve()/'identity_crops'/fingerprint(binding)[:24];path=folder/'head_shoulders.png';manifest=folder/'CROP.json'
    if create and not manifest.exists():
        if path.exists():raise ValueError('static_frame_orphan_identity_crop')
        folder.mkdir(parents=True,exist_ok=True);path.write_bytes(pixels);_freeze(manifest,binding)
    if read(manifest)!=binding or sha(path)!=binding['crop_sha256'] or path.read_bytes()!=pixels:
        raise ValueError('static_frame_actual_identity_crop_changed')
    return dict(input_name='identity_'+row['entity_id']+'_'+binding['crop_sha256'][:16]+'.png',path=str(path),sha256=binding['crop_sha256']),dict(binding,
        path=str(path),manifest_path=str(manifest),manifest_sha256=sha(manifest))


def contexts(entity,shot,item,*,width=736,height=1312):
    layout=deepcopy(entity['spatial_layout']);view=shot.get('place_view','front');layout['cameras'][view]=camera_for(entity,shot,item)
    visible=environment._perspective(layout,view,(width,height),return_visibility=True)[1]
    anchors=[]
    for obj in layout['objects']+layout['openings']:
        if obj['id'] in visible:
            description=(obj['color']+' '+obj['kind'].replace('_',' ') if 'color' in obj else obj['kind']+' on the '+obj['wall']+' wall')
            if obj['kind']=='bed':description+=' frame and its raised sleeping surface'
            elif obj['kind']=='bedding':description+=' sheet on the raised bed mattress'
            anchors.append(dict(id=obj['id'],kind=obj['kind'],description=description,**visible[obj['id']],distance_band='middle'))
    semantic=dict(layout_design='The same fixed room and furnishings from its approved design, viewed through the supplied shot-specific geometry guide.',
        space_type=layout['space_type'],camera_description='Match the shot-specific geometry reference camera and partial framing.',visible_anchors=anchors,
        comparison_rule='Judge this supplied shot-specific guide, allowing partial framing and occlusion. Full room reference supplies identity, not the current camera.')
    material=deepcopy(entity.get('static_materials',{}))
    positive=dict(surface_materials=material,visible_furnishings_and_openings=[{k:v for k,v in a.items() if k not in ('id','distance_band')} for a in anchors],
        camera='Match the supplied geometry reference framing and viewpoint.')
    return positive,semantic


def prompt(plan,shot,entity,*,width=736,height=1312):
    item=entry(plan,shot);positive,_=contexts(entity,shot,item,width=width,height=height)
    return ('One still photograph at the beginning of the shot. The first reference defines this camera and the room geometry. '
        +'The photograph contains exactly '+str(len(shot['visible_cast']))+' visible person'+('s. ' if len(shot['visible_cast'])!=1 else '. ')
        +
        'Each following portrait crop supplies the identity and collar appearance of one specified visible person, independent of body pose. '
        'The final references supply surface colors and finishes. '+item['static_start_prompt']
        +'\nRoom appearance and visible geometry: '+json.dumps(positive,ensure_ascii=False))


def binding(plan,shot,guide_value,crops,prompt_text):
    item=entry(plan,shot)
    return dict(schema='first_frame_static_binding/v13',contract=CONTRACT,static_plan=item['static_plan'],
        packet_sha256=plan['packet_sha256'],source_shot_sha256=item['source_shot_sha256'],binding_sha256=shot['binding_sha256'],
        visible_cast=deepcopy(shot['visible_cast']),guide_sha256=guide_value['sha256'],identity_crops=crops,
        prompt_sha256=hashlib.sha256(prompt_text.encode('utf-8')).hexdigest())
