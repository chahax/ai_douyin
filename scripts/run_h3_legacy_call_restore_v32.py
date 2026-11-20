"""Explicit new-root recipe restoration CLI; prepare/status are CPU only."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_legacy_call_restore_v32 as f
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','status','execute']);p.add_argument('--run',type=Path,default=f.RUN);p.add_argument('--poll-seconds',type=int,default=30);p.add_argument('--max-seconds',type=int,default=86400);a=p.parse_args()
    value=f.prepare(a.run) if a.action=='prepare' else f.status(a.run) if a.action=='status' else f.execute(a.run,poll_seconds=a.poll_seconds,max_seconds=a.max_seconds)
    print(json.dumps(value,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
