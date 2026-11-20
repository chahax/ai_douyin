"""One explicitly authorized disposition; preserves the original unknown fact."""
import datetime
import hashlib
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psutil
from src.operations_accounts.fanqie_account_control import FanqieAccounts,write_json
from src.operations_accounts.browser_control import BrowserControlStore,_json
from src.operations_accounts.fanqie_login_recovery import dispose_login


if __name__=='__main__':
    a=FanqieAccounts()
    command_id='17e509dd6f2d485f85b9618bf5ad3928'
    resource='fanqie:52ce7e06afc9451b8a81bfd9269ad94e'
    folder=a.folder(command_id)
    if (folder/'DISPOSITION_COMPLETED.json').exists():
        raise RuntimeError('This one-time disposition has already completed')
    original_times={54180:'23:33:56',49296:'23:33:56',8116:'23:33:57',23300:'23:33:57',19524:'23:34:02',53568:'23:34:02'}
    observations={}
    def original_alive(pid):
        expected=datetime.datetime.fromisoformat('2026-10-24T'+original_times[pid]+'+08:00').timestamp()
        try:
            observed=psutil.Process(pid).create_time()
            alive=abs(observed-expected)<3
            observations[str(pid)]={'expected_created_at':expected,'observed_created_at':observed,'original_process_present':alive,'pid_reused':not alive}
            return alive
        except psutil.NoSuchProcess:
            observations[str(pid)]={'expected_created_at':expected,'original_process_present':False}
            return False
    for pid in original_times:
        if original_alive(pid): raise RuntimeError('Original process still present; no mutation performed')
    write_json(folder/'PROCESS_EXIT_CHECK.json',{'observed_at':time.time(),'processes':observations})
    grant=write_json(folder/'USER_DISPOSITION_AUTHORIZATION.json',{
        'decision_source':'explicit_user_statement','command_id':command_id,'resource_id':resource,
        'user_statement':'允许处置并重开一次','scope':'保留原未知记录，取消这条原番茄开窗任务，同专属环境重开一次',
        'observed_at':time.time()})
    before=BrowserControlStore(a.db).get(command_id)
    result=dispose_login(a,command_id,grant,expected_sha=hashlib.sha256(_json(before).encode()).hexdigest(),exited_pids=list(original_times),pid_exists=original_alive)
    print(write_json(folder/'DISPOSITION_COMPLETED.json',result))
