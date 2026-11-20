"""Explicit new-run CLI; no deployed defaults or old runs are modified."""
import argparse
from pathlib import Path
import sys
import hashlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation.pipeline import extract_cards


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--run',required=True);ap.add_argument('--source',required=True)
    ap.add_argument('--route-plan',required=True);ap.add_argument('--statement',required=True)
    ap.add_argument('--max-calls',type=int,default=8)
    args=ap.parse_args();source=read(Path(args.source));plan=read(Path(args.route_plan))
    plan={k:plan[k] for k in ('routes','inference','context')}
    if not 1<=args.max_calls<=8:ap.error('max-calls must be 1..8')
    plan.update(max_calls=args.max_calls,source_sha256=digest(source),version='novel_adaptation/cards-v2',
        user_statement=args.statement,chapter_indices=[ch['index'] for ch in source['chapters']])
    run=Path(args.run);run.mkdir(exist_ok=False)
    pins={}
    for path in [Path(__file__),Path('src/content_factory/novel_adaptation/contracts.py'),
            Path('src/content_factory/novel_adaptation/pipeline.py'),Path('src/content_factory/novel_adaptation/patching.py'),
            Path('src/content_factory/serial_story_transport_v6.py'),Path('scripts/serial_native_worker_v6.py')]:
        data=path.read_bytes();pins[str(path)]=hashlib.sha256(data).hexdigest()
        target=run/'implementation'/path.name;target.parent.mkdir(exist_ok=True);target.write_bytes(data)
    plan['implementation_pin']=pins
    freeze(run/'PLAN.json',plan);freeze(run/'SOURCE.json',source)
    freeze(run/'AUTHORIZATION.json',{'origin':'explicit_user_approval','statement':args.statement,
        'source_sha256':digest(source),'destinations':{'writer':plan['routes']['writer']},'media':False})
    extract_cards(run,source,plan)
