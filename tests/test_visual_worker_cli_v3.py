"""Filesystem/owner boundaries on the actual external asset worker entry."""
from pathlib import Path
import json
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
ENTRY=ROOT/'scripts/run_visual_asset_pipeline_v3.py'


@pytest.mark.parametrize('token',['../outside','..\\outside','/absolute','x'*81])
def test_unsafe_launch_token_cannot_create_external_exit_receipt(tmp_path,token):
    from src.content_factory import visual_asset_pipeline_v3 as flow
    root=tmp_path/'visual_asset_runs_v3';run=root/'paused';run.mkdir(parents=True)
    source=tmp_path/'SOURCE.md';source.write_text('Immutable actual input.',encoding='utf-8')
    flow.prepare(run,dict(schema='visual_asset_packet/v3',book_id='test',source=dict(path=str(source),sha256=flow.file_sha(source)),characters=[],places=[],shots=[]),{})
    flow.set_paused(run,True,actor='qa',role='admin')
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result=subprocess.run([sys.executable,str(ENTRY),'run','--run',str(run),'--runs-root',str(root),'--launch-id',token],
        capture_output=True,text=True,timeout=30)
    assert result.returncode==2 and json.loads(result.stdout)['message']=='invalid_launch_id'
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_legacy_batch_refused_before_read_or_write(tmp_path):
    outside=tmp_path/'h3_six_children_full_script_recovery_20261104';outside.mkdir()
    original=outside/'PAUSE.json';original.write_text('{"original":"keep"}',encoding='utf-8')
    result=subprocess.run([sys.executable,str(ENTRY),'resume','--run',str(outside),'--runs-root',str(tmp_path/'visual_asset_runs_v3')],capture_output=True,text=True,timeout=30)
    assert result.returncode==2 and json.loads(result.stdout)['message']=='run_outside_visual_asset_namespace'
    assert original.read_text(encoding='utf-8')=='{"original":"keep"}' and len(list(outside.iterdir()))==1
