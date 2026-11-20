"""Source-bound material crops for rooms sharing one residence, never room geometry."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import re

import numpy as np
from PIL import Image,ImageFilter

from . import visual_environment_v4 as environment
from . import visual_asset_registry_v3 as registry
from . import visual_image_jobs_v3 as jobs
from .visual_shot_binding_v3 import fingerprint

SCHEMA='residence_style_reference/v5'
APPEARANCE_SCHEMA='residence_appearance_reference/v6'
MATERIAL_CONTRACT='material/v1'
APPEARANCE_CONTRACT='appearance/v1'
MASK_VERSION='visible_surface_masks/exposure-v2'
MIN_PATCH_SIDE=64
MAX_PATCH_SIDE=256
SLOTS=('wall','floor','wood')
CHECKS=('palette','era_finish','wear','rendering_style')


class StyleStale(ValueError):pass


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def identity(row):return {k:row[k] for k in ('asset_id','version','entity_id','kind','view','design_version','sha256')}


def reference_contract(config):
    value=config.get('style_reference_contract',MATERIAL_CONTRACT)
    if value not in (MATERIAL_CONTRACT,APPEARANCE_CONTRACT):raise ValueError('residence_reference_contract_unsupported')
    if value==APPEARANCE_CONTRACT and not config.get('style_reference_parent_manifest'):
        raise ValueError('appearance_reference_requires_frozen_parent_crops')
    return value


def group_for(packet,entity):
    gid=entity.get('style_group_id')
    if not gid:return None
    groups=[g for g in packet.get('style_groups',[]) if g['id']==gid]
    if len(groups)!=1:raise ValueError('residence_style_group_missing_or_duplicate')
    group=groups[0]
    if (group.get('definition_sha256')!=fingerprint({k:v for k,v in group.items() if k!='definition_sha256'})
        or entity.get('home_style_sha256')!=group['definition_sha256'] or entity.get('style_version')!=group['style_version']
        or group.get('source')!=packet['source'] or entity['id'] not in group['members']):
        raise StyleStale('residence_style_definition_changed')
    return group


def validate_groups(packet):
    groups=packet.get('style_groups',[]);places={p['id']:p for p in packet.get('places',[])};seen=set()
    if not isinstance(groups,list):raise ValueError('residence_style_groups_invalid')
    for group in groups:
        if (not isinstance(group,dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',str(group.get('id','')))
            or group['id'] in seen or not isinstance(group.get('members'),list) or not group['members']
            or len(group['members'])!=len(set(group['members'])) or not set(group['members'])<=set(places)
            or group.get('master_place_id') not in group['members'] or set(group.get('room_materials',{}))!=set(group['members'])):
            raise ValueError('residence_style_members_or_master_invalid')
        seen.add(group['id']);slots=group.get('required_material_slots')
        if not isinstance(slots,list) or not 1<=len(slots)<=3 or len(set(slots))!=len(slots) or not set(slots)<=set(SLOTS):
            raise ValueError('residence_style_material_slots_invalid')
        shared=group.get('shared_style')
        if (not isinstance(shared,dict) or not shared or any(not re.fullmatch(r'[A-Za-z0-9_]{1,80}',str(k))
            or not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',v) for k,v in shared.items())):
            raise ValueError('residence_style_shared_enums_invalid')
        if 'wood' in slots and shared.get('wood_color') not in environment.COLORS:raise ValueError('residence_style_wood_material_missing')
        for pid in group['members']:
            entity=places[pid]
            if entity.get('style_group_id')!=group['id']:raise ValueError('residence_style_member_group_disagrees')
            group_for(packet,entity)
            if group['room_materials'][pid]!=entity.get('static_materials'):raise ValueError('residence_style_room_materials_disagree')
    for entity in places.values():group_for(packet,entity)
    return groups


def _material_key(group,entity,slot):
    materials=entity['static_materials']
    return materials['wall_surface'] if slot=='wall' else materials['floor_surface'] if slot=='floor' else group['shared_style']['wood_color']


def _rectangle(mask):
    """Largest axis-aligned rectangle wholly inside an eroded visible surface."""
    mask=np.array(Image.fromarray(mask.astype(np.uint8)*255).filter(ImageFilter.MinFilter(7)))>0
    heights=[0]*mask.shape[1];best=(0,0,0,0);best_area=0
    for y,row in enumerate(mask):
        heights=[height+1 if on else 0 for height,on in zip(heights,row)];stack=[]
        for x,height in enumerate(heights+[0]):
            start=x
            while stack and stack[-1][1]>height:
                left,old=stack.pop();width=x-left
                if min(width,old)>=MIN_PATCH_SIDE and width*old>best_area:
                    best_area=width*old;best=(left,y-old+1,width,old)
                start=left
            if not stack or stack[-1][1]<height:stack.append((start,height))
    x,y,w,h=best
    if min(w,h)<MIN_PATCH_SIDE:raise ValueError('residence_style_pure_material_roi_too_small')
    cw,ch=min(w,MAX_PATCH_SIDE),min(h,MAX_PATCH_SIDE)
    return dict(x=x+(w-cw)//2,y=y+(h-ch)//2,width=cw,height=ch)


def _exposed_rectangle(mask,source):
    """Rank pure source pixels by visibility, not brightness-edit or geometry area."""
    pure=np.array(Image.fromarray(mask.astype(np.uint8)*255).filter(ImageFilter.MinFilter(7)))>0
    rgb=np.asarray(source.convert('RGB'),dtype=np.float64)/255
    luminance=rgb[...,0]*.2126+rgb[...,1]*.7152+rgb[...,2]*.0722
    if luminance.shape!=pure.shape:raise ValueError('residence_style_quality_mask_dimensions_changed')
    def integral(value):return np.pad(value.cumsum(0).cumsum(1),((1,0),(1,0)))
    counts=integral(pure.astype(np.int64));light=integral(luminance);squares=integral(luminance*luminance)
    usable=integral(((luminance>=.07)&(luminance<=.95)).astype(np.int64));height,width=pure.shape
    best=None;best_score=-1
    def consider(xs,ys,w,h):
        nonlocal best,best_score
        xx=xs[None,:];yy=ys[:,None];area=w*h
        def sums(table):return table[yy+h,xx+w]-table[yy,xx+w]-table[yy+h,xx]+table[yy,xx]
        valid=sums(counts)==area;mean=sums(light)/area
        deviation=np.sqrt(np.maximum(0,sums(squares)/area-mean*mean));fraction=sums(usable)/area
        valid&=(mean>=.055)&(mean<=.95)&(fraction>=.50)
        exposure=np.clip(mean/.18,0,1)*np.clip((1-mean)/.08,0,1)
        score=exposure*(.70*fraction+.15*np.minimum(deviation/.05,1)+.15*min((area**.5)/MAX_PATCH_SIDE,1))
        score=np.where(valid,score,-1);index=np.unravel_index(int(score.argmax()),score.shape);quality=float(score[index])
        if quality>best_score:
            best_score=quality;best=dict(x=int(xs[index[1]]),y=int(ys[index[0]]),width=w,height=h,
                quality=dict(luminance_mean=float(mean[index]),usable_fraction=float(fraction[index]),
                    luminance_std=float(deviation[index]),score=quality))
    for w,h in ((256,256),(192,192),(128,128),(96,96),(64,64),(64,128),(128,64),(64,256),(256,64),(96,192),(192,96)):
        if w>width or h>height:continue
        xs=np.unique(np.r_[np.arange(0,width-w+1,16),width-w]);ys=np.unique(np.r_[np.arange(0,height-h+1,16),height-h])
        consider(xs,ys,w,h)
    # Exact mask rectangle avoids missing a narrow valid region between grid steps.
    fallback=_rectangle(mask)
    consider(np.array([fallback['x']]),np.array([fallback['y']]),fallback['width'],fallback['height'])
    if best is None or best_score<0:raise ValueError('residence_style_actual_exposure_insufficient')
    quality=best.pop('quality');return best,quality


def _crop_bytes(path,roi):
    if set(roi)!={'x','y','width','height'} or any(type(v) is not int for v in roi.values()):raise ValueError('residence_style_roi_invalid')
    with Image.open(path) as image:
        if (min(roi['x'],roi['y'])<0 or min(roi['width'],roi['height'])<MIN_PATCH_SIDE
            or roi['x']+roi['width']>image.width or roi['y']+roi['height']>image.height):raise ValueError('residence_style_roi_outside_source')
        output=io.BytesIO();image.convert('RGB').crop((roi['x'],roi['y'],roi['x']+roi['width'],roi['y']+roi['height'])).save(output,format='PNG')
        return output.getvalue(),[image.width,image.height]


def _current_master(bundle):
    master=bundle['master'];rows=registry.get(bundle['library'],book_id=bundle['book_id'],entity_id=master['identity']['entity_id'],
        kind='place',view='front',design_version=master['identity']['design_version'])
    current=max(rows,key=lambda row:row['version']) if rows else None
    if not current or identity(current)!=master['identity'] or current['status']!='reviewed':raise StyleStale('residence_style_master_version_changed_or_unreviewed')
    path=(Path(bundle['library'])/current['file']).resolve()
    if path!=Path(master['path']).resolve() or sha(path)!=master['identity']['sha256']:raise ValueError('residence_style_master_file_changed')
    if fingerprint(current.get('review'))!=master['review_sha256']:raise StyleStale('residence_style_master_review_changed')


def _validate_bundle(bundle):
    contract=bundle.get('reference_contract',MATERIAL_CONTRACT)
    if (bundle.get('schema')!=(APPEARANCE_SCHEMA if contract==APPEARANCE_CONTRACT else SCHEMA)
        or contract not in (MATERIAL_CONTRACT,APPEARANCE_CONTRACT)):
        raise ValueError('residence_style_reference_schema_invalid')
    if bundle.get('renderer')!=environment.RENDERER or bundle.get('mask_version')!=MASK_VERSION:
        raise StyleStale('residence_style_renderer_or_mask_changed')
    group=bundle['group']
    if (group['definition_sha256']!=fingerprint({k:v for k,v in group.items() if k!='definition_sha256'})
        or sha(group['source']['path'])!=group['source']['sha256']):raise StyleStale('residence_style_original_source_changed')
    _current_master(bundle);base=Path(bundle['manifest_path']).parent.resolve()
    for patch in bundle['patches']:
        crop=Path(patch['path']).resolve()
        if not crop.is_relative_to(base) or crop.parent!=base/'patches':raise ValueError('residence_style_crop_outside_bundle')
        raw,dimensions=_crop_bytes(bundle['master']['path'],patch['pixel_roi'])
        digest=hashlib.sha256(raw).hexdigest()
        if (dimensions!=patch['source_dimensions'] or patch['source_sha256']!=bundle['master']['identity']['sha256']
            or sha(crop)!=patch['sha256'] or digest!=patch['sha256']):raise ValueError('residence_style_actual_crop_changed')
    if contract==APPEARANCE_CONTRACT:
        inherited=bundle.get('inherited_reference',{})
        if sha(inherited['path'])!=inherited.get('sha256'):raise ValueError('appearance_parent_reference_changed')
        parent=read(inherited['path']);parent['manifest_path']=inherited['path'];parent['manifest_sha256']=inherited['sha256']
        if parent.get('schema')!=SCHEMA or parent.get('reference_contract',MATERIAL_CONTRACT)!=MATERIAL_CONTRACT:
            raise ValueError('appearance_parent_must_be_original_material_bundle')
        _validate_bundle(parent)
        if (parent['group']!=bundle['group'] or parent['master']!=bundle['master']
            or [{k:p[k] for k in p if k!='path'} for p in parent['patches']]!=
               [{k:p[k] for k in p if k!='path'} for p in bundle['patches']]):
            raise ValueError('appearance_reference_must_keep_original_crops')
    return bundle


def _load(path):
    path=Path(path).resolve();bundle=read(path);bundle.update(manifest_path=str(path),manifest_sha256=sha(path))
    return _validate_bundle(bundle)


def reference_path(reference_root,group,master_row,guide,*,contract=MATERIAL_CONTRACT,parent_manifest=None):
    binding=dict(group=group,master=identity(master_row),review=fingerprint(master_row.get('review')),guide=guide,
        mask_version=MASK_VERSION,renderer=environment.RENDERER)
    if contract==APPEARANCE_CONTRACT:
        if not parent_manifest:raise ValueError('appearance_reference_requires_frozen_parent_crops')
        binding.update(reference_contract=contract,parent_manifest_path=str(Path(parent_manifest).resolve()),
            parent_manifest_sha256=sha(parent_manifest))
    return Path(reference_root)/group['id']/fingerprint(binding)[:24]/'MANIFEST.json'


def prepare_reference(run,group,master_entity,master_row,master_path,guide,*,library_path,
                      contract=MATERIAL_CONTRACT,parent_manifest=None):
    if master_row['status']!='reviewed' or master_row['entity_id']!=group['master_place_id'] or master_row['view']!='front':
        raise ValueError('residence_style_master_must_be_reviewed_front')
    if master_row.get('provenance',{}).get('source')!=group['source']:raise ValueError('residence_style_master_original_source_disagrees')
    if sha(master_path)!=master_row['sha256'] or sha(guide['path'])!=guide['sha256']:raise ValueError('residence_style_source_or_guide_changed')
    with Image.open(master_path) as image:size=image.size
    with Image.open(guide['path']) as image:guide_size=image.size
    if (guide_size!=size or guide.get('layout_sha256')!=fingerprint(master_entity['spatial_layout'])
        or guide.get('camera')!=master_entity['spatial_layout']['cameras']['front'] or guide.get('view')!='front'
        or guide.get('renderer')!=environment.RENDERER):raise ValueError('residence_style_source_guide_alignment_invalid')
    path=reference_path(Path(run)/'style_references',group,master_row,guide,contract=contract,parent_manifest=parent_manifest);folder=path.parent
    if path.exists():return load_reference(path,group,master_row,master_path,require_ready=False)
    patches=[]
    parent=None
    if contract==APPEARANCE_CONTRACT:
        parent=load_reference(parent_manifest,group,master_row,master_path,require_ready=False)
        if parent.get('reference_contract',MATERIAL_CONTRACT)!=MATERIAL_CONTRACT:
            raise ValueError('appearance_parent_must_be_original_material_bundle')
        patches=deepcopy(parent['patches'])
        for patch in patches:patch['path']=str((folder/'patches'/(patch['slot']+'.png')).resolve())
    else:
        _,masks=environment._perspective(master_entity['spatial_layout'],'front',size,return_surfaces=True)
        with Image.open(master_path) as source:source_rgb=source.convert('RGB')
        for slot in group['required_material_slots']:
            roi,quality=_exposed_rectangle(masks[slot],source_rgb);raw,dimensions=_crop_bytes(master_path,roi)
            patches.append(dict(slot=slot,material_key=_material_key(group,master_entity,slot),path=str((folder/'patches'/(slot+'.png')).resolve()),
                sha256=hashlib.sha256(raw).hexdigest(),source_sha256=master_row['sha256'],source_dimensions=dimensions,pixel_roi=roi,
                selection_quality=quality))
    (folder/'patches').mkdir(parents=True,exist_ok=True)
    for patch in patches:
        raw,_=_crop_bytes(master_path,patch['pixel_roi']);target=Path(patch['path'])
        if target.exists():
            if sha(target)!=patch['sha256']:raise ValueError('residence_style_crop_not_overwritten')
        else:
            with target.open('xb') as stream:stream.write(raw)
    bundle=dict(schema=SCHEMA,group=deepcopy(group),book_id=master_row['book_id'],library=str(Path(library_path).resolve()),
        master=dict(identity=identity(master_row),path=str(Path(master_path).resolve()),review_sha256=fingerprint(master_row.get('review')),
            layout_sha256=fingerprint(master_entity['spatial_layout']),camera_sha256=fingerprint(master_entity['spatial_layout']['cameras']['front']),
            guide_sha256=guide['sha256']),
        renderer=environment.RENDERER,mask_version=MASK_VERSION,patches=patches)
    if contract==APPEARANCE_CONTRACT:
        bundle.update(schema=APPEARANCE_SCHEMA,reference_contract=contract,source_review_limit=1,
            inherited_reference=dict(path=parent['manifest_path'],sha256=parent['manifest_sha256'],reference_contract=MATERIAL_CONTRACT))
    jobs._freeze(path,bundle)
    return _load(path)


def _request(bundle,mode,target,entity):
    _validate_bundle(bundle);group=bundle['group'];patches=bundle['patches']
    if mode=='target':
        if entity.get('style_group_id')!=group['id'] or entity.get('home_style_sha256')!=group['definition_sha256']:
            raise StyleStale('residence_style_cross_group_reference_refused')
        patches=[patch for patch in patches if patch['material_key']==_material_key(group,entity,patch['slot'])]
        if not patches:raise ValueError('residence_style_no_compatible_material_patches')
    semantic=dict(shared_style=deepcopy(group['shared_style']),room_overrides=deepcopy(entity['static_materials']),
        material_slots=[{k:patch[k] for k in ('slot','material_key')} for patch in patches])
    request=dict(mode=mode,target=str(Path(target).resolve()),semantic=semantic,
        source_context=dict(path=bundle['master']['path'],sha256=bundle['master']['identity']['sha256']),
        binding=dict(manifest_path=bundle['manifest_path'],manifest_sha256=bundle['manifest_sha256'],group_id=group['id'],
            group_definition_sha256=group['definition_sha256'],style_version=group['style_version'],
            master_identity=bundle['master']['identity'],source_context_sha256=bundle['master']['identity']['sha256'],
            target_sha256=sha(target),target_place_id=entity['id'],
            room_materials=deepcopy(entity['static_materials']),
            patches=[{k:patch[k] for k in ('slot','material_key','sha256','pixel_roi','source_sha256')} for patch in patches]),
        patches=[{k:patch[k] for k in ('slot','material_key','path','sha256')} for patch in patches])
    if bundle.get('reference_contract')==APPEARANCE_CONTRACT:
        request['binding'].update(reference_contract=APPEARANCE_CONTRACT,
            inherited_reference_sha256=bundle['inherited_reference']['sha256'])
    return request


def reference_request(bundle):
    group=bundle['group'];entity=dict(id=group['master_place_id'],static_materials=group['room_materials'][group['master_place_id']])
    return _request(bundle,'reference',bundle['master']['path'],entity)


def target_request(bundle,entity,target_path):return _request(bundle,'target',target_path,entity)


def verify_result(request,result,*,require_accepted=True):
    if request.get('mode') not in ('reference','target'):raise ValueError('residence_style_request_mode_invalid')
    binding=request['binding'];bundle=_load(binding['manifest_path'])
    contract=binding.get('reference_contract',MATERIAL_CONTRACT)
    appearance=contract==APPEARANCE_CONTRACT
    if contract!=bundle.get('reference_contract',MATERIAL_CONTRACT):raise ValueError('residence_reference_contract_changed')
    if appearance and binding.get('inherited_reference_sha256')!=bundle['inherited_reference']['sha256']:
        raise ValueError('appearance_parent_binding_changed')
    if sha(binding['manifest_path'])!=binding['manifest_sha256']:raise ValueError('residence_style_manifest_changed')
    expected=[{k:p[k] for k in ('slot','material_key','sha256')} for p in request['patches']]
    original={p['slot']:p for p in bundle['patches']}
    room_materials=bundle['group']['room_materials'].get(binding.get('target_place_id'))
    if not room_materials:raise ValueError('residence_style_target_room_missing')
    target_entity=dict(static_materials=room_materials)
    compatible=(bundle['patches'] if request['mode']=='reference' else
        [p for p in bundle['patches'] if p['material_key']==_material_key(bundle['group'],target_entity,p['slot'])])
    if (binding['group_id']!=bundle['group']['id'] or binding['group_definition_sha256']!=bundle['group']['definition_sha256']
        or binding['style_version']!=bundle['group']['style_version'] or binding['master_identity']!=bundle['master']['identity']
        or binding['target_sha256']!=sha(request['target']) or any(p!= {k:original[p['slot']][k] for k in p} for p in binding['patches'])
        or request['semantic']['shared_style']!=bundle['group']['shared_style']
        or any(p!={k:original[p['slot']][k] for k in ('slot','material_key','path','sha256')} for p in request['patches'])
        or request['semantic']['material_slots']!=[{k:p[k] for k in ('slot','material_key')} for p in request['patches']]):
        raise ValueError('residence_style_request_binding_changed')
    if (not room_materials or binding.get('room_materials')!=room_materials or request['semantic']['room_overrides']!=room_materials
        or [p['slot'] for p in request['patches']]!=[p['slot'] for p in compatible]
        or (request['mode']=='reference' and Path(request['target']).resolve()!=Path(bundle['master']['path']).resolve())):
        raise ValueError('residence_style_compatible_room_scope_changed')
    if (request.get('source_context')!=dict(path=bundle['master']['path'],sha256=bundle['master']['identity']['sha256'])
        or binding.get('source_context_sha256')!=bundle['master']['identity']['sha256']
        or result.get('source_context_sha256')!=bundle['master']['identity']['sha256']):
        raise ValueError('residence_style_source_context_changed')
    if (result.get('schema')!=('residence_appearance_visual_review/v6' if appearance else 'residence_style_visual_review/v5')
        or result.get('mode')!=request['mode']
        or result.get('target_sha256')!=sha(request['target']) or result.get('style_binding_sha256')!=fingerprint(binding)
        or result.get('patch_bindings')!=expected or result.get('layout_approved') is not False
        or result.get('novel_fidelity_approved') is not False):raise ValueError('residence_style_review_binding_changed')
    if appearance and (result.get('approval_scope')!=APPEARANCE_CONTRACT or result.get('material_identity_approved') is not False):
        raise ValueError('appearance_review_scope_or_identity_claim_invalid')
    patch_checks=result.get('patch_checks',[])
    if (set(result.get('checks',{}))!=set(CHECKS) or not isinstance(patch_checks,list)
        or ([p.get('slot') for p in patch_checks]!=[p['slot'] for p in request['patches']]
            and not (not require_accepted and result.get('decision')=='unavailable' and patch_checks==[]))):
        raise ValueError('residence_style_review_coverage_changed')
    patch_keys=('usable_color','visible_finish','layout_free') if appearance else ('material_match','texture_only','identifiable')
    if (any(value is not None and type(value) is not bool for value in result['checks'].values())
        or any(p.get(k) is not None and type(p[k]) is not bool for p in patch_checks for k in patch_keys)
        or any(not isinstance(p.get('evidence'),str) or not p['evidence'].strip() for p in patch_checks)
        or type(result.get('completion_known')) is not bool or type(result.get('outcome_unknown')) is not bool
        or result['completion_known']==result['outcome_unknown'] or type(result.get('retryable')) is not bool
        or result.get('decision') not in ('accepted','needs_review','repair_required','unavailable')):
        raise ValueError('residence_style_review_types_or_completion_invalid')
    if require_accepted and (result.get('decision')!='accepted' or not all(result['checks'][key] is True for key in CHECKS)
        or any(any(p.get(key) is not True for key in patch_keys) or not p.get('evidence') for p in patch_checks)
        or result.get('completion_known') is not True or result.get('outcome_unknown') is not False
        or not result.get('visual_evidence') or (request['mode']=='reference' and result.get('style_reference_ready') is not True)):
        raise ValueError('residence_style_review_not_accepted')
    return True


def accept_reference(bundle,result):
    request=reference_request(bundle);verify_result(request,result,require_accepted=False)
    folder=Path(bundle['manifest_path']).parent
    jobs._freeze(folder/'REFERENCE_REVIEW.json',result)
    if result.get('decision')=='accepted':
        verify_result(request,result)
        jobs._freeze(folder/'READY.json',_ready_binding(bundle,request,folder))
    return (folder/'READY.json').exists()


def _ready_binding(bundle,request,folder):
    binding=dict(manifest_sha256=bundle['manifest_sha256'],review_sha256=sha(folder/'REFERENCE_REVIEW.json'),
        request_binding_sha256=fingerprint(request['binding']),style_reference_ready=True)
    if bundle.get('reference_contract')==APPEARANCE_CONTRACT:
        binding.update(reference_contract=APPEARANCE_CONTRACT,material_identity_approved=False)
    return binding


def load_reference(path,group,current_master_row,master_path,*,require_ready=True):
    bundle=_load(path)
    if (bundle['group']!=group or bundle['master']['identity']!=identity(current_master_row)
        or Path(bundle['master']['path']).resolve()!=Path(master_path).resolve() or bundle['renderer']!=environment.RENDERER):
        raise StyleStale('residence_style_group_master_or_renderer_changed')
    if require_ready:
        folder=Path(path).parent;ready=read(folder/'READY.json');result=read(folder/'REFERENCE_REVIEW.json');request=reference_request(bundle)
        if ready!=_ready_binding(bundle,request,folder):raise ValueError('residence_style_ready_receipt_changed')
        verify_result(request,result)
    return bundle
