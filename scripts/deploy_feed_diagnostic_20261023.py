"""Deploy fixed read-only feed diagnostic while all business is paused."""
import hashlib
import json
import sqlite3
import time
from pathlib import Path
import xml.etree.ElementTree as ET
import psutil

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/novel_feed_activation/diagnostic_deploy_20261023'


def main():
    suite=ET.parse(ROOT/'data/novel_feed_activation/diagnostic_final.xml').getroot().find('testsuite')
    assert int(suite.attrib['tests'])==54 and all(int(suite.attrib[k])==0 for k in ('failures','errors','skipped'))
    p=psutil.Process(31580)
    assert abs(p.create_time()-1792765451.8368316)<.001
    assert p.cmdline()==[str(ROOT/'.venv/Scripts/pythonw.exe'),str(ROOT/'scripts/run_streamlit_web.py')]
    assert not p.children(recursive=True)
    with sqlite3.connect(ROOT/'data/account_refresh.db') as db:
        assert not db.execute("SELECT 1 FROM account_controls WHERE state!='paused'").fetchone()
        for table in ('refresh_accounts','smart_accounts','playback_accounts'):
            assert not db.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR lease_until!=0').fetchone()
    with sqlite3.connect(ROOT/'data/douyin.db') as db:
        assert not db.execute("SELECT 1 FROM account_runtime_state WHERE lock_owner!=''").fetchone()
    with sqlite3.connect(ROOT/'data/account_browser_control.db') as db:
        assert not db.execute("SELECT 1 FROM browser_control_commands WHERE state IN ('running','queued','paused')").fetchone()
        assert db.execute("SELECT state FROM browser_control_owners WHERE account_id='account:9158f1d29f70eff9819c46b4'").fetchone()[0]=='released'
    OUT.mkdir(exist_ok=False)
    sources=['src/platform_adapter/feed_surface_diagnostic.py','src/platform_adapter/browser_session.py','src/operations_accounts/browser_control_runtime.py']
    proof={'at':time.time(),'authorization':'监控下不行你一步步调试','pid':p.pid,
        'sources':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in sources},
        'no_active_business_or_child_processes':True,'phase':'stop_intent'}
    (OUT/'DEPLOYMENT.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    p.terminate()
    for _ in range(12):
        try:p.wait(timeout=5);break
        except psutil.TimeoutExpired:
            if not psutil.pid_exists(p.pid):break
    assert not psutil.pid_exists(p.pid), 'Old backend exit unconfirmed; no new command queued'
    proof['phase']='old_backend_stopped'
    (OUT/'DEPLOYMENT.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    from src.operations_accounts.browser_control_runtime import _submit
    command=_submit('novel_account_02','read',dict(method='inspect_recommendation_surface',params={},operation_profile=None),
        'user-feed-diagnostic-20261023-first',10)
    (OUT/'COMMAND.json').write_text(json.dumps(command,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'queued_diagnostic':command['command_id'],'phase':proof['phase']}))


if __name__=='__main__':main()
