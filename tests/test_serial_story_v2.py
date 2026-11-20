from copy import deepcopy
import json
from pathlib import Path
import pytest
from PIL import Image
from test_serial_story_v1 import Fake, make_run, source, bible, episode, script
from src.content_factory import serial_story_production_v2 as p
from src.content_factory import serial_story_contract_v1 as c
from src.content_factory import serial_story_assets_v2 as assets
from src.content_factory.corpus_screenplay_v1 import read, freeze, digest
from src.content_factory.serial_story_runtime_v2 import run_lock
from src.web.serial_story_panel_v2 import artifact


def prepare(tmp_path,n=2,batch=1):
    make_run(tmp_path,n)
    run=tmp_path/'v2'
    p.prepare(tmp_path/'manifest.json',run,user_statement='offline test only',episode_limit=batch)
    return run


def native_value(native):
    message=native['choices'][0]['message']
    return json.loads(message['tool_calls'][0]['function']['arguments'] if 'tool_calls' in message else message['content'])


def set_value(native,value):
    message=native['choices'][0]['message']; text=json.dumps(value,ensure_ascii=False)
    if 'tool_calls' in message: message['tool_calls'][0]['function']['arguments']=text
    else: message['content']=text
    return native


class RepairFake(Fake):
    def __init__(self,verdict='upheld'):
        super().__init__(); self.issued=False; self.verdict=verdict
    def call(self,role,messages,schema):
        payload=json.loads(messages[1]['content'])
        native=super().call(role,messages,schema)
        value=native_value(native)
        if 'review_sha256' in payload:
            value={'candidate_sha256':payload['candidate_sha256'],'review_sha256':payload['review_sha256'],
                   'findings':[{'index':i,'verdict':self.verdict,'reason':'fixture','source_ids':['CH1-P001']} for i in range(len(payload['review']['issues']))]}
        elif 'candidate' in payload and 'chapter_index' in payload['candidate'] and not self.issued:
            value.update(decision='revise',issues=[{'owner':'materials','path':'/claims/0/statement',
                         'reason':'fixture correction','source_ids':['CH1-P001']}]); self.issued=True
        elif 'chapter' in payload and 'required_corrections' in payload:
            value['claims'][0]['statement']='林岚向阿禾交接钥匙'
        return set_value(native,value)


def test_resume_next_episode_reuses_original_model_receipts(tmp_path):
    run=prepare(tmp_path); first=Fake()
    result=p.execute(run,fixture_client=first)
    assert result['error'] is None,result
    assert result['state']['status']=='ready_for_next_batch'
    old_calls=result['state']['calls_started']
    previous=artifact(run,'EPISODE_000_ACCEPTED.json')
    second=Fake(); result=p.execute(run,fixture_client=second,resume=True)
    assert result['error'] is None,result
    assert result['accepted_episodes']==2
    assert not any('chapter' in payload for _,payload in second.calls)
    assert not any('episode' in payload and payload['episode']['id']=='E1' and 'candidate' not in payload for _,payload in second.calls)
    assert result['state']['calls_started']==old_calls+len(second.calls)
    assert artifact(run,'EPISODE_001_ACCEPTED.json')['binding']['previous_state_sha256']==digest(previous['bound']['end_state'])


def test_upheld_semantic_issue_repairs_material_then_downstream(tmp_path):
    run=prepare(tmp_path); fake=RepairFake(); result=p.execute(run,fixture_client=fake)
    assert result['error'] is None,result
    checkpoint=read(run/'CHECKPOINT.json')
    assert checkpoint['generation']==1
    assert set(checkpoint['corrections'])=={'MATERIAL_0001'}
    assert artifact(run,'MATERIALS_BOUND.json')['materials'][0]['claims'][0]['statement']=='林岚向阿禾交接钥匙'
    assert len([1 for _,v in fake.calls if 'chapter' in v and v['chapter']['index']==1])==2


@pytest.mark.parametrize('verdict',['rejected','uncertain'])
def test_unsupported_review_does_not_modify_story(tmp_path,verdict):
    run=prepare(tmp_path); result=p.execute(run,fixture_client=RepairFake(verdict))
    assert result['error']
    assert read(run/'CHECKPOINT.json')['generation']==0
    assert not read(run/'CHECKPOINT.json')['corrections']


def test_cooperative_pause_and_resume(tmp_path):
    run=prepare(tmp_path); freeze(run/'PAUSE_REQUESTED.json',{'user_requested':True})
    fake=Fake(); result=p.execute(run,fixture_client=fake)
    assert result['state']['status']=='paused' and not fake.calls
    (run/'PAUSE_REQUESTED.json').unlink()
    result=p.execute(run,fixture_client=fake,resume=True)
    assert result['error'] is None,result


def test_unknown_request_never_resumed(tmp_path):
    run=prepare(tmp_path); result=p.execute(run,fixture_client=Fake('unknown'))
    assert result['state']['pending'] is not None
    with pytest.raises(ValueError,match='no_replay'): p.execute(run,fixture_client=Fake(),resume=True)


