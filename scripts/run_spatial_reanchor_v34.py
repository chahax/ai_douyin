"""CPU prepare/render of source-current-state v33 anchor stage."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_spatial_reanchor_v34 as s
p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','render']);p.add_argument('--run',type=Path,default=s.RUN);p.add_argument('--spec',type=Path,default=s.SPEC);p.add_argument('--blender',type=Path);a=p.parse_args()
result=s.prepare(a.run,a.spec) if a.action=='prepare' else s.render(a.run,a.blender)
print(json.dumps(result,ensure_ascii=True,indent=2))
