"""Durable asset preparation between accepted text and video, never resumes old H3."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import time
import urllib.request
import uuid

from PIL import Image

from . import visual_asset_registry_v3 as library
from . import visual_image_jobs_v3 as images
from . import visual_environment_v4 as environment
from . import visual_gpu_handoff_v4 as gpu_handoff
from . import visual_residence_style_v5 as residence_style
from . import visual_generation_reference_v7 as generation_refs
from . import visual_first_frame_static_v13 as static_frames
from . import visual_first_frame_review_paths_v16 as frame_review_paths
from .visual_shot_binding_v3 import fingerprint,compile_bindings

VIEWS=library.CHARACTER_VIEWS
BLIND_COUNT_REFRESH_POLICY='retry_known_blind_count_null'
REFERENCE_DELIVERY='reference_assets/v20'


def reference_delivery(config):
    mode=config.get('h3_delivery','first_frame/v3')
    if mode not in ('first_frame/v3',REFERENCE_DELIVERY):
        raise ValueError('unsupported_h3_asset_delivery_mode')
    return mode==REFERENCE_DELIVERY


def _blind_count_refresh_enabled(config):
    value=config.get(BLIND_COUNT_REFRESH_POLICY,False)
    if type(value) is not bool:raise ValueError('blind_count_refresh_requires_boolean')
    return value


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def file_sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
def freeze(path,value):
    path=Path(path)
    if path.exists():
        if read(path)!=value:raise ValueError('frozen_input_changed')
    else:write(path,value)


def prepare(run,packet,config):
    run=Path(run).resolve()
    gpu_handoff.enabled(config)
    residence_style.reference_contract(config)
    residence_style.validate_groups(packet)
    if generation_refs.enabled(config):generation_refs.validate(run,packet,config)
    static_frames.validate_plan(packet,config)
    if config.get('environment_continuation'):
        from . import visual_environment_continuation_v6 as continuation
        continuation.validate(run,packet,config)
    if packet.get('style_groups'):
        config=deepcopy(config)
        if not config.get('environment_continuation') and not generation_refs.enabled(config):config['style_reference_root']=str(run/'style_references')
    _blind_count_refresh_enabled(config)
    reference_delivery(config)
    if packet.get('schema')!='visual_asset_packet/v3' or not str(packet.get('book_id','')).strip():raise ValueError('invalid_asset_packet')
    if len({c['id'] for c in packet['characters']})!=len(packet['characters']):raise ValueError('duplicate_character')
    for place in packet.get('places',[]):
        if place.get('spatial_layout'):
            environment.validate_layout(place['spatial_layout'])
            environment.design_description(place,require=True)
            if not place.get('front_prompt','').strip():raise ValueError('environment_front_prompt_required')
    source=packet['source'];p=Path(source['path'])
    if not p.is_file() or file_sha(p)!=source['sha256']:raise ValueError('source_changed')
    plan=dict(schema='visual_asset_pipeline/v3',packet=deepcopy(packet),config=deepcopy(config),
              packet_sha256=fingerprint(packet),publication=False,old_h3_resume=False)
    run.mkdir(parents=True,exist_ok=True);freeze(run/'PLAN.json',plan)
    if not (run/'STATE.json').exists():write(run/'STATE.json',dict(status='prepared',jobs={},repairs={},events=[],created_at=time.time()))
    return status(run)


def status(run):
    run=Path(run);plan=read(run/'PLAN.json');state=read(run/'STATE.json')
    _blind_count_refresh_enabled(plan['config'])
    reference_delivery(plan['config'])
    if plan['packet_sha256']!=fingerprint(plan['packet']):raise ValueError('packet_changed')
    if file_sha(plan['packet']['source']['path'])!=plan['packet']['source']['sha256']:raise ValueError('script_changed')
    if plan['config'].get('environment_continuation'):
        from . import visual_environment_continuation_v6 as continuation
        continuation.validate(run,plan['packet'],plan['config'])
    if generation_refs.enabled(plan['config']):generation_refs.validate(run,plan['packet'],plan['config'])
    static_frames.validate_plan(plan['packet'],plan['config'])
    return dict(plan=plan,state=state,paused=(run/'PAUSE.json').exists(),production_approved=False)


def set_paused(run,paused,*,actor,role):
    if role not in ('admin','superadmin') or not actor:raise PermissionError('admin_required')
    run=Path(run);status(run)
    audit=dict(actor=actor,action='pause' if paused else 'resume',at=time.time())
    write(run/'CONTROL'/f'{uuid.uuid4().hex}.json',audit)
    if paused:write(run/'PAUSE.json',audit)
    else:(run/'PAUSE.json').unlink(missing_ok=True)
    return audit


def asset_requirements(packet):
    rows=[]
    for kind,key in [('character','characters'),('place','places')]:
        for c in packet.get(key,[]):
            views=c.get('required_views',list(VIEWS) if kind=='character' else ['front','layout'])
            for view in views:rows.append(dict(entity_id=c['id'],kind=kind,view=view,design_version=c.get('design_version','v1')))
    return rows


def _raw_lookup(plan,req):
    rows=library.get(plan['config']['library'],book_id=plan['packet']['book_id'],**req)
    return max(rows,key=lambda x:x['version']) if rows else None


def _asset_identity(row):
    return {k:row[k] for k in ('asset_id','version','entity_id','kind','view','design_version','sha256')}


def _entity(plan,req):
    return next(c for c in plan['packet']['characters' if req['kind']=='character' else 'places'] if c['id']==req['entity_id'])


def _visible_age_band(packet,visible_cast):
    characters={c['id']:c for c in packet['characters']}
    bands=[characters.get(cid,{}).get('age_band','unknown') for cid in visible_cast]
    if not bands or any(b not in ('adult','child') for b in bands):return 'unknown'
    return bands[0] if len(set(bands))==1 else 'mixed'


def _reference_slots(plan,req):
    """A pose reference never replaces the independently bound canonical identity."""
    entity=_entity(plan,req)
    if req['kind']=='place' and entity.get('spatial_layout'):
        environment.validate_layout(entity['spatial_layout'])
        slots=[] if req['view']=='front' else [{**req,'view':'front'}]
        group=residence_style.group_for(plan['packet'],entity)
        if group and entity['id']!=group['master_place_id']:
            master=next(p for p in plan['packet']['places'] if p['id']==group['master_place_id'])
            slots.append(dict(entity_id=master['id'],kind='place',view='front',design_version=master['design_version']))
        return slots
    if req['view']=='front':
        return [{**req,'entity_id':entity['canonical_from_role']}] if entity.get('canonical_from_role') else []
    slots=[{**req,'view':'front'}]
    if req['view']=='right_profile':slots.append({**req,'view':'right_oblique'})
    return slots


def _dependencies(plan,row):
    provenance=row.get('provenance',{})
    entity=_entity(plan,{k:row[k] for k in ('entity_id','kind','view','design_version')})
    if row['kind']=='place' and entity.get('spatial_layout'):
        guide=provenance.get('environment_guide')
        if (not guide or guide.get('renderer')!=environment.RENDERER or guide.get('layout_sha256')!=fingerprint(entity['spatial_layout']) or
                guide.get('design_sha256')!=_environment_design_sha(entity) or guide.get('view')!=row['view']):return [],False
        if file_sha(guide['path'])!=guide.get('sha256'):raise ValueError('environment_guide_changed')
        if generation_refs.enabled(plan['config']) and not generation_refs.baseline_front(plan,row):
            binding=provenance.get('generation_reference')
            if not generation_refs.current_binding(plan,binding,'place_asset'):return [],False
            inputs,roles=_isolated_place_inputs(plan,entity,guide)
            generation_refs.verify_job(plan,binding,'place_asset',inputs,roles,receipt=provenance.get('receipt'),require_receipt=True)
            if [output['sha256'] for output in provenance['receipt']['images']]!=[row['sha256']]:
                raise ValueError('generation_policy_asset_output_changed')
        group=residence_style.group_for(plan['packet'],entity)
        if group and entity['id']!=group['master_place_id']:
            expected=provenance.get('residence_style')
            current=_style_reference_for_entity(None,plan,entity)
            if not current or not expected or expected!=_style_provenance(current,entity):return [],False
    slots=_reference_slots(plan,{k:row[k] for k in ('entity_id','kind','view','design_version')})
    explicit=provenance.get('dependencies')
    if explicit is not None:
        if not isinstance(explicit,list):raise ValueError('invalid_asset_dependencies')
        if provenance.get('dependency_fingerprint') is not None and provenance['dependency_fingerprint']!=fingerprint(explicit):
            raise ValueError('asset_dependency_fingerprint_changed')
        if {(x.get('entity_id'),x.get('kind'),x.get('view'),x.get('design_version')) for x in explicit}!=\
                {(x['entity_id'],x['kind'],x['view'],x['design_version']) for x in slots}:
            raise ValueError('asset_dependency_scope_changed')
        return deepcopy(explicit),True
    if not slots:return [],True
    # Existing v3 imports retain the immutable manifest rather than modifying it.
    # No native success or semantic acceptance is invented while adapting it.
    entry=provenance
    if provenance.get('manifest_path'):
        path=Path(provenance['manifest_path'])
        if file_sha(path)!=provenance.get('manifest_sha256'):raise ValueError('asset_source_manifest_changed')
        matches=[i for i in read(path).get('items',[]) if
            i.get('character_id')==row['entity_id'] and i.get('view')==row['view'] and i.get('sha256')==row['sha256']]
        if len(matches)!=1:raise ValueError('asset_source_manifest_item_changed')
        entry=matches[0]
    deps=[]
    for slot in slots:
        expected=(entry.get('reference_sha256') if row['view']=='front' or slot['view']=='right_oblique'
                  else entry.get('ultimate_canonical_sha256'))
        if not expected:return [],False
        candidates=library.get(plan['config']['library'],book_id=plan['packet']['book_id'],**slot)
        candidates=[c for c in candidates if c['sha256']==expected]
        if not candidates:return [],False
        same_import=[c for c in candidates if provenance.get('manifest_sha256') and
                     c.get('provenance',{}).get('manifest_sha256')==provenance['manifest_sha256']]
        # Bind the original version; a later same-pixel design version is not it.
        deps.append(_asset_identity(min(same_import or candidates,key=lambda c:c['version'])))
    return deps,True


def _lookup(plan,req,_seen=(),_layout_only=False):
    row=_raw_lookup(plan,req)
    if not row:return None
    token=(row['asset_id'],row['version'])
    if token in _seen:raise ValueError('asset_dependency_cycle')
    deps,known=_dependencies(plan,row);stale=not known;blocked=False
    for expected in deps:
        source=_lookup(plan,{k:expected[k] for k in ('entity_id','kind','view','design_version')},_seen+ (token,))
        if not source or _asset_identity(source)!=expected or source.get('dependency_stale'):
            stale=True
        elif source['status']!='reviewed':blocked=True
    row['dependency_fingerprint']=fingerprint(deps) if known else None
    if stale or blocked:
        row.update(status='candidate',dependency_stale=stale,
                   dependency_error='source_version_changed_or_unbound' if stale else 'source_not_reviewed')
    if not _layout_only and row['kind']=='place' and row['status']=='reviewed':
        entity=_entity(plan,req)
        if (plan['config'].get('generation_reference_policy')=='geometry_materials_only/v1'
                and not generation_refs.baseline_front(plan,row)):
            inventory=_review_layout_inventory(plan,entity)
            receipt=_consume_layout_inventory(_latest_review({},row),inventory)
            if receipt.get('decision')!='accepted' or receipt.get('checks',{}).get('layout') is not True:
                row.update(status='candidate',dependency_error='furniture_inventory_review_not_accepted')
        if entity.get('style_group_id'):
            bundle=_style_reference_for_entity(None,plan,entity)
            if not bundle:row.update(status='candidate',dependency_stale=False,dependency_error='residence_style_not_ready')
            else:
                row['residence_style_binding']=_style_provenance(bundle,entity)
                group=residence_style.group_for(plan['packet'],entity)
                if not (entity['id']==group['master_place_id'] and row['view']=='front'):
                    _verify_residence_style_receipt(None,plan,entity,_image_path(plan,row),_latest_review({},row))
    return row


def _requirements_status(plan):
    result=dict(ready=True,complete=True,require_reviewed=True,selected=[],missing=[],pending=[],rejected=[],errors=[])
    for req in asset_requirements(plan['packet']):
        try:row=_lookup(plan,req)
        except (ValueError,OSError,KeyError) as error:
            result['errors'].append(dict(**req,reason=str(error)));continue
        if not row:result['missing'].append(req)
        elif row['status']=='reviewed':result['selected'].append(row)
        else:result['rejected' if row['status']=='rejected' else 'pending'].append(
            dict(**req,asset_id=row['asset_id'],version=row['version'],dependency_error=row.get('dependency_error')))
    result['complete']=not(result['missing'] or result['errors'])
    result['ready']=not(result['missing'] or result['pending'] or result['rejected'] or result['errors'])
    return result


def _image_path(plan,row):
    path=(Path(plan['config']['library'])/row['file']).resolve()
    if file_sha(path)!=row['sha256']:raise ValueError('registered_asset_changed')
    return path


def _environment_design_sha(entity):
    design={k:entity.get(k) for k in ('spatial_layout','layout_design','front_prompt')}
    if entity.get('background_contract'):
        design.update({k:entity.get(k) for k in ('background_contract','static_materials')})
        design['renderer']=environment.RENDERER
    if entity.get('style_group_id'):design.update({k:entity.get(k) for k in ('style_group_id','style_version','home_style_sha256')})
    return fingerprint(design)


def _style_provenance(bundle,entity):
    request=residence_style.target_request(bundle,entity,bundle['master']['path'])
    provenance=dict(manifest_path=bundle['manifest_path'],manifest_sha256=bundle['manifest_sha256'],
        group_id=bundle['group']['id'],definition_sha256=bundle['group']['definition_sha256'],
        master_identity=bundle['master']['identity'],patch_bindings=[{k:p[k] for k in ('slot','material_key','sha256')} for p in request['patches']])
    if bundle.get('reference_contract')==residence_style.APPEARANCE_CONTRACT:
        provenance['reference_contract']=residence_style.APPEARANCE_CONTRACT
    return provenance


def _style_reference_for_entity(run,plan,entity):
    group=residence_style.group_for(plan['packet'],entity)
    if not group:return None
    master=next(p for p in plan['packet']['places'] if p['id']==group['master_place_id'])
    req=dict(entity_id=master['id'],kind='place',view='front',design_version=master['design_version'])
    row=_raw_lookup(plan,req)
    if not row or row['status']!='reviewed':return None
    guide=row.get('provenance',{}).get('environment_guide')
    if (not guide or guide.get('design_sha256')!=_environment_design_sha(master)
        or guide.get('renderer')!=environment.RENDERER):return None
    if file_sha(guide['path'])!=guide.get('sha256'):raise ValueError('residence_style_master_guide_changed')
    root=Path(plan['config']['style_reference_root'])
    contract=residence_style.reference_contract(plan['config'])
    path=residence_style.reference_path(root,group,row,guide,contract=contract,
        parent_manifest=plan['config'].get('style_reference_parent_manifest'))
    if not (path.parent/'READY.json').exists():return None
    return residence_style.load_reference(path,group,row,_image_path(plan,row))


def _ensure_style_references(run,plan,state,reviewer):
    for group in plan['packet'].get('style_groups',[]):
        entity=next(p for p in plan['packet']['places'] if p['id']==group['master_place_id'])
        if plan['config'].get('environment_continuation') or generation_refs.enabled(plan['config']):
            bundle=_style_reference_for_entity(run,plan,entity)
            if not bundle:raise ValueError('continuation_inherited_style_reference_not_ready')
            state.setdefault('style_references',{})[group['id']]=dict(status='style_reference_ready',
                manifest_path=bundle['manifest_path'],manifest_sha256=bundle['manifest_sha256'],
                inherited_reference=True,source_reference_review_calls=0)
            write(Path(run)/'STATE.json',state)
            continue
        req=dict(entity_id=entity['id'],kind='place',view='front',design_version=entity['design_version'])
        row=_lookup(plan,req,_layout_only=True)
        if not row or row['status']!='reviewed':continue
        guide=row['provenance']['environment_guide']
        contract=residence_style.reference_contract(plan['config'])
        bundle=residence_style.prepare_reference(run,group,entity,row,_image_path(plan,row),guide,library_path=plan['config']['library'],
            contract=contract,parent_manifest=plan['config'].get('style_reference_parent_manifest'))
        folder=Path(bundle['manifest_path']).parent;result_path=folder/'REFERENCE_REVIEW.json'
        request=residence_style.reference_request(bundle)
        if result_path.exists():result=read(result_path)
        elif contract==residence_style.APPEARANCE_CONTRACT:
            result=reviewer.review_residence_appearance(request,evidence_dir=folder/'visual_review')
        else:result=reviewer.review_style_materials(request,evidence_dir=folder/'visual_review')
        ready=residence_style.accept_reference(bundle,result)
        state.setdefault('style_references',{})[group['id']]=dict(status='style_reference_ready' if ready else 'style_reference_not_accepted',
            manifest_path=bundle['manifest_path'],manifest_sha256=bundle['manifest_sha256'],decision=result['decision'])
        write(Path(run)/'STATE.json',state)


def _environment_guide(run,entity,view,*,width=768,height=1024):
    """A geometry guide is a frozen input, never a generated photo promoted to layout."""
    key=fingerprint(dict(layout=entity['spatial_layout'],renderer=environment.RENDERER,width=width,height=height))[:24]
    manifest=environment.render_guides(entity['spatial_layout'],Path(run)/'environment_guides'/key,width=width,height=height)
    return dict(manifest['views'][view],design_sha256=_environment_design_sha(entity),renderer=environment.RENDERER,
                manifest_path=str((Path(run)/'environment_guides'/key/'GUIDES.json').resolve()))


@contextmanager
def gpu_access(plan,for_review=True):
    config=plan['config'];gpu_handoff.enabled(config)
    root=Path(config['gpu_lock_root']);root.mkdir(parents=True,exist_ok=True)
    with images.run_lock(root,name='GPU.lock'):
        protected=config.get('protected_pause_path')
        if protected and not Path(protected).is_file():raise ValueError('protected_legacy_batch_not_paused')
        op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        @contextmanager
        def dispatch_guard():
            if for_review:
                with images.run_lock(Path(config['image_service']['input_root']),name='VISUAL_GPU.lock'):yield
            else:yield
        with dispatch_guard():
            with op.open(config['image_service']['service_url'].rstrip('/')+'/queue',timeout=15) as f:q=json.load(f)
            if (not isinstance(q,dict) or any(k not in q or type(q[k]) is not list for k in ('queue_running','queue_pending'))
                or any(not isinstance(row,list) or len(row)<3 or not isinstance(row[1],str) or not isinstance(row[2],dict)
                       for key in ('queue_running','queue_pending') for row in q[key])):
                raise ValueError('native_gpu_queue_schema_invalid')
            if q.get('queue_running') or q.get('queue_pending'):raise images.JobBusyError('native_gpu_queue_busy')
            if for_review:gpu_handoff.ensure_review_ready(config)
            else:gpu_handoff.assert_dispatch_allowed(config)
            yield


def _reference_roi_evidence(plan,state,req,front):
    if req['kind']!='character' or req['view'] not in ('face','clothing','hands') or not front or front['status']!='reviewed':return None
    approved=_latest_review(state,front)
    roi=approved.get('rois',{}).get(req['view'])
    if (approved.get('decision')!='accepted' or not isinstance(roi,dict) or set(roi)!={'x','y','width','height'} or
            any(type(v) is not int for v in roi.values()) or min(roi['x'],roi['y'])<0 or min(roi['width'],roi['height'])<1):return None
    with Image.open(_image_path(plan,front)) as source:
        width,height=source.size
        if roi['x']+roi['width']>width or roi['y']+roi['height']>height:return None
        crop=source.convert('RGB').crop((roi['x'],roi['y'],roi['x']+roi['width'],roi['y']+roi['height']))
        out=io.BytesIO();crop.save(out,format='PNG')
    binding=dict(asset_id=front['asset_id'],version=front['version'],image_sha256=front['sha256'],review_sha256=fingerprint(approved))
    return dict(source_sha256=front['sha256'],source_dimensions=[width,height],pixel_roi=deepcopy(roi),roi_name=req['view'],
                roi_source=binding,roi_source_sha256=fingerprint(binding),crop_sha256=hashlib.sha256(out.getvalue()).hexdigest(),
                coordinate_system='source_pixels')


def _can_enhance_review(plan,state,key,old,count,roi):
    return bool(roi and old.get('decision')=='needs_review' and old.get('completion_known') is True and
                old.get('outcome_unknown') is False and not old.get('reference_roi_evidence') and
                key not in state.get('roi_enhancements',{}) and count<plan['config'].get('max_review_attempts',2))


def _can_refresh_blind_count(plan,state,key,row,old,count):
    """Explicitly refresh a known incomplete room count, never a general failure.

    The former room contract allowed count=null. Other checks must already be
    positive, so layout/pose/ROI defects or an unknown call cannot use this lane.
    The successor still performs a complete new visual review of the same image.
    """
    if not _blind_count_refresh_enabled(plan['config']):return False
    checks=old.get('checks',{})
    return bool(row['kind']=='place' and old.get('decision')=='needs_review' and
        old.get('completion_known') is True and old.get('outcome_unknown') is False and
        old.get('target_sha256')==row['sha256'] and
        'people_count' in old.get('observations',{}) and old['observations']['people_count'] is None and
        set(checks)==set(library.REVIEW_CHECKS['place']) and checks.get('consistency') is None and
        all(checks[k] is True for k in checks if k!='consistency') and
        all(i.get('severity')=='note' for i in old.get('issues',[])) and
        old.get('blind_count_recheck') is None and key not in state.get('blind_count_refreshes',{}) and
        count<min(2,plan['config'].get('max_review_attempts',2)))


def _requires_residence_style(plan,entity):
    group_id=entity.get('style_group_id')
    if not group_id:return False
    matches=[g for g in plan['packet'].get('style_groups',[]) if g['id']==group_id]
    if len(matches)!=1:raise ValueError('missing_or_duplicate_residence_style_group')
    return True


def _require_current_shot_style(packet,shot):
    """A new house palette never silently rebinds an old prose/staging prompt."""
    entity=next((p for p in packet.get('places',[]) if p['id']==shot.get('place_id')),None)
    if not entity or not entity.get('style_group_id'):return
    group=residence_style.group_for(packet,entity)
    invalid=packet.get('shot_invalidations',[])
    if isinstance(invalid,dict):marked=shot['id'] in invalid
    elif isinstance(invalid,list):marked=any(
        item==shot['id'] or (isinstance(item,dict) and item.get('shot_id',item.get('id'))==shot['id']) for item in invalid)
    else:raise ValueError('invalid_residence_shot_invalidation_contract')
    if marked or shot.get('home_style_sha256')!=group['definition_sha256']:
        raise ValueError('shot_home_style_needs_restage:'+shot['id'])


def _residence_style_review(run,plan,entity,target,reviewer,evidence_dir,*,allow_master_bootstrap=False):
    if not _requires_residence_style(plan,entity):return None
    from . import visual_residence_style_v5 as residence_style
    bundle=_style_reference_for_entity(run,plan,entity)
    if not bundle:
        group=next(g for g in plan['packet']['style_groups'] if g['id']==entity['style_group_id'])
        if allow_master_bootstrap and group['master_place_id']==entity['id']:return None
        raise ValueError('residence_style_reference_not_ready')
    request=residence_style.target_request(bundle,entity,str(target))
    if request.get('binding',{}).get('reference_contract')=='appearance/v1':
        result=reviewer.review_residence_appearance(request,evidence_dir=evidence_dir)
    else:result=reviewer.review_style_materials(request,evidence_dir=evidence_dir)
    residence_style.verify_result(request,result,require_accepted=False)
    if result.get('target_sha256')!=file_sha(target):raise ValueError('residence_style_review_wrong_target')
    return dict(request=request,request_sha256=fingerprint(request),result=result)


def _combine_residence_style(layout,style):
    if style is None:return layout
    result=deepcopy(layout);s=style['result'];result['layout_review']=deepcopy(layout);result['style_review']=deepcopy(style)
    # Preserve exact room/actor check names and values; a separate style pass
    # cannot upgrade a layout null, false, count mismatch or unknown outcome.
    decisions=[layout['decision'],s['decision']]
    result['decision']=('unavailable' if 'unavailable' in decisions else 'repair_required' if 'repair_required' in decisions else
        'accepted' if all(d=='accepted' for d in decisions) else 'needs_review')
    if result['decision']!='unavailable':
        if any(v is False for v in layout.get('checks',{}).values()):result['decision']='repair_required'
        elif result['decision']=='accepted' and any(v is None for v in layout.get('checks',{}).values()):result['decision']='needs_review'
    result['completion_known']=all(r.get('completion_known') is True for r in (layout,s))
    result['outcome_unknown']=not result['completion_known']
    result['retryable']=(result['decision']=='unavailable' and result['completion_known'] and
        all(r.get('retryable') is True for r in (layout,s) if r['decision']=='unavailable'))
    result['inference_dispatched']=any(r.get('inference_dispatched') is True for r in (layout,s))
    result['visual_evidence']=list(layout.get('visual_evidence',[]))+list(s.get('visual_evidence',[]))
    return result


def _verify_residence_style_receipt(run,plan,entity,target,combined):
    if not _requires_residence_style(plan,entity):return
    from . import visual_residence_style_v5 as residence_style
    record=combined.get('style_review')
    if not isinstance(record,dict) or record.get('request_sha256')!=fingerprint(record.get('request')):
        raise ValueError('residence_style_review_receipt_required')
    bundle=_style_reference_for_entity(run,plan,entity)
    current=residence_style.target_request(bundle,entity,str(target))
    if current!=record['request']:raise ValueError('residence_style_review_dependency_changed')
    residence_style.verify_result(current,record['result'])
    if record['result'].get('decision')!='accepted':raise ValueError('residence_style_not_accepted')


def _review_layout_inventory(plan,entity):
    """New-policy reviews count the fixed design; legacy reviewed assets stay untouched."""
    if plan['config'].get('generation_reference_policy')!='geometry_materials_only/v1':return None
    if not entity.get('spatial_layout'):raise ValueError('new_geometry_policy_requires_spatial_layout')
    from .visual_asset_review_v3 import inventory_from_layout
    return inventory_from_layout(entity['spatial_layout'])


def _consume_layout_inventory(result,inventory):
    if inventory is None:return result
    from .visual_asset_review_v3 import enforce_layout_inventory,ReviewProtocolError
    if result.get('layout_object_inventory')!=inventory:raise ReviewProtocolError('layout inventory review binding missing/changed')
    # A failed or unknown native call did not observe furniture. Preserve its
    # original status and missing observations; never manufacture an empty room.
    if result.get('decision')=='unavailable' and result.get('object_observations') is None:return result
    return enforce_layout_inventory(result,inventory)


def _verify_first_frame_inventory(plan,entity,review):
    """Read-only qualification: both composite and actual room observation bind."""
    from .visual_known_capacity_extension_v17 import verify_applied
    verify_applied(review)
    _verify_first_frame_inventory_contents(plan,entity,review)


def _verify_first_frame_inventory_contents(plan,entity,review):
    """Inventory facts, also used before an amendment's CAS append is committed."""
    inventory=_review_layout_inventory(plan,entity)
    if inventory is None:return
    values=[review]
    if 'subreviews' in review:
        rooms=[r for r in review['subreviews'] if 'layout' in r.get('checks',{})]
        if len(rooms)!=1:raise ValueError('first_frame_furniture_room_subreview_required')
        values+=rooms
    else:raise ValueError('first_frame_furniture_room_subreview_required')
    if static_frames.enabled(plan['config']) and any(value.get('split_observation',{}).get('schema')!='split_people_furniture_observation/v14' for value in values):
        raise ValueError('static_first_frame_split_native_observation_required')
    for value in values:
        checked=_consume_layout_inventory(deepcopy(value),inventory)
        if checked.get('decision')!='accepted' or checked.get('checks',{}).get('layout') is not True:
            raise ValueError('first_frame_furniture_inventory_not_accepted')
    if values[0]['object_observations']!=values[1]['object_observations']:
        raise ValueError('first_frame_furniture_observations_disagree')
    if values[0].get('split_observation')!=values[1].get('split_observation'):
        raise ValueError('first_frame_split_observation_proofs_disagree')


