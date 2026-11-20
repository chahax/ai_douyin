"""One resumable entry: dedicated Fanqie corpus -> analysis -> script review.

No video generation, promotion application or publication. Text-service calls
require the explicit --execute-text switch and a user scope statement.
"""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.operations_accounts.fanqie_account_control import FanqieAccounts,launch_worker
from src.operations_accounts.browser_control import BrowserControlStore
from src.platform_adapter.fanqie_book_corpus import atomic
from src.content_factory.corpus_screenplay_v1 import prepare,execute,freeze,read
from src.content_factory import corpus_production_v4 as whole_chapter
from src.content_factory import corpus_production_v3 as extractive
from src.content_factory import corpus_production_v5 as chapter_facts
from src.content_factory import corpus_production_v6 as chapter_materials
from src.content_factory import corpus_production_v7 as minimax_materials
from src.content_factory import corpus_production_v8 as temporal_materials
from src.content_factory import corpus_production_v9 as addressed_materials


TEXT_ROUTES = {route.VERSION: route for route in (extractive, whole_chapter, chapter_facts, chapter_materials, minimax_materials, temporal_materials, addressed_materials)}


def execute_text_pipeline(run):
    """Continue a frozen route; only new workflows select the new pipeline."""
    plan = read(Path(run) / 'PLAN.json')
    state = read(Path(run) / 'STATE.json')
    if state.get('pending') or state.get('status') in {'needs_attention', 'outcome_unknown', 'reviewed_draft_ready'}:
        return state
    version = plan.get('version')
    if version in TEXT_ROUTES:
        route = TEXT_ROUTES[version]
        state = route.execute_local(run)
        return route.execute_cloud(run) if state['status'] == 'materials_ready' else state
    if version is None and str(plan.get('schema', '')).startswith('corpus_screenplay/'):
        return execute(run)
    raise ValueError('unsupported_frozen_text_pipeline')

def workflow(run,resource,title,previous_status,user_statement,*,execute_text=False,
             accounts=None,launch=launch_worker,prepare_text=None,execute_script=None,
             timeout=7200,poll_seconds=5):
    run=Path(run).resolve();run.mkdir(parents=True,exist_ok=True)
    lock=run/'WORKFLOW.lock'
    with lock.open('x') as f:f.write('one original workflow')
    accounts=accounts or FanqieAccounts()
    try:
        job_path=run/'JOB.json'
        if job_path.exists():
            job=read(job_path)
            if (job['resource'],job['title'],job['previous_status'],job['user_statement'])!=(resource,title,str(Path(previous_status).resolve()),user_statement):
                raise ValueError('original_workflow_scope_changed')
        else:
            command=accounts.queue(resource,'fanqie_book_inspect',book_name=title,chapters=0)
            if command['kind']!='fanqie_book_inspect' or command['payload'].get('book_name')!=title or command['payload'].get('chapters')!=0:
                raise ValueError('different_original_account_task_pending')
            job={'resource':resource,'title':title,'command_id':command['command_id'],
                 'previous_status':str(Path(previous_status).resolve()),'user_statement':user_statement,
                 'text_pipeline':addressed_materials.VERSION}
            freeze(job_path,job)
            launch(command,accounts)
        deadline=time.monotonic()+timeout
        store=BrowserControlStore(accounts.db)
        while True:
            command=store.get(job['command_id'])
            if command['state']=='succeeded':break
            status={'stage':'acquisition','command_id':job['command_id'],'state':command['state'],
                    'reason':command.get('error_code') or (command.get('result') or {}).get('reason')}
            atomic(run/'STATUS.json',status)
            if command['state'] not in {'queued','running'} or time.monotonic()>=deadline:return status
            time.sleep(poll_seconds)
        evidence=read(accounts.folder(job['command_id'])/'BOOK_INSPECTION.json')
        if evidence.get('corpus',{}).get('status')!='accessible_catalogue_complete':raise ValueError('all_readable_acquisition_required')
        text_run=run/'text'
        if not text_run.exists():
            version = job.get('text_pipeline')
            if version is not None and version not in TEXT_ROUTES:
                raise ValueError('unsupported_frozen_text_pipeline')
            selected_prepare = prepare_text or (TEXT_ROUTES[version].prepare if version else prepare)
            selected_prepare(evidence['corpus_path'],text_run,user_statement=user_statement,previous_status=previous_status)
        status=(execute_script or execute_text_pipeline)(text_run) if execute_text else read(text_run/'STATE.json')
        atomic(run/'STATUS.json',{'stage':'text','text_run':str(text_run),**status})
        return status
    finally:lock.unlink()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('run','resource','book-name','previous-status','user-statement'):p.add_argument('--'+name,required=True)
    p.add_argument('--execute-text',action='store_true')
    a=p.parse_args()
    print(json.dumps(workflow(a.run,a.resource,a.book_name,a.previous_status,a.user_statement,execute_text=a.execute_text),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
