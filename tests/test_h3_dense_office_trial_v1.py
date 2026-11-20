"""First-frame-only graph identity and durable one-video submission guards."""
import copy

import pytest

from src.content_factory import h3_dense_office_trial_v1 as trial


def test_fl2va_first_frame_graph_exactly_twenty_nodes():
    source=trial.read(trial.speed.OUT/'workflow_api.json');original=copy.deepcopy(source)
    before=trial.sha(trial.speed.OUT/'workflow_api.json')
    parameters=dict(prompt='offline exact authored dialogue',opening_frame_input='h3_dense_office_trial_20261018/opening_frame.png',
                    noise_seed=202610181751,output_prefix=trial.PREFIX)
    graph=trial.compile_graph(source,trial.recipe(),parameters)
    assert len(graph)==20 and source==original and trial.sha(trial.speed.OUT/'workflow_api.json')==before==trial.SOURCE_SHA
    assert graph['condition']==dict(class_type='MiniMaxH3ImageToVideo',inputs=dict(clip=['128',0],vae=['119',0],
                                  prompt=parameters['prompt'],width=768,height=416,length=362,first_frame=['ref_scene',0]))
    assert graph['127']['inputs']['unet_name']==trial.MODEL
    assert 'ref_C01' not in graph and 'ref_C02' not in graph
    assert sum(node['class_type']=='LoadImage' for node in graph.values())==1
    assert not any(node['class_type'] in ('LoadAudio','MiniMaxH3AddGuide') or 'lora' in node['class_type'].lower() for node in graph.values())
    assert graph['130']['inputs']['audio']==['121',0] and graph['124']['inputs']['steps']==12
    assert graph['condition']['inputs'].keys()=={'clip','vae','prompt','width','height','length','first_frame'}
    normalized=copy.deepcopy(graph)
    for node in ('condition','127','129','ref_scene','save_video','save_audio','save_first','save_last'):normalized[node]=original[node]
    for node in ('ref_C01','ref_C02'):normalized[node]=original[node]
    assert normalized==original
    bad=dict(parameters,opening_frame_input='old/rejected/native_last.png')
    with pytest.raises(ValueError):trial.compile_graph(source,trial.recipe(),bad)


def test_unknown_claim_stops_original_id_recovers_and_failed_stops(tmp_path,monkeypatch):
    global_claim=tmp_path/'global.json';monkeypatch.setattr(trial,'GLOBAL_CLAIM',global_claim)
    trial.durable(global_claim,{'unknown':True})
    with pytest.raises(ValueError,match='unknown request'):trial.state(tmp_path)
    trial.durable(tmp_path/'SUBMISSION_RESPONSE.json',{'prompt_id':'original-office-id'})
    assert trial.state(tmp_path)==('query',{'prompt_id':'original-office-id','technical_status':'pending'})
    trial.durable(tmp_path/'receipt.json',{'prompt_id':'original-office-id','technical_status':'failed'})
    with pytest.raises(ValueError,match='known service failure'):trial.state(tmp_path)


def test_submit_persists_id_once_and_before_wait(tmp_path,monkeypatch):
    global_claim=tmp_path/'global.json';monkeypatch.setattr(trial,'GLOBAL_CLAIM',global_claim)
    for name,value in [('AUTHORIZATION.json',{}),('PRIMARY_TRIAL_REVIEW.json',{}),('workflow_api.json',{}),('SOURCE_RECIPE.json',{}),('PARAMETERS.json',{})]:
        trial.durable(tmp_path/name,value)
    prepared=dict(authorization=trial.binding(tmp_path/'AUTHORIZATION.json'),graph=trial.binding(tmp_path/'workflow_api.json'),
                  sources={},opening_image={'path':'offline','sha256':'offline'},source_recipe=trial.binding(tmp_path/'SOURCE_RECIPE.json'),
                  parameters=trial.binding(tmp_path/'PARAMETERS.json'))
    trial.durable(tmp_path/'PREPARED.json',prepared)
    monkeypatch.setattr(trial,'admission',lambda out:({},{}));monkeypatch.setattr(trial,'review_gate',lambda out:prepared)
    monkeypatch.setattr(trial,'opening_binding',lambda *args:None);monkeypatch.setattr(trial.speed,'check_service',lambda *args:None)
    monkeypatch.setattr(trial,'compile_graph',lambda *args:{})
    class Client:
        def __init__(self):self.posts=0
        def post_graph(self,request):
            assert global_claim.exists() and (tmp_path/'SUBMISSION_CLAIM.json').exists()
            self.posts+=1;return {'prompt_id':'original-office-id','node_errors':{}}
    client=Client();record=trial.submit_once(client,tmp_path)
    assert client.posts==1 and record['prompt_id']=='original-office-id'
    assert trial.read(tmp_path/'job_ids.json')=={'S01':'original-office-id'}
    assert trial.read(tmp_path/'receipt.json')['technical_status']=='pending'
    with pytest.raises(ValueError,match='no repeated POST'):trial.submit_once(client,tmp_path)
    assert client.posts==1


def test_pending_collect_and_service_error_never_post(tmp_path,monkeypatch):
    monkeypatch.setattr(trial,'GLOBAL_CLAIM',tmp_path/'global.json')
    trial.durable(tmp_path/'receipt.json',{'prompt_id':'original-office-id','technical_status':'pending'})
    class Client:
        def get(self,path):assert path=='/history/original-office-id';return {}
        def post_graph(self,request):pytest.fail('original-ID collect cannot POST')
    assert trial.collect(Client(),tmp_path)['technical_status']=='pending'
    trial.durable(tmp_path/'workflow_api.json',{})
    trial.durable(tmp_path/'SUBMISSION_CLAIM.json',{'at':trial.now()})
    trial.durable(tmp_path/'PREPARED.json',dict(graph=trial.binding(tmp_path/'workflow_api.json'),authorization={},sources={},opening_image={}))
    monkeypatch.setattr(trial.h,'history_graph_identity',lambda *args:{'graph_identity_verified':True})
    class Failed(Client):
        def get(self,path):return {'original-office-id':{'status':{'status_str':'error','completed':False}}}
    with pytest.raises(ValueError,match='known service failure'):trial.collect(Failed(),tmp_path)
    assert trial.read(tmp_path/'receipt.json')['technical_status']=='failed'
    assert trial.read(tmp_path/'MEDIA_EVENTS.json')['events'][-1]['failure'] is True