def review_candidates(run,plan,state,reviewer):
    pending=[];requests=[]
    for req in asset_requirements(plan['packet']):
        row=_lookup(plan,req)
        if not row or row['status']=='reviewed' or row.get('dependency_error'):continue
        key=f"{row['asset_id']}:v{row['version']}:{row['sha256']}"
        old=state.get('reviews',{}).get(key) or _latest_review(state,row)
        count=state.get('review_attempts',{}).get(key,1 if old else 0)
        entity=next(c for c in plan['packet']['characters' if req['kind']=='character' else 'places'] if c['id']==req['entity_id'])
        front=_lookup(plan,{**req,'view':'front'})
        reference=_image_path(plan,front) if front and req['view']!='front' else None
        roi=_reference_roi_evidence(plan,state,req,front)
        enhanced=_can_enhance_review(plan,state,key,old,count,roi)
        count_refresh=_can_refresh_blind_count(plan,state,key,row,old,count)
        if old and not (enhanced or count_refresh or (old.get('decision')=='unavailable' and old.get('retryable') is True and
                old.get('completion_known') is True and old.get('outcome_unknown') is False and
                count<plan['config'].get('max_review_attempts',2))):continue
        expectation=dict(kind=req['kind'],view=req['view'],expected_people=1 if req['kind']=='character' else 0,
                         age_band=entity.get('age_band','unknown'),appearance_description=environment.design_description(entity) if req['kind']=='place' else entity.get('appearance_design',''),
                         locate_rois=['face','clothing','hands'] if req['kind']=='character' and req['view']=='front' else [])
        if roi:expectation.update(reference_roi=roi['pixel_roi'],reference_roi_source=roi['roi_source'])
        request=dict(target=str(_image_path(plan,row)),reference=str(reference) if reference else None,expectation=expectation)
        guide=None
        if req['kind']=='place' and entity.get('spatial_layout'):
            guide=_environment_guide(run,entity,req['view'])
            request['layout_guide']=guide['path'];expectation['environment_context']=environment.review_context(entity,req['view'])
        if req['kind']=='place':
            inventory=_review_layout_inventory(plan,entity)
            if inventory is not None:expectation['layout_object_inventory']=inventory
        requests.append(request)
        pending.append((key,row,old,count,roi,enhanced,guide,count_refresh))
    if not requests:return 0
    batch=fingerprint(dict(requests=requests,attempts={key:count for key,_,_,count,_,_,_,_ in pending}))
    results=reviewer.review_many(requests,evidence_dir=Path(run)/'reviews'/batch)
    if len(results)!=len(pending):raise ValueError('visual_review_batch_incomplete')
    for (key,row,old,count,roi,enhanced,guide,count_refresh),result,request in zip(pending,results,requests):
        if result.get('target_sha256')!=row['sha256']:raise ValueError('visual_review_wrong_image')
        if row['kind']=='place' and row['view']!='front':
            if not request.get('reference'):raise ValueError('environment_nonfront_source_front_required')
            if result.get('reference_sha256')!=file_sha(request['reference']):
                raise ValueError('environment_review_front_source_mismatch')
        if roi and (result.get('reference_sha256')!=roi['source_sha256'] or result.get('reference_roi_evidence')!=roi):
            raise ValueError('reference_roi_review_mismatch')
        if guide and result.get('layout_guide_sha256')!=guide['sha256']:raise ValueError('environment_review_guide_mismatch')
        result=_consume_layout_inventory(result,request['expectation'].get('layout_object_inventory'))
        if row['kind']=='place' and result['decision']=='accepted':
            entity=_entity(plan,row)
            style=_residence_style_review(run,plan,entity,_image_path(plan,row),reviewer,
                Path(run)/'style_reviews'/batch/key.replace(':','_'),allow_master_bootstrap=True)
            result=_combine_residence_style(result,style)
        decision=result['decision'];mapped=decision if decision in ('accepted','rejected','repair_required','unavailable') else 'unavailable'
        observations=result.get('visual_evidence') or [str(x) for x in result.get('issues',[])] or ['review unavailable']
        evidence=dict(image_sha256=row['sha256'],observations=observations,
                      review=fingerprint(result),model=result.get('model_binding'),
                      rois=deepcopy(result.get('rois',{})),reference_roi_evidence=deepcopy(result.get('reference_roi_evidence')),
                      source_review=deepcopy(result))
        library.review(plan['config']['library'],book_id=row['book_id'],asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'],
                       decision=mapped,reviewer='local_visual_model',checks={k:v for k,v in result.get('checks',{}).items() if type(v) is bool},evidence=evidence)
        if old:state.setdefault('review_history',{}).setdefault(key,[]).append(deepcopy(old))
        if enhanced:state.setdefault('roi_enhancements',{})[key]=dict(reference_roi_evidence=roi,review_sha256=fingerprint(result))
        if count_refresh:state.setdefault('blind_count_refreshes',{})[key]=dict(
            policy=BLIND_COUNT_REFRESH_POLICY,previous_review_sha256=fingerprint(old),
            review_sha256=fingerprint(result),target_sha256=row['sha256'])
        state.setdefault('reviews',{})
        state['reviews'][key]=result
        state.setdefault('review_attempts',{})[key]=count+1
        write(Path(run)/'STATE.json',state)
    return len(pending)


