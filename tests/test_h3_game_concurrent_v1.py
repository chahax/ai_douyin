"""Three scoped guards for the independent single hardware-load test."""
import copy
from pathlib import Path

import pytest

from src.content_factory import h3_game_concurrent_v1 as trial


def test_exact_graph_delta_preserves_native_audio_and_fixed_fixture():
    auth,source,prior=trial.admission()
    before=trial.sha(auth['source_bindings']['source_graph']['path']);original=copy.deepcopy(source)
    prompt=Path(auth['source_bindings']['prompt']['path']).read_text(encoding='utf-8')
    params=dict(prompt=prompt,first_frame_input='h3_game_concurrent_20261018/opening_frame.png',
                noise_seed=202610182135,output_prefix=trial.PREFIX)
    graph=trial.compile_graph(source,trial.recipe(),params)
    restored=copy.deepcopy(graph)
    for node,key in [('condition','prompt'),('ref_scene','image'),('129','noise_seed')]+[
            ('save_'+role,'filename_prefix') for role in ('video','audio','first','last')]:
        restored[node]['inputs'][key]=source[node]['inputs'][key]
    assert restored==original==source and trial.sha(auth['source_bindings']['source_graph']['path'])==before==trial.SOURCE_SHA
    assert len(graph)==20 and graph['130']['inputs']['audio']==['121',0]
    assert graph['condition']['inputs']['prompt']==prompt and prior['prompt_id']==trial.SOURCE_TASK_ID
    assert auth['story_segment'] is False and trial.failure_count(auth,trial.OUT)==3
    with pytest.raises(ValueError):trial.compile_graph(source,trial.recipe(),dict(params,first_frame_input='S04/native_last.png'))


def test_single_post_claim_and_original_id_recovery(tmp_path,monkeypatch):
    monkeypatch.setattr(trial,'GLOBAL_CLAIM',tmp_path/'global.json')
    server=tmp_path/'server.log';server.write_bytes(b'previous | 12/12 [08:24<00:00]\n')
    monkeypatch.setattr(trial,'SERVER_LOG',server)
    for name in ('AUTHORIZATION.json','PRIMARY_TRIAL_REVIEW.json','workflow_api.json','SOURCE_RECIPE.json','PARAMETERS.json'):
        trial.durable(tmp_path/name,{})
    prepared=dict(authorization=trial.binding(tmp_path/'AUTHORIZATION.json'),sources={},first_frame={},game_identity={},
                  graph=trial.binding(tmp_path/'workflow_api.json'),source_recipe=trial.binding(tmp_path/'SOURCE_RECIPE.json'),
                  parameters=trial.binding(tmp_path/'PARAMETERS.json'))
    trial.durable(tmp_path/'PREPARED.json',prepared)
    monkeypatch.setattr(trial,'admission',lambda out:({},{},{}));monkeypatch.setattr(trial,'review_gate',lambda out:prepared)
    monkeypatch.setattr(trial.s01.speed,'check_service',lambda *args:None)
    monkeypatch.setattr(trial,'require_game',lambda *args:None);monkeypatch.setattr(trial,'compile_graph',lambda *args:{})
    class Client:
        posts=0
        def post_graph(self,request):
            assert trial.GLOBAL_CLAIM.exists() and (tmp_path/'SUBMISSION_CLAIM.json').exists()
            self.posts+=1;return dict(prompt_id='hardware-original',node_errors={})
        def get(self,path):
            assert path=='/history/hardware-original';return {}
    client=Client();row=trial.submit_once(client,tmp_path)
    assert row['prompt_id']=='hardware-original' and row['media_submissions']==1
    assert row['story_segment'] is False
    with pytest.raises(ValueError,match='no repeated POST'):trial.submit_once(client,tmp_path)
    (tmp_path/'receipt.json').unlink()
    assert trial.collect(client,tmp_path)['prompt_id']=='hardware-original'
    assert trial.status(client,tmp_path)['media_submissions']==1 and client.posts==1
    (tmp_path/'SUBMISSION_RESPONSE.json').unlink()
    with pytest.raises(trial.UnresolvedClaimError):trial.submit_once(client,tmp_path)
    assert trial.status(client,tmp_path)['media_submissions'] is None and client.posts==1


def test_game_absent_blocks_dispatch_and_telemetry_unknown_is_not_zero(tmp_path,monkeypatch):
    monkeypatch.setattr(trial,'GLOBAL_CLAIM',tmp_path/'global.json')
    monkeypatch.setattr(trial,'admission',lambda out:({'game':dict(pid=37860,name='VampireSurvivors.exe')},{},{}))
    monkeypatch.setattr(trial,'review_gate',lambda out:dict(game_identity={}))
    monkeypatch.setattr(trial.s01.speed,'check_service',lambda *args:None)
    def absent(pid):raise trial.psutil.NoSuchProcess(pid)
    monkeypatch.setattr(trial.psutil,'Process',absent)
    class Client:
        def post_graph(self,request):pytest.fail('absent game must never dispatch')
    with pytest.raises(ValueError,match='game is not running'):trial.submit_once(Client(),tmp_path)
    assert not (tmp_path/'SUBMISSION_CLAIM.json').exists() and not trial.GLOBAL_CLAIM.exists()
    def unavailable(*args,**kwargs):raise TimeoutError('sample unavailable')
    monkeypatch.setattr(trial.subprocess,'run',unavailable);monkeypatch.setattr(trial,'windows_commit',unavailable)
    telemetry=trial.Telemetry(tmp_path,dict(pid=37860,name='VampireSurvivors.exe',create_time=1))
    monkeypatch.setattr(trial.psutil,'cpu_percent',lambda interval=None:0.0)
    monkeypatch.setattr(trial.threading,'get_ident',lambda:101)
    row=telemetry.sample('offline')
    assert row['gpu'] is None and row['system']['commit_bytes'] is None
    assert row['system']['cpu_percent'] is None and row['system']['cpu_sample_window_seconds'] is None
    assert row['game']['running'] is False and row['game']['rss_bytes'] is None
    monkeypatch.setattr(trial.threading,'get_ident',lambda:202)
    worker_first=telemetry.sample('worker_first')
    assert worker_first['system']['cpu_percent'] is None
    summary=trial.summarize_telemetry(tmp_path)
    assert summary['gpu_memory_used_peak_mib'] is None and summary['game_running_all_samples'] is False
    assert summary['system_cpu_peak_percent'] is None
    assert summary['game_fps'] is None and summary['samples_with_errors']==2
