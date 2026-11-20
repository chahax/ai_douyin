from pathlib import Path
import subprocess,json,datetime
root=Path('tools/scene_lab_20261006').resolve()
uv=Path('C:/Users/c/AppData/Roaming/Python/Python314/Scripts/uv.exe')
import concurrent.futures

def install(kind):
    env=root/'envs'/kind
    subprocess.run([str(uv),'venv',str(env),'--python','C:/Python314/python.exe'],check=True)
    py=env/'Scripts/python.exe'
    if kind=='blender_mcp':
        src=next((root/'sources/ahujasid__blender-mcp').iterdir())
        args=[str(src)]
    else: args=['comfy-mcp==0.10.0','comfy-cli==1.22.0']
    subprocess.run([str(uv),'pip','install','--python',str(py),*args],check=True)
    pkgs=subprocess.check_output([str(uv),'pip','freeze','--python',str(py)],text=True)
    (root/f'INSTALLED_{kind}.txt').write_text(pkgs,encoding='utf-8')
    return {'kind':kind,'python':str(py),'packages':pkgs}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
    results=list(ex.map(install,['blender_mcp','comfy_mcp']))
(root/'MCP_INSTALL_RECEIPT.json').write_text(json.dumps({'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'environments':results,'global_codex_configuration_changed':False},indent=2),encoding='utf-8')
print(json.dumps({'installed':[x['kind'] for x in results]}))
