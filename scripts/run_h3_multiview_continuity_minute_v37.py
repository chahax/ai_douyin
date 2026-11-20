"""Explicit image/video stages; no automatic warm model-family switching."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_multiview_continuity_minute_v37 as f

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','status','collect','step','execute','assemble'])
    p.add_argument('--run',type=Path,default=f.RUN);p.add_argument('--stage',choices=['images','videos'])
    p.add_argument('--shot',choices=f.IDS)
    p.add_argument('--poll-seconds',type=float,default=30);p.add_argument('--max-seconds',type=float,default=86400);a=p.parse_args()
    if a.action in ('step','execute') and (not a.stage or not a.shot):p.error('step/execute require explicit --stage and --shot')
    if a.action=='prepare':result=f.prepare(a.run)
    elif a.action=='status':result=f.status(a.run)
    elif a.action=='collect':result=f.collect_known(a.run)
    elif a.action=='assemble':result=f.assemble(a.run)
    elif a.action=='step':result=f.tick(a.run,stage=a.stage,shot=a.shot,allow_submit=False)
    else:result=f.execute(a.run,stage=a.stage,shot=a.shot,poll_seconds=a.poll_seconds,max_seconds=a.max_seconds)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
