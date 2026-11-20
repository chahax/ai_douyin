from types import SimpleNamespace
import pytest
from scripts import run_screenplay_trial as trial


def test_shortened_execution_needs_reviewed_duration(tmp_path):
    review = tmp_path / 'review.json'
    trial.write(review, {'execution_duration_seconds': 7, 'duration_rationale': 'Reduce measured pauses'})
    plan = {'execution_duration_seconds': 7, 'bindings': {'trial_review': {'path': str(review)}}}
    assert trial.execution_duration(plan, {'duration_seconds': 10}) == 7
    plan['execution_duration_seconds'] = 6
    with pytest.raises(ValueError, match='reviewed timing'):
        trial.execution_duration(plan, {'duration_seconds': 10})
    plan['execution_duration_seconds'] = 7
    with pytest.raises(ValueError, match='reviewed timing'):
        trial.execution_duration(plan, {'duration_seconds': 5})


def setup(tmp_path,monkeypatch):
    payload={'content':[{'type':'text','text':'prompt'}],'duration':5}
    manifest={'trial_schema':'reviewed_screenplay_first_shot/v1','allowed_shots':['S01'],
              'campaign_path':'fixture','api_model':'model','api_base_url':'https://example.org','script_sha256':''}
    trial.write(tmp_path/'trial_plan.json',{})
    trial.write(tmp_path/'request.preview.json',payload)
    trial.write(tmp_path/'locked_script.json',{})
    manifest.update(trial_plan_sha256=trial.sha(tmp_path/'trial_plan.json'),
                    request_sha256=trial.sha(tmp_path/'request.preview.json'),script_sha256=trial.sha(tmp_path/'locked_script.json'))
    trial.write(tmp_path/'production.json',manifest)
    monkeypatch.setattr(trial,'verify_inputs',lambda _:({'version':{'shots':[{'duration_seconds':5}]}},{},'prompt'))
    monkeypatch.setattr(trial.campaign,'reserve',lambda *args:None)
    return payload


def test_unknown_submit_is_durable_and_cannot_spend_twice(tmp_path,monkeypatch):
    payload=setup(tmp_path,monkeypatch);calls=[]
    def create(_):
        assert (tmp_path/'S01.json').exists()
        calls.append(1)
        raise TimeoutError('unknown response')
    client=SimpleNamespace(config=SimpleNamespace(model='model',base_url='https://example.org'),
                           build_task_payload=lambda *a,**k:payload,create_task=create)
    with pytest.raises(TimeoutError):trial.submit(tmp_path,client)
    assert trial.read(tmp_path/'S01.json')['status']=='submission_unknown'
    with pytest.raises(ValueError,match='Existing receipt'):trial.submit(tmp_path,client)
    assert len(calls)==1


def test_modified_payload_blocks_before_network(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch)
    trial.write(tmp_path/'request.preview.json',{'duration':15})
    with pytest.raises(ValueError,match='changed'):trial.submit(tmp_path,None)


def predecessor(tmp_path,monkeypatch):
    import time
    monkeypatch.setattr(trial,'ROOT',tmp_path)
    folder=tmp_path/'data/video_generation/first';folder.mkdir(parents=True)
    video=folder/'S01.mp4';video.write_bytes(b'original video')
    tail=folder/'S01.last_frame.png';tail.write_bytes(b'original tail')
    review=folder/'review.json';trial.write(review,{'decision':'passed','checks':{k:True for k in trial.REVIEW_CHECKS}})
    campaign=folder.parent/'campaign.json'
    trial.write(campaign,{'current_series_id':'series_001','shots':['S01','S02'],
       'series':[{'id':'series_001','runs':[str(folder)]}],
       'attempts':[{'id':'attempt_001','status':'passed','shot':'S01','series_id':'series_001',
                    'review_path':str(review),'review_sha256':trial.sha(review)}]})
    trial.write(folder/'production.json',{'campaign_path':str(campaign),'campaign_series_id':'series_001'})
    trial.write(folder/'S01.json',{'campaign_attempt_id':'attempt_001','status':'downloaded','script_sha256':'story',
       'local_video':str(video),'video_sha256':trial.sha(video),'last_frame':str(tail),'last_frame_sha256':trial.sha(tail),
       'submit_id':'native-task','latest_response':{'status':'succeeded','created_at':int(time.time()),
          'content':{'last_frame_url':'https://example.org/original-tail'}}})
    return folder,campaign,{'shot_id':'S02','previous_run':str(folder),'bindings':{'story':{'sha256':'story'}}}


def test_continuation_uses_only_approved_original_tail(tmp_path,monkeypatch):
    folder,campaign,plan=predecessor(tmp_path,monkeypatch)
    refs,binding=trial.preceding_reference(plan)
    assert refs[0].role=='first_frame' and refs[0].source=='https://example.org/original-tail'
    assert binding['first_frame_sha256']==trial.sha(folder/'S01.last_frame.png')
    (folder/'S01.last_frame.png').write_bytes(b'changed')
    with pytest.raises(ValueError,match='approved original tail'):trial.preceding_reference(plan)


def test_pending_predecessor_cannot_release_continuation(tmp_path,monkeypatch):
    _,campaign,plan=predecessor(tmp_path,monkeypatch)
    data=trial.read(campaign);data['attempts'][0]['status']='awaiting_review';trial.write(campaign,data)
    with pytest.raises(ValueError,match='approved original tail'):trial.preceding_reference(plan)