def _newly_reviewable(plan,state):
    """A newly approved parent unlocks existing children without regenerating them."""
    for req in asset_requirements(plan['packet']):
        row=_lookup(plan,req)
        if not row or row['status']=='reviewed' or row.get('dependency_error'):continue
        old=_latest_review(state,row)
        if not old:return True
        key=f"{row['asset_id']}:v{row['version']}:{row['sha256']}"
        if _can_refresh_blind_count(plan,state,key,row,old,state.get('review_attempts',{}).get(key,1)):return True
        front=_lookup(plan,{**req,'view':'front'})
        if _can_enhance_review(plan,state,key,old,state.get('review_attempts',{}).get(key,1),_reference_roi_evidence(plan,state,req,front)):return True
    return False


def _latest_review(state,row):
    if not row:return {}
    value=state.get('reviews',{}).get(f"{row['asset_id']}:v{row['version']}:{row['sha256']}")
    if value is not None:return value if value.get('target_sha256')==row['sha256'] else {}
    event=row.get('review') or {};evidence=event.get('evidence',{})
    source=evidence.get('source_review',{})
    if (event.get('file_sha256')!=row['sha256'] or evidence.get('image_sha256')!=row['sha256'] or
            source.get('target_sha256')!=row['sha256'] or fingerprint(source)!=evidence.get('review')):return {}
    return deepcopy(source)


