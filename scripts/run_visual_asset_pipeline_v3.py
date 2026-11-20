"""Automated local asset preparation. Viewing status never schedules media."""
import argparse
import json
from pathlib import Path
import sys
import os
import time
import uuid
import re
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_asset_pipeline_v3 as flow
from src.content_factory import visual_image_jobs_v3 as jobs

PROJECT=Path(__file__).resolve().parents[1]


def checked_run(run,runs_root):
    run=run.resolve();runs_root=runs_root.resolve()
    default=(PROJECT/'data/visual_asset_pipeline/runs').resolve()
    if runs_root!=default and runs_root.name!='visual_asset_runs_v3':raise ValueError('invalid_runs_namespace')
    if run==runs_root or not run.is_relative_to(runs_root):raise ValueError('run_outside_visual_asset_namespace')
    return run


def begin_worker(run,launch_id):
    import psutil
    if launch_id is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',launch_id):
        raise ValueError('invalid_launch_id')
    process=psutil.Process();plan_sha=flow.file_sha(run/'PLAN.json')
    with jobs.run_lock(run,name='WORKER_CONTROL.lock'):
        old=flow.read(run/'WORKER.json') if (run/'WORKER.json').exists() else None
        if old and old['pid']!=os.getpid():
            try:
                p=psutil.Process(old['pid'])
                if abs(p.create_time()-old['create_time'])<0.01:raise ValueError('original_worker_still_running')
            except psutil.NoSuchProcess:pass
        value=dict(pid=os.getpid(),create_time=process.create_time(),cmdline=process.cmdline(),launch_id=launch_id or uuid.uuid4().hex,plan_sha256=plan_sha,at=time.time())
        flow.write(run/'WORKER.json',value);return value


def end_worker(run,worker,status,error=None):
    value=dict(worker,exited_at=time.time(),exit_known=True,status=status,error=error)
    flow.write(run/'WORKER_EXITS'/(worker['launch_id']+'.json'),value)
    flow.write(run/'WORKER_EXIT.json',value)


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','prepare-cast','run','tick','status','pause','resume'])
    p.add_argument('--run',type=Path,required=True);p.add_argument('--packet',type=Path);p.add_argument('--config',type=Path)
    p.add_argument('--cast-root',type=Path);p.add_argument('--book-id');p.add_argument('--operator',default='local_cli_owner')
    p.add_argument('--launch-id');p.add_argument('--runs-root',type=Path,default=PROJECT/'data/visual_asset_pipeline/runs')
    a=p.parse_args()
    a.run=checked_run(a.run,a.runs_root)
    if a.action in ('prepare','prepare-cast'):
        if not a.config:p.error('config required')
        if a.action=='prepare-cast':
            if not a.cast_root or not a.book_id:p.error('cast-root and book-id required')
            packet=flow.packet_from_cast(a.cast_root,a.book_id)
        else:
            if not a.packet:p.error('packet required')
            packet=flow.read(a.packet)
        result=flow.prepare(a.run,packet,flow.read(a.config))
    elif a.action=='status':result=flow.status(a.run)
    elif a.action in ('pause','resume'):result=flow.set_paused(a.run,a.action=='pause',actor=a.operator,role='admin')
    else:
        from src.content_factory.visual_asset_review_v3 import VisualReviewClient
        worker=begin_worker(a.run,a.launch_id) if a.action=='run' else None
        try:
            config=flow.status(a.run)['plan']['config'];reviewer=VisualReviewClient(config['visual_review'])
            result=(flow.tick if a.action=='tick' else flow.run_until_idle)(a.run,reviewer=reviewer)
        except BaseException as error:
            if worker:end_worker(a.run,worker,'failed',dict(type=type(error).__name__,message=str(error)))
            raise
        else:
            if worker:end_worker(a.run,worker,result.get('status','completed'))
    print(json.dumps(result,ensure_ascii=True,indent=2));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,PermissionError,KeyError) as e:
        print(json.dumps(dict(status='error',type=type(e).__name__,message=str(e)),ensure_ascii=True));raise SystemExit(2)
