"""Explicit baseline R1/R2 execution; R2 preparation requires the R1 review."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_baseline_two_rounds_v38 as f

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['bootstrap','prepare','status','collect','step','execute','assemble'])
    p.add_argument('--round',choices=['R1','R2'],default='R1',dest='round_name');p.add_argument('--run',type=Path)
    p.add_argument('--poll-seconds',type=float,default=30);p.add_argument('--max-seconds',type=float,default=86400);a=p.parse_args();run=a.run or f.ROOT/a.round_name
    if a.action=='bootstrap':value=f.bootstrap()
    elif a.action=='prepare':value=f.prepare(run)
    elif a.action=='status':value=f.status(run)
    elif a.action=='collect':value=f.collect_known(run)
    elif a.action=='step':value=f.tick(run,allow_submit=False)
    elif a.action=='assemble':value=f.assemble(run)
    else:value=f.execute(run,poll_seconds=a.poll_seconds,max_seconds=a.max_seconds)
    print(json.dumps(value,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
