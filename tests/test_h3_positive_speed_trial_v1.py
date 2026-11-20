"""The speed-only graph delta and durable one-POST recovery; no live service."""
import copy
import json
from types import SimpleNamespace

import pytest

from src.content_factory import h3_positive_speed_trial_v1 as trial


def test_exact_speed_delta_keeps_source_and_native_audio():
    source=json.loads((trial.SOURCE/'segments/S01/GRAPH_PREVIEW.json').read_bytes())
    original=copy.deepcopy(source);before=trial.sha(trial.SOURCE/'segments/S01/GRAPH_PREVIEW.json')
    parameters=dict(width=768,height=416,steps=12,noise_seed=202610181601,output_prefix=trial.PREFIX)
    graph=trial.compile_graph(source,trial.recipe(),parameters)
    normalized=copy.deepcopy(graph)
    for node,key in [('condition','width'),('condition','height'),('124','steps'),('129','noise_seed')]+[('save_'+role,'filename_prefix') for role in ('video','audio','first','last')]:
        normalized[node]['inputs'][key]=source[node]['inputs'][key]
    assert normalized==original and source==original
    assert before==trial.SOURCE_SHA==trial.sha(trial.SOURCE/'segments/S01/GRAPH_PREVIEW.json')
    assert len(graph)==22 and graph['130']['inputs']['audio']==['121',0]
    assert graph['condition']['inputs']['length']==362 and graph['130']['inputs']['fps']==24
    assert not any(row['class_type'] in ('LoadAudio','MiniMaxH3AddGuide') or 'lora' in row['class_type'].lower() for row in graph.values())
    bad=dict(parameters,steps=8)
    with pytest.raises(ValueError):trial.compile_graph(source,trial.recipe(),bad)


def test_unknown_claim_never_resubmits_but_original_id_recovers(tmp_path,monkeypatch):
    global_claim=tmp_path/'global.json';monkeypatch.setattr(trial,'GLOBAL_CLAIM',global_claim)
    trial.durable(global_claim,{'at':'unknown'})
    with pytest.raises(ValueError,match='unknown outcome'):trial.state(tmp_path)
    trial.durable(tmp_path/'SUBMISSION_RESPONSE.json',{'prompt_id':'original-id'})
    assert trial.state(tmp_path)==('query',dict(prompt_id='original-id',technical_status='pending'))
    trial.durable(tmp_path/'receipt.json',dict(prompt_id='original-id',technical_status='succeeded'))
    assert trial.state(tmp_path)[0]=='saved'
    trial.durable(tmp_path/'receipt.json',dict(prompt_id='original-id',technical_status='failed'))
    with pytest.raises(ValueError,match='known service failure'):trial.state(tmp_path)


def test_one_post_acceptance_persists_id_and_blocks_second(tmp_path,monkeypatch):
    global_claim=tmp_path/'global.json';monkeypatch.setattr(trial,'GLOBAL_CLAIM',global_claim)
    graph={'offline':'graph'}
    trial.durable(tmp_path/'workflow_api.json',graph)
    trial.durable(tmp_path/'SOURCE_RECIPE.json',{})
    trial.durable(tmp_path/'PARAMETERS.json',{})
    trial.durable(tmp_path/'AUTHORIZATION.json',{})
    trial.durable(tmp_path/'PRIMARY_TRIAL_REVIEW.json',{})
    prepared=dict(authorization=trial.binding(tmp_path/'AUTHORIZATION.json'),sources={},graph=trial.binding(tmp_path/'workflow_api.json'),
                  source_recipe=trial.binding(tmp_path/'SOURCE_RECIPE.json'),parameters=trial.binding(tmp_path/'PARAMETERS.json'))
    trial.durable(tmp_path/'PREPARED.json',prepared)
    monkeypatch.setattr(trial,'admission',lambda out:({},{}))
    monkeypatch.setattr(trial,'review_gate',lambda out:prepared)
    monkeypatch.setattr(trial,'check_service',lambda *args:None)
    monkeypatch.setattr(trial,'compile_graph',lambda *args:graph)
    class Client:
        def __init__(self):self.posts=0
        def post_graph(self,request):
            assert global_claim.exists() and (tmp_path/'SUBMISSION_CLAIM.json').exists()
            self.posts+=1;return {'prompt_id':'original-trial-id','node_errors':{}}
    client=Client();record=trial.submit_once(client,tmp_path)
    assert client.posts==1 and record['prompt_id']=='original-trial-id'
    assert trial.read(tmp_path/'job_ids.json')=={'S01':'original-trial-id'}
    assert trial.read(tmp_path/'receipt.json')['technical_status']=='pending'
    with pytest.raises(ValueError,match='never repeat POST'):trial.submit_once(client,tmp_path)
    assert client.posts==1


def test_collection_uses_original_id_without_post_and_validates_packets(tmp_path,monkeypatch):
    monkeypatch.setattr(trial,'GLOBAL_CLAIM',tmp_path/'global.json')
    trial.durable(tmp_path/'receipt.json',dict(prompt_id='original-id',technical_status='pending'))
    class Client:
        def get(self,path):assert path=='/history/original-id';return {}
        def post_graph(self,request):pytest.fail('collection must never POST')
    assert trial.collect(Client(),tmp_path)['technical_status']=='pending'
    metadata=dict(streams=[dict(codec_type='video',codec_name='h264',width=768,height=416,nb_frames='362',avg_frame_rate='24/1',nb_read_packets='362'),
                           dict(codec_type='audio',codec_name='aac',nb_read_packets='473')],format={'duration':str(362/24)})
    monkeypatch.setattr(trial,'environment',lambda:{})
    monkeypatch.setattr(trial.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=json.dumps(metadata)))
    assert trial.probe(tmp_path/'file.mp4')==metadata
    metadata['streams'][0]['width']=1280
    with pytest.raises(ValueError,match='resolution'):trial.probe(tmp_path/'file.mp4')
    # A completed service error is retained and cannot be dispatched again.
    trial.durable(tmp_path/'workflow_api.json',{})
    trial.durable(tmp_path/'PREPARED.json',dict(graph=trial.binding(tmp_path/'workflow_api.json'),authorization={},sources={}))
    trial.durable(tmp_path/'SUBMISSION_CLAIM.json',{'at':trial.now()})
    monkeypatch.setattr(trial.helpers,'history_graph_identity',lambda *args:{'graph_identity_verified':True})
    class FailedClient(Client):
        def get(self,path):return {'original-id':{'status':{'status_str':'error','completed':False}}}
    with pytest.raises(ValueError,match='known service failure'):trial.collect(FailedClient(),tmp_path)
    assert trial.read(tmp_path/'receipt.json')['technical_status']=='failed'
    assert trial.read(tmp_path/'MEDIA_EVENTS.json')['events'][-1]['failure'] is True
    with pytest.raises(ValueError,match='known service failure'):trial.state(tmp_path)
