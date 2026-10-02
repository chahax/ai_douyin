"""Source-bound Flux inpaint for correcting a reviewed local keyframe region."""
from __future__ import annotations
import argparse,json,shutil,time,urllib.request,uuid
from pathlib import Path
def req(url,payload=None):
 data=None if payload is None else json.dumps(payload).encode("utf-8");r=urllib.request.Request(url,data=data)
 if data is not None:r.add_header("Content-Type","application/json")
 with urllib.request.urlopen(r,timeout=120) as x:return json.loads(x.read())
def wait(base,pid,timeout):
 end=time.time()+timeout
 while time.time()<end:
  d=req(f"{base}/history/{pid}")
  if pid in d:
   h=d[pid]
   if h.get("status",{}).get("status_str")=="error":raise RuntimeError(json.dumps(h["status"],ensure_ascii=False))
   return h
  time.sleep(2)
 raise TimeoutError(pid)
def saved(h,root):
 for o in h.get("outputs",{}).values():
  for i in o.get("images",[]):
   if i.get("type")=="output":return root/i.get("subfolder","")/i["filename"]
 raise RuntimeError("No saved image")
def main():
 ap=argparse.ArgumentParser();ap.add_argument("plan",type=Path);ap.add_argument("--output-dir",type=Path,required=True);ap.add_argument("--base-url",default="http://127.0.0.1:8190");ap.add_argument("--comfy-input",type=Path,default=Path(r"D:\IT\AI_vido\ComfyUI\input"));ap.add_argument("--comfy-output",type=Path,default=Path(r"D:\IT\AI_vido\ComfyUI\output"));ap.add_argument("--input-prefix",required=True);ap.add_argument("--filename-prefix",required=True);ap.add_argument("--timeout-seconds",type=int,default=3600);a=ap.parse_args()
 p=json.loads(a.plan.resolve().read_text(encoding="utf-8"))
 if p.get("publish_allowed") is not False:raise ValueError("plan must remain non-publishable")
 source=Path(p["masked_image"]).resolve();destdir=a.comfy_input.resolve()/Path(a.input_prefix.replace("/","\\"));destdir.mkdir(parents=True,exist_ok=True);dest=destdir/source.name;shutil.copy2(source,dest);rel=f"{a.input_prefix}/{source.name}"
 g={
 "1":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":p["checkpoint"]}},
 "2":{"class_type":"LoadImage","inputs":{"image":rel}},
 "3":{"class_type":"CLIPTextEncode","inputs":{"text":p["prompt"],"clip":["1",1]}},
 "4":{"class_type":"CLIPTextEncode","inputs":{"text":p.get("negative_prompt",""),"clip":["1",1]}},
 "5":{"class_type":"VAEEncodeForInpaint","inputs":{"pixels":["2",0],"vae":["1",2],"mask":["2",1],"grow_mask_by":int(p.get("grow_mask_by",8))}},
 "6":{"class_type":"KSampler","inputs":{"model":["1",0],"seed":int(p["seed"]),"steps":int(p["steps"]),"cfg":float(p["cfg"]),"sampler_name":p["sampler"],"scheduler":p["scheduler"],"positive":["3",0],"negative":["4",0],"latent_image":["5",0],"denoise":float(p.get("denoise",1.0))}},
 "7":{"class_type":"VAEDecode","inputs":{"samples":["6",0],"vae":["1",2]}},
 "8":{"class_type":"SaveImage","inputs":{"images":["7",0],"filename_prefix":a.filename_prefix}}}
 out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=True);(out/"workflow.api.json").write_text(json.dumps(g,ensure_ascii=False,indent=2),encoding="utf-8")
 pid=req(f"{a.base_url}/prompt",{"prompt":g,"client_id":str(uuid.uuid4())})["prompt_id"];print(f"queued {pid}",flush=True)
 src=saved(wait(a.base_url,pid,a.timeout_seconds),a.comfy_output.resolve());target=out/p.get("output_name","output.png");shutil.copy2(src,target);(out/"run_report.json").write_text(json.dumps({"status":"generated","prompt_id":pid,"source":str(source),"output":str(target)},ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(target,flush=True)
if __name__=="__main__":main()
