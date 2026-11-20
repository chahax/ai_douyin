from pathlib import Path
import json,sys,httpx,hashlib,zipfile,re
from datetime import datetime,timezone
B=Path(r'D:\IT\ai_douyin\tools\scene_lab_20261006');P=json.loads((B/'DOWNLOAD_PLAN.json').read_text(encoding='utf-8'))
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def get(url,path,expected=None):
 path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists():
  if expected and sha(path)!=expected:raise ValueError('existing file digest mismatch')
  return {'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size,'url':url,'existing':True}
 part=path.with_suffix(path.suffix+'.part');h=httpx.Client(timeout=httpx.Timeout(60,read=60),follow_redirects=True)
 with h.stream('GET',url) as r:
  r.raise_for_status();size=int(r.headers.get('content-length','0'));done=0;checkpoint=0
  with part.open('xb') as f:
   for chunk in r.iter_bytes(1024*1024):
    f.write(chunk);done+=len(chunk)
    if done-checkpoint>256*1024*1024:print(json.dumps({'download':path.name,'downloaded_mib':round(done/1048576),'total_mib':round(size/1048576) if size else None}),flush=True);checkpoint=done
 h.close();digest=sha(part)
 if expected and digest!=expected:raise ValueError('download checksum mismatch '+path.name)
 part.replace(path);return {'path':str(path),'sha256':digest,'bytes':done,'url':url,'verified_expected_sha256':bool(expected)}
def unpack(path,dest):
 if dest.exists():raise ValueError('refuse replace existing extraction')
 dest.mkdir(parents=True)
 with zipfile.ZipFile(path) as z:
  for info in z.infolist():
   target=(dest/info.filename).resolve()
   if not target.is_relative_to(dest.resolve()):raise ValueError('archive escapes destination')
  z.extractall(dest)
 return str(dest)
def write(name,data):
 with (B/name).open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
kind=sys.argv[1];rows=[]
if kind=='blender':
 name=P['blender']['url'].rsplit('/',1)[1]
 with httpx.Client(timeout=30,follow_redirects=True) as h:r=h.get(P['blender']['checksum_url']);r.raise_for_status();raw=r.text
 (B/'blender_checksums.sha256').write_text(raw,encoding='utf-8');lines=[x for x in raw.splitlines() if name in x];assert len(lines)==1;expected=lines[0].split()[0];assert len(expected)==64
 row=get(P['blender']['url'],B/'downloads'/name,expected);row['extracted']=unpack(Path(row['path']),B/'blender');rows.append(row)
elif kind=='sources':
 for repo,x in P['repos'].items():
  if repo=='Comfy-Org/example_workflows':continue
  name=repo.replace('/','__')
  row=get(x['archive_url'],B/'downloads'/(name+'.zip'));row['commit']=x['commit'];row['extracted']=unpack(Path(row['path']),B/'sources'/name);rows.append(row);print(json.dumps({'source_downloaded':repo,'commit':x['commit'][:12]}),flush=True)
 with httpx.Client(timeout=30,follow_redirects=True) as h:
  repo='Comfy-Org/example_workflows';commit=P['repos'][repo]['commit'];r=h.get(f'https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1');r.raise_for_status();tree=r.json()['tree']
  candidates=[x['path'] for x in tree if x['type']=='blob' and x['path'].endswith('.json') and '/wan/vace/' in x['path']]
  for path in candidates:rows.append(get(f'https://raw.githubusercontent.com/{repo}/{commit}/{path}',B/'templates'/path))
  docs=h.get('https://api.github.com/repos/Comfy-Org/docs/commits/main');docs.raise_for_status();dc=docs.json()['sha'];md=get(f'https://raw.githubusercontent.com/Comfy-Org/docs/{dc}/tutorials/video/wan/vace.mdx',B/'templates'/'vace_source.mdx');rows.append(md)
  for url in sorted(set(re.findall(r'https://[^\s\)\"<>]+\.json',Path(md['path']).read_text(encoding='utf-8')))):
   fn=url.rsplit('/',1)[-1];rows.append(get(url,B/'templates'/'official_vace'/fn))
  rows.append(get('https://raw.githubusercontent.com/comfyanonymous/ComfyUI_examples/master/controlnet/depth_controlnet.png',B/'templates'/'depth_controlnet_official.png'))
elif kind=='weights':
 v=P['vace_candidate'];x=next(y for y in v['files'] if y['path'].endswith('/wan2.1_vace_1.3B_fp16.safetensors'));url=f'https://huggingface.co/{v["repo"]}/resolve/{v["commit"]}/{x["path"]}?download=true';row=get(url,B/'models'/'diffusion_models'/'wan2.1_vace_1.3B_fp16.safetensors',x['lfs']['oid']);row['hf_commit']=v['commit'];rows.append(row)
else:raise ValueError('unknown kind')
write('DOWNLOAD_RECEIPT_'+kind+'.json',{'at_utc':datetime.now(timezone.utc).isoformat(),'downloads':rows,'paid_calls':0})
print(json.dumps({'operation':kind,'files':len(rows),'bytes':sum(x['bytes'] for x in rows),'complete':True}),flush=True)
