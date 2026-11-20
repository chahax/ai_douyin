from copy import deepcopy
from pathlib import Path
import pytest
from scripts import run_six_children_minute_20261102 as r

def prepared(tmp_path,monkeypatch):
    run=tmp_path/'minute';(run/'assets').mkdir(parents=True);(run/'segments').mkdir();(run/'deliverables').mkdir()
    opening=run/'assets/opening.original.jpeg';opening.write_bytes(b'\xff\xd8original opening fixture')
    request=run/'assets/request.json';r.durable(request,{'model':'doubao-seedream-5-0-pro-260628','prompt':'fictional text only'})
    receipt=run/'assets/receipt.json';r.durable(receipt,dict(status='downloaded',model='doubao-seedream-5-0-pro-260628',reference_image=None,request_sha256=r.sha(request),image=str(opening),image_sha256=r.sha(opening)))
    r.durable(run/'assets/PROVENANCE.json',dict(receipt=r.binding(receipt)))
    source=tmp_path/'source.md';source.write_text('source screenplay',encoding='utf-8');monkeypatch.setattr(r,'SOURCE',source)
    r.prepare(run);return run

class Fake:
    def __init__(self):self.posts=[];self.queries=[]
    def build_task_payload(self,prompt,**kwargs):
        return dict(prompt=prompt,duration=kwargs['duration'],reference=kwargs['references'][0].to_content())
    def create_task(self,payload):self.posts.append(deepcopy(payload));return dict(id='task-'+str(len(self.posts)))
    def get_task(self,task_id):self.queries.append(task_id);return dict(id=task_id,status='succeeded')
    def download_video(self,task,path):path.write_bytes(('video '+task['id']).encode())
    def download_last_frame(self,task,path):path.write_bytes(b'\xff\xd8'+task['id'].encode())

def test_four_shots_use_original_tails_and_no_resubmit(tmp_path,monkeypatch):
    run=prepared(tmp_path,monkeypatch);client=Fake()
    r.execute(run,client=client,probe=lambda p:{'streams':[]},sleep=lambda n:None)
    assert len(client.posts)==4 and all(x['duration']==15 for x in client.posts)
    for i in range(1,4):
        previous=run/'segments'/f'S{i:02}'/'last_frame.original'
        assert client.posts[i]['reference']['image_url']['url']==r.image_uri(previous)
        assert client.posts[i]['reference']['role']=='first_frame'
    r.execute(run,client=client,probe=lambda p:{},sleep=lambda n:None)
    assert len(client.posts)==4
    s=r.read(run/'STATE.json');assert s['video_posts']==4 and s['content_status']=='awaiting_human_review'

def test_unknown_submission_is_not_replayed(tmp_path,monkeypatch):
    run=prepared(tmp_path,monkeypatch)
    class Unknown(Fake):
        def create_task(self,payload):self.posts.append(payload);raise TimeoutError('submit unknown')
    client=Unknown()
    with pytest.raises(TimeoutError):r.execute(run,client=client)
    with pytest.raises(ValueError,match='not_resubmitted'):r.execute(run,client=client)
    assert len(client.posts)==1 and r.read(run/'STATE.json')['video_posts']==1

def test_frozen_reference_change_stops_before_api(tmp_path,monkeypatch):
    run=prepared(tmp_path,monkeypatch);client=Fake();(run/'assets/opening.original.jpeg').write_bytes(b'changed')
    with pytest.raises(ValueError,match='frozen_input'):r.execute(run,client=client)
    assert not client.posts

def test_known_provider_rejection_is_preserved(tmp_path,monkeypatch):
    from src.content_factory.seedance_client import SeedanceAPIError
    run=prepared(tmp_path,monkeypatch)
    class Reject(Fake):
        def create_task(self,payload):self.posts.append(payload);raise SeedanceAPIError('rejected',status_code=400)
    client=Reject()
    with pytest.raises(SeedanceAPIError):r.execute(run,client=client)
    assert r.read(run/'STATE.json')['segments']['S01']['status']=='request_rejected'
    with pytest.raises(ValueError,match='not_resubmitted'):r.execute(run,client=client)
    assert len(client.posts)==1

def test_native_asset_provenance_required(tmp_path,monkeypatch):
    run=prepared(tmp_path,monkeypatch);client=Fake()
    receipt=run/'assets/receipt.json';data=r.read(receipt);data['reference_image']='external.png';r.durable(receipt,data)
    r.durable(run/'assets/PROVENANCE.json',dict(receipt=r.binding(receipt)))
    plan=r.read(run/'PLAN.json');plan['asset_provenance']=r.binding(run/'assets/PROVENANCE.json');r.durable(run/'PLAN.json',plan)
    with pytest.raises(ValueError,match='native_text_to_image'):r.execute(run,client=client)
    assert not client.posts
