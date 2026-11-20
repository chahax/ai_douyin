"""Explicit per-shot text preparation after a real first-frame ready receipt.

Reads the routing plan but never writes it or submits any image/video job.
"""
from pathlib import Path
from . import visual_h3_native_prompt_v15 as native


def _row(production_plan,shot_id):
    production=native.stage.files.read(production_plan)
    found=[row for row in production['shots'] if row['id']==shot_id]
    if len(found)!=1:raise native.NativePromptBlocked('unique_production_shot_required')
    row=found[0];parent=native._read_binding(production['parent'])
    packet_path=Path(row['packet']).resolve()
    if native.stage.files.file_sha(packet_path)!=row['packet_sha256']:
        raise native.NativePromptBlocked('motion_route_packet_changed')
    packet=native.stage.files.read(packet_path)
    if len(packet['shots'])!=1 or packet['shots'][0]['id']!=shot_id or packet['source']!=parent['source']:
        raise native.NativePromptBlocked('motion_route_source_scope_changed')
    source=next((s for s in parent['shots'] if s['id']==shot_id),None)
    if source!=packet['shots'][0] or row['source_native_frames']!=source['source_native_frames']:
        raise native.NativePromptBlocked('motion_route_source_shot_or_clock_changed')
    if ('native_seconds' in row and abs(row['native_seconds']-source['source_native_frames']/24)>1e-8
            or 'source' in production and production['source']!=parent['source']):
        raise native.NativePromptBlocked('motion_route_source_shot_or_clock_changed')
    return production,row,packet


def status(production_plan,shot_id,run):
    _,row,_=_row(production_plan,shot_id)
    asset=Path(row['asset_run']);ready=(asset/'H3_INPUT_READY.json').is_file() and (asset/'PLAN.json').is_file()
    result=dict(shot_id=shot_id,ready_evidence_exists=ready,full_ready_validation_required=True,
        media_dispatch=False,model_called=False,run=str(Path(run).resolve()))
    if (Path(run)/'PLAN.json').is_file():result['text_status']=native.status(run)
    return result


def _require_ready(row,packet):
    asset=Path(row['asset_run']).resolve()
    if not (asset/'H3_INPUT_READY.json').is_file() or not (asset/'PLAN.json').is_file():
        raise native.NativePromptBlocked('shot_first_frame_not_ready_no_model_call')
    from .visual_h3_handoff_v3 import validate_ready
    snapshot,_,_=validate_ready(asset)
    if snapshot['plan']['packet']!=packet:
        raise native.NativePromptBlocked('motion_ready_asset_packet_changed')
    selected=row.get('first_frame_plan')
    if selected and snapshot['plan']['config'].get('first_frame_plan')!=selected:
        raise native.NativePromptBlocked('motion_ready_selected_static_route_changed')
    return asset


def prepare(production_plan,shot_id,run,*,user_statement,official_guide_path,known_predecessor=None,known_issue=None,issue_evidence=None,frame_correction_proof=None,source_audio_insertion=None,camera_contract=native.CAMERA_CONTRACT_V19,camera_design=None):
    production,row,packet=_row(production_plan,shot_id);asset=_require_ready(row,packet)
    return native.prepare(run,production['parent']['path'],row['packet'],asset,
        user_statement=user_statement,official_guide_path=official_guide_path,
        known_predecessor=known_predecessor,known_issue=known_issue,issue_evidence=issue_evidence,frame_correction_proof=frame_correction_proof,source_audio_insertion=source_audio_insertion,camera_contract=camera_contract,camera_design=camera_design)


def plan(production_plan,shot_id,run,*,client=None):
    production,row,packet=_row(production_plan,shot_id);asset=_require_ready(row,packet)
    state=native.status(run);frozen=state['plan']
    if (Path(frozen['asset_plan']['path']).resolve()!=asset/'PLAN.json'
            or frozen['full_parent']!=production['parent'] or frozen['packet']!=dict(path=str(Path(row['packet']).resolve()),sha256=row['packet_sha256'])):
        raise native.NativePromptBlocked('prepared_motion_route_changed_use_explicit_successor')
    return native.plan(run,client=client)
