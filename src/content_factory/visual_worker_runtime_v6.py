"""Per-worker Windows venv redirector bypass; no global environment changes."""
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import site
import sys
import time
import uuid

VERSION='python_worker_direct_base_short_temp/v2'
TEMP_ROOT=Path(__file__).resolve().parents[2]/'data'/'visual_worker_runtime'/'temp'


def prepare(command,env,*,platform=None,runtime=None,temp_root=None):
    """Keep argv[0]/venv semantics while CreateProcess targets the real runtime."""
    runtime=runtime or sys;platform=platform or os.name;child_env=dict(env)
    prefix=Path(runtime.prefix).resolve();base_prefix=Path(runtime.base_prefix).resolve()
    metadata=dict(schema=VERSION,mode='ordinary_python',argv0=command[0],expected_prefix=str(prefix),
        expected_base_prefix=str(base_prefix))
    options=dict(env=child_env)
    if platform=='nt':
        original_temp={key:child_env.get(key) for key in ('TEMP','TMP')}
        job=fingerprint(dict(command=list(command),original_temp=original_temp,prefix=str(prefix)))
        root=Path(temp_root if temp_root is not None else TEMP_ROOT).resolve();folder=root/job[:32]
        if len(str(folder))>180:raise ValueError('worker_private_temp_root_must_be_short')
        folder.mkdir(parents=True,exist_ok=True);owner=folder/'TEMP_BINDING.json';binding=dict(schema=VERSION,job_sha256=job)
        if owner.exists():
            if json.loads(owner.read_text(encoding='utf-8'))!=binding:raise ValueError('worker_private_temp_owner_changed')
        else:
            with owner.open('x',encoding='utf-8') as stream:json.dump(binding,stream)
        child_env.update(TEMP=str(folder),TMP=str(folder))
        metadata.update(private_temp=str(folder),private_temp_job_sha256=job,
            original_temp_lengths={key:len(value) if value is not None else None for key,value in original_temp.items()})
    if platform=='nt' and prefix!=base_prefix:
        executable=Path(runtime.executable).resolve();base=Path(runtime._base_executable).resolve()
        if Path(command[0]).resolve()!=executable:raise ValueError('worker_argv0_does_not_match_current_venv')
        cfg=prefix/'pyvenv.cfg'
        if not executable.is_file() or not base.is_file() or not cfg.is_file():raise ValueError('worker_venv_runtime_unconfirmed')
        lines={k.strip().lower():v.strip() for line in cfg.read_text(encoding='utf-8').splitlines()
            if '=' in line for k,v in [line.split('=',1)]}
        if not lines.get('home') or Path(lines['home']).resolve()!=base.parent:
            raise ValueError('worker_base_runtime_does_not_match_venv_home')
        child_env['__PYVENV_LAUNCHER__']=str(executable)
        options['executable']=str(base)
        metadata.update(mode='windows_venv_direct_base',physical_executable=str(base),
            base_executable_sha256=hashlib.sha256(base.read_bytes()).hexdigest(),
            venv_launcher_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
            pyvenv_cfg_sha256=hashlib.sha256(cfg.read_bytes()).hexdigest())
    return options,metadata


def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def save_launch(folder,metadata):
    """Same launch policy can be reused, never overwrite another policy record."""
    path=Path(folder)/'WORKER_LAUNCH.json'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8'))!=metadata:raise ValueError('worker_launch_runtime_policy_changed')
    else:
        with path.open('x',encoding='utf-8') as stream:json.dump(metadata,stream,ensure_ascii=False,indent=2)


def receipt():
    actual=sys.executable
    if os.name=='nt':
        buffer=ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetModuleFileNameW(None,buffer,len(buffer)):raise ctypes.WinError()
        actual=buffer.value
    specs={}
    for name in ('torch','transformers','bitsandbytes','numpy','PIL'):
        found=importlib.util.find_spec(name);specs[name]=found.origin if found else None
    return dict(schema=VERSION,pid=os.getpid(),ppid=os.getppid(),at=time.time(),actual_executable=actual,
        sys_executable=sys.executable,base_executable=sys._base_executable,prefix=sys.prefix,base_prefix=sys.base_prefix,
        site_packages=site.getsitepackages(),package_specs=specs,
        model_packages_imported={name:name in sys.modules for name in ('torch','transformers','bitsandbytes')})


def save_runtime(folder,binding):
    value=receipt();value['request_binding_sha256']=binding;folder=Path(folder)
    primary=folder/'WORKER_RUNTIME.json'
    path=primary if not primary.exists() else folder/('WORKER_RUNTIME_'+uuid.uuid4().hex+'.json')
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
    return value
