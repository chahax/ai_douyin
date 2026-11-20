"""One explicit local S02 video probe, no observer or service management."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_s02_prompt_probe_v39 as f

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','status','collect','step','execute','finalize']);p.add_argument('--run',type=Path,default=f.RUN)
    p.add_argument('--poll-seconds',type=float,default=30);p.add_argument('--max-seconds',type=float,default=86400);a=p.parse_args()
    if a.action=='prepare':v=f.prepare(a.run)
    elif a.action=='status':v=f.status(a.run)
    elif a.action=='collect':v=f.collect_known(a.run)
    elif a.action=='step':v=f.tick(a.run,allow_submit=False)
    elif a.action=='finalize':v=f.finalize(a.run)
    else:v=f.execute(a.run,poll_seconds=a.poll_seconds,max_seconds=a.max_seconds)
    print(json.dumps(v,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
