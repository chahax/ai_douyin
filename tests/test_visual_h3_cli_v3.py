"""Independent CLI/temporary HTTP black boxes, not generated-video content QA."""
import json
from pathlib import Path
import subprocess
import sys
import pytest

from test_visual_h3_handoff_v3 import native_media,service,setup,write
from src.content_factory import visual_h3_handoff_v3 as h

ENTRY=h.PROJECT/'scripts/run_visual_h3_v3.py'


def cli(*args):
    result=subprocess.run([sys.executable,str(ENTRY),*map(str,args)],cwd=h.PROJECT,
        capture_output=True,text=True,encoding='utf-8',timeout=30)
    return result,json.loads(result.stdout)


def test_prepare_and_run_default_never_post(tmp_path,service):
    assets,destination,cfg=setup(tmp_path,service)
    fresh=destination.parent/'cli_new'
    path=tmp_path/'config.json';write(path,cfg)
    result,value=cli('prepare','--run',fresh,'--asset-run',assets,'--config',path)
    assert result.returncode==0 and value['video_enabled'] is False
    result,value=cli('run','--run',fresh)
    assert result.returncode==0 and value['dispatch']=='video_policy_disabled'
    assert service.posts==[]


def test_config_true_needs_explicit_prepare_flag(tmp_path,service):
    assets,destination,cfg=setup(tmp_path,service,enabled=True)
    path=tmp_path/'config.json';write(path,cfg)
    result,value=cli('prepare','--run',destination.parent/'cli_new','--asset-run',assets,'--config',path)
    assert result.returncode==2 and value['message']=='explicit_enable_video_flag_required'
    assert service.posts==[]


def test_exact_original_id_collected_while_paused_cli(tmp_path,service):
    assets,destination,cfg=setup(tmp_path,service,enabled=True,shots=1)
    h.prepare_from_ready(assets,destination,cfg)
    result,value=cli('tick','--run',destination)
    assert result.returncode==0 and value['shots'][0]['prompt_id']=='native_1'
    assert len(service.posts)==1
    result,value=cli('pause','--run',destination,'--operator','qa_owner')
    assert result.returncode==0 and value['paused'] is True
    service.complete()
    result,value=cli('tick','--run',destination)
    assert result.returncode==0 and value['status']=='media_review_required'
    assert value['shots'][0]['prompt_id']=='native_1' and len(service.posts)==1
    assert (destination/'PAUSE.json').exists()


def test_unknown_post_cli_no_replay(tmp_path,service):
    assets,destination,cfg=setup(tmp_path,service,enabled=True,shots=1)
    h.prepare_from_ready(assets,destination,cfg)
    service.drop=True
    result,value=cli('tick','--run',destination)
    assert result.returncode==0 and value['status']=='outcome_unknown'
    result,value=cli('tick','--run',destination)
    assert result.returncode==0 and value['status']=='outcome_unknown' and len(service.posts)==1


@pytest.mark.parametrize('action',['status','tick','run','resume'])
def test_existing_policy_cannot_change_by_later_flag(tmp_path,service,action):
    assets,destination,cfg=setup(tmp_path,service)
    h.prepare_from_ready(assets,destination,cfg)
    before=(destination/'PLAN.json').read_bytes()
    result,value=cli(action,'--run',destination,'--enable-video')
    assert result.returncode==2 and value['message']=='policy_changes_require_new_prepare_plan'
    assert (destination/'PLAN.json').read_bytes()==before and service.posts==[]
