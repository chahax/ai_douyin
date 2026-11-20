from pathlib import Path
import subprocess,socket,json,datetime
root=Path('tools/scene_lab_20261006').resolve();app=Path('D:/IT/AI_vido/ComfyUI'); port=8192
with socket.socket() as s:
    if s.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('experiment port already used; do not replace server')
for p in ['input','output','user','logs']:(root/'comfy'/p).mkdir(parents=True,exist_ok=True)
yml=root/'comfy/extra_models.yaml'
yml.write_text('scene_lab:\n  base_path: '+str(root).replace('\\','/')+'/models\n  diffusion_models: diffusion_models\n',encoding='utf-8')
args=[str(app/'.venv/Scripts/python.exe'),'-u',str(app/'main.py'),'--listen','127.0.0.1','--port',str(port),'--disable-auto-launch','--disable-all-custom-nodes','--cache-none','--reserve-vram','1.5','--user-directory',str(root/'comfy/user'),'--input-directory',str(root/'comfy/input'),'--output-directory',str(root/'comfy/output'),'--extra-model-paths-config',str(yml)]
with (root/'comfy/logs/stdout.log').open('wb') as o,(root/'comfy/logs/stderr.log').open('wb') as e:
 p=subprocess.Popen(args,cwd=app,stdout=o,stderr=e,stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
receipt={'pid':p.pid,'args':args,'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'endpoint':f'http://127.0.0.1:{port}','production_environment_modified':False,'new_dependencies_in_comfy':False,'paid_calls':0}
(root/'comfy/SERVER_START.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(json.dumps(receipt))