def _isolated_place_inputs(plan,entity,guide):
    if not guide:raise ValueError('geometry_material_generation_requires_camera_guide')
    bundle=_style_reference_for_entity(None,plan,entity)
    if not bundle:raise ValueError('geometry_material_generation_requires_approved_reference')
    inputs=[dict(input_name='geometry_'+guide['sha256'][:20]+'.png',path=guide['path'],sha256=guide['sha256'])]
    roles=['geometry']
    for patch in generation_refs.layout_free_patches(bundle,entity):
        inputs.append(dict(input_name='material_'+patch['slot']+'_'+patch['sha256'][:20]+'.png',path=patch['path'],sha256=patch['sha256']))
        roles.append('material:'+patch['slot'])
    return inputs,roles


def _generation(run,plan,state,req):
    packet=plan['packet'];entity=_entity(plan,req)
    view=req['view'];current=_lookup(plan,req);attempt_key=f"{req['kind']}:{req['entity_id']}:{view}"
    if current and not current.get('dependency_stale') and _latest_review(state,current).get('decision') not in ('repair_required','rejected'):
        return None
    dependencies=[]
    for slot in _reference_slots(plan,req):
        source=_lookup(plan,slot)
        if not source or source['status']!='reviewed':return None
        dependencies.append(_asset_identity(source))
    scope=fingerprint(dependencies)
    prior_scope=state.setdefault('repair_scopes',{}).get(attempt_key)
    if prior_scope is not None and prior_scope!=scope:
        state.setdefault('repair_history',[]).append(dict(requirement=req,scope=prior_scope,attempts=state['repairs'].get(attempt_key,0)))
        state['repairs'][attempt_key]=0
    state['repair_scopes'][attempt_key]=scope
    attempts=state['repairs'].get(attempt_key,0)
    if current and attempts>=plan['config'].get('max_repair_rounds',2):return None
    refs=[];inputs=[];roi=None;guide=None;style_source=None;input_roles=[]
    isolated=generation_refs.enabled(plan['config'])
    prompt=entity.get('view_prompts',{}).get(view) if view!='front' else entity.get('front_prompt')
    if not prompt and not (req['kind']=='place' and entity.get('spatial_layout')):return None
    parent=entity.get('canonical_from_role')
    if req['kind']=='place' and entity.get('spatial_layout'):
        guide=_environment_guide(run,entity,view);name='geometry_'+guide['sha256'][:20]+'.png'
        refs.append(dict(input_name=name));inputs.append(dict(input_name=name,path=guide['path'],sha256=guide['sha256']))
        input_roles.append('geometry')
        prompt=generation_refs.place_prompt(entity,view) if isolated else environment.place_prompt(entity,view)
        if view!='front' and not isolated:
            src=_lookup(plan,{**req,'view':'front'})
            if not src or src['status']!='reviewed':return None
            name='asset_'+src['sha256'][:20]+'.png';p=_image_path(plan,src)
            refs.append(dict(input_name=name));inputs.append(dict(input_name=name,path=str(p),sha256=src['sha256']))
        group=residence_style.group_for(packet,entity)
        if group and (isolated or not (entity['id']==group['master_place_id'] and view=='front')):
            bundle=_style_reference_for_entity(run,plan,entity)
            if not bundle:return None
            request=residence_style.target_request(bundle,entity,bundle['master']['path'])
            patches=generation_refs.layout_free_patches(bundle,entity) if isolated else request['patches']
            for patch in patches:
                name='material_'+patch['slot']+'_'+patch['sha256'][:20]+'.png'
                refs.append(dict(input_name=name));inputs.append(dict(input_name=name,path=patch['path'],sha256=patch['sha256']))
                input_roles.append('material:'+patch['slot'])
            style_source=_style_provenance(bundle,entity)
            prompt+=('\nThe final '+str(len(request['patches']))+' references are close-up material samples only: '
                +', '.join(p['slot']+' '+p['material_key'] for p in request['patches'])
                +'. Match their surface palette, texture, age and wear on compatible materials in this room. '
                'Keep the room geometry, visible furnishings and room-specific materials from the first reference and current camera.')
    elif view=='front' and parent:
        src=_lookup(plan,{**req,'entity_id':parent,'view':'front'})
        if not src or src['status']!='reviewed':return None
        name='asset_'+src['sha256'][:20]+'.png';p=_image_path(plan,src)
        refs=[dict(input_name=name)];inputs=[dict(input_name=name,path=str(p),sha256=src['sha256'])]
    elif view!='front':
        sourceview='right_oblique' if view=='right_profile' else 'front'
        src=_lookup(plan,{**req,'view':sourceview})
        if not src or src['status']!='reviewed':return None
        if view in ('face','clothing','hands'):
            roi=_latest_review(state,src).get('rois',{}).get(view)
            if not roi:return None
        name='asset_'+src['sha256'][:20]+'.png';p=_image_path(plan,src)
        refs=[dict(input_name=name,**({'roi':roi} if roi else {}))];inputs=[dict(input_name=name,path=str(p),sha256=src['sha256'])]
    generation_header=generation_refs.header(plan,'place_asset') if isolated and req['kind']=='place' else None
    identity=fingerprint(dict(packet=plan['packet_sha256'],req=req,prompt=prompt,inputs=inputs,
                           dependencies=dependencies,environment_guide=guide,attempt=attempts,
                           **({'residence_style':style_source} if style_source else {}),
                           **({'generation_reference':generation_header} if generation_header else {})))[:24]
    jid='asset_'+identity;folder=Path(run)/'image_jobs'/jid
    config=images.Config(**plan['config']['image_service']);prefix=config.allowed_prefix+'/'+jid
    graph=images.build_graph([dict(id=req['entity_id']+'_'+view,prompt=prompt,seed=int(identity[:8],16),references=refs)],prefix)
    images.prepare_job(folder,graph,config,inputs,job_id=jid)
    generation_binding=generation_refs.bind_job(plan,'place_asset',inputs,input_roles,folder) if generation_header else None
    state['jobs'][jid]=dict(requirement=req,folder=str(folder),attempt=attempts,kind='asset',
                           dependencies=dependencies,dependency_fingerprint=scope,environment_guide=guide,
                           **({'residence_style':style_source} if style_source else {}),
                           **({'generation_reference':generation_binding} if generation_binding else {}));write(Path(run)/'STATE.json',state)
    return jid


