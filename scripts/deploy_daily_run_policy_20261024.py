"""One idle deployment for the user's removal of ordinary daily run caps."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import xml.etree.ElementTree as ET
import psutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/publish_runs/ferry_seedance_20261024'


def main():
    suite = ET.parse(ROOT/'data/qa/daily_run_policy_20261024.xml').getroot().find('testsuite')
    assert int(suite.attrib['tests']) > 20
    assert all(int(suite.attrib[k]) == 0 for k in ('errors', 'failures', 'skipped'))
    assert not (OUT/'DEPLOYMENT_STOP.json').exists(), 'One-time deployment already recorded'
    pid = int((ROOT/'data/logs/streamlit_web.pid').read_text())
    process = psutil.Process(pid)
    assert pid == 20628 and abs(process.create_time()-1792823108.571128) < .001
    assert process.cmdline() == [str(ROOT/'.venv/Scripts/pythonw.exe'), str(ROOT/'scripts/run_streamlit_web.py')]
    assert not process.children(recursive=True), 'Live browser or worker must finish first'
    with sqlite3.connect((ROOT/'data/account_refresh.db').as_uri()+'?mode=ro', uri=True) as db:
        for table in ('refresh_accounts', 'smart_accounts', 'playback_accounts'):
            assert not db.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR lease_until!=0').fetchone()
    with sqlite3.connect((ROOT/'data/account_browser_control.db').as_uri()+'?mode=ro', uri=True) as db:
        assert not db.execute("SELECT 1 FROM browser_control_commands WHERE state IN ('queued','running','paused')").fetchone()
        original = db.execute('SELECT * FROM browser_control_commands ORDER BY command_id').fetchall()
    sources = ['src/operations_accounts/daily_run_policy.py', 'src/operations_accounts/repository.py',
               'src/operations_accounts/browser_control_runtime.py', 'src/web/account_exception_notice.py']
    evidence = {'at':time.time(), 'user_statement':'不要这个额度设计继续', 'pid':pid,
                'created_at':process.create_time(), 'children':[], 'tests':suite.attrib,
                'original_commands_sha256':hashlib.sha256(json.dumps(original,ensure_ascii=False).encode()).hexdigest(),
                'sources':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in sources}}
    (OUT/'DEPLOYMENT_BEFORE.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2),encoding='utf-8')
    process.terminate()
    try:
        process.wait(timeout=15)
    except psutil.TimeoutExpired:
        assert not psutil.pid_exists(pid)
    assert not psutil.pid_exists(pid)
    evidence['stopped_at'] = time.time()
    (OUT/'DEPLOYMENT_STOP.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'stopped_pid':pid,'old_commands_preserved':True}))


if __name__ == '__main__':
    main()
