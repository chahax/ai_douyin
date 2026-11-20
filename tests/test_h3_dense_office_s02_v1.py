"""Exact S02 graph delta, original tail admission and one-POST/offset recovery."""
import copy
from pathlib import Path

import pytest

from src.content_factory import h3_dense_office_s02_v1 as trial


def test_source_graph_changes_only_prompt_tail_seed_prefix():
    source=trial.read(trial.s01.OUT/'workflow_api.json');original=copy.deepcopy(source)
    before=trial.sha(trial.s01.OUT/'workflow_api.json')
    parameters=dict(prompt='offline dialogue',first_frame_input='h3_dense_office_s02_20261018/S01_native_last.png',noise_seed=202610181821,output_prefix=trial.PREFIX)
    graph=trial.compile_graph(source,trial.recipe(),parameters)
    normalized=copy.deepcopy(graph)
    for node,key in [('condition','prompt'),('ref_scene','image'),('129','noise_seed')]+[('save_'+role,'filename_prefix') for role in ('video','audio','first','last')]:
        normalized[node]['inputs'][key]=source[node]['inputs'][key]
    assert normalized==original and source==original and trial.sha(trial.s01.OUT/'workflow_api.json')==before==trial.SOURCE_SHA
    assert len(graph)==20 and graph['condition']['inputs']['first_frame']==['ref_scene',0]
    assert graph['130']['inputs']['audio']==['121',0] and graph['124']['inputs']['steps']==12
    with pytest.raises(ValueError):trial.compile_graph(source,trial.recipe(),dict(parameters,first_frame_input='another/frame.png'))


def test_real_predecessor_tail_and_continuation_binding(tmp_path,monkeypatch):
    auth,_,prior=trial.admission()
    assert prior['prompt_id']==trial.PREDECESSOR_ID and auth['first_frame']['sha256']==trial.TAIL_SHA
    changed=copy.deepcopy(auth);changed['first_frame']['sha256']='changed'
    trial.durable(tmp_path/'AUTHORIZATION.json',changed)
    with pytest.raises(ValueError):trial.admission(tmp_path)
    actual_read=trial.read;acceptance_path=Path(auth['source_bindings']['continuation']['path']).resolve()
    def read_without_acceptance(path):
        value=actual_read(path)
        if Path(path).resolve()==acceptance_path:value=dict(value,human_approved_for_continuation=False)
        return value
    monkeypatch.setattr(trial,'read',read_without_acceptance)
    with pytest.raises(ValueError,match='explicit continuation'):trial.admission()


def test_unknown_claim_status_and_known_id_only_get(tmp_path,monkeypatch):
    global_claim=tmp_path/'global.json';monkeypatch.setattr(trial,'GLOBAL_CLAIM',global_claim)
    trial.durable(global_claim,{'unknown':True})
    class Client:
        def get(self,path):assert path=='/history/original-s02';return {}
        def post_graph(self,request):pytest.fail('status/collect cannot dispatch')
    assert trial.status(Client(),tmp_path)['media_submissions'] is None
    with pytest.raises(trial.UnresolvedClaimError):trial.state(tmp_path)
    trial.durable(tmp_path/'SUBMISSION_RESPONSE.json',{'prompt_id':'original-s02'})
    assert trial.status(Client(),tmp_path)['media_submissions']==1
    assert trial.collect(Client(),tmp_path)['media_submissions']==1
    trial.durable(tmp_path/'receipt.json',dict(prompt_id='original-s02',technical_status='failed'))
    with pytest.raises(ValueError,match='known S02 service failure'):trial.state(tmp_path)
    assert trial.status(Client(),tmp_path)['media_submissions']==1


def test_one_post_saves_id_and_sampling_excludes_previous_run(tmp_path,monkeypatch):
    monkeypatch.setattr(trial,'GLOBAL_CLAIM',tmp_path/'global.json')
    server_log=tmp_path/'server.log';server_log.write_bytes(b'old | 12/12 [13:27<00:00]\nPrompt executed\n')
    monkeypatch.setattr(trial,'SERVER_LOG',server_log)
    for name in ('AUTHORIZATION.json','PRIMARY_TRIAL_REVIEW.json','workflow_api.json','SOURCE_RECIPE.json','PARAMETERS.json'):
        trial.durable(tmp_path/name,{})
    prepared=dict(authorization=trial.binding(tmp_path/'AUTHORIZATION.json'),sources={},first_frame={},graph=trial.binding(tmp_path/'workflow_api.json'),
                  source_recipe=trial.binding(tmp_path/'SOURCE_RECIPE.json'),parameters=trial.binding(tmp_path/'PARAMETERS.json'))
    trial.durable(tmp_path/'PREPARED.json',prepared)
    prior=dict(graph={},files={'last':{'path':'offline'}})
    monkeypatch.setattr(trial,'admission',lambda out:({},{},prior));monkeypatch.setattr(trial,'review_gate',lambda out:prepared)
    monkeypatch.setattr(trial.s01.speed,'check_service',lambda *a:None);monkeypatch.setattr(trial.h,'check_predecessor',lambda *a:{})
    monkeypatch.setattr(trial,'compile_graph',lambda *a:{})
    class Client:
        def __init__(self):self.posts=0
        def post_graph(self,request):
            assert (tmp_path/'SUBMISSION_CLAIM.json').exists() and trial.GLOBAL_CLAIM.exists()
            self.posts+=1
            with server_log.open('ab') as handle:handle.write(b'new | 1/12 [01:10<00:00]\nnew | 2/12 [02:00<00:00]\n')
            return {'prompt_id':'original-s02','node_errors':{}}
    client=Client();row=trial.submit_once(client,tmp_path)
    assert row['prompt_id']=='original-s02' and row['media_submissions']==1
    assert trial.read(tmp_path/'job_ids.json')=={'S02':'original-s02'}
    with pytest.raises(ValueError,match='no repeated POST'):trial.submit_once(client,tmp_path)
    assert client.posts==1
    observations=trial.sampling_observations(tmp_path)
    assert [entry['step'] for entry in observations['observations']]==[1,2]
    assert observations['observations'][-1]['adjacent_step_delta_seconds']==50
    assert observations['sampling_total_seconds'] is None
