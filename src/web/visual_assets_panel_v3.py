"""Read-only asset dashboard and explicit administrator media controls."""
from copy import deepcopy
from contextvars import ContextVar
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from src.content_factory import visual_asset_pipeline_v3 as flow
from src.content_factory import visual_asset_registry_v3 as library
from src.content_factory import visual_image_jobs_v3 as images
from src.content_factory.visual_shot_binding_v3 import fingerprint

ROOT=Path(__file__).resolve().parents[2]
BOOK_ID='7302660145530539062'
_RENDER_SCOPE=ContextVar('visual_assets_panel_route_scope',default=None)


def render_route(render_main,root=ROOT):
    """Mount once even when the dashboard module was cached before this panel.

    State lives only in this route invocation, never in a session/global flag.
    Nested wrappers share the scope; the outermost wrapper always restores it.
    """
    state=_RENDER_SCOPE.get();token=None
    if state is None:
        state={'rendered':False};token=_RENDER_SCOPE.set(state)
    try:
        result=render_main()
        if not state['rendered']:render(root)
        return result
    finally:
        if token is not None:_RENDER_SCOPE.reset(token)


def home(root=ROOT):return Path(root).resolve()/'data/visual_asset_pipeline'
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def _admin():
    from src.web.components.auth import get_current_user,get_current_role
    actor,role=get_current_user(),get_current_role()
    if not actor or role not in ('admin','superadmin'):raise PermissionError('运营管理员权限必需')
    return actor,role


def _audit(root,actor,action,**detail):
    event=dict(actor=actor,action=action,at=time.time(),**detail)
    flow.write(home(root)/'audit'/(uuid.uuid4().hex+'.json'),event);return event


def scoped_run(root,run):
    base=home(root)/'runs';path=Path(run).resolve()
    if not path.is_relative_to(base) or path==base or path.parent!=base:raise ValueError('仅允许新资产任务目录')
    return path


def default_config(root=ROOT):
    root=Path(root).resolve();old=root/'data/video_generation/h3_six_children_full_script_recovery_20261104/PAUSE.json'
    service=root/'data/video_generation/h3_six_children_s01_720p_20261102'
    return dict(library=str(root/'data/serial_story_assets'),gpu_lock_root=str(home(root)/'gpu'),protected_pause_path=str(old),
        image_service=dict(service_url='http://127.0.0.1:8190',input_root=str(service/'input'),output_root=str(service/'output'),
                           allowed_prefix='visual_assets_v3',protected_pause_path=str(old)),
        visual_review=dict(provider='transformers_local',model_path=str(root/'.local_models/video_analysis/Qwen3-VL-4B-Instruct'),quantization='nf4',timeout=900,max_tokens=1800),
        max_repair_rounds=2,max_review_attempts=2)


def prepare_current(root=ROOT):
    actor,role=_admin();root=Path(root).resolve();cast=root/'data/image_model_trials/20261106_novel_cast_turnaround'
    packet=flow.packet_from_cast(cast,BOOK_ID)
    # Both original provenance guards run before any image is admitted as a candidate.
    manifest=read(cast/'FINAL_MAP.json')
    if flow.file_sha(cast/'CAST_PLAN.json')!=manifest['cast_plan_sha256']:raise ValueError('cast_plan_changed')
    identity='cast_'+fingerprint(dict(packet=packet,cast_plan_sha256=manifest['cast_plan_sha256'],manifest_sha256=flow.file_sha(cast/'FINAL_MAP.json')))[:24]
    destination=scoped_run(root,home(root)/'runs'/identity)
    imported=library.import_manifest(root/'data/serial_story_assets',cast/'FINAL_MAP.json',book_id=BOOK_ID,verify_native=True)
    flow.prepare(destination,packet,default_config(root))
    # The import has already completed under native provenance validation.
    with images.run_lock(destination,'PANEL.lock'):
        state=read(destination/'STATE.json');state['import_complete']=True;flow.write(destination/'STATE.json',state)
        _audit(root,actor,'prepare_current_cast',run=str(destination),manifest_sha256=imported['manifest_sha256'])
    return dict(status='candidate_imported',run=str(destination),production_approved=False)


def control_run(root,run,paused):
    actor,role=_admin();run=scoped_run(root,run)
    result=flow.set_paused(run,paused,actor=actor,role=role)
    _audit(root,actor,'pause_run' if paused else 'resume_run',run=str(run));return result


