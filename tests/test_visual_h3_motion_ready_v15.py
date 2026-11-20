"""Ready-only CLI boundary: never text-call an unready production shot."""
from pathlib import Path
import pytest
from src.content_factory import visual_h3_motion_ready_v15 as ready
from test_visual_h3_native_prompt_v15 import planner_fixture,Client


def route(run):
    flow=ready.native;p=flow.status(run)['plan'];scope=flow._read_binding(p['packet']);shot=scope['shots'][0]
    asset=Path(p['asset_plan']['path']).parent
    row=dict(id=shot['id'],packet=p['packet']['path'],packet_sha256=p['packet']['sha256'],
        source_native_frames=shot['source_native_frames'],asset_run=str(asset),first_frame_plan=p['selected_static_plan'])
    path=run.parent/'routing.json';flow.stage.files.write(path,dict(parent=p['full_parent'],shots=[row]))
    return path,row


def test_unready_shot_status_is_readonly_and_plan_never_calls_model(tmp_path,monkeypatch):
    run,_=planner_fixture(tmp_path,monkeypatch);path,row=route(run)
    ready.native.stage.files.write(path,dict(parent=ready.native.status(run)['plan']['full_parent'],shots=[dict(row,asset_run=str(tmp_path/'not_ready'))]))
    unused=tmp_path/'visual_h3_native_prompts_v15'/'unprepared';client=Client()
    result=ready.status(path,'F0001',unused)
    assert result['ready_evidence_exists'] is False and not unused.exists()
    with pytest.raises(ready.native.NativePromptBlocked,match='first_frame_not_ready_no_model_call'):
        ready.plan(path,'F0001',unused,client=client)
    assert not client.calls and not unused.exists()


def test_ready_shot_can_use_frozen_native_plan_without_modifying_route(tmp_path,monkeypatch):
    run,_=planner_fixture(tmp_path,monkeypatch);path,_=route(run);before=path.read_bytes();client=Client()
    binding=ready.plan(path,'F0001',run,client=client)
    assert len(client.calls)==1 and ready.native.verify_plan(binding['path'])
    assert path.read_bytes()==before


@pytest.mark.parametrize('field',['source_native_frames','native_seconds'])
def test_route_frame_count_change_rejected_before_model_call(tmp_path,monkeypatch,field):
    run,_=planner_fixture(tmp_path,monkeypatch);path,row=route(run);value=ready.native.stage.files.read(path)
    value['shots'][0][field]=row['source_native_frames']+17 if field=='source_native_frames' else 99.0
    ready.native.stage.files.write(path,value);client=Client()
    with pytest.raises(ready.native.NativePromptBlocked,match='source_shot_or_clock_changed'):
        ready.plan(path,'F0001',run,client=client)
    assert not client.calls
