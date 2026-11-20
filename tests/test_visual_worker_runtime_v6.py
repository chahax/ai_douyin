"""No-model Windows worker identity checks; never execute production requests."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import uuid
import psutil

import pytest

from src.content_factory import visual_worker_runtime_v6 as r


def fake_runtime(tmp_path):
    prefix=tmp_path/'venv';base=tmp_path/'base';(prefix/'Scripts').mkdir(parents=True);base.mkdir()
    exe=prefix/'Scripts/python.exe';exe.write_bytes(b'fixture redirector')
    original=base/'python.exe';original.write_bytes(b'fixture real runtime')
    (prefix/'pyvenv.cfg').write_text('home = '+str(base)+'\n',encoding='utf-8')
    return types.SimpleNamespace(prefix=str(prefix),base_prefix=str(base),executable=str(exe),_base_executable=str(original))


def test_windows_venv_child_uses_base_application_and_preserves_argv_and_parent_env(tmp_path):
    runtime=fake_runtime(tmp_path);command=[runtime.executable,'-B','worker.py'];env={'TEMP':'long-owned-temp','HF_HUB_OFFLINE':'1'}
    before=deepcopy(env);options,receipt=r.prepare(command,env,platform='nt',runtime=runtime,temp_root=tmp_path.parent.parent/'runtime-temp')
    assert options['executable']==runtime._base_executable
    assert options['env']['__PYVENV_LAUNCHER__']==runtime.executable
    assert options['env']['TEMP']==options['env']['TMP'] and len(options['env']['TEMP'])<180
    assert options['env']['TEMP']!='long-owned-temp' and env==before and command[0]==runtime.executable
    assert receipt['mode']=='windows_venv_direct_base' and len(receipt['base_executable_sha256'])==64


@pytest.mark.parametrize('platform,venv',[('posix',True),('nt',False)])
def test_other_runtimes_are_not_redirected(tmp_path,platform,venv):
    runtime=fake_runtime(tmp_path)
    if not venv:runtime.prefix=runtime.base_prefix
    options,receipt=r.prepare([runtime.executable],{'TEMP':'keep'},platform=platform,runtime=runtime,temp_root=tmp_path.parent.parent/'runtime-temp')
    assert 'executable' not in options and '__PYVENV_LAUNCHER__' not in options['env'] and receipt['mode']=='ordinary_python'


@pytest.mark.parametrize('mutation',[
    lambda rt:Path(rt._base_executable).unlink(),
    lambda rt:(Path(rt.prefix)/'pyvenv.cfg').write_text('home = unrelated'),
])
def test_missing_or_wrong_base_runtime_is_not_silently_substituted(tmp_path,mutation):
    runtime=fake_runtime(tmp_path);mutation(runtime)
    with pytest.raises(ValueError):r.prepare([runtime.executable],{},platform='nt',runtime=runtime,temp_root=tmp_path.parent.parent/'runtime-temp')


def test_foreign_argv_and_changed_runtime_receipt_are_rejected(tmp_path):
    runtime=fake_runtime(tmp_path)
    with pytest.raises(ValueError,match='argv0'):r.prepare(['other.exe'],{},platform='nt',runtime=runtime,temp_root=tmp_path.parent.parent/'runtime-temp')
    _,receipt=r.prepare([runtime.executable],{},platform='nt',runtime=runtime,temp_root=tmp_path.parent.parent/'runtime-temp')
    r.save_launch(tmp_path,receipt);original=(tmp_path/'WORKER_LAUNCH.json').read_bytes();r.save_launch(tmp_path,receipt)
    with pytest.raises(ValueError,match='policy_changed'):r.save_launch(tmp_path,dict(receipt,mode='wrong'))
    assert (tmp_path/'WORKER_LAUNCH.json').read_bytes()==original


@pytest.mark.skipif(os.name!='nt' or sys.prefix==sys.base_prefix,reason='Requires the actual project Windows venv.')
@pytest.mark.parametrize('long_request',[False,True])
def test_native_direct_worker_with_long_private_temp_preserves_actual_venv_without_model_import(tmp_path,long_request):
    case=tmp_path/uuid.uuid4().hex;case.mkdir();env_folder=case
    while len(str(env_folder/'TEMP'))<279:env_folder=env_folder/('p'*50)
    env_folder.mkdir(parents=True);temp=env_folder/'TEMP';temp.mkdir();cache=env_folder/'cache'
    folder=case/'job'
    if long_request:
        while len(str(folder/'REQUEST.json'))<279:folder=folder/('q'*50)
    folder.mkdir(parents=True);request=folder/'REQUEST.json';output=folder/'RESULTS.json';request.write_text(json.dumps({'case':case.name}))
    code=('import json,sys;from pathlib import Path;from src.content_factory import visual_worker_runtime_v6 as r;'
        'raw=Path(sys.argv[1]).read_bytes();v=r.receipt();v["request_read_bytes"]=len(raw);'
        'Path(sys.argv[2]).write_text(json.dumps(v))')
    command=[sys.executable,'-B','-c',code,str(request),str(output)]
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HOME=str(cache),HF_MODULES_CACHE=str(cache/'modules'),
        TORCH_HOME=str(cache/'torch'),TEMP=str(temp),TMP=str(temp),PYTHONUTF8='1')
    options,launch=r.prepare(command,env)
    assert len(options['env']['TEMP'])<180 and options['env']['HF_HOME']==env['HF_HOME']
    completed=subprocess.run(command,cwd=Path(__file__).resolve().parents[1],**options,capture_output=True,text=True,
        timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    assert completed.returncode==0,completed.stderr
    receipt=json.loads(output.read_text());assert receipt['request_read_bytes']>0
    assert Path(receipt['actual_executable']).resolve()==Path(sys._base_executable).resolve()
    assert Path(receipt['prefix']).resolve()==Path(sys.prefix).resolve()
    assert Path(receipt['sys_executable']).resolve()==Path(sys.executable).resolve()
    for name in ('torch','transformers','bitsandbytes'):
        assert Path(receipt['package_specs'][name]).is_relative_to(Path(sys.prefix))
        assert receipt['model_packages_imported'][name] is False
    assert receipt['pid']>0 and receipt['ppid']==os.getpid()
    r.save_launch(folder,launch)
    assert json.loads((folder/'WORKER_LAUNCH.json').read_text())['mode']=='windows_venv_direct_base'


def test_private_temp_is_job_bound_and_does_not_change_caches_or_parent_environment(tmp_path):
    runtime=fake_runtime(tmp_path);env=dict(TEMP='x'*290,TMP='y'*290,HF_HOME='keep-long-cache',TORCH_HOME='keep-torch')
    before=deepcopy(env);root=tmp_path.parent.parent/'runtime-temp'
    first,proof=r.prepare([runtime.executable,'job1'],env,platform='nt',runtime=runtime,temp_root=root)
    again,_=r.prepare([runtime.executable,'job1'],env,platform='nt',runtime=runtime,temp_root=root)
    second,_=r.prepare([runtime.executable,'job2'],env,platform='nt',runtime=runtime,temp_root=root)
    assert first['env']['TEMP']==again['env']['TEMP']!=second['env']['TEMP']
    assert first['env']['HF_HOME']==env['HF_HOME'] and first['env']['TORCH_HOME']==env['TORCH_HOME'] and env==before
    assert proof['original_temp_lengths']==dict(TEMP=290,TMP=290)
    owner=Path(first['env']['TEMP'])/'TEMP_BINDING.json';owner.write_text('{}')
    with pytest.raises(ValueError,match='owner_changed'):r.prepare([runtime.executable,'job1'],env,platform='nt',runtime=runtime,temp_root=root)


@pytest.mark.skipif(os.name!='nt' or sys.prefix==sys.base_prefix,reason='Requires the actual project Windows venv.')
def test_native_worker_can_spawn_nvidia_with_short_private_temp_without_importing_models(tmp_path):
    output=tmp_path/'NESTED_RESOURCE.json';private=tmp_path
    while len(str(private/'temp'))<271:private=private/('long_'+uuid.uuid4().hex)
    private.mkdir(parents=True);temp=private/'temp';temp.mkdir()
    env=dict(os.environ,TEMP=str(temp),TMP=str(temp),HF_HOME=str(private/'cache'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    code=('import subprocess,json,sys,os,time;from pathlib import Path;from src.content_factory import visual_worker_runtime_v6 as r;'
        'start=time.monotonic();v=subprocess.run([r"C:\\Windows\\System32\\nvidia-smi.exe","--id=0","--query-gpu=memory.free",'
        '"--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=5,check=True,creationflags=subprocess.CREATE_NO_WINDOW);'
        'out=r.receipt();out.update(seconds=time.monotonic()-start,nvidia_memory_free=v.stdout.strip(),temp=os.environ["TEMP"],hf_home=os.environ["HF_HOME"]);'
        'Path(sys.argv[1]).write_text(json.dumps(out))')
    command=[sys.executable,'-B','-c',code,str(output)];options,launch=r.prepare(command,env)
    process=subprocess.Popen(command,cwd=Path(__file__).resolve().parents[1],**options,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    try:stdout,stderr=process.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        members=[psutil.Process(process.pid)]+psutil.Process(process.pid).children(recursive=True)
        identities=[(member.pid,member.create_time()) for member in members];process.terminate()
        for pid,created in identities:
            try:
                member=psutil.Process(pid)
                if member.create_time()==created:member.terminate()
            except psutil.NoSuchProcess:pass
        psutil.wait_procs(members,timeout=5)
        pytest.fail('Owned no-model nested resource probe exceeded 15 seconds; its family was closed.')
    assert process.returncode==0,stderr
    receipt=json.loads(output.read_text());assert float(receipt['nvidia_memory_free'])>=0 and receipt['seconds']<5
    assert len(receipt['temp'])<180 and receipt['hf_home']==env['HF_HOME']
    assert receipt['model_packages_imported']==dict(torch=False,transformers=False,bitsandbytes=False)
    assert Path(receipt['prefix'])==Path(sys.prefix) and receipt['pid']==process.pid
    assert launch['original_temp_lengths']['TEMP']>=271