def _process(pid):
    import psutil
    try:
        p=psutil.Process(pid)
        return dict(pid=p.pid,create_time=p.create_time(),cmdline=p.cmdline())
    except psutil.NoSuchProcess:return None
    except psutil.AccessDenied:raise ValueError('worker_identity_unreadable') from None


def _token_processes(token):
    import psutil
    found=[]
    for p in psutil.process_iter(['pid','create_time','cmdline']):
        try:
            if token in (p.info.get('cmdline') or []):found.append(dict(pid=p.pid,create_time=p.info['create_time'],cmdline=p.info['cmdline']))
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    return found


def _unlocked_exit(folder,old):
    try:
        with images.run_lock(folder,'EXECUTION.lock'):return dict(status='ended',worker=old,exit_proof='original_pid_exited_and_run_lock_available')
    except images.JobBusyError:return dict(status='outcome_unknown',worker=old,error='run_lock_held')


def worker_state(folder):
    """No writes, process creation, sockets, or model discovery."""
    folder=Path(folder);claim=folder/'WORKER_LAUNCH_CLAIM.json';record=folder/'WORKER.json'
    if not record.exists():
        if not claim.exists():return dict(status='not_started')
        try:
            intent=read(claim);parent=read(folder/'WORKER_PARENT_LAUNCH.json')
            if intent['id']!=parent.get('launch_id'):raise ValueError('launch_token_mismatch')
            live=_process(parent['pid'])
            if live:
                same=abs(live['create_time']-parent['create_time'])<.01 and live['cmdline']==parent['cmdline']
                return dict(status='running' if same else 'outcome_unknown',worker=parent)
            if _token_processes(intent['id']):return dict(status='running',worker=parent)
            return dict(status='ended',worker=parent,exit_proof='parent_exited_no_live_launch_token')
        except (OSError,ValueError,KeyError,TypeError):
            error=folder/'WORKER_LAUNCH_ERROR.json'
            if error.exists() and read(error).get('known_not_started') is True:return dict(status='ended',exit_proof='launch_rejected_before_process_creation')
            return dict(status='outcome_unknown')
    try:
        old=read(record)
        if type(old.get('pid')) is not int or not isinstance(old.get('cmdline'),list):raise ValueError('worker_record_invalid')
        if claim.exists() and old.get('launch_id')!=read(claim)['id']:raise ValueError('worker_launch_token_mismatch')
        if old.get('launch_id') and (claim.exists() or '--launch-id' in old['cmdline']) and old['launch_id'] not in old['cmdline']:raise ValueError('worker_argv_token_mismatch')
        if not any(Path(arg).name in ('run_visual_asset_pipeline_v3.py','run_visual_asset_watch_v3.py') for arg in old['cmdline']):raise ValueError('unexpected_worker_entry')
        if (folder/'PLAN.json').exists() and (old.get('plan_sha256')!=flow.file_sha(folder/'PLAN.json') or str(folder.resolve()) not in old['cmdline']):raise ValueError('worker_plan_binding_changed')
        if folder.parent.name=='watchers' and old.get('policy_sha256','')[:32]!=folder.name:raise ValueError('worker_policy_binding_changed')
        observed=_process(old['pid'])
        if observed:
            same=abs(observed['create_time']-old['create_time'])<.01 and observed['cmdline']==old['cmdline']
            return dict(status='running' if same else 'outcome_unknown',worker=old)
        end=folder/'WORKER_EXIT.json'
        if end.exists():
            receipt=read(end)
            if receipt.get('exit_known') is True and receipt.get('pid')==old['pid'] and abs(receipt.get('create_time',-1)-old['create_time'])<.01:
                return dict(status='ended',worker=old,exit=receipt)
        return dict(status='ended',worker=old,exit_proof='original_worker_pid_exited')
    except (OSError,ValueError,KeyError,TypeError) as error:return dict(status='outcome_unknown',error=str(error))