def _collect_generated(run,plan,state,jid,receipt):
    task=state['jobs'][jid]
    outputs=receipt.get('images') or receipt.get('outputs')
    if not outputs or len(outputs)!=1:raise ValueError('single_asset_output_required')
    out=outputs[0]
    path=out.get('path') or out.get('local_path')
    if task['kind']=='first_frame':
        state.setdefault('first_frames',{})[task['shot_id']]=dict(path=path,sha256=out['sha256'],binding_sha256=task['binding_sha256'],job_id=jid,
            **({'environment_guide':task['environment_guide']} if task.get('environment_guide') else {}),
            **({'generation_reference':task['generation_reference'],'generation_receipt':receipt} if task.get('generation_reference') else {}),
            **({'static_start':task['static_start']} if task.get('static_start') else {}))
        task['status']='collected';write(Path(run)/'STATE.json',state);return
    req=task['requirement']
    entity=next(c for c in plan['packet']['characters' if req['kind']=='character' else 'places'] if c['id']==req['entity_id'])
    library.register(plan['config']['library'],path,book_id=plan['packet']['book_id'],**req,
                     expected_sha256=out.get('sha256'),input_sha256=fingerprint(dict(task=task,source=plan['packet']['source'],entity=entity)),
                     identity_group=entity.get('identity_group',entity['id']),
                     provenance=dict(job_id=jid,receipt=receipt,entity=entity,source=plan['packet']['source'],
                                     dependencies=task.get('dependencies',[]),dependency_fingerprint=task.get('dependency_fingerprint'),
                                     environment_guide=task.get('environment_guide'),
                                     **({'residence_style':task['residence_style']} if task.get('residence_style') else {}),
                                     **({'generation_reference':task['generation_reference']} if task.get('generation_reference') else {})))
    key=f"{req['kind']}:{req['entity_id']}:{req['view']}";state['repairs'][key]=task['attempt']+1
    task['status']='collected';write(Path(run)/'STATE.json',state)


