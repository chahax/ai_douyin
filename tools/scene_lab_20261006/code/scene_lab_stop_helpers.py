from pathlib import Path
import json,datetime,psutil,httpx
root=Path('D:/IT/ai_douyin/tools/scene_lab_20261006')
with httpx.Client(trust_env=False,timeout=10) as c:
 q=c.get('http://127.0.0.1:8192/queue').json();assert not q['queue_running'] and not q['queue_pending'],'do not stop pending jobs'
results=[]
for kind,path in [('comfy',root/'comfy/SERVER_START.json'),('blender',root/'BLENDER_MCP_PROCESS.json')]:
 r=json.loads(path.read_text(encoding='utf-8-sig'));pid=r['pid']
 try:
  p=psutil.Process(pid);cmd=' '.join(p.cmdline()).replace('\\','/').lower()
  if kind=='comfy':assert 'scene_lab_20261006/comfy/user' in cmd and '--port 8192' in cmd
  else:assert 'scene_lab_20261006/blender/blender-4.5.14-windows-x64/blender.exe' in cmd and 'scene_lab_blender_mcp_ui.py' in cmd
  p.terminate();p.wait(timeout=10);results.append({'kind':kind,'pid':pid,'stopped_owned_helper':True})
 except psutil.NoSuchProcess:results.append({'kind':kind,'pid':pid,'already_exited':True})
(root/'HELPER_STOP_RECEIPT.json').write_text(json.dumps({'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'queue_confirmed_empty':True,'results':results},indent=2),encoding='utf-8')
print(json.dumps(results))
