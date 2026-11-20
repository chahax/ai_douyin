import asyncio,json,os,sys
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
root=Path('D:/IT/ai_douyin/tools/scene_lab_20261006')
async def probe(kind):
 env=dict(os.environ);env.update({'DO_NOT_TRACK':'1','COMFY_NO_TELEMETRY':'1','NO_PROXY':'127.0.0.1,localhost','no_proxy':'127.0.0.1,localhost'})
 if kind=='blender_mcp':
  cmd=str(root/'envs/blender_mcp/Scripts/mcp-for-blender.exe');env.update({'BLENDER_HOST':'127.0.0.1','BLENDER_PORT':'9878'})
  calls=[('get_scene_info',{})]
 else:
  cmd=str(root/'envs/comfy_mcp/Scripts/comfy-mcp.exe');env.update({'COMFY_BIN':str(root/'envs/comfy_mcp/Scripts/comfy.exe'),'COMFY_LOCAL_URL':'http://127.0.0.1:8192','COMFYUI_URL':'http://127.0.0.1:8192'})
  calls=[('server_info',{}),('validate_workflow',{'workflow_path':str(root/'comfy/workflows/still_office.json')})]
 results={}
 with (root/f'{kind}_handshake_stderr.log').open('w',encoding='utf-8') as err:
  async with stdio_client(StdioServerParameters(command=cmd,args=[],env=env,cwd=str(root)),errlog=err) as (read,write):
   async with ClientSession(read,write) as session:
    init=await asyncio.wait_for(session.initialize(),timeout=70);results['initialize']=init.model_dump(mode='json')
    ts=await session.list_tools();results['tool_names']=[t.name for t in ts.tools]
    for name,args in calls:
     r=await asyncio.wait_for(session.call_tool(name,args),timeout=75);results[name]=r.model_dump(mode='json')
 (root/f'{kind}_HANDSHAKE.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
 print(json.dumps({'kind':kind,'tools':len(results['tool_names']),'results':{n:results[n] for n,_ in calls}},ensure_ascii=False)[:6500],flush=True)
async def main():
 for kind in ['blender_mcp','comfy_mcp']:
  try:await probe(kind)
  except Exception as e:print(kind,type(e).__name__,str(e),flush=True)
asyncio.run(main())
