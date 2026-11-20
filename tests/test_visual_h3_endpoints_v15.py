"""Explicit source-static endpoint eligibility and frozen native ID collection."""
from copy import deepcopy
import hashlib
from pathlib import Path

from PIL import Image
import pytest

from src.content_factory import visual_h3_endpoints_v15 as e
from src.content_factory import visual_h3_handoff_v3 as h
from src.content_factory import visual_h3_native_prompt_v15 as native
from test_visual_h3_handoff_v3 import setup,service,native_media


def certificate_args(asset):
    snapshot,ready,bindings=h.validate_ready(asset);shot=bindings['shots'][0]
    text=Path(snapshot['plan']['packet']['source']['path']).read_text(encoding='utf-8')
    quote='The man looks at the door.';start=text.index(quote)
    evidence=[dict(id='fixture_action',start=start,end=start+len(quote),text=quote,sha256=hashlib.sha256(quote.encode()).hexdigest())]
    authorization=dict(actor='protocol_fixture',statement='Explicit fixture decision: same endpoint posture/camera/location; no visual quality claim.',
        shot_id=shot['id'],binding_sha256=shot['binding_sha256'],same_start_end_pose=True,same_start_end_camera=True,
        same_start_end_location=True,full_native_video_required=True)
    return evidence,authorization


def endpoint_config(asset,tmp_path,config,monkeypatch):
    evidence,authorization=certificate_args(asset)
    binding=e.prepare_certificate(asset,tmp_path/'new_certificates'/'ENDPOINT.json','shot1',source_action_evidence=evidence,authorization=authorization)
    path=tmp_path/'NATIVE_PLAN_FIXTURE.json';h.write(path,dict(protocol_fixture=True))
    native_binding=dict(path=str(path),sha256=h.file_sha(path))
    def load(packet,binding,shot):
        if h.file_sha(binding['path'])!=binding['sha256']:raise ValueError('fixture_native_plan_changed')
        return dict(source_shot=shot['id'])
    def compile(shot,timing,entry,anchor_mode='first'):
        return ('Endpoint '+anchor_mode+' fixture.\nintegrated_multimodal_description: [Shot 1] A still-positioned man breathes gently.\n'
            'overall_soundscape: Quiet room ambience.\nnon_diegetic_music: N/A')
    # Dispatcher/graph integration only; the independent native compiler has separate semantic/source tests.
    monkeypatch.setattr(native,'load_for',load);monkeypatch.setattr(native,'compile_for',compile)
    config.update(keyframe_policy=e.POLICY,source_endpoint_certificate=binding,
        native_prompt_contract='official_multimodal/v15',native_prompt_plan=native_binding)
    return config


def test_default_handoff_remains_first_only_and_has_no_new_conditioning_metadata(tmp_path,service):
    asset,run,config=setup(tmp_path,service,shots=1);h.prepare_from_ready(asset,run,config)
    plan=h.read(run/'PLAN.json');row=plan['shots'][0];graph=h.read(run/'shots'/'shot1'/'workflow_api.json')
    assert 'last_frame' not in graph['condition']['inputs']
    assert 'keyframe_policy' not in plan['config'] and 'keyframe_conditioning' not in row and 'native_prompt' not in row
    graph['condition']['inputs']['last_frame']=['ref_scene',0]
    with pytest.raises(h.HandoffIntegrityError):h._validate_graph(graph,row['scope'],row['input_name'])


def test_explicit_single_shot_certificate_opens_same_slot_first_last_and_tracks_true_method(tmp_path,service,monkeypatch):
    asset,run,config=setup(tmp_path,service,shots=1);old={p:p.read_bytes() for p in asset.rglob('*') if p.is_file()}
    endpoint_config(asset,tmp_path,config,monkeypatch);h.prepare_from_ready(asset,run,config)
    plan=h.read(run/'PLAN.json');row=plan['shots'][0];graph=h.read(run/'shots'/'shot1'/'workflow_api.json')
    assert graph['condition']['inputs']['first_frame']==graph['condition']['inputs']['last_frame']==['ref_scene',0]
    assert set(graph)==set(h.CLASSES) and sum(n['class_type']=='LoadImage' for n in graph.values())==1
    assert row['keyframe_conditioning']['source_same_frame_conditioning'] is True
    assert row['keyframe_conditioning']['first_frame_sha256']==row['keyframe_conditioning']['last_frame_sha256']==row['first_frame']['sha256']
    assert row['native_prompt']['anchor_mode']=='first_last' and 'Endpoint first_last' in graph['condition']['inputs']['prompt']
    assert all(path.read_bytes()==before for path,before in old.items()) and not service.posts
    h._load(run)
    graph['condition']['inputs']['last_frame']=['pick_last',0]
    with pytest.raises(h.HandoffIntegrityError):h._validate_graph(graph,row['scope'],row['input_name'],keyframe_policy=e.POLICY)


