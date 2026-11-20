"""One-shot metadata-only install; no reload/close/restart of the original owner."""
import json
import os
from pathlib import Path
import threading

ROOT=Path(__file__).resolve().parents[2]
HERE=ROOT/'data/development_checkpoints/manual_display_close_race_20261103'
ARM=HERE/'CLAIM_GUARD_ARM.json'


def install_if_armed():
    if not ARM.exists():return
    config=json.loads(ARM.read_text(encoding='utf8'))
    if os.getpid()!=config['backend_pid']:return
    import psutil
    if psutil.Process().create_time()!=config['backend_create_time']:return
    for thread in threading.enumerate():
        target=getattr(thread,'_target',None)
        if (thread.name!='AccountBrowser-'+config['account_key'] or not thread.is_alive()
                or getattr(target,'__name__','')!='_host'
                or Path(target.__code__.co_filename).resolve()!=ROOT/'src/operations_accounts/browser_control_runtime.py'
                or getattr(thread,'_args',())!=(config['account_key'],)):
            continue
        namespace=target.__globals__;previous=namespace['_poll_manual_windows']
        if getattr(previous,'_paused_claim_runtime',False):return
        def poll(actor,resource):
            if (actor.account_id==config['account_id'] and actor.owner_id==config['owner_id']
                    and actor.generation==config['generation']):
                actor._assert_thread();actor._check_owner()
                from .paused_browser_claims import install
                def protected_poll(current_actor,current_resource):
                    install(current_actor,current_resource)
                    return previous(current_actor,current_resource)
                protected_poll._paused_claim_runtime=True
                namespace['_poll_manual_windows']=protected_poll
                (HERE/'CLAIM_GUARD_INSTALLED.json').write_text(json.dumps({
                    'backend_pid':os.getpid(),'owner_id':actor.owner_id,'generation':actor.generation,
                    'manual_tasks_preserved':list(resource.manual_tasks),'browser_operations':False,
                    'covers_future_owners':True},indent=2),encoding='utf8')
                return protected_poll(actor,resource)
            return previous(actor,resource)
        poll._paused_claim_deployment=True
        namespace['_poll_manual_windows']=poll
        return
