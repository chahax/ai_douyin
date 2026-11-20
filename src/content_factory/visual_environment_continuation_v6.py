"""Explicit reviewed-front -> reverse/side continuation, with read-only origins."""
from copy import deepcopy
import json
from pathlib import Path
import re

from . import visual_environment_v4 as environment
from . import visual_residence_style_v5 as style
from .visual_shot_binding_v3 import fingerprint

SCHEMA='reviewed_environment_continuation/v1'
CONFIG_KEY='environment_continuation'
PREVIEW='Reviewed residence background reverse/side continuation only; no character import, first frame, video or publication.'


def _views(views):
    if (not isinstance(views,(tuple,list)) or not views or len(views)!=len(set(views))
        or not set(views)<=set(('reverse','side'))):raise ValueError('continuation_only_new_reverse_or_side_views')
    return [view for view in ('reverse','side') if view in views]


def _target(origin,new_run):
    origin=Path(origin).resolve();new_run=Path(new_run).resolve()
    if (new_run==origin or new_run.parent!=origin.parent or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',new_run.name)):
        raise ValueError('continuation_requires_distinct_sibling_run')
    return new_run


def _guide_proof(entity,row,pipeline):
    guide=row.get('provenance',{}).get('environment_guide')
    if not isinstance(guide,dict):raise ValueError('continuation_front_guide_missing')
    path=Path(guide['path']).resolve();manifest_path=Path(guide['manifest_path']).resolve()
    manifest=pipeline.read(manifest_path);binding=manifest.get('binding',{})
    if (path!=manifest_path.parent/'front.png' or guide.get('view')!='front'
        or guide.get('renderer')!=environment.RENDERER or binding.get('renderer')!=environment.RENDERER
        or binding.get('schema')!=environment.VERSION or binding.get('layout')!=entity['spatial_layout']
        or binding.get('layout_sha256')!=fingerprint(entity['spatial_layout'])
        or guide.get('layout_sha256')!=fingerprint(entity['spatial_layout'])
        or guide.get('camera')!=entity['spatial_layout']['cameras']['front']
        or guide.get('design_sha256')!=pipeline._environment_design_sha(entity)
        or pipeline.file_sha(path)!=guide.get('sha256')):
        raise ValueError('continuation_front_guide_changed')
    view=manifest.get('views',{}).get('front')
    if not isinstance(view,dict) or any(view.get(k)!=guide.get(k) for k in view):
        raise ValueError('continuation_front_guide_manifest_changed')
    return dict(guide=deepcopy(guide),manifest_sha256=pipeline.file_sha(manifest_path))


def _origin_snapshot(origin_run):
    from . import visual_asset_pipeline_v3 as pipeline
    origin=Path(origin_run).resolve();snapshot=pipeline.status(origin);plan=snapshot['plan'];packet=plan['packet'];config=plan['config']
    if config.get(CONFIG_KEY):raise ValueError('continuation_origin_must_be_original_front_run')
    if packet.get('characters') or packet.get('shots') or not packet.get('places') or not packet.get('style_groups'):
        raise ValueError('continuation_requires_background_only_front_origin')
    if any(place.get('required_views')!=['front'] for place in packet['places']):
        raise ValueError('continuation_origin_must_require_only_fronts')
    style.validate_groups(packet)
    report=pipeline._requirements_status(plan)
    if not report['ready'] or len(report['selected'])!=len(packet['places']):
        raise ValueError('continuation_origin_fronts_not_currently_reviewed')
    fronts=[]
    selected={row['entity_id']:row for row in report['selected']}
    for entity in packet['places']:
        row=selected.get(entity['id'])
        if not row or row['status']!='reviewed':raise ValueError('continuation_source_front_not_reviewed')
        path=pipeline._image_path(plan,row)
        fronts.append(dict(identity=pipeline._asset_identity(row),book_id=row['book_id'],file=str(path),
            review_sha256=fingerprint(row.get('review')),provenance_sha256=fingerprint(row.get('provenance')),
            guide=_guide_proof(entity,row,pipeline),style_binding=row.get('residence_style_binding')))
    bundles=[]
    for group in packet['style_groups']:
        master=next(p for p in packet['places'] if p['id']==group['master_place_id'])
        bundle=pipeline._style_reference_for_entity(origin,plan,master)
        if not bundle:raise ValueError('continuation_origin_style_reference_not_ready')
        folder=Path(bundle['manifest_path']).parent
        bundles.append(dict(group_id=group['id'],definition_sha256=group['definition_sha256'],
            manifest_path=bundle['manifest_path'],manifest_sha256=bundle['manifest_sha256'],
            ready_sha256=pipeline.file_sha(folder/'READY.json'),review_sha256=pipeline.file_sha(folder/'REFERENCE_REVIEW.json'),
            master_identity=bundle['master']['identity'],reference_contract=bundle.get('reference_contract',style.MATERIAL_CONTRACT),
            parent=deepcopy(bundle.get('inherited_reference')),patch_bindings=[{k:p[k] for k in
                ('slot','material_key','sha256','source_sha256','source_dimensions','pixel_roi')} for p in bundle['patches']]))
    return dict(origin_run=str(origin),origin_plan_sha256=pipeline.file_sha(origin/'PLAN.json'),
        origin_packet_sha256=plan['packet_sha256'],book_id=packet['book_id'],source=deepcopy(packet['source']),
        origin_reference_root=str(Path(config['style_reference_root']).resolve()),fronts=fronts,bundles=bundles),plan


def _derived_packet(origin_packet,views,proof):
    packet=deepcopy(origin_packet)
    for entity in packet['places']:entity['required_views']=['front']+views
    packet.pop('import_manifest',None)
    packet['preview_scope']=PREVIEW
    packet['environment_continuation']=dict(schema=SCHEMA,origin_run=proof['origin']['origin_run'],
        origin_plan_sha256=proof['origin']['origin_plan_sha256'],requested_views=views)
    return packet


def _derivation(origin,plan,new_run,views,allowed_prefix):
    proof=dict(schema=SCHEMA,target_run=str(new_run),requested_views=views,allowed_prefix=allowed_prefix,origin=origin,
        scope=dict(new_views=len(plan['packet']['places'])*len(views),max_images_per_view=1,
            max_known_review_attempts=2,source_reference_review_calls=0,first_frames=False,videos=False,publication=False))
    packet=_derived_packet(plan['packet'],views,proof);config=deepcopy(plan['config'])
    config.update(style_reference_root=origin['origin_reference_root'],max_repair_rounds=1,max_review_attempts=2)
    config['image_service']['allowed_prefix']=allowed_prefix
    config[CONFIG_KEY]=proof
    return dict(packet=packet,config=config,run=str(new_run),proof=proof)


def derive(origin_run,new_run,*,views=('reverse','side'),allowed_prefix=None):
    """Read-only derivation. Does not create a run, reference file or model job."""
    views=_views(views);new_run=_target(origin_run,new_run);origin,plan=_origin_snapshot(origin_run)
    from .visual_image_jobs_v3 import _relative
    prefix=_relative(allowed_prefix if allowed_prefix is not None else plan['config']['image_service'].get('allowed_prefix','visual_assets_v3'))
    return _derivation(origin,plan,new_run,views,prefix)


def validate(run,packet,config):
    """Recheck current source rows and frozen reference files, never a global INDEX SHA."""
    proof=config.get(CONFIG_KEY)
    if not isinstance(proof,dict) or proof.get('schema')!=SCHEMA:raise ValueError('continuation_proof_invalid')
    origin=proof.get('origin',{});views=_views(proof.get('requested_views'))
    if str(_target(origin['origin_run'],run))!=proof.get('target_run'):raise ValueError('continuation_target_changed')
    current,origin_plan=_origin_snapshot(origin['origin_run'])
    if current!=origin:raise ValueError('continuation_origin_assets_or_reference_changed')
    from .visual_image_jobs_v3 import _relative
    prefix=_relative(proof.get('allowed_prefix'))
    expected=_derivation(current,origin_plan,Path(run).resolve(),views,prefix)
    if proof!=expected['proof'] or packet!=expected['packet'] or config!=expected['config']:
        raise ValueError('continuation_packet_config_or_budget_changed')
    return proof


def prepare(origin_run,new_run,*,views=('reverse','side'),allowed_prefix=None):
    """Create only the derived run; no GPU, reference review or business dispatch."""
    from . import visual_asset_pipeline_v3 as pipeline
    derived=derive(origin_run,new_run,views=views,allowed_prefix=allowed_prefix)
    pipeline.prepare(new_run,derived['packet'],derived['config'])
    return dict(run=derived['run'],packet=derived['packet'],config=derived['config'],
        status=pipeline.status(new_run)['state']['status'],production_approved=False)
