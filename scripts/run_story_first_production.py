"""Versioned story-first route; old corpus tasks are never migrated."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import story_first_production_v1 as v1, story_first_production_v2 as v2
from src.content_factory import story_first_production_v3 as v3
from src.content_factory import story_first_production_v4 as v4
from src.content_factory import story_first_production_v5 as v5
from src.content_factory.corpus_screenplay_v1 import read
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['prepare','execute','status']);ap.add_argument('--run',required=True)
    ap.add_argument('--source-run');ap.add_argument('--scope-file')
    ap.add_argument('--version',choices=['v1','v2','v3','v4','v5'],default='v5')
    args=ap.parse_args()
    if args.action=='prepare':
        p={'v1':v1,'v2':v2,'v3':v3,'v4':v4,'v5':v5}[args.version]
        if not args.source_run or not args.scope_file:ap.error('prepare needs source-run and explicit scope-file')
        scope=read(args.scope_file)
        result=p.prepare(args.source_run,args.run,user_statement=scope['user_statement'],
           approved_source_sha256=scope['approved_source_sha256'],approved_destinations=scope['approved_destinations'],target_seconds=scope.get('target_seconds',60))
    elif args.action=='execute':
        version=read(Path(args.run)/'PLAN.json')['version']
        implementations={v1.VERSION:v1,v2.VERSION:v2,v3.VERSION:v3,v4.VERSION:v4,v5.VERSION:v5}
        if version not in implementations:raise ValueError('unsupported frozen version')
        result=implementations[version].execute(args.run)
    else:result=read(Path(args.run)/'STATE.json')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.action=='execute' and result['error']:raise SystemExit(1)
if __name__=='__main__':main()
