"""One-time deployment and explicitly requested original-account playback recovery."""
import hashlib
import json
import sqlite3
import time
from pathlib import Path
import xml.etree.ElementTree as ET
import psutil

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/novel_feed_activation/clear_resume_20261023'
ACCOUNT='account:9158f1d29f70eff9819c46b4'


def main():
    suite=ET.parse(ROOT/'data/novel_feed_activation/clear_resume_final.xml').getroot().find('testsuite')
    assert int(suite.attrib['tests'])==66 and all(int(suite.attrib[k])==0 for k in ('errors','failures','skipped'))
    proc=psutil.Process(34044)
    assert abs(proc.create_time()-1792768466.0236084)<.001
    assert proc.cmdline()==[str(ROOT/'.venv/Scripts/pythonw.exe'),str(ROOT/'scripts/run_streamlit_web.py')]
    assert not proc.children(recursive=True)
    with sqlite3.connect(ROOT/'data/account_refresh.db') as db:
        db.row_factory=sqlite3.Row
        before=[dict(x) for x in db.execute('SELECT * FROM account_controls')]
        assert all(x['state']=='paused' for x in before)
        assert next(x for x in before if x['account_uuid']==ACCOUNT)['revision']==4
        for table in ('refresh_accounts','smart_accounts','playback_accounts'):
            assert not db.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR lease_until!=0').fetchone()
    with sqlite3.connect(ROOT/'data/account_browser_control.db') as db:
        assert db.execute('SELECT state FROM browser_control_commands WHERE command_id=?',('98cdf4505c494458928fb0b4624c1dc9',)).fetchone()[0]=='succeeded'
        assert not db.execute("SELECT 1 FROM browser_control_commands WHERE state IN ('queued','running','paused')").fetchone()
        assert not db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND state IN ('waiting_human','outcome_unknown')",(ACCOUNT,)).fetchone()
    OUT.mkdir(exist_ok=False)
    sources=['src/operations_accounts/clear_feed_resume.py','src/operations_accounts/browser_control_runtime.py','src/scheduler/account_refresh.py']
    proof={'at':time.time(),'authorization':'没验证码就继续执行刷视频程序啊','controls':before,
           'sources':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in sources},
           'window_closed_normally':True,'old_backend':34044}
    (OUT/'BEFORE.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    proc.terminate()
    for _ in range(12):
        try:proc.wait(timeout=5);break
        except psutil.TimeoutExpired:
            if not psutil.pid_exists(proc.pid):break
    assert not psutil.pid_exists(proc.pid)
    # The known closed window has no worker or unresolved command. Return only
    # this stopped owner's generation; preserve the other account's old record.
    from src.operations_accounts.browser_control import BrowserControlStore
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    store.release_owner(ACCOUNT,'backend:34044:c0febe5758454b3f9c21467eb6440efe',6)
    (OUT/'OWNER_RELEASE.json').write_text(json.dumps({'at':time.time(),'generation':6,
        'old_process_exited':True,'original_manual_window_succeeded':True}),encoding='utf-8')
    from src.scheduler.account_refresh import complete_account_handling
    result=complete_account_handling(ACCOUNT,'novel_account_02',handled_by='user:resume-clear-feed-20261023',
                                    plan_kinds=('playback',),expected_revision=4)
    (OUT/'RECOVERY_REQUEST.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    assert result['accepted'], result
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