@pytest.mark.parametrize('change',[
    lambda auth:auth.update(same_start_end_pose=False),lambda auth:auth.update(same_start_end_camera='true'),
    lambda auth:auth.update(full_native_video_required=False),lambda auth:auth.update(shot_id='shot2'),
    lambda auth:auth.update(binding_sha256='0'*64),lambda auth:auth.update(statement=''),
])
def test_static_endpoint_is_not_automatic_for_other_or_changed_actions(tmp_path,service,change):
    asset,_,_=setup(tmp_path,service,shots=1);evidence,authorization=certificate_args(asset);change(authorization)
    with pytest.raises(ValueError):e.prepare_certificate(asset,tmp_path/'BAD.json','shot1',source_action_evidence=evidence,authorization=authorization)
    assert not (tmp_path/'BAD.json').exists() and not service.posts


def test_source_evidence_is_exact_and_single_shot_authority_cannot_expand_to_batch(tmp_path,service):
    asset,_,_=setup(tmp_path,service,shots=2);evidence,authorization=certificate_args(asset)
    with pytest.raises(ValueError,match='single_explicit_shot_scope'):
        e.prepare_certificate(asset,tmp_path/'BATCH.json','shot1',source_action_evidence=evidence,authorization=authorization)
    assert not (tmp_path/'BATCH.json').exists()


@pytest.mark.parametrize('kind',['quote','range','book','frame','authority'])
def test_updated_file_hash_cannot_hide_forged_certificate_semantics_or_image_identity(tmp_path,service,monkeypatch,kind):
    asset,run,config=setup(tmp_path,service,shots=1);endpoint_config(asset,tmp_path,config,monkeypatch)
    path=Path(config['source_endpoint_certificate']['path']);value=h.read(path)
    if kind=='quote':value['source_action_evidence'][0]['text']='An invented new ending.'
    elif kind=='range':value['source_action_evidence'][0]['start']+=1
    elif kind=='book':value['book_id']='another_book'
    elif kind=='frame':value['frame']['sha256']='0'*64
    else:value['authorization']['same_start_end_location']=False
    h.write(path,value);config['source_endpoint_certificate']['sha256']=h.file_sha(path)
    with pytest.raises(ValueError):h.prepare_from_ready(asset,run,config)
    assert not run.exists() and not service.posts


def test_opt_in_certificate_and_native_contract_are_required_together(tmp_path,service):
    asset,run,config=setup(tmp_path,service,shots=1)
    for partial in [dict(keyframe_policy=e.POLICY),dict(source_endpoint_certificate={}),
                    dict(keyframe_policy=e.POLICY,source_endpoint_certificate=dict(path='x',sha256='0'*64))]:
        with pytest.raises(ValueError):h.prepare_from_ready(asset,run,dict(config,**partial))
    assert not run.exists()


def test_low_resolution_probe_keeps_original_277_frame_timeline_and_same_input_slots(tmp_path):
    frame_path=tmp_path/'first.png';Image.new('RGB',(736,1312),'gray').save(frame_path)
    frame=dict(path=str(frame_path),sha256=h.file_sha(frame_path));shot=dict(id='F0001',binding_sha256='a'*64,
        visual_prompt='One man remains reclined.',visible_cast=['su_mo'],audio=[],start=0,end=277/24)
    timing=h._timing(shot);graph=h.build_graph(h.read(h.DEFAULT_BASE),shot,frame,timing,'test/first.png','visual_h3_v3/probe/F0001',
        288,512,keyframe_policy=e.POLICY,native_prompt='Native first-last prompt fixture.')
    assert graph['condition']['inputs']['length']==277 and timing['native_frames']==277
    assert graph['condition']['inputs']['first_frame']==graph['condition']['inputs']['last_frame']==['ref_scene',0]
    assert graph['130']['inputs']['fps']==24 and graph['pick_last']['inputs']['batch_index']==276


def test_current_external_revocation_stops_dispatch_but_keeps_original_id_collection(tmp_path,service,monkeypatch):
    asset,run,config=setup(tmp_path,service,shots=1,enabled=True);endpoint_config(asset,tmp_path,config,monkeypatch)
    h.prepare_from_ready(asset,run,config);h.submit_next(run);assert len(service.posts)==1
    before=h.read(run/'shots'/'shot1'/'STATE.json')['prompt_id']
    Path(config['source_endpoint_certificate']['path']).write_bytes(b'changed')
    h._load(run,current=False)
    with pytest.raises(ValueError):h._load(run,current=True)
    service.complete();h.poll_collect(run)
    state=h.read(run/'shots'/'shot1'/'STATE.json');result=h.read(run/'shots'/'shot1'/'RESULT.json')
    assert state['status']=='technical_saved' and result['prompt_id']==before and len(service.posts)==1
    assert result['keyframe_conditioning']['source_same_frame_conditioning'] is True
    assert result['production_approved'] is False and result['content_status']=='media_review_required'
    proof=result['keyframe_conditioning'];proof['last_frame_sha256']='0'*64;h.write(run/'shots'/'shot1'/'RESULT.json',result)
    with pytest.raises(h.HandoffIntegrityError):h._verify_result(run/'shots'/'shot1',h.read(run/'PLAN.json'),h.read(run/'PLAN.json')['shots'][0],state)
