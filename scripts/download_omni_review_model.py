"""Download pinned public model files with range and SHA256 validation."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1] / '.local_models/video_analysis/Qwen2.5-Omni-3B'
ROOT.mkdir(parents=True, exist_ok=True)
meta = requests.get('https://modelscope.cn/api/v1/models/Qwen/Qwen2.5-Omni-3B/repo/files?Revision=master&Recursive=true', timeout=30).json()['Data']['Files']
(ROOT / 'download_manifest.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def part(row, start, end):
    path = ROOT / (row['Name'] + f'.range_{start}_{end}')
    if path.exists() and path.stat().st_size == end-start+1:
        return path
    url = f"https://modelscope.cn/models/Qwen/Qwen2.5-Omni-3B/resolve/master/{row['Path']}"
    for attempt in range(3):
        try:
            with requests.get(url, headers={'Range':f'bytes={start}-{end}'}, stream=True, timeout=60) as response:
                response.raise_for_status()
                full = response.status_code == 200 and start == 0 and end == row['Size']-1
                if not full and (response.status_code != 206 or response.headers.get('Content-Range') != f"bytes {start}-{end}/{row['Size']}"):
                    raise ValueError('Range response mismatch')
                with path.open('wb') as stream:
                    for chunk in response.iter_content(1024*1024):
                        stream.write(chunk)
            if path.stat().st_size != end-start+1:
                raise ValueError('Incomplete range')
            return path
        except Exception:
            if attempt == 2:
                raise

for row in meta:
    if row['Type'] != 'blob':
        continue
    dest = ROOT / row['Name']
    if dest.exists() and dest.stat().st_size == row['Size'] and sha(dest) == row['Sha256']:
        continue
    size = row['Size']
    chunk = 8*1024*1024 if size > 100_000_000 else size
    ranges = [(s, min(size-1,s+chunk-1)) for s in range(0,size,chunk)]
    print('Downloading', row['Name'], size, flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        parts = list(pool.map(lambda se:part(row,*se), ranges))
    temp = dest.with_suffix(dest.suffix+'.verified_download')
    with temp.open('wb') as output:
        for path in parts:
            with path.open('rb') as stream:
                while block := stream.read(8*1024*1024):
                    output.write(block)
    if sha(temp) != row['Sha256']:
        raise ValueError('SHA256 mismatch for '+row['Name'])
    temp.replace(dest)
    for path in parts:
        path.unlink()
    print('Verified', row['Name'], flush=True)
print('Model ready', flush=True)
