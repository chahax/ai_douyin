"""Download authorized spatial tooling from official origins, entirely on D:."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib,json,time,urllib.request,zipfile

ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/'data/tools/spatial_20261107'
MODELS=ROOT/'data/models/spatial_20261107'
def write(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def download(url,path):
 path.parent.mkdir(parents=True,exist_ok=True);partial=path.with_suffix(path.suffix+'.part');state=path.with_suffix(path.suffix+'.download.json')
 if path.exists():return path
 for attempt in range(5):
  try:
   offset=partial.stat().st_size if partial.exists() else 0
   req=urllib.request.Request(url,headers={'User-Agent':'ai-douyin-spatial-setup/24',**({'Range':f'bytes={offset}-'} if offset else {})})
   with urllib.request.urlopen(req,timeout=60) as r:
    resume=offset>0 and r.status==206
    if not resume:offset=0
    total=int(r.headers.get('Content-Length','0'))+offset;done=offset;last=0
    with partial.open('ab' if resume else 'wb') as f:
     while chunk:=r.read(4*1024*1024):
      f.write(chunk);done+=len(chunk)
      if time.monotonic()-last>10:
       write(state,dict(status='downloading',url=url,bytes=done,total=total,attempt=attempt+1));print(path.name,done,total,flush=True);last=time.monotonic()
    if total and done!=total:raise ValueError('incomplete content length')
   partial.replace(path);sha=hashlib.file_digest(path.open('rb'),'sha256').hexdigest();write(state,dict(status='downloaded',url=url,path=str(path),bytes=path.stat().st_size,sha256=sha));return path
  except Exception as e:
   write(state,dict(status='download_error',url=url,attempt=attempt+1,error=repr(e),partial_bytes=partial.stat().st_size if partial.exists() else 0));print(path.name,type(e).__name__,flush=True)
   if attempt==4:raise
   time.sleep(2)
def extract(path,target):
 target.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(path) as z:
  for item in z.infolist():
   if not (target/item.filename).resolve().is_relative_to(target.resolve()):raise ValueError('unsafe zip path')
  z.extractall(target)
def blender():
 version='4.5.9';name=f'blender-{version}-windows-x64.zip';base='https://download.blender.org/release/Blender4.5/'
 checksum=download(base+f'blender-{version}.sha256',TOOLS/'downloads'/f'blender-{version}.sha256')
 archive=download(base+name,TOOLS/'downloads'/name)
 expected=next(x.split()[0] for x in checksum.read_text().splitlines() if x.split()[-1].lstrip('*')==name)
 actual=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
 if actual!=expected:raise ValueError('official Blender SHA256 mismatch')
 target=TOOLS/'blender';exe=target/f'blender-{version}-windows-x64/blender.exe'
 if not exe.exists():extract(archive,target)
 write(TOOLS/'BLENDER_READY.json',dict(status='sha256_verified_extracted',executable=str(exe),version=version,archive=str(archive),official_sha256=expected))
 return str(exe)
def sharp():
 archive=download('https://codeload.github.com/apple-aiml-research/ml-sharp/zip/refs/heads/main',TOOLS/'downloads/ml-sharp-main.zip')
 target=TOOLS/'sharp_source'
 if not (target/'ml-sharp-main/pyproject.toml').exists():extract(archive,target)
 weight=download('https://ml-site.cdn-apple.com/models/sharp/sharp_2572gikvuh.pt',MODELS/'sharp_2572gikvuh.pt')
 write(TOOLS/'SHARP_DOWNLOADED.json',dict(source=str(target/'ml-sharp-main'),weight=str(weight),weight_sha256=hashlib.file_digest(weight.open('rb'),'sha256').hexdigest(),weight_bytes=weight.stat().st_size,verification='Official Apple CDN HTTPS and complete Content-Length; local SHA256 recorded, upstream SHA256 not published in README.'))
 return str(weight)
if __name__=='__main__':
 with ThreadPoolExecutor(max_workers=2) as pool:
  results=list(pool.map(lambda fn:fn(),[blender,sharp]))
 write(TOOLS/'DOWNLOAD_RESULT.json',dict(results=results,finished_at=time.time()));print(json.dumps(results),flush=True)
