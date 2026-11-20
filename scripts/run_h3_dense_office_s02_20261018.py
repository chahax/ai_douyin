"""Only S02 prepare/validate/run/status/collect; original S01 stays frozen."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import h3_dense_office_s02_v1 as trial

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['prepare','validate','run','status','collect'])
    parser.add_argument('--wait-timeout',type=float,default=21600);parser.add_argument('--poll-seconds',type=float,default=30)
    args=parser.parse_args();os.environ.update(trial.s01.speed.environment())
    try:
        if args.operation=='prepare':result=trial.prepare()
        elif args.operation=='validate':result=trial.validate_native()
        else:
            client=trial.h.LocalH3Client()
            if args.operation=='run':result=trial.run(client,timeout=args.wait_timeout,poll=args.poll_seconds)
            elif args.operation=='collect':
                with trial.process_lock(trial.OUT/'.s02_trial.lock'):result=trial.collect(client)
            else:result=trial.status(client)
        print(json.dumps({key:result[key] for key in ('status','local_state','prompt_id','technical_status','content_status','delivery','graph','graph_sha256','media_submissions','submission_outcome') if key in result},ensure_ascii=False))
    except Exception as exc:
        trial.durable(trial.OUT/'LOCAL_STOP.json',dict(at=trial.now(),operation=args.operation,error_type=type(exc).__name__,error=str(exc),automatic_retry=False));raise
