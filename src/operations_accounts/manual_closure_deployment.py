"""One armed deployment bridge; installs only a closed-tab poll on the live owner.

No browser or DB state changes on the frontend thread. The original account
thread performs the native observation and its usual fenced completion.
"""
import json
import os
from pathlib import Path
import threading

ROOT=Path(__file__).resolve().parents[2]
CHECKPOINT=ROOT/'data/development_checkpoints/publication_workflow_completion_20261102'
ARM=CHECKPOINT/'MANUAL_CLOSURE_ARM.json'


def install_if_armed():
    if not ARM.exists():return
    config=json.loads(ARM.read_text(encoding='utf8'))
    if os.getpid()!=config['backend_pid']:return
    for thread in threading.enumerate():
        target=getattr(thread,'_target',None)
        if (thread.name!='AccountBrowser-'+config['account_key'] or not thread.is_alive()
                or getattr(target,'__name__','')!='_host'
                or Path(target.__code__.co_filename).resolve()!=ROOT/'src/operations_accounts/browser_control_runtime.py'
                or getattr(thread,'_args',())!=(config['account_key'],)):
            continue
        namespace=target.__globals__
        previous=namespace['_poll_manual_windows']
        if getattr(previous,'_closed_tab_deployment_version',0)>=2:return
        from .manual_tab_closure import settle_closed_manual_tabs
        def poll(actor,resource):
            if (actor.account_id==config['account_id'] and actor.owner_id==config['owner_id']
                    and actor.generation==config['generation'] and config['manual_id'] in resource.manual_tasks
                    and resource.session is not None and getattr(resource.session,'_proc',None) is not None):
                if config.get('close_original_environment'):
                    from .manual_environment_retirement import close_original_environment
                    if close_original_environment(actor,resource,config,CHECKPOINT):return
                status=resource.session.window_status()
                safe={'owner_id':actor.owner_id,'generation':actor.generation,
                    'tabs':[{'tab_id':r['tab_id'],'role':r.get('role'),'closed':r.get('closed'),
                             'blank':r.get('url')=='about:blank'}for r in status.get('tabs',[])],
                    'context_closed':status.get('context_closed')}
                stopped=settle_closed_manual_tabs(actor,resource,status)
                safe['original_manual_settled']=config['manual_id'] not in resource.manual_tasks
                safe['blank_worker_retired']=stopped
                (CHECKPOINT/'MANUAL_CLOSURE_OBSERVATION.json').write_text(json.dumps(safe,indent=2),encoding='utf8')
                if stopped:return
            return previous(actor,resource)
        poll._closed_tab_deployment=True
        poll._closed_tab_deployment_version=2
        namespace['_poll_manual_windows']=poll
        (CHECKPOINT/'MANUAL_CLOSURE_INSTALLED.json').write_text(json.dumps({'backend_pid':os.getpid(),
            'thread_name':thread.name,'owner_id':config['owner_id'],'version':2}),encoding='utf8')
        return