@contextmanager
def _tick_guard(run):
    with images.run_lock(run):
        try:yield
        except images.JobBusyError:raise
        except Exception as error:
            path=Path(run)/'STATE.json'
            if path.is_file():
                state=read(path);state.update(status='failed',error=dict(type=type(error).__name__,message=str(error)))
                _withdraw_ready(run,state,'execution_or_input_validation_failed');write(path,state)
            raise


def tick(run,*,reviewer=None):
    run=Path(run)
    with _tick_guard(run):
        snapshot=status(run);plan,state=snapshot['plan'],snapshot['state']
        config=plan['config'];packet=plan['packet']
        if snapshot['paused'] and not any(t.get('status')!='collected' for t in state['jobs'].values()):
            state['status']='paused';write(run/'STATE.json',state);return state
        if not state.get('import_complete') and packet.get('import_manifest'):
            imported=library.import_manifest(config['library'],packet['import_manifest'],book_id=packet['book_id'])
            state['import_complete']=True;state['imported']=len(imported['assets']);write(run/'STATE.json',state)
        # Always reconcile the original IDs before considering another submission.
        for jid,task in list(state['jobs'].items()):
            if task.get('status')=='collected':continue
            js=images.status(task['folder'])
            if js.get('prompt_id'):
                js=images.poll(task['folder'])
                if js.get('status') in ('native_complete','saved','collected','completed'):
                    receipt=images.collect(task['folder']);_collect_generated(run,plan,state,jid,receipt)
                else:
                    state['status']='image_'+js.get('status','unknown');write(run/'STATE.json',state);return state
            elif js.get('status') in ('unknown','outcome_unknown'):
                state['status']='outcome_unknown';write(run/'STATE.json',state);return state
            else:
                if snapshot['paused']:
                    state['status']='paused';write(run/'STATE.json',state);return state
                with gpu_access(plan,for_review=False):images.submit(task['folder'])
                state['status']='image_submitted';write(run/'STATE.json',state);return state
        if (run/'PAUSE.json').exists():
            state['status']='paused';write(run/'STATE.json',state);return state
        reviewed=0
        if reviewer:
            with gpu_access(plan):
                state['status']='reviewing';write(run/'STATE.json',state)
                reviewed=review_candidates(run,plan,state,reviewer)
                _ensure_style_references(run,plan,state,reviewer)
        if (run/'PAUSE.json').exists():
            state['status']='paused';write(run/'STATE.json',state);return state
        report=_requirements_status(plan)
        state['requirements']=report
        if report['ready']:
            state['status']='assets_ready'
            if reference_delivery(config):
                # The reference model consumes reviewed identities/environment
                # directly. Do not synthesize an unrelated per-shot first frame
                # or inherit its two-person composition/camera restrictions.
                from .visual_h3_reference_bundle_v20 import collect
                state['reference_assets']={shot['id']:collect(run,shot['id'])['bundle_sha256']
                                           for shot in packet.get('shots',[])}
                state['status']='reference_assets_ready'
                write(run/'STATE.json',state);return state
            if packet.get('shots'):
                try:
                    for shot in packet['shots']:_require_current_shot_style(packet,shot)
                except ValueError as error:
                    _withdraw_ready(run,state,'residence_shot_requires_restage')
                    state.update(status='needs_restage',waiting_reason=str(error));write(run/'STATE.json',state);return state
                bindings=compile_bindings(packet,lambda req:_lookup(plan,req))
                if (run/'SHOT_BINDINGS.json').exists() and read(run/'SHOT_BINDINGS.json')!=bindings:
                    old={s['id']:s['binding_sha256'] for s in read(run/'SHOT_BINDINGS.json')['shots']}
                    new={s['id']:s['binding_sha256'] for s in bindings['shots']}
                    _withdraw_ready(run,state,'asset_versions_or_binding_changed',
                                    affected_shots={sid for sid in set(old)|set(new) if old.get(sid)!=new.get(sid)})
                freeze(run/'SHOT_BINDINGS.json',bindings)
                state['last_binding_snapshot']=bindings
                state['status']='shot_bindings_ready'
                for shot in bindings['shots']:
                    frame=state.setdefault('first_frames',{}).get(shot['id'])
                    if frame and frame['binding_sha256']!=shot['binding_sha256']:raise ValueError('first_frame_assets_changed')
                    if not frame:
                        jid=_prepare_first_frame(run,plan,state,shot)
                        state['status']='first_frame_prepared';write(run/'STATE.json',state);return state
                    if file_sha(frame['path'])!=frame['sha256']:raise ValueError('reviewed_first_frame_changed')
                    bound_place=next(a for a in shot['references'] if a['kind']=='place')
                    bound_environment=_entity(plan,{k:bound_place[k] for k in ('entity_id','kind','view','design_version')})
                    if bound_environment.get('spatial_layout'):
                        with Image.open(frame['path']) as image:fw,fh=image.size
                        expected_guide=_first_frame_guide(run,plan,shot,bound_environment,width=fw,height=fh,create=False)
                        if frame.get('environment_guide')!=expected_guide:raise ValueError('first_frame_environment_guide_binding_changed')
                        if frame.get('review',{}).get('decision')=='accepted' and frame['review'].get('layout_guide_sha256')!=expected_guide['sha256']:
                            raise ValueError('first_frame_accepted_guide_binding_changed')
                    _verify_first_frame_generation(plan,shot,frame)
                    prior=frame.get('review');retry=(prior and prior.get('decision')=='unavailable' and prior.get('retryable') is True and
                        prior.get('completion_known') is True and prior.get('outcome_unknown') is False and
                        frame.get('review_attempts',0)<config.get('max_review_attempts',2))
                    if reviewer and (not prior or retry):
                        with gpu_access(plan):
                            chars=[dict(id=a['entity_id'],path=str(_image_path(plan,a))) for a in shot['references'] if a['kind']=='character']
                            place=next(a for a in shot['references'] if a['kind']=='place')
                            place_entity=_entity(plan,{k:place[k] for k in ('entity_id','kind','view','design_version')})
                            place_request=dict(id=place['entity_id'],path=str(_image_path(plan,place)))
                            expectation=dict(expected_people=len(shot['visible_cast']),age_band=_visible_age_band(packet,shot['visible_cast']),
                                appearance_description=(static_frames.entry(plan,shot)['static_start_prompt'] if static_frames.enabled(config) else shot['visual_prompt']))
                            guide=None
                            if place_entity.get('spatial_layout'):
                                with Image.open(frame['path']) as current_frame:fw,fh=current_frame.size
                                guide=_first_frame_guide(run,plan,shot,place_entity,width=fw,height=fh,create=False)
                                if frame.get('environment_guide')!=guide:raise ValueError('first_frame_environment_guide_binding_changed')
                                place_request.update(layout_guide=guide['path'],description=environment.design_description(place_entity,require=True))
                                expectation['environment_context']=(static_frames.contexts(place_entity,shot,static_frames.entry(plan,shot),width=fw,height=fh)[1]
                                    if static_frames.enabled(config) else environment.review_context(place_entity,shot.get('place_view','front')))
                            inventory=_review_layout_inventory(plan,place_entity)
                            if inventory is not None:expectation['layout_object_inventory']=inventory
                            if inventory is not None and static_frames.enabled(config):
                                expectation['furniture_observation_scope']='split_target_only/v14'
                            if prior:frame.setdefault('review_history',[]).append(prior)
                            evidence_args=(shot['binding_sha256'],frame['sha256'],frame.get('review_attempts',0))
                            history=state.get('first_frame_history',{}).get(shot['id'],[])
                            composition_evidence=frame_review_paths.select(run/'first_frame_reviews',*evidence_args,repair_history=history)
                            frame['review']=reviewer.review_composition(frame['path'],characters=chars,place=place_request,expectation=expectation,evidence_dir=composition_evidence)
                            frame['review']=_consume_layout_inventory(frame['review'],inventory)
                            if frame['review']['decision']=='accepted':
                                style=_residence_style_review(run,plan,place_entity,frame['path'],reviewer,
                                    frame_review_paths.select(run/'first_frame_style_reviews',*evidence_args,repair_history=history))
                                frame['review']=_combine_residence_style(frame['review'],style)
                            frame['review_attempts']=frame.get('review_attempts',0)+1
                            if guide and frame['review'].get('layout_guide_sha256')!=guide['sha256']:raise ValueError('first_frame_review_guide_mismatch')
                        if frame['review'].get('target_sha256')!=frame['sha256']:raise ValueError('first_frame_review_wrong_target')
                    if frame.get('review'):
                        frame['review']=_consume_layout_inventory(frame['review'],_review_layout_inventory(plan,bound_environment))
                    if not frame.get('review') or frame['review']['decision']!='accepted':
                        if frame.get('review',{}).get('decision')=='repair_required' and state.setdefault('frame_repairs',{}).get(shot['id'],0)<config.get('max_repair_rounds',2):
                            state.setdefault('first_frame_history',{}).setdefault(shot['id'],[]).append(frame)
                            state['frame_repairs'][shot['id']]=state['frame_repairs'].get(shot['id'],0)+1
                            del state['first_frames'][shot['id']]
                            _prepare_first_frame(run,plan,state,shot)
                            state['status']='first_frame_prepared';write(run/'STATE.json',state);return state
                        state['status']='blocked_first_frame_review';write(run/'STATE.json',state);return state
                    _verify_residence_style_receipt(run,plan,bound_environment,frame['path'],frame['review'])
                    _verify_first_frame_inventory(plan,bound_environment,frame['review'])
                freeze(run/'H3_INPUT_READY.json',dict(schema='h3_visual_input/v3',source=packet['source'],shots=bindings['shots'],first_frames=state['first_frames'],old_batch_resume=False,publication=False))
                state['status']='h3_inputs_ready'
            write(run/'STATE.json',state);return state
        if reference_delivery(config):state.pop('reference_assets',None)
        _withdraw_ready(run,state,'required_assets_not_ready',affected_shots=_affected_shots(plan,state,run))
        for req in asset_requirements(packet):
            row=_lookup(plan,req)
            if row and row['status']=='reviewed':continue
            jid=_generation(run,plan,state,req)
            if jid:
                state['status']='image_prepared';write(run/'STATE.json',state);return state
        if reviewed and _newly_reviewable(plan,state):
            state['status']='review_pending';write(run/'STATE.json',state);return state
        state['status']='blocked_review_or_design';write(run/'STATE.json',state);return state


