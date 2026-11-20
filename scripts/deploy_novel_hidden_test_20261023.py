"""One idle-backend deployment and one short original-account hidden test."""
import hashlib
import json
import sqlite3
import time
from pathlib import Path
import xml.etree.ElementTree as ET

import psutil

from src.operations_accounts.browser_control import BrowserControlStore
from src.operations_accounts.browser_host_retirement import retire
from src.scheduler.browser_visibility import set_automatic_windows
from src.scheduler.account_refresh import set_playback_policy, request_account_recovery

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = 'account:9158f1d29f70eff9819c46b4'
OUT = ROOT / 'data/novel_feed_activation/hidden_test_20261023'


def read(name, sql, args=()):
    with sqlite3.connect((ROOT / 'data' / name).as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        return [dict(r) for r in db.execute(sql,args)]


def main():
    OUT.mkdir(exist_ok=False)
    suite=ET.parse(ROOT/'data/novel_feed_activation/hidden_tests.xml').getroot().find('testsuite')
    assert int(suite.attrib['tests'])==133
    assert all(int(suite.attrib[k])==0 for k in ('errors','failures','skipped'))
    proc=psutil.Process(25096)
    assert abs(proc.create_time()-1792759326.7459831)<.001
    assert proc.cmdline()==[str(ROOT/'.venv/Scripts/pythonw.exe'),str(ROOT/'scripts/run_streamlit_web.py')]
    assert not proc.children(recursive=True)
    for table in ('refresh_accounts','smart_accounts','playback_accounts'):
        assert not read('account_refresh.db',f'SELECT * FROM {table} WHERE run_id IS NOT NULL OR lease_until!=0')
    assert not read('douyin.db',"SELECT account_uuid FROM account_runtime_state WHERE lock_owner!=''")
    assert not read('account_refresh.db',"SELECT account_uuid FROM account_controls WHERE state!='paused'")
    assert not read('account_browser_control.db',"SELECT command_id FROM browser_control_commands WHERE state IN ('running','queued','paused')")
    manual=read('account_browser_control.db','SELECT * FROM browser_control_commands WHERE command_id=?',('0454a41bba72497b8d73b7c0860b1dcf',))[0]
    assert manual['state']=='succeeded'
    owner=read('account_browser_control.db','SELECT * FROM browser_control_owners WHERE account_id=?',(ACCOUNT,))[0]
    before={'at':time.time(),'authorization':'测试下你测试，隐藏浏览器别前端显示然后别放声音',
            'novel_owner':owner,'manual_window':manual,
            'legal_waiting_window':read('account_browser_control.db','SELECT * FROM browser_control_commands WHERE command_id=?',('10b2bcfbba84499b93ad1a9891ec0226',))[0],
            'playback_policy':read('account_refresh.db','SELECT * FROM playback_policies WHERE account_uuid=?',(ACCOUNT,))[0],
            'bindings':read('douyin.db','SELECT account_uuid,platform_identity_key,browser_environment_key FROM account_runtime_bindings'),
            'sources':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
                'src/scheduler/browser_visibility.py','src/scheduler/account_manual_windows.py',
                'src/operations_accounts/browser_control_runtime.py','src/operations_accounts/manual_handling.py',
                'src/platform_adapter/douyin_recommendation_playback.py')}}
    (OUT/'BEFORE.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
    # Both accounts paused, no handlers/leases/children. Original legal waiting
    # record remains untouched; a missing window is never called CAPTCHA success.
    assert not proc.children(recursive=True)
    proc.terminate();proc.wait(timeout=20)
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    assert retire(store,ACCOUNT,owner['owner_id'],owner['generation'],evidence={
        'host_stopped':True,'worker_stopped':True,'source':'user_authorized_hidden_test_deployment',
        'backend_pid':25096,'evidence':str(OUT/'BEFORE.json')})
    set_automatic_windows(ACCOUNT,False,authorization=before['authorization'])
    set_playback_policy(ACCOUNT,'novel_account_02',True,86400,
        dict(max_videos=1,per_video_seconds=15,total_minutes=2,min_relevance_score=0.0,auto_like=False,auto_comment=False),
        authorization_reference=before['authorization']+'；本次短测1条15秒、总计2分钟；后续还原已保存日常计划')
    assert request_account_recovery(ACCOUNT,'novel_account_02')
    (OUT/'DEPLOYMENT.json').write_text(json.dumps({'at':time.time(),'old_backend_stopped':True,
        'novel_owner_released':True,'hidden_test_configured':True,'original_identity_probe_requested':True,
        'legal_waiting_window_unchanged':read('account_browser_control.db','SELECT * FROM browser_control_commands WHERE command_id=?',('10b2bcfbba84499b93ad1a9891ec0226',))[0]==before['legal_waiting_window']},indent=2),encoding='utf-8')
    print('Idle backend stopped; hidden short test and original identity probe configured.')


if __name__=='__main__':
    main()
