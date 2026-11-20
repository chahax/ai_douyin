"""CPU spatial blocking CLI; no Comfy, service or model APIs."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_spatial_scene_v24 as spatial


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','validate','render']);p.add_argument('--run',type=Path,default=spatial.DEFAULT_RUN);p.add_argument('--source',type=Path,default=spatial.SOURCE);p.add_argument('--blender',type=Path);p.add_argument('--timeout',type=int,default=900);p.add_argument('--render-tag',default='blender_fov_r1');p.add_argument('--material-policy',choices=[spatial.LEGACY_MATERIALS,spatial.SKIN_MATERIALS],default=spatial.LEGACY_MATERIALS);args=p.parse_args()
    if args.action=='prepare':result=spatial.prepare(args.run,args.source)
    elif args.action=='validate':result=spatial.validate(json.loads((args.run/'SPATIAL_PLAN.json').read_text(encoding='utf-8')))
    else:
        if not args.blender:p.error('--blender required')
        result=spatial.render(args.run,args.blender,timeout=args.timeout,render_tag=args.render_tag,material_policy=args.material_policy)
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
