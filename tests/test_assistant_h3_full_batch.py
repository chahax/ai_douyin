"""Necessary native wiring, identity and durable recovery checks; no API/model calls."""
import copy
import pytest
from src.content_factory import assistant_h3_full_batch as batch


def test_compiler_native_guide_audio_and_fixed_baseline():
    plan=batch.read(batch.OUT/'BATCH_PLAN.json')
    baseline=batch.read(batch.bound(plan['baseline_graph']))
    frozen=copy.deepcopy(baseline)
    recipe=batch.read(batch.OUT/'runtime/SOURCE_RECIPE.json')
    parameters=dict(prompt='offline exact dialogue',noise_seed=2026101602,native_tail_input='S02/previous_native.png',
                    reference_audio_input='shared/S01_reference_audio.flac',output_prefix='batch/S02')
    graph=batch.compile_graph(baseline,recipe,parameters)
    assert baseline==frozen
    assert graph['126']['inputs']['conditioning']==['continuation_native_guide',0]
    assert graph['125']['inputs']['latent_image']==['condition',1]
    guide=graph['continuation_native_guide']['inputs']
    assert guide==dict(positive=['condition',0],latent=['condition',1],vae=['119',0],image=['continuation_native_tail',0],frame_idx=0)
    assert 'audio' not in guide
    assert graph['condition']['inputs']['ref_audios.ref_audio_0']==['s01_reference_audio',0]
    assert graph['condition']['inputs']['audio_vae']==['120',0]
    assert graph['124']['inputs']['steps']==20 and graph['130']['inputs']['fps']==24
    assert graph['save_video']['inputs']['filename_prefix']=='batch/S02/video'
    batch.check_schema(graph,batch.read(batch.OUT/'NODE_SCHEMA.json'))
    bad=copy.deepcopy(baseline);bad['condition']['inputs']['width']=640
    with pytest.raises(ValueError):batch.compile_graph(bad,recipe,parameters)


def test_history_only_known_numeric_coercions():
    plan=batch.read(batch.OUT/'BATCH_PLAN.json');graph=batch.read(batch.bound(plan['baseline_graph']))
    entry=copy.deepcopy(batch.read(batch.bound(plan['existing_segment']['history']))[batch.S01_ID])
    assert batch.history_graph_identity(graph,entry,batch.S01_ID)['graph_identity_verified']
    entry['prompt'][2]['129']['inputs']['noise_seed']+=1
    with pytest.raises(ValueError):batch.history_graph_identity(graph,entry,batch.S01_ID)
    with pytest.raises(ValueError):batch.history_graph_identity(graph,entry,'another-id')


def test_unknown_claim_never_becomes_new_post(tmp_path):
    batch.durable(tmp_path/'SUBMISSION_CLAIM.json',{'at':'offline'})
    with pytest.raises(ValueError,match='unknown request'):
        batch.state_action(tmp_path)
    batch.durable(tmp_path/'SUBMISSION_RESPONSE.json',{'prompt_id':'original-known-id'})
    action,row=batch.state_action(tmp_path)
    assert action=='query' and row['prompt_id']=='original-known-id'


def test_pending_saved_and_known_failure_recovery(tmp_path):
    path=tmp_path/'receipt.json'
    batch.durable(path,dict(prompt_id='original-id',technical_status='pending'))
    assert batch.state_action(tmp_path)==('query',dict(prompt_id='original-id',technical_status='pending'))
    batch.durable(path,dict(prompt_id='original-id',technical_status='succeeded'))
    assert batch.state_action(tmp_path)[0]=='saved'
    batch.durable(path,dict(prompt_id='original-id',technical_status='failed'))
    with pytest.raises(ValueError,match='known service failure'):batch.state_action(tmp_path)


def test_failure_history_unknown_and_limit_rejected(tmp_path):
    plan=batch.read(batch.OUT/'BATCH_PLAN.json')
    assert batch.failure_count(plan,tmp_path)==1
    batch.durable(tmp_path/'MEDIA_EVENTS.json',{'events':[{'failure':True}]*9})
    with pytest.raises(ValueError,match='exhausted'):batch.failure_count(plan,tmp_path)
    batch.durable(tmp_path/'MEDIA_EVENTS.json',{'events':[{'failure':None}]})
    with pytest.raises(ValueError,match='unknown current'):batch.failure_count(plan,tmp_path)


def test_submit_acceptance_persists_original_id_before_wait(tmp_path,monkeypatch):
    sid='S02';directory=tmp_path/'segments'/sid;directory.mkdir(parents=True)
    global_root=tmp_path/'story';global_root.mkdir()
    batch.durable(directory/'workflow_api.json',{'offline':'graph'})
    plan=dict(global_claim_root=str(global_root))
    segment=dict(segment_id=sid)
    tail=tmp_path/'tail.png';tail.write_bytes(b'offline-native-original')
    preview=dict(segment_id=sid,graph=batch.binding(directory/'workflow_api.json'),predecessor={'segment_id':'S01'},first_frame=batch.binding(tail))
    calls=[]
    class Client:
        def get(self,path):
            assert path=='/queue';return {'queue_running':[],'queue_pending':[]}
        def post_graph(self,request):
            assert (directory/'SUBMISSION_CLAIM.json').exists()
            assert (global_root/'H3_FULL_PERMANENT_CLAIMS_20261016/S02.json').exists()
            calls.append(request);return {'prompt_id':'original-h3-id','node_errors':{}}
    monkeypatch.setattr(batch,'failure_count',lambda *a:1)
    monkeypatch.setattr(batch,'review_gate',lambda *a:None)
    monkeypatch.setattr(batch,'check_predecessor',lambda *a:{'original':True})
    monkeypatch.setattr(batch,'native_validate',lambda *a:None)
    batch.durable(tmp_path/'BATCH_PLAN.json',plan)
    record=batch.submit_once(plan,segment,{'offline':'graph'},preview,{},Client(),tmp_path)
    assert record['prompt_id']=='original-h3-id' and record['segment_id']==sid
    assert batch.read(directory/'receipt.json')['prompt_id']=='original-h3-id'
    assert batch.read(tmp_path/'job_ids.json')=={'S02':'original-h3-id'}
    assert len(calls)==1 and batch.state_action(directory)[0]=='query'
    with pytest.raises(ValueError,match='durable submission state'):
        batch.submit_once(plan,segment,{},preview,{},Client(),tmp_path)
    assert len(calls)==1


def test_stop_arriving_during_native_validation_prevents_post(tmp_path,monkeypatch):
    directory=tmp_path/'segments/S02';directory.mkdir(parents=True)
    batch.durable(directory/'workflow_api.json',{})
    batch.durable(tmp_path/'BATCH_PLAN.json',{})
    plan=dict(global_claim_root=str(tmp_path/'global'))
    preview=dict(graph=batch.binding(directory/'workflow_api.json'),predecessor={},first_frame={})
    monkeypatch.setattr(batch,'failure_count',lambda *a:1)
    monkeypatch.setattr(batch,'review_gate',lambda *a:None)
    monkeypatch.setattr(batch,'check_predecessor',lambda *a:{})
    monkeypatch.setattr(batch,'native_validate',lambda *a:batch.durable(tmp_path/'STOP_REQUESTED.json',{'user':'stop'}))
    class Client:
        def get(self,path):return {}
        def post_graph(self,request):pytest.fail('stop must prevent POST')
    with pytest.raises(ValueError,match='after native validation'):
        batch.submit_once(plan,{'segment_id':'S02'},{},preview,{},Client(),tmp_path)
