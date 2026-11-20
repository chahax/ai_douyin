"""Real process-boundary recovery and exclusion, with no network/model calls."""
import subprocess,sys
import pytest
from test_stage_session import setup
from src.content_factory.novel_adaptation.stage_session import step,inspect

FLAGS=getattr(subprocess,'CREATE_NO_WINDOW',0)


def test_process_dies_after_native_save_then_reconciles_without_redispatch(tmp_path):
    root=setup(tmp_path)
    script='''import os,sys
from pathlib import Path
from src.content_factory.corpus_screenplay_v1 import freeze
from src.content_factory.novel_adaptation.stage_session import step
def worker(folder,state,plan):
    folder.mkdir()
    freeze(folder/'OUTPUT.json',{'native':'completed before process exit'})
    freeze(folder/'STATE.json',{'status':'done','pending':None,'calls_started':9,'reported_tokens':110})
    os._exit(7)
step(Path(sys.argv[1]),{'author':worker})
'''
    result=subprocess.run([sys.executable,'-c',script,str(root)],creationflags=FLAGS)
    assert result.returncode==7
    assert inspect(root)['pending_stage']==0
    recovered=step(root,{'author':lambda *a:pytest.fail('duplicate provider dispatch')})
    assert recovered['calls_started']==9 and len(recovered['completed'])==1


def test_another_process_holding_session_lock_prevents_dispatch(tmp_path):
    root=setup(tmp_path)
    script='''import sys
from pathlib import Path
from src.content_factory.serial_story_runtime_v2 import run_lock
with run_lock(Path(sys.argv[1])):
    print('locked',flush=True)
    sys.stdin.readline()
'''
    child=subprocess.Popen([sys.executable,'-c',script,str(root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                           text=True,creationflags=FLAGS)
    try:
        assert child.stdout.readline().strip()=='locked'
        with pytest.raises(ValueError,match='already_executing'):
            step(root,{'author':lambda *a:pytest.fail('concurrent dispatch')})
        assert inspect(root)['pending_stage'] is None
    finally:
        child.communicate('\n',timeout=10)
