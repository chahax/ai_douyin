"""Low-denoise Flux img2img for source-bound scene keyframes."""
from __future__ import annotations
import argparse, json, shutil, time, urllib.request, uuid
from pathlib import Path

def request_json(url, payload=None):
    data=None if payload is None else json.dumps(payload).encode("utf-8")
    req=urllib.request.Request(url,data=data)
    if data is not None:req.add_header("Content-Type","application/json")
    with urllib.request.urlopen(req,timeout=120) as response:return json.loads(response.read())

def wait_history(base_url,prompt_id,timeout):
    deadline=time.time()+timeout
    while time.time()<deadline:
        value=request_json(f"{base_url}/history/{prompt_id}")
        if prompt_id in value:
            result=value[prompt_id]
            if result.get("status",{}).get("status_str")=="error":
                raise RuntimeError(json.dumps(result["status"],ensure_ascii=False))
            return result
        time.sleep(2)
    raise TimeoutError(prompt_id)

def saved_image(history,output_root):
    for output in history.get("outputs",{}).values():
        for image in output.get("images",[]):
            if image.get("type")=="output":
                return output_root/image.get("subfolder","")/image["filename"]
    raise RuntimeError("No saved image")

def workflow(checkpoint,image,prompt,negative,seed,steps,cfg,sampler,scheduler,denoise,prefix):
    return {
      "1":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":checkpoint}},
      "2":{"class_type":"LoadImage","inputs":{"image":image}},
      "3":{"class_type":"CLIPTextEncode","inputs":{"text":prompt,"clip":["1",1]}},
      "4":{"class_type":"CLIPTextEncode","inputs":{"text":negative,"clip":["1",1]}},
      "5":{"class_type":"VAEEncode","inputs":{"pixels":["2",0],"vae":["1",2]}},
      "6":{"class_type":"KSampler","inputs":{"model":["1",0],"seed":seed,"steps":steps,"cfg":cfg,"sampler_name":sampler,"scheduler":scheduler,"positive":["3",0],"negative":["4",0],"latent_image":["5",0],"denoise":denoise}},
      "7":{"class_type":"VAEDecode","inputs":{"samples":["6",0],"vae":["1",2]}},
      "8":{"class_type":"SaveImage","inputs":{"images":["7",0],"filename_prefix":prefix}}}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("plan",type=Path);ap.add_argument("--output-dir",type=Path,required=True)
    ap.add_argument("--base-url",default="http://127.0.0.1:8190")
    ap.add_argument("--comfy-input",type=Path,default=Path(r"D:\IT\AI_vido\ComfyUI\input"))
    ap.add_argument("--comfy-output",type=Path,default=Path(r"D:\IT\AI_vido\ComfyUI\output"))
    ap.add_argument("--input-prefix",required=True);ap.add_argument("--filename-prefix",required=True)
    ap.add_argument("--timeout-seconds",type=int,default=3600)
    a=ap.parse_args();plan=json.loads(a.plan.resolve().read_text(encoding="utf-8"))
    if plan.get("publish_allowed") is not False:raise ValueError("plan must remain non-publishable")
    source=Path(plan["input_image"]).resolve()
    if not source.is_file():raise FileNotFoundError(source)
    target_dir=a.comfy_input.resolve()/Path(a.input_prefix.replace("/","\\"))
    target_dir.mkdir(parents=True,exist_ok=True);target=target_dir/source.name;shutil.copy2(source,target)
    rel=f"{a.input_prefix}/{source.name}"
    graph=workflow(plan["checkpoint"],rel,plan["prompt"],plan.get("negative_prompt",""),int(plan["seed"]),int(plan["steps"]),float(plan["cfg"]),plan["sampler"],plan["scheduler"],float(plan["denoise"]),a.filename_prefix)
    out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    (out/"workflow.api.json").write_text(json.dumps(graph,ensure_ascii=False,indent=2),encoding="utf-8")
    response=request_json(f"{a.base_url}/prompt",{"prompt":graph,"client_id":str(uuid.uuid4())});pid=response["prompt_id"];print(f"queued {pid}",flush=True)
    history=wait_history(a.base_url,pid,a.timeout_seconds);src=saved_image(history,a.comfy_output.resolve())
    destination=out/(plan.get("output_name") or source.name);shutil.copy2(src,destination)
    report={"status":"generated","prompt_id":pid,"source":str(source),"output":str(destination),"denoise":plan["denoise"],"seed":plan["seed"]}
    (out/"run_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(destination,flush=True)

if __name__=="__main__":main()