def run_until_idle(run,*,reviewer=None,poll_seconds=5,max_ticks=10000):
    for _ in range(max_ticks):
        try:result=tick(run,reviewer=reviewer)
        except images.JobBusyError as error:
            try:
                with images.run_lock(run):
                    state=read(Path(run)/'STATE.json')
                    state.update(status='waiting_gpu' if str(error)=='native_gpu_queue_busy' else 'waiting_resource',
                                 heartbeat_at=time.time(),waiting_reason=str(error))
                    write(Path(run)/'STATE.json',state)
            except images.JobBusyError:
                # Another executor owns this run. Never overwrite its progress,
                # or turn ordinary contention into a worker crash.
                pass
            time.sleep(poll_seconds);continue
        except Exception as error:
            state=read(Path(run)/'STATE.json');state.update(status='failed',error=dict(type=type(error).__name__,message=str(error)))
            _withdraw_ready(Path(run),state,'execution_or_input_validation_failed')
            write(Path(run)/'STATE.json',state);raise
        if result['status'] in ('assets_ready','reference_assets_ready','h3_inputs_ready','blocked_first_frame_review','blocked_review_or_design','needs_restage','outcome_unknown','paused') or result['status'].startswith(('image_failed','image_rejected','image_interrupted','image_outcome_unknown')):return result
        time.sleep(poll_seconds)
    return read(Path(run)/'STATE.json')


def _affected_shots(plan,state,run):
    bindings=(read(Path(run)/'SHOT_BINDINGS.json') if (Path(run)/'SHOT_BINDINGS.json').is_file()
              else state.get('last_binding_snapshot',{}))
    affected=set()
    for shot in bindings.get('shots',[]):
        for reference in shot['references']:
            req={k:reference[k] for k in ('entity_id','kind','view','design_version')}
            current=_lookup(plan,req)
            if not current or current['status']!='reviewed' or _asset_identity(current)!=_asset_identity(reference):
                affected.add(shot['id']);break
    return affected


def _withdraw_ready(run,state,reason,*,affected_shots=None):
    files=[Path(run)/n for n in ('H3_INPUT_READY.json','SHOT_BINDINGS.json') if (Path(run)/n).is_file()]
    frames=state.setdefault('first_frames',{})
    removed={sid:frame for sid,frame in frames.items() if affected_shots is None or sid in affected_shots}
    if not files and not removed:return
    folder=Path(run)/'invalidated'/uuid.uuid4().hex;folder.mkdir(parents=True,exist_ok=False)
    for p in files:p.rename(folder/p.name)
    for sid in removed:
        del frames[sid]
        state.setdefault('frame_repairs',{}).pop(sid,None)
    event=dict(at=time.time(),reason=reason,archived_files=[str(folder/p.name) for p in files],frames=removed)
    state.setdefault('invalidations',[]).append(event);write(folder/'INVALIDATION.json',event)
    write(Path(run)/'STATE.json',state)


