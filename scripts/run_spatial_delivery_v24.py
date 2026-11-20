"""Independent local Ref2VA + time-anchored-guide diagnostic executor."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_spatial_delivery_v24 as flow

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('prepare','status','submit','poll','execute','assemble','pause','resume'))
    p.add_argument('--run',type=Path,required=True);p.add_argument('--spec',type=Path);p.add_argument('--approval',type=Path)
    p.add_argument('--poll-seconds',type=float,default=30);p.add_argument('--max-seconds',type=float,default=86400);a=p.parse_args()
    if a.command=='prepare':
        if not a.spec or not a.approval:p.error('prepare requires --spec and --approval')
        result=flow.prepare(a.spec,a.approval,a.run)
    elif a.command=='execute':result=flow.execute(a.run,a.poll_seconds,a.max_seconds)
    elif a.command in ('pause','resume'):
        run,plan=flow._load(a.run)
        with flow.jobs.run_lock(run):
            if a.command=='pause':flow.native.write(run/'PAUSE.json',dict(actor='operator',at=flow.time.time()))
            else:(run/'PAUSE.json').unlink(missing_ok=True)
        result=flow.status(run)
    else:result=getattr(flow,{'submit':'submit_next','poll':'poll_collect'}.get(a.command,a.command))(a.run)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
