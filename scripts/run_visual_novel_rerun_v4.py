"""Explicit existing-screenplay visual planning; image/video execution is separate."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_novel_rerun_v4 as flow


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','plan','status','sample','import-locations'])
    p.add_argument('--run',type=Path,required=True);p.add_argument('--source',type=Path);p.add_argument('--coverage',type=Path)
    p.add_argument('--cast-root',type=Path);p.add_argument('--book-id');p.add_argument('--user-statement');p.add_argument('--config',type=Path)
    p.add_argument('--phase',choices=['locations','designs','staging','all'],default='all');p.add_argument('--scene-ids');p.add_argument('--shot-ids')
    p.add_argument('--place-ids');p.add_argument('--origin-run',type=Path)
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.action=='prepare':
        if not all((a.source,a.coverage,a.cast_root,a.book_id,a.user_statement)):p.error('explicit source, coverage, cast-root, book-id and user-statement required')
        result=flow.prepare(a.run,a.source,a.coverage,a.cast_root,a.book_id,user_statement=a.user_statement,config=flow.files.read(a.config) if a.config else None)
    elif a.action=='plan':result=flow.plan(a.run,phase=a.phase,scene_ids=a.scene_ids.split(',') if a.scene_ids else None,
        place_ids=a.place_ids.split(',') if a.place_ids else None,shot_ids=a.shot_ids.split(',') if a.shot_ids else None)
    elif a.action=='import-locations':
        if not a.origin_run:p.error('origin-run required for import-locations')
        result=flow.import_locations(a.run,a.origin_run)
    elif a.action=='sample':
        result=flow.sample_packet(a.run,shot_ids=a.shot_ids.split(',') if a.shot_ids else None)
        if not a.output:p.error('output required for sample')
        flow.files.freeze(a.output,result)
    else:result=flow.status(a.run)
    print(json.dumps(result,ensure_ascii=True,indent=2));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,KeyError) as e:
        print(json.dumps(dict(status='error',type=type(e).__name__,message=str(e)),ensure_ascii=True));raise SystemExit(2)
