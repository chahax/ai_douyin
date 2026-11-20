"""Bounded resumable official Blender download; replaces stopped shared downloader."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,urllib.request,hashlib,zipfile,time

R=Path(__file__).resolve().parents[1]/'data/tools/spatial_20261107'
URL='https://mirrors.tuna.tsinghua.edu.cn/blender/release/Blender4.5/blender-4.5.9-windows-x64.zip'
SIZE=399051129
def part(index):
 start=index*(SIZE//8);end=(index+1)*(SIZE//8)-1 if index<7 else SIZE-1
 p=R/'downloads/blender_parts'/f'{index:02d}.part';p.parent.mkdir(parents=True,exist_ok=True)
 for attempt in range(5):
  have=p.stat().st_size if p.exists() else 0
  if have==end-start+1:return p
  try:
   req=urllib.request.Request(URL,headers={'Range':f'bytes={start+have}-{end}'})
   with urllib.request.urlopen(req,timeout=60) as r:
    if r.status!=206 or r.headers.get('Content-Range')!=f'bytes {start+have}-{end}/{SIZE}':raise ValueError('range response mismatch')
    with p.open('ab') as f:
     while c:=r.read(1024*1024):f.write(c)
   if p.stat().st_size!=end-start+1:raise ValueError('range incomplete')
   print('part_complete',index,p.stat().st_size,flush=True);return p
  except Exception as e:
   print('part_error',index,attempt,repr(e),flush=True)
   if attempt==4:raise
   time.sleep(2)
if __name__=='__main__':
 with ThreadPoolExecutor(max_workers=8) as pool:parts=list(pool.map(part,range(8)))
 final=R/'downloads/blender-4.5.9-windows-x64.zip'
 with final.open('wb') as out:
  for p in parts:
   with p.open('rb') as f:
    while c:=f.read(4*1024*1024):out.write(c)
 expected=next(line.split()[0] for line in (R/'downloads/blender-4.5.9.sha256').read_text().splitlines() if line.split()[-1].lstrip('*')==final.name)
 actual=hashlib.file_digest(final.open('rb'),'sha256').hexdigest()
 if actual!=expected:raise ValueError('official SHA256 mismatch')
 target=R/'blender';target.mkdir(exist_ok=True)
 with zipfile.ZipFile(final) as z:
  for x in z.infolist():
   if not (target/x.filename).resolve().is_relative_to(target.resolve()):raise ValueError('unsafe zip')
  z.extractall(target)
 v=dict(status='sha256_verified_extracted',executable=str(target/'blender-4.5.9-windows-x64/blender.exe'),version='4.5.9',archive=str(final),official_sha256=expected)
 (R/'BLENDER_READY.json').write_text(json.dumps(v,indent=2),encoding='utf-8');print(json.dumps(v),flush=True)
