"""One idle service deployment; preserve known-closed manual command history."""
import sys,json,time,sqlite3,hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
import psutil
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'data/novel_feed_activation/feed_entry_20261024'
A='account:9158f1d29f70eff9819c46b4'

def main():
    for filename,n in [('feed_entry_final.xml',33)]:
        s=ET.parse(ROOT/'data/novel_feed_activation'/filename).getroot().find('testsuite')
        assert int(s.attrib['tests'])==n and all(int(s.attrib[k])==0 for k in ('errors','failures','skipped'))
    p=psutil.Process(26936)
    assert abs(p.create_time()-1792818046.1365547)<.001
    assert p.cmdline()==[str(ROOT/'.venv/Scripts/pythonw.exe'),str(ROOT/'scripts/run_streamlit_web.py')]
    assert not p.children(recursive=True)
    with sqlite3.connect(ROOT/'data/account_refresh.db') as db:
        assert not db.execute("SELECT 1 FROM account_controls WHERE state!='paused'").fetchone()
        for t in ('refresh_accounts','smart_accounts','playback_accounts'):
            assert not db.execute(f'SELECT 1 FROM {t} WHERE run_id IS NOT NULL OR lease_until!=0').fetchone()
    from src.operations_accounts.browser_control import BrowserControlStore
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    original=store.get('9b5e8026cfd742a6a3dc0d8b422a6972');assert original['state']=='succeeded'
    with store._db() as db:
        assert not db.execute("SELECT 1 FROM browser_control_commands WHERE state IN ('queued','running','paused')").fetchone()
    OUT.mkdir(exist_ok=False)
    files=['src/platform_adapter/recommendation_entry.py','src/platform_adapter/douyin_recommendation_playback.py','src/platform_adapter/feed_surface_diagnostic.py','src/operations_accounts/clear_feed_resume.py','src/operations_accounts/browser_control_runtime.py','src/web/account_exception_notice.py']
    (OUT/'BEFORE.json').write_text(json.dumps({'at':time.time(),'old_window':original,'old_pid':26936,
        'sources':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}},ensure_ascii=False,indent=2),encoding='utf-8')
    p.terminate()
    for _ in range(10):
        try:p.wait(timeout=5);break
        except psutil.TimeoutExpired:
            if not psutil.pid_exists(p.pid):break
    assert not psutil.pid_exists(p.pid)
    store.release_owner(A,'backend:26936:3b959717e01941339d36ce71c46b7a8a',10)
    from src.operations_accounts.browser_control_runtime import queue_manual_window
    result=queue_manual_window(A,'novel_account_02','user:repair-nonplaying-visible-feed-20261024')
    (OUT/'DEPLOYMENT.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
