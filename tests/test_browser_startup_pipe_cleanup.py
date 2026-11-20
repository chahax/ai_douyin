"""Real dummy subprocesses reproduce inherited pipes without a browser."""
import io
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace as NS

import psutil
import pytest

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import BrowserSessionConfig


def session(tmp_path):
    return BrowserSession(BrowserSessionConfig(base_url='about:blank', home_url='about:blank',
        user_data_dir=str(tmp_path/'profile'), storage_state_path=str(tmp_path/'state.json'), headless=True))


def test_start_timeout_preserves_family_until_captured_and_reaps_before_pipe_close(tmp_path):
    pidfile=tmp_path/'dummy_child.pid'
    script=('import subprocess,sys,time,pathlib\n'
            'child=subprocess.Popen([sys.executable,"-S","-c","import time;time.sleep(60)"],'
            'stdin=subprocess.DEVNULL,stdout=sys.stdout,stderr=sys.stderr,'
            'creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))\n'
            f'pathlib.Path({str(pidfile)!r}).write_text(str(child.pid))\n'
            'time.sleep(60)\n')
    proc=subprocess.Popen([sys.executable,'-S','-c',script],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    child=None
    family=[]
    s=session(tmp_path);s._proc=proc
    try:
        deadline=time.monotonic()+5
        while not pidfile.exists() and time.monotonic()<deadline:
            threading.Event().wait(.01)
        assert pidfile.exists()
        child=psutil.Process(int(pidfile.read_text()))
        family=psutil.Process(proc.pid).children(recursive=True)
        # Windows venv launchers can add an intermediate Python process.
        assert child.pid in {p.pid for p in family}
        with pytest.raises(TimeoutError):
            s._read_child_line(.01,label='start')
        assert proc.poll() is None  # Startup cleanup can still prove the family.
        started=time.monotonic()
        s._discard_starting_worker()
        assert time.monotonic()-started<8
        assert proc.poll() is not None and not child.is_running() and s._startup_cleanup_verified
        assert proc.stdout.closed and proc.stderr.closed
    finally:
        if proc.poll() is None:
            family=psutil.Process(proc.pid).children(recursive=True)
        if proc.poll() is None:
            proc.kill();proc.wait(timeout=5)
        for member in reversed(family):
            if member.is_running():
                member.kill();member.wait(timeout=5)


def test_unknown_inherited_reader_cannot_block_failure_return(tmp_path):
    release=threading.Event()
    blocked=NS(close=lambda:release.wait(5))
    s=session(tmp_path)
    s._proc=NS(pid=2147483647,stdin=io.BytesIO(),stdout=blocked,stderr=blocked,
               kill=lambda:None,wait=lambda **kw:None,poll=lambda:0)
    try:
        started=time.monotonic()
        s._discard_starting_worker()
        assert time.monotonic()-started<1 and s._proc is None
        assert not s._startup_cleanup_verified
    finally:
        release.set()
