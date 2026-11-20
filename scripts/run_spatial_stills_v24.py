"""Explicit local spatial still CLI. prepare/status never submit media."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_spatial_stills_v24 as stills
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','prepare-batch','status','tick','execute']);p.add_argument('--run',type=Path,required=True);p.add_argument('--handoff',type=Path);p.add_argument('--render-result',type=Path);p.add_argument('--inputs',type=Path);p.add_argument('--authorization',type=Path);p.add_argument('--config',type=Path);p.add_argument('--require-material-policy');p.add_argument('--reference-packing');p.add_argument('--batch');p.add_argument('--ids',nargs='+');p.add_argument('--poll-seconds',type=int,default=10);p.add_argument('--max-seconds',type=int,default=1800);a=p.parse_args()
 if a.action=='prepare':
  if not all((a.handoff,a.render_result,a.inputs,a.authorization,a.config)):p.error('prepare requires handoff/render-result/inputs/authorization/config')
  result=stills.prepare(a.run,handoff=a.handoff,render_result=a.render_result,inputs=a.inputs,authorization=a.authorization,config=a.config,require_material_policy=a.require_material_policy,reference_packing=a.reference_packing)
 elif a.action=='status':result=stills.status(a.run,a.batch)
 else:
  if not a.batch:p.error('batch required')
  if a.action=='prepare-batch':result=stills.prepare_batch(a.run,a.batch,a.ids)
  elif a.action=='tick':result=stills.tick(a.run,a.batch)
  else:result=stills.execute(a.run,a.batch,a.poll_seconds,a.max_seconds)
 print(json.dumps(result,ensure_ascii=True,indent=2))
if __name__=='__main__':main()
