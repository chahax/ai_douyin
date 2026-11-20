import asyncio,json,os,sys,datetime,hashlib
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
root=Path('D:/IT/ai_douyin/tools/scene_lab_20261006');name=sys.argv[1]
contract=json.loads((root/'comfy/EXPERIMENT_CONTRACT.json').read_text());item=next(x for x in contract['planned_jobs'] if x['id']==name)
job=root/'comfy/jobs'/name;job.mkdir(parents=True,exist_ok=True)
intent=job/'SUBMIT_INTENT.json'
with intent.open('x',encoding='utf-8') as f:json.dump({'id':name,'workflow_sha256':item['sha256'],'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'automatic_retry':False,'paid_calls':0},f,indent=2)
async def main():
 env=dict(os.environ);env.update({'COMFY_BIN':str(root/'envs/comfy_mcp/Scripts/comfy.exe'),'COMFY_LOCAL_URL':'http://127.0.0.1:8192','COMFYUI_URL':'http://127.0.0.1:8192','NO_PROXY':'127.0.0.1,localhost','no_proxy':'127.0.0.1,localhost','DO_NOT_TRACK':'1','COMFY_NO_TELEMETRY':'1'})
 assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()==item['sha256']
 with (job/'mcp_stderr.log').open('w',encoding='utf-8') as err:
  async with stdio_client(StdioServerParameters(command=str(root/'envs/comfy_mcp/Scripts/comfy-mcp.exe'),env=env,cwd=str(root)),errlog=err) as (r,w):
   async with ClientSession(r,w) as session:
    await asyncio.wait_for(session.initialize(),timeout=70)
    result=await asyncio.wait_for(session.call_tool('run_workflow',{'workflow_path':item['path'],'wait':False,'confirm_spend':False}),timeout=80)
    receipt=result.model_dump(mode='json');(job/'SUBMIT_RESULT.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False)[:7000],flush=True)
try:asyncio.run(main())
except BaseException as e:
 (job/'SUBMIT_OUTCOME_UNKNOWN.json').write_text(json.dumps({'type':type(e).__name__,'message':str(e),'do_not_resubmit':True,'intent_may_not_have_dispatched':True}),encoding='utf-8');raise
