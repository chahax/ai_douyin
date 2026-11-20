"""CPU preparation or explicitly approved serial native-media coordination."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_continuity_minute_v34 as f

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','status','context','context-entry','anchor','select-anchor','video','advance','approval-request','collect','assemble','execute'])
    p.add_argument('--run',type=Path,default=f.RUN);p.add_argument('--shot',choices=f.IDS,default='S01');p.add_argument('--kind',choices=['image','video'],default='image')
    p.add_argument('--receipt',type=Path);p.add_argument('--coverage-review',type=Path)
    p.add_argument('--poll-seconds',type=int,default=20);p.add_argument('--max-seconds',type=int,default=86400);a=p.parse_args()
    if a.action in ('prepare','status','advance','collect','assemble'):
        method={'collect':f.collect_known}.get(a.action,getattr(f,a.action,None));value=method(a.run)
    elif a.action=='context':value=f.stage_context(a.run,a.shot)
    elif a.action=='context-entry':value=f.prepare_context_entry(a.run,a.shot)
    elif a.action=='anchor':value=f.prepare_anchor(a.run,a.shot)
    elif a.action=='select-anchor':
        if a.receipt is None or a.coverage_review is None:p.error('select-anchor requires --receipt and --coverage-review')
        value=f.select_anchor(a.run,a.shot,f.bind(a.receipt),f.bind(a.coverage_review))
    elif a.action=='video':value=f.prepare_video(a.run,a.shot)
    elif a.action=='approval-request':value=f.approval_request(a.run,a.shot,a.kind)
    else:value=f.execute(a.run,poll_seconds=a.poll_seconds,max_seconds=a.max_seconds)
    print(json.dumps(value,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
