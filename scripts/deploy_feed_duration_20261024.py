"""Deploy tested follow-up after a known-ended feed loading failure; no manual reopen."""
import sys,json,time,sqlite3,hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'data/novel_feed_activation/feed_duration_20261024'
A='account:9158f1d29f70eff9819c46b4'
def main():
    for filename,n in [('feed_duration_final.xml',62)]:
        s=ET.parse(ROOT/'data/novel_feed_activation'/filename).getroot().find('testsuite')
        assert int(s.attrib['tests'])==n and all(int(s.attrib[k])==0 for k in ('errors','failures','skipped'))
    p=psutil.Process(29052);assert abs(p.create_time()-1792822032.4738612)<.001
    assert p.cmdline()==[str(ROOT/'.venv/Scripts/pythonw.exe'),str(ROOT/'scripts/run_streamlit_web.py')]
    assert not p.children(recursive=True)
    with sqlite3.connect(ROOT/'data/account_refresh.db') as db:
        assert db.execute('SELECT state,revision,error_code FROM account_controls WHERE account_uuid=?',(A,)).fetchone()==('paused',25,'feed_not_ready')
        for t in ('refresh_accounts','smart_accounts','playback_accounts'):
            assert not db.execute(f'SELECT 1 FROM {t} WHERE run_id IS NOT NULL OR lease_until!=0').fetchone()
        assert db.execute('SELECT enabled FROM retained_feed_preferences WHERE account_uuid=?',(A,)).fetchone()[0]==1
    from src.operations_accounts.browser_control import BrowserControlStore,_json
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    original=store.get('a782697e79004431b9d0b6c35932caf9')
    assert original['state']=='failed' and original['result']['maintenance_result']['error_code']=='feed_not_ready'
    with store._db() as db:
        assert not db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND state IN ('queued','running','paused','waiting_human','outcome_unknown')",(A,)).fetchone()
        assert db.execute('SELECT state FROM browser_control_owners WHERE account_id=?',(A,)).fetchone()['state']=='released'
    OUT.mkdir(exist_ok=False)
    files=['src/operations_accounts/browser_control_runtime.py','src/platform_adapter/douyin_recommendation_playback.py','src/operations_accounts/retained_feed_session.py']
    (OUT/'BEFORE.json').write_text(_json({'at':time.time(),'known_failure':original,'old_pid':p.pid,'sources':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},'authorization':'User accepted minimized muted original account and explicitly requested continuing deployment and live daily playback. This fixes the known-ended feed loading failure; no unknown replay and no further manual-window request.'}),encoding='utf-8')
    p.terminate()
    try:p.wait(timeout=10)
    except psutil.TimeoutExpired:assert not psutil.pid_exists(p.pid)
    assert not psutil.pid_exists(p.pid)
    from src.scheduler.account_refresh import complete_account_handling
    result=complete_account_handling(A,'novel_account_02',handled_by='user:continue-tested-minimized-feed-fix',plan_kinds=('playback',),expected_revision=25)
    (OUT/'RECOVERY.json').write_text(_json(result),encoding='utf-8');print(_json(result))
if __name__=='__main__':main()
