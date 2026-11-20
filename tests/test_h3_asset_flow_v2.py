from copy import deepcopy
import json

from src.content_factory import h3_asset_flow_v2 as flow
from h3_asset_flow_fixture_v2 import build_fixture

def test_actual_archived_source_offline_voice_and_state_compile(tmp_path):
    spec,out=build_fixture(tmp_path)
    value=flow.prepare(spec,out)
    assert value['status']=='offline_draft_valid'
    manifest=flow.read(out/'INPUT_MANIFEST.json');graph=flow.read(out/'DRAFT_WORKFLOW.json')
    assert len(manifest['references'])==9 and len(manifest['voice_resolution']['voices'])==3
    assert manifest['routes']['audio_references']==3 and manifest['routes']['audio_vae_input_connected'] is True
    assert manifest['angle_selection']['side_priority'][0]=='ye_dong'
    assert graph['condition']['inputs']['audio_vae']==['120',0]
    assert all(graph['condition']['inputs']['ref_audios.ref_audio_'+str(i)]==['voice_'+str(i),0] for i in range(3))
    assert '旁白' not in manifest['compiled_prompt']
    assert flow.validate(out)['status']=='offline_draft_verified'
    assert flow.prepare(spec,out)==value
    assert not list(out.rglob('CLAIM.json')) and not list(out.rglob('*READY*'))

def test_missing_reviewed_voice_is_a_notice_without_a_draft(tmp_path):
    spec,out=build_fixture(tmp_path,reviewed=False)
    assert flow.prepare(spec,out)['status']=='needs_material_or_state'
    assert not (out/'DRAFT_WORKFLOW.json').exists()
    assert flow.validate(out)['status']=='notice_verified'

def test_known_fifth_actor_guide_and_stale_state_basis_cannot_dispatch(tmp_path):
    spec_path,out=build_fixture(tmp_path)
    spec=flow.read(spec_path);spec['guide']['review']['unexpected_actor_ids']=['blue_copy']
    spec['guide']['review']['observed_actor_count']=5
    assert 'known_extra_actor' in str(flow.compile_spec(spec))
    spec=flow.read(spec_path);state=flow._bound(spec['state_plan']);state['initial_basis']['guide_review_sha256']='0'*64
    spec['state_plan']=flow.freeze(tmp_path/'bad_state.json',state)
    assert 'state_initial_guide_binding' in str(flow.compile_spec(spec))

def test_tampered_waveform_route_or_source_is_rejected(tmp_path):
    spec_path,out=build_fixture(tmp_path);flow.prepare(spec_path,out)
    graph_path=out/'DRAFT_WORKFLOW.json';graph=flow.read(graph_path)
    del graph['condition']['inputs']['audio_vae']
    graph_path.write_text(json.dumps(graph),encoding='utf-8')
    import pytest
    with pytest.raises(ValueError):flow.validate(out)

def test_required_voice_is_default_and_prompt_only_is_explicit(tmp_path):
    spec_path,out=build_fixture(tmp_path,reviewed=False);spec=flow.read(spec_path)
    del spec['voice']['mode']
    assert flow.compile_spec(spec)['status']=='needs_material_or_state'
    spec['voice']['mode']='prompt_only';value=flow.compile_spec(spec)
    assert value['manifest']['voice_resolution']['control_mode']=='prompt_only'
    assert value['manifest']['voice_resolution']['voices']==[]
    assert 'audio_vae' not in value['graph']['condition']['inputs']
    assert value['manifest']['routes']['audio_references']==0
    assert value['manifest']['routes']['audio_vae_input_connected'] is False

def test_changed_spec_cannot_leave_a_partial_new_draft_in_a_notice_namespace(tmp_path):
    spec_path,out=build_fixture(tmp_path,reviewed=False);flow.prepare(spec_path,out)
    spec=flow.read(spec_path);spec['voice']['mode']='prompt_only'
    spec_path.write_text(json.dumps(spec),encoding='utf-8')
    import pytest
    with pytest.raises(ValueError,match='new_output_namespace'):flow.prepare(spec_path,out)
    assert not (out/'DRAFT_WORKFLOW.json').exists() and not (out/'INPUT_MANIFEST.json').exists()

def test_check_cannot_claim_production_permissions(tmp_path):
    spec_path,out=build_fixture(tmp_path);flow.prepare(spec_path,out)
    p=out/'CHECK_RESULT.json';check=flow.read(p);check['production_dispatch_allowed']=True
    p.write_text(json.dumps(check),encoding='utf-8')
    import pytest
    with pytest.raises(ValueError,match='permission_changed'):flow.validate(out)

def test_rejected_image_is_not_resurrected_by_old_candidate_allowance(tmp_path,monkeypatch):
    spec_path,_=build_fixture(tmp_path);original=flow.features._asset
    def rejected(*args,**kwargs):
        row,pinned=original(*args,**kwargs);row=deepcopy(row);row['status']='rejected';return row,pinned
    monkeypatch.setattr(flow.features,'_asset',rejected)
    assert flow.compile_spec(flow.read(spec_path))['status']=='needs_material_or_state'