def test_double_launch_locked(tmp_path):
    run=prepare(tmp_path)
    with run_lock(run):
        with pytest.raises(ValueError,match='already_executing'): p.execute(run,fixture_client=Fake())


def test_cached_native_response_tamper_rejected(tmp_path):
    run=prepare(tmp_path); p.execute(run,fixture_client=Fake())
    path=run/'RESPONSE_001.json'; data=read(path); data['native']['id']='tampered'
    path.write_text(json.dumps(data),encoding='utf-8')
    fake=Fake(); result=p.execute(run,fixture_client=fake,resume=True)
    assert 'changed' in result['error']['reason'] and not fake.calls


def test_asset_versions_and_binding_are_book_scoped(tmp_path):
    picture=tmp_path/'reference.png'; Image.new('RGB',(8,8),'blue').save(picture)
    library=tmp_path/'library'; rows=[]
    for entity,kind in [('林岚','character'),('阿禾','character'),('厨房','place')]:
        rows.append(assets.register(library,picture,book_id='fixture',entity_id=entity,kind=kind,view='正面'))
    newer=assets.register(library,picture,book_id='fixture',entity_id='林岚',kind='character',view='正面')
    assert newer['asset_id']==rows[0]['asset_id'] and newer['version']==2
    ep=episode(1); bound=c.script_valid(script(ep),source(),bible(),ep)
    shots=c.split_shots(bound,15)
    binding=assets.bind(library,'fixture',bound,shots,rows)
    assert binding['shots'][0]['assets'][0]['version']==1
    with pytest.raises(ValueError,match='scope'): assets.bind(library,'another',bound,shots,rows)
    with pytest.raises(ValueError,match='incomplete'): assets.bind(library,'fixture',bound,shots,rows[:1])
    (library/rows[0]['file']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'): assets.bind(library,'fixture',bound,shots,rows)


def test_artifact_path_traversal_rejected(tmp_path):
    run=tmp_path/'run'; run.mkdir()
    freeze(run/'ARTIFACT_INDEX.json',{'x':{'path':'../secret.json','sha256':'x'}})
    with pytest.raises(ValueError,match='outside_run'): artifact(run,'x')


class SceneRepairFake(Fake):
    def __init__(self): super().__init__(); self.issued=False
    def call(self,role,messages,schema):
        payload=json.loads(messages[1]['content']); native=super().call(role,messages,schema); value=native_value(native)
        if 'review_sha256' in payload:
            value={'candidate_sha256':payload['candidate_sha256'],'review_sha256':payload['review_sha256'],
                   'findings':[{'index':0,'verdict':'upheld','reason':'fixture','source_ids':['CH1-P001']}]}
        elif 'candidate' in payload and 'script' in payload['candidate'] and not self.issued:
            value.update(decision='revise',issues=[{'owner':'staging','path':'/script/scenes/0/performance',
                         'reason':'fixture staging correction','source_ids':['CH1-P001']}]); self.issued=True
        elif 'current_scene' in payload and 'required_corrections' in payload: value['performance']='迟疑后点头'
        return set_value(native,value)


def test_staging_repair_reuses_chapters_and_fixed_story(tmp_path):
    run=prepare(tmp_path); fake=SceneRepairFake(); result=p.execute(run,fixture_client=fake)
    assert result['error'] is None,result
    assert set(read(run/'CHECKPOINT.json')['corrections'])=={'EPISODE_000_SCENE_000'}
    assert len([1 for _,v in fake.calls if 'chapter' in v])==2
    assert len([1 for _,v in fake.calls if 'episode' in v and 'current_scene' not in v and 'candidate' not in v])==1
    assert artifact(run,'EPISODE_000_ACCEPTED.json')['bound']['script']['scenes'][0]['performance']=='迟疑后点头'


def test_pause_after_completed_call_reuses_it_on_resume(tmp_path):
    run=prepare(tmp_path)
    class PausingFake(Fake):
        def call(self,role,messages,schema):
            result=super().call(role,messages,schema)
            if len(self.calls)==1: freeze(run/'PAUSE_REQUESTED.json',{'user_requested':True})
            return result
    result=p.execute(run,fixture_client=PausingFake())
    assert result['state']['status']=='paused' and result['state']['calls_started']==1
    (run/'PAUSE_REQUESTED.json').unlink(); fake=Fake()
    result=p.execute(run,fixture_client=fake,resume=True)
    assert result['error'] is None,result
    assert not any('chapter' in v and v['chapter']['index']==1 for _,v in fake.calls)


def test_web_render_does_not_dispatch_or_authorize(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src.web import serial_story_panel_v2 as panel
    monkeypatch.setattr(panel,'ROOT',tmp_path)
    def fail(*args,**kwargs): raise AssertionError('render must not dispatch')
    monkeypatch.setattr(panel,'launch',fail)
    app=AppTest.from_string('from src.web.serial_story_panel_v2 import render_page\nrender_page()').run()
    assert not app.exception
    assert any('建立计划' in x.value for x in app.info)