def _first_frame_guide(run,plan,shot,entity,*,width=736,height=1312,create=True):
    if static_frames.enabled(plan['config']):return static_frames.guide(run,plan,shot,entity,width=width,height=height,create=create)
    return _environment_guide(run,entity,shot.get('place_view','front'),width=width,height=height)


def _prepare_first_frame(run,plan,state,shot):
    _require_current_shot_style(plan['packet'],shot)
    width=plan['config'].get('first_frame_width',736);height=plan['config'].get('first_frame_height',1312)
    place=next(a for a in shot['references'] if a['kind']=='place')
    place_entity=_entity(plan,{k:place[k] for k in ('entity_id','kind','view','design_version')})
    guide=(_first_frame_guide(run,plan,shot,place_entity,width=width,height=height)
           if place_entity.get('spatial_layout') else None)
    isolated=generation_refs.enabled(plan['config']);generation_header=generation_refs.header(plan,'first_frame') if isolated else None
    static=static_frames.enabled(plan['config']);crops=[]
    config=images.Config(**plan['config']['image_service']);inputs=[];refs=[]
    if guide:
        name='geometry_'+guide['sha256'][:20]+'.png'
        refs.append(dict(input_name=name));inputs.append(dict(input_name=name,path=guide['path'],sha256=guide['sha256']))
    for a in shot['references']:
        if isolated and a['kind']=='place':continue
        if static:
            item,crop=static_frames.character_input(run,plan,a,create=True);crops.append(crop)
            refs.append(dict(input_name=item['input_name']));inputs.append(item)
        else:
            p=_image_path(plan,a);name='asset_'+fingerprint(_asset_identity(a))[:20]+'.png'
            refs.append(dict(input_name=name));inputs.append(dict(input_name=name,path=str(p),sha256=a['sha256']))
    input_roles=['geometry']+['character:'+a['entity_id'] for a in shot['references'] if a['kind']=='character'] if isolated else []
    if isolated:
        appearance_inputs,appearance_roles=_isolated_place_inputs(plan,place_entity,guide)
        for item,role in zip(appearance_inputs[1:],appearance_roles[1:]):
            refs.append(dict(input_name=item['input_name']));inputs.append(item);input_roles.append(role)
    prompt=static_frames.prompt(plan,shot,place_entity,width=width,height=height) if static else shot['visual_prompt']
    if guide and not static:prompt=('The first reference is a geometry blockout for the exact camera and empty physical space. '
        +('Character references supply fictional people; the final references are layout-free surface appearance samples. '
          if isolated else 'Other references supply actual fictional people and the established room appearance. ')
        +'Recreate natural materials, '
        'the specified visible people and their actions in this camera; do not render blocks, diagrams or reference labels. '
        +prompt+'\nFixed room/camera: '+json.dumps(
            environment.render_context(place_entity,shot.get('place_view','front'),width=width,height=height)
            if place_entity.get('background_contract') else environment.review_context(place_entity,shot.get('place_view','front')),ensure_ascii=False))
    static_binding=static_frames.binding(plan,shot,guide,crops,prompt) if static else None
    identity=fingerprint(dict(binding=shot['binding_sha256'],role='first_frame',width=width,height=height,
                              environment_guide=guide,attempt=state.get('frame_repairs',{}).get(shot['id'],0),
                              **({'generation_reference':generation_header} if generation_header else {}),
                              **({'static_start':static_binding} if static_binding else {})))[:24];jid='frame_'+identity
    graph=images.build_graph([dict(id='first_frame',prompt=prompt,seed=int(identity[:8],16),references=refs)],
                             config.allowed_prefix+'/'+jid,width=width,height=height)
    folder=Path(run)/'image_jobs'/jid;images.prepare_job(folder,graph,config,inputs,job_id=jid)
    binding=generation_refs.bind_job(plan,'first_frame',inputs,input_roles,folder) if isolated else None
    state['jobs'][jid]=dict(kind='first_frame',folder=str(folder),shot_id=shot['id'],binding_sha256=shot['binding_sha256'],environment_guide=guide,
        **({'generation_reference':binding} if binding else {}),**({'static_start':static_binding} if static_binding else {}))
    write(Path(run)/'STATE.json',state);return jid


def _verify_first_frame_generation(plan,shot,frame):
    if not generation_refs.enabled(plan['config']):return
    place=next(a for a in shot['references'] if a['kind']=='place')
    entity=_entity(plan,{k:place[k] for k in ('entity_id','kind','view','design_version')})
    appearance,appearance_roles=_isolated_place_inputs(plan,entity,frame.get('environment_guide'))
    inputs=[appearance[0]];roles=['geometry'];crops=[];static=static_frames.enabled(plan['config'])
    for actor in shot['references']:
        if actor['kind']!='character':continue
        if static:
            item,crop=static_frames.character_input(Path(frame['generation_reference']['job_dir']).parent.parent,plan,actor,create=False)
            inputs.append(item);crops.append(crop)
        else:
            inputs.append(dict(input_name='asset_'+fingerprint(_asset_identity(actor))[:20]+'.png',
                path=str(_image_path(plan,actor)),sha256=actor['sha256']))
        roles.append('character:'+actor['entity_id'])
    inputs.extend(appearance[1:]);roles.extend(appearance_roles[1:])
    if static:
        with Image.open(frame['path']) as image:width,height=image.size
        expected_guide=static_frames.guide(Path(frame['generation_reference']['job_dir']).parent.parent,plan,shot,entity,width=width,height=height,create=False)
        if frame['environment_guide']!=expected_guide:raise ValueError('static_frame_current_guide_changed')
        expected=static_frames.binding(plan,shot,frame['environment_guide'],crops,static_frames.prompt(plan,shot,entity,width=width,height=height))
        if frame.get('static_start')!=expected:raise ValueError('static_frame_source_crop_or_prompt_binding_changed')
        graph=read(Path(frame['generation_reference']['job_dir'])/'workflow_api.json')
        if hashlib.sha256(graph['first_frame__positive']['inputs']['text'].encode('utf-8')).hexdigest()!=expected['prompt_sha256']:
            raise ValueError('static_frame_native_prompt_changed')
    generation_refs.verify_job(plan,frame.get('generation_reference'),'first_frame',inputs,roles,receipt=frame.get('generation_receipt'),require_receipt=True)
    outputs=frame['generation_receipt']['images']
    if len(outputs)!=1 or outputs[0]['sha256']!=frame.get('sha256') or Path(outputs[0]['path']).resolve()!=Path(frame['path']).resolve():
        raise ValueError('generation_policy_first_frame_output_changed')


def packet_from_cast(cast_root,book_id):
    cast_root=Path(cast_root).resolve();plan=read(cast_root/'CAST_PLAN.json')
    descriptions=read(cast_root/'VIEW_DESCRIPTIONS.json');characters=[]
    front_rows={r['character_id']:r for r in read(cast_root/'FINAL_MAP.json')['items'] if r['view']=='front'}
    for c in plan['characters']:
        child=type(c.get('visual_design_age')) is int and c['visual_design_age']<18
        prompts=deepcopy(descriptions['defaults']);prompts['right_profile']=descriptions['right_profile_from_pose']
        characters.append(dict(id=c['id'],name=c['name'],identity_group=c['identity_group'],design_version='v1',
            age_band='child' if child else 'adult',front_prompt=front_rows[c['id']].get('prompt',c['front_prompt']),view_prompts=prompts,
            canonical_from_role=c.get('canonical_from_role'),
            appearance_design=c['front_prompt'],source_facts=c['source_facts']))
    return dict(schema='visual_asset_packet/v3',book_id=str(book_id),source=plan['source'],characters=characters,
                places=[],shots=[],import_manifest=str(cast_root/'FINAL_MAP.json'))
