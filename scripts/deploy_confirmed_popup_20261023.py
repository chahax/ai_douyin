"""Enable confirmed-challenge popups and open the already verified current case."""
import hashlib
import json
import sqlite3
import time
from pathlib import Path
import xml.etree.ElementTree as ET
import psutil

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/novel_feed_activation/confirmed_popup_20261023'
ACCOUNT='account:9158f1d29f70eff9819c46b4'


def main():
    for file,count in [('confirmed_popup_tests.xml',162),('confirmed_popup_final.xml',7)]:
        suite=ET.parse(ROOT/'data/novel_feed_activation'/file).getroot().find('testsuite')
        assert int(suite.attrib['tests'])==count and all(int(suite.attrib[k])==0 for k in ('errors','failures','skipped'))
    evidence_path=ROOT/'data/feed_surface_diagnostics/3fed21d855c44ca7b0386e5e7db9e3a5/EVIDENCE.json'
    evidence=json.loads(evidence_path.read_text(encoding='utf-8'))
    assert len(evidence['samples'])>=2
    assert all(s['challenge']['blocking'] and 'challenge_ready' in s['challenge']['surface_states'] for s in evidence['samples'][-2:])
    proc=psutil.Process(31940)
    assert abs(proc.create_time()-1792766297.739355)<.001
    assert proc.cmdline()==[str(ROOT/'.venv/Scripts/pythonw.exe'),str(ROOT/'scripts/run_streamlit_web.py')]
    assert not proc.children(recursive=True)
    with sqlite3.connect(ROOT/'data/account_refresh.db') as db:
        db.row_factory=sqlite3.Row
        controls=[dict(r) for r in db.execute('SELECT * FROM account_controls')]
        assert all(r['state']=='paused' for r in controls)
        novel=next(r for r in controls if r['account_uuid']==ACCOUNT)
        assert novel['revision']==4 and novel['error_code']=='verification_ui_unconfirmed'
        for table in ('refresh_accounts','smart_accounts','playback_accounts'):
            assert not db.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR lease_until!=0').fetchone()
    from src.operations_accounts.browser_control import BrowserControlStore
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    with store._db() as db:
        assert not db.execute("SELECT 1 FROM browser_control_commands WHERE state IN ('running','queued','paused')").fetchone()
        assert db.execute('SELECT state FROM browser_control_owners WHERE account_id=?',(ACCOUNT,)).fetchone()[0]=='released'
        assert not db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND state IN ('waiting_human','outcome_unknown')",(ACCOUNT,)).fetchone()
    OUT.mkdir(exist_ok=False)
    sources=['src/scheduler/browser_visibility.py','src/scheduler/account_manual_windows.py',
             'src/operations_accounts/browser_control_runtime.py','src/platform_adapter/browser_session.py','src/platform_adapter/models.py']
    before={'at':time.time(),'authorization':'有滑块可以弹的这个可以加入到自动化中吗',
        'controls':controls,'evidence_path':str(evidence_path),'evidence_sha256':hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        'sources':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}}
    (OUT/'BEFORE.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
    assert not proc.children(recursive=True)
    proc.terminate()
    for _ in range(12):
        try:proc.wait(timeout=5);break
        except psutil.TimeoutExpired:
            if not psutil.pid_exists(proc.pid):break
    assert not psutil.pid_exists(proc.pid)
    from src.scheduler.browser_visibility import set_automatic_windows
    set_automatic_windows(ACCOUNT,True,confirmed_only=True,authorization=before['authorization'])
    # Current incident predates the selector fix and retains its original
    # unconfirmed error. This explicitly requested opening uses the subsequent
    # confirmed read-only evidence, without rewriting old playback outcomes.
    from src.operations_accounts.browser_control_runtime import queue_manual_window
    command=queue_manual_window(ACCOUNT,'novel_account_02','user:confirmed-slider:incident37:3fed21d855c44ca7b0386e5e7db9e3a5')
    (OUT/'DEPLOYMENT.json').write_text(json.dumps({'at':time.time(),'old_backend_stopped':True,'mode':'confirmed_only',
        'current_window':command,'old_playback_result_unchanged':True},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(command,ensure_ascii=False))


if __name__=='__main__':main()