def _launch(root,folder,args,actor):
    if not Path(args[0]).is_file() or not Path(args[1]).is_file():raise ValueError('asset_worker_entry_unavailable')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with images.run_lock(folder,'WORKER_LAUNCH.lock'):
        prior=worker_state(folder)
        if prior['status']=='running':return dict(status='already_running',worker=prior.get('worker'))
        if prior['status']=='outcome_unknown':raise ValueError('原worker结果未知，保留记录，不重复启动')
        if prior['status']=='ended':
            proof=_unlocked_exit(folder,prior.get('worker'))
            if proof['status']!='ended':raise ValueError('原run锁仍占用，保留记录')
        if (folder/'WORKER_LAUNCH_CLAIM.json').exists():
            history=folder/'worker_history'/uuid.uuid4().hex;history.mkdir(parents=True)
            for name in ('WORKER_LAUNCH_CLAIM.json','WORKER.json','WORKER_EXIT.json','WORKER_PARENT_LAUNCH.json','WORKER_LAUNCH_ERROR.json'):
                p=folder/name
                if p.exists():p.rename(history/name)
        token=uuid.uuid4().hex;args=[*args,'--launch-id',token]
        claim=dict(id=token,cmdline=args,actor=actor,at=time.time())
        flow.freeze(folder/'WORKER_LAUNCH_CLAIM.json',claim)
        _audit(root,actor,'launch_worker_claim',folder=str(folder),claim_id=claim['id'],script=args[1])
        options=dict(cwd=str(Path(root).resolve()),stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if os.name=='nt':
            info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0;options['startupinfo']=info
        process=None
        try:
            with (folder/'WORKER_STDOUT.log').open('ab') as stdout,(folder/'WORKER_STDERR.log').open('ab') as stderr:
                process=subprocess.Popen(args,stdout=stdout,stderr=stderr,**options)
            observed=_process(process.pid)
            if not observed or token not in observed['cmdline'] or args[1] not in observed['cmdline']:raise ValueError('worker_launch_identity_unconfirmed')
            flow.write(folder/'WORKER_PARENT_LAUNCH.json',dict(**observed,launch_id=claim['id']))
            # The interpreter writes its own PID, exact argv and PLAN binding.
            # A Windows venv launcher PID must never overwrite that receipt.
            return dict(status='started',parent=observed,launch_id=token)
        except Exception as error:
            known=process is None and isinstance(error,(FileNotFoundError,PermissionError))
            flow.write(folder/'WORKER_LAUNCH_ERROR.json',dict(type=type(error).__name__,message=str(error),outcome_unknown=not known,known_not_started=known))
            if known:raise ValueError('worker创建被明确拒绝，未创建进程：'+type(error).__name__) from error
            raise ValueError('worker启动回执未知，保留原claim：'+type(error).__name__) from error


def launch_worker(root,run):
    actor,role=_admin();root=Path(root).resolve();run=scoped_run(root,run);status=flow.status(run)
    if status['paused']:raise ValueError('任务已暂停，先明确继续后续')
    args=[str(root/'.venv/Scripts/pythonw.exe'),str(root/'scripts/run_visual_asset_pipeline_v3.py'),'run','--run',str(run),'--operator',actor]
    if not Path(args[0]).is_file() or not Path(args[1]).is_file():raise ValueError('asset_worker_entry_unavailable')
    return _launch(root,run,args,actor)


def resume_run(root,run):
    _admin();control_run(root,run,False)
    return launch_worker(root,run)


def save_policy(root,policy):
    actor,role=_admin();root=Path(root).resolve();policy=deepcopy(policy);policy['actor']=actor
    from scripts.run_visual_asset_watch_v3 import validate_policy
    validate_policy(root,policy)
    path=home(root)/'policies'/(fingerprint(policy)[:32]+'.json');flow.freeze(path,policy)
    _audit(root,actor,'save_media_policy',path=str(path),policy_sha256=fingerprint(policy),enabled=policy['enabled'])
    return str(path)


def control_watch(root,paused):
    actor,role=_admin();path=home(root)/'PAUSE.json'
    event=_audit(root,actor,'pause_text_handoff' if paused else 'resume_text_handoff')
    if paused:flow.write(path,event)
    else:path.unlink(missing_ok=True)
    return event


def launch_watch(root,policy_path,*,execute=False):
    actor,role=_admin();root=Path(root).resolve();path=Path(policy_path).resolve()
    if path.parent!=home(root)/'policies':raise ValueError('policy_outside_asset_root')
    policy=read(path)
    from scripts.run_visual_asset_watch_v3 import validate_policy
    validate_policy(root,policy)
    if policy.get('enabled') is not True or (home(root)/'PAUSE.json').exists():raise ValueError('文本接入未启用或已暂停')
    folder=home(root)/'watchers'/fingerprint(policy)[:32]
    args=[str(root/'.venv/Scripts/pythonw.exe'),str(root/'scripts/run_visual_asset_watch_v3.py'),'--policy',str(path),'--watch']
    if execute:args.append('--execute')
    return _launch(root,folder,args,actor)


def resume_watch(root):
    _admin();control_watch(root,False);result=[]
    # Only resume previously launched policies, with their previous execution mode.
    for p in sorted((home(root)/'policies').glob('*.json')):
        policy=read(p);folder=home(root)/'watchers'/fingerprint(policy)[:32]
        if policy.get('enabled') is not True:continue
        record=folder/'WORKER_LAUNCH_CLAIM.json'
        if not record.exists():record=folder/'WORKER.json'
        if not record.exists():continue
        args=read(record).get('cmdline',[])
        result.append(dict(policy=str(p),result=launch_watch(root,p,execute='--execute' in args)))
    return result


def snapshot(root=ROOT):
    root=Path(root).resolve();base=home(root);result=dict(runs=[],assets=[],policies=[],errors=[],watch_paused=(base/'PAUSE.json').exists())
    for p in sorted((base/'runs').glob('*/PLAN.json')):
        try:
            run=scoped_run(root,p.parent);status=flow.status(run);plan=status['plan'];state=status['state']
            readiness=flow._requirements_status(plan)
            missing=[dict(r,readiness=kind) for kind in ('missing','pending','rejected','errors') for r in readiness[kind]]
            job_rows=[]
            for jid,j in state.get('jobs',{}).items():
                native=Path(j['folder']).resolve()/'STATE.json'
                if not native.is_relative_to(run/'image_jobs'):raise ValueError('image_job_outside_bound_run')
                item=read(native) if native.is_file() else {}
                job_rows.append(dict(id=jid,status=item.get('status','not_started'),prompt_id=item.get('prompt_id'),kind=j.get('kind')))
            direct=flow.reference_delivery(plan['config'])
            h3=None;h3_path=root/'data/video_generation'/('visual_h3_ref_v20' if direct else 'visual_h3_v3')/run.name
            if (h3_path/'PLAN.json').exists():
                try:
                    if direct:
                        from src.content_factory.visual_h3_reference_delivery_v20 import status as h3_status
                    else:
                        from src.content_factory.visual_h3_handoff_v3 import status as h3_status
                    h3_plan=read(h3_path/'PLAN.json')
                    if Path(h3_plan['asset_run']).resolve()!=run:raise ValueError('new_h3_asset_binding_changed')
                    h3=dict(path=str(h3_path),**h3_status(h3_path))
                except (OSError,ValueError,TypeError,KeyError) as error:h3=dict(path=str(h3_path),status='unavailable',error=str(error))
            result['runs'].append(dict(path=str(run),book_id=plan['packet']['book_id'],status=state.get('status'),paused=status['paused'],worker=worker_state(run),
                missing=missing,jobs=job_rows,reviews=state.get('reviews',{}),error=state.get('error'),characters=plan['packet']['characters'],h3_handoff=h3))
        except (ValueError,OSError,KeyError,TypeError) as error:result['errors'].append(dict(path=str(p),error=str(error)))
    index=root/'data/serial_story_assets/INDEX.json'
    if index.exists():
        try:
            books=sorted({a['book_id'] for a in read(index)['assets']})
            for book in books:result['assets'].extend(library.get(index.parent,book_id=book,verify_file=False))
        except (ValueError,OSError,KeyError,TypeError) as error:result['errors'].append(dict(path=str(index),error=str(error)))
    for p in sorted((base/'policies').glob('*.json')):
        try:
            policy=read(p);folder=base/'watchers'/fingerprint(policy)[:32]
            result['policies'].append(dict(path=str(p),policy=policy,worker=worker_state(folder),latest=read(folder/'LATEST.json') if (folder/'LATEST.json').exists() else None))
        except (ValueError,OSError) as error:result['errors'].append(dict(path=str(p),error=str(error)))
    return result


def render(root=ROOT):
    state=_RENDER_SCOPE.get()
    if state is not None:
        if state['rendered']:return
        state['rendered']=True
    import streamlit as st
    from src.web.components.auth import get_current_user,get_current_role
    actor,role=get_current_user(),get_current_role();admin=bool(actor and role in ('admin','superadmin'))
    with st.expander('人物、环境与首帧自动化',expanded=True):
        data=snapshot(root);st.caption('候选导入、视觉审核和首帧生成独立运行；原H3视频任务保持暂停。查看页面不派发任务。')
        for error in data['errors']:st.error(str(error))
        if st.button('导入当前九人81张候选并建立任务',disabled=not admin,key='visual_import_current'):
            try:st.success(str(prepare_current(root)))
            except Exception as e:st.error(str(e))
        rows=data['assets'];books=sorted({r['book_id'] for r in rows})
        if books:
            book=st.selectbox('资产书籍',books,key='visual_book');rows=[r for r in rows if r['book_id']==book]
            person=st.selectbox('人物或地点',['全部']+sorted({r['entity_id'] for r in rows}),key='visual_entity')
            view=st.selectbox('视图',['全部']+sorted({r['view'] for r in rows}),key='visual_view')
            status=st.selectbox('资产状态',['全部']+sorted({r['status'] for r in rows}),key='visual_status')
            visible=[r for r in rows if (person=='全部' or r['entity_id']==person) and (view=='全部' or r['view']==view) and (status=='全部' or r['status']==status)]
            st.dataframe([{k:r.get(k) for k in ('entity_id','kind','view','version','status','sha256')} for r in visible],use_container_width=True)
            for r in visible[:12]:
                path=(Path(root)/'data/serial_story_assets'/r['file']).resolve()
                if path.is_relative_to((Path(root)/'data/serial_story_assets').resolve()) and path.is_file():st.image(str(path),caption=f"{r['entity_id']} · {r['view']} · {r['status']}",width=180)
        else:st.info('资产库尚未导入。当前81张均为候选，不等于制作批准。')
        if data['runs']:
            selected=st.selectbox('资产任务',[r['path'] for r in data['runs']],key='visual_run');row=next(r for r in data['runs'] if r['path']==selected)
            st.write(dict(status=row['status'],paused=row['paused'],worker=row['worker']['status'],missing_views=len(row['missing'])))
            st.dataframe(row['missing'],use_container_width=True);st.dataframe(row['jobs'],use_container_width=True)
            if row['reviews']:st.json(row['reviews'],expanded=False)
            if row['error']:st.error(str(row['error']))
            if row['h3_handoff']:
                st.caption('新H3接续计划（独立目录，视频派发默认关闭）')
                st.json(row['h3_handoff'],expanded=False)
            for label,action in [('暂停后续资产任务',lambda:control_run(root,selected,True)),('继续后续资产任务',lambda:resume_run(root,selected)),('启动资产执行器',lambda:launch_worker(root,selected))]:
                if st.button(label,disabled=not admin,key='visual_'+label):
                    try:st.success(str(action()))
                    except Exception as e:st.error(str(e))
        with st.expander('独立文本接入策略（默认关闭）'):
            st.caption('仅接入已落盘、非模拟、通过文本审核的集数。执行器不会修改原文本授权。')
            text=st.text_area('独立媒体策略 JSON',value='{"schema":"visual_media_policy/v3","enabled":false}',key='visual_policy_json',disabled=not admin)
            if st.button('保存独立文本接入策略',disabled=not admin,key='visual_save_policy'):
                try:st.success(save_policy(root,json.loads(text)))
                except Exception as e:st.error(str(e))
            if data['policies']:
                policy=st.selectbox('已保存策略',[p['path'] for p in data['policies']],key='visual_saved_policy')
                selected_policy=next(p for p in data['policies'] if p['path']==policy)
                st.write(dict(enabled=selected_policy['policy'].get('enabled'),paused=data['watch_paused'],worker=selected_policy['worker']['status']))
                if selected_policy['latest']:st.json(selected_policy['latest'],expanded=False)
                execute=st.checkbox('接入后自动执行新资产任务',value=False,disabled=not admin,key='visual_watch_execute')
                if st.button('启动文本接入执行器',disabled=not admin,key='visual_start_watch'):
                    try:st.success(str(launch_watch(root,policy,execute=execute)))
                    except Exception as e:st.error(str(e))
            for label,paused in [('暂停文本自动接入',True),('继续文本自动接入',False)]:
                if st.button(label,disabled=not admin,key='visual_'+label):
                    try:st.success(str(control_watch(root,True) if paused else resume_watch(root)))
                    except Exception as e:st.error(str(e))
