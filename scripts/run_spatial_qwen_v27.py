"""Explicit root-gated Qwen fallback; CPU prepare reserves no image budget."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_spatial_qwen_v27 as q
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','prepare-batch','status','submit','poll','collect','execute']);p.add_argument('--run',type=Path,required=True);p.add_argument('--source-stills',type=Path);p.add_argument('--batch');p.add_argument('--ids',nargs='+');p.add_argument('--approval',type=Path);p.add_argument('--poll-seconds',type=int,default=10);p.add_argument('--max-seconds',type=int,default=3600);a=p.parse_args()
 if a.action=='prepare':
  if not a.source_stills:p.error('source-stills required')
  result=q.prepare(a.run,a.source_stills)
 else:
  if not a.batch:p.error('batch required')
  if a.action=='prepare-batch':result=q.prepare_batch(a.run,a.batch,a.ids)
  elif a.action=='status':result=q.status(a.run,a.batch)
  elif a.action in ('submit','execute'):
   if not a.approval:p.error('explicit root approval file required')
   result=q.submit(a.run,a.batch,a.approval) if a.action=='submit' else q.execute(a.run,a.batch,a.approval,poll_seconds=a.poll_seconds,max_seconds=a.max_seconds)
  else:result=getattr(q,a.action)(a.run,a.batch)
 print(json.dumps(result,ensure_ascii=True,indent=2))
if __name__=='__main__':main()
