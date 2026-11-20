from pathlib import Path
import httpx,json,hashlib,datetime,sys,struct
root=Path('tools/scene_lab_20261006').resolve();contract=json.loads((root/'comfy/EXPERIMENT_CONTRACT.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
summary=[]
with httpx.Client(trust_env=False,timeout=15) as c:
 for item in contract['planned_jobs']:
  job=root/'comfy/jobs'/item['id'];sub=job/'SUBMIT_RESULT.json'
  if not sub.exists():summary.append({'id':item['id'],'status':'not_submitted'});continue
  r=json.loads(sub.read_text());d=json.loads(r['content'][0]['text']);pid=d.get('prompt_id')
  if not pid:summary.append({'id':item['id'],'status':'submit_not_accepted','result':d});continue
  h=c.get('http://127.0.0.1:8192/history/'+pid).json();entry=h.get(pid)
  if not entry:summary.append({'id':item['id'],'prompt_id':pid,'status':'pending_or_running'});continue
  final=job/'FINAL_RECEIPT.json'
  if final.exists():rec=json.loads(final.read_text())
  else:
   (job/'HISTORY_FINAL.json').write_text(json.dumps(h,indent=2),encoding='utf-8')
   saved=[]
   for node,val in entry.get('outputs',{}).items():
    for key,items in val.items():
     if not isinstance(items,list):continue
     for x in items:
      if not isinstance(x,dict) or 'filename' not in x:continue
      p=root/'comfy/output'/x.get('subfolder','')/x['filename'];p=p.resolve()
      if not p.is_relative_to(root/'comfy/output'):raise RuntimeError('unexpected output path')
      if p.exists():saved.append({'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p),'node':node,'output_key':key})
   success=entry.get('status',{}).get('status_str')=='success' and entry.get('status',{}).get('completed') is True
   rec={'id':item['id'],'prompt_id':pid,'interface_success':success,'outputs_saved':saved,'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'awaiting_human_review' if success and saved else 'execution_failed','human_content_approval':None,'assistant_video_content_review_performed':False,'auto_retries':0,'paid_cloud_calls':0}
   with final.open('x',encoding='utf-8') as f:json.dump(rec,f,indent=2)
  summary.append(rec)
(root/'comfy/EXECUTION_STATUS.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
