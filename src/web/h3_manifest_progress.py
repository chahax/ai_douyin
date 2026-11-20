"""Render scoped H3 receipts, monitor health and manual administration actions."""
import json
import re
import time
from math import isfinite
from pathlib import Path


def read(path):
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('记录格式错误')
    return value


def _supervisor_process_alive(row):
    import psutil
    try:
        process=psutil.Process(row['pid'])
        return abs(process.create_time()-row['create_time'])<.01 and process.cmdline()==row['cmdline']
    except (psutil.NoSuchProcess,psutil.AccessDenied,KeyError,TypeError):
        return False


def load_supervisor(home,now=None,process_alive=None):
    now=time.time() if now is None else now
    path=Path(home)/'STATE.json'
    if not path.exists():return dict(status='not_started',protected=False,label='持久监护尚未启动')
    try:
        state=read(path)
        heartbeat=state.get('heartbeat_epoch')
        if (type(heartbeat) not in (int,float) or not isfinite(heartbeat)
                or type(now) not in (int,float) or not isfinite(now) or heartbeat<0):
            raise ValueError('心跳时间无效')
        age=now-heartbeat
        fresh=0<=age<=90
        alive=(process_alive or _supervisor_process_alive)(state.get('supervisor',{}))
        active=state.get('status') in ('starting','monitoring','recovering','waiting_gpu','backoff')
        protected=bool(fresh and alive and active)
        labels={'starting':'监护启动中','monitoring':'监护在线，正在跟踪原生成进程','recovering':'监护在线，正在恢复原任务',
                'waiting_gpu':'监护在线，等待GPU队列','backoff':'监护在线，退避等待恢复','complete':'批次技术收存完成，监护已停止；内容仍须审核',
                'paused':'监护已暂停','blocked':'自动恢复已阻塞','configuration_changed':'冻结配置变化，恢复已停止',
                'restart_exhausted':'连续恢复失败，已停止重启','crashed':'监护异常退出，等待ensure恢复'}
        label=labels.get(state.get('status'),'监护状态未知')
        if active and not protected:
            label='未受持久监护保护：'+('心跳时间待核对' if age<0 else '心跳已过期' if not fresh else '监护进程身份未确认')
        return dict(status=state.get('status'),protected=protected,label=label,heartbeat_age_seconds=round(age,1),
                    reason=state.get('reason'),next_retry_epoch=state.get('next_retry_epoch') or state.get('next_launch_epoch'),
                    last_error=state.get('last_error'))
    except (OSError,ValueError,TypeError,KeyError) as error:
        return dict(status='unavailable',protected=False,label='监护证据无法读取，不能确认保护状态',reason=str(error))



from src.web.h3_recovery_control import NEW, OLD, approved, digest


def recovery_segment(folder, item):
    name = item['id']
    if item.get('prior'):
        old = folder.parent/OLD
        segment = (old/name).resolve()
        receipt = segment/'receipt.json'
        if (not segment.is_relative_to(old) or Path(item['prior']['path']).resolve()!=receipt
                or digest(receipt)!=item['prior']['sha256']):
            raise ValueError('原分段回执绑定异常')
        return segment, None
    marker = folder/'segments'/name/'STATE.json'
    if not marker.is_file():
        return None, None
    row = read(marker)
    segment = Path(row['folder']).resolve()
    allowed = [folder/k/name for k in ('A0','A1','original_capture')]
    if segment not in allowed:
        raise ValueError('记录指向未授权分段目录')
    return segment, row


def load(folder):
    folder=Path(folder).resolve()
    plan,state=read(folder/'PLAN.json'),read(folder/'STATE.json')
    recovery=plan.get('schema')=='h3_restart_continuation/v1'
    if recovery:
        approved(folder)
    elif plan.get('schema')!='h3_full_script_manifest/v1':
        raise ValueError('不支持的清单类型')
    rows,errors,seen=[],[],set()
    for item in plan['segments']:
        name=item['id']
        if not isinstance(name,str) or not re.fullmatch(r'F\d+',name) or name in seen:
            raise ValueError('分段编号无效或重复')
        seen.add(name)
        row=dict(id=name,status='prepared',video=None,completed=False,prompt_id=None)
        rows.append(row)
        try:
            segment,cursor=recovery_segment(folder,item) if recovery else (folder/name,None)
            if segment is None:
                continue
            if segment.is_symlink():
                raise ValueError('分段目录不能为符号链接')
            if cursor and cursor['status']!='saved':
                row.update(status=cursor['status'],prompt_id=cursor.get('prompt_id'))
                continue
            value=read(segment/'STATE.json')
            row.update(status=value['status'],prompt_id=value.get('prompt_id'))
            if value['status']=='saved':
                receipt=read(segment/'receipt.json')
                video=Path(receipt['delivery']['path']).resolve()
                if (receipt.get('technical_status')!='succeeded' or not row['prompt_id']
                    or receipt.get('prompt_id')!=row['prompt_id'] or cursor and cursor.get('prompt_id')!=row['prompt_id']
                    or not video.is_relative_to(segment) or video.suffix.lower()!='.mp4' or not video.is_file()):
                    raise ValueError('成功回执或本地视频不匹配')
                row.update(completed=True,video=video)
        except (OSError,ValueError,KeyError,TypeError) as error:
            row['status']='unavailable'
            errors.append(f'{name}：{error}')
    return dict(state=state,rows=rows,errors=errors,completed=sum(r['completed'] for r in rows),total=len(rows),
                recovery=recovery,minutes=sum(x['frames'] for x in plan['segments'])/24/60)


def service_status(home):
    value=read(home/'STATE.json')
    age=time.time()-float(value['heartbeat_epoch'])
    fresh=0<=age<=90 and _supervisor_process_alive(value.get('guard',{}))
    return value['status'],fresh,age,value.get('reason') or value.get('observation',{}).get('reason')


def show_controls(st,folder):
    from src.web.components.auth import get_current_user,get_current_role,has_permission
    from src.web.h3_recovery_control import control
    user=get_current_user()
    if not user or not has_permission(get_current_role(),'admin'):
        return
    try:
        marker=folder/'PAUSE.json'
        if marker.exists():
            pause=read(marker)
            st.warning('存在暂停标记，已提交的 GPU 任务可继续执行。')
            if pause.get('source')!='h3_dashboard':
                st.caption('此暂停由其他操作创建。')
                return
            action='resume'
            pressed=st.button('继续原批次',key='h3_resume_'+str(pause.get('id')))
        else:
            pause={}
            action='pause'
            pressed=st.button('暂停后续派发',key='h3_pause',disabled=read(folder/'STATE.json').get('status') not in ('running','prepared'))
            st.caption('调度器在下次轮询时处理暂停；已提交的当前段继续生成。')
        if pressed:
            st.success(control(folder,action,get_current_user(),get_current_role(),pause.get('id')))
            st.rerun()
    except (ValueError,OSError,KeyError,TypeError) as error:
        st.warning(f'未执行操作或正在等待原执行器退出：{error}')


def render(root):
    import streamlit as st
    parent=Path(root)/'data/video_generation'
    folder=parent/NEW if (parent/NEW/'PLAN.json').is_file() else parent/OLD
    if not (folder/'PLAN.json').is_file():
        return
    st.subheader('完整前三章 · 本地 MiniMax H3')
    @st.fragment(run_every=30)
    def live_panel():
        show_status(st,root,folder)
    live_panel()
    try:
        data=load(folder)
    except (OSError,ValueError,KeyError,TypeError) as error:
        st.error(f'完整稿进度无法读取：{error}')
        return
    if data['recovery']:
        show_controls(st,folder)
    completed={r['id']:r['video'] for r in reversed(data['rows']) if r['completed']}
    if completed:
        latest=next(iter(completed))
        st.caption('最近保存的分段 '+latest)
        st.code(str(completed[latest]),language=None)
        selected=st.selectbox('选择已保存分段',list(completed),key='h3_complete_segment')
        if st.button('打开所选分段',key='h3_open_segment'):
            st.session_state['h3_opened_segment']=selected
        if selected==st.session_state.get('h3_opened_segment'):
            path=completed[selected]
            st.video(str(path),autoplay=False)
            st.download_button('下载所选分段',path.read_bytes(),file_name=path.name,key='h3_download_segment')
    with st.expander('全部分段'):
        st.dataframe([{'分段':r['id'],'状态':r['status'],'已保存':r['completed']} for r in data['rows']],hide_index=True)


def show_status(st,root,folder):
    try:
        data=load(folder)
    except (OSError,ValueError,KeyError,TypeError) as error:
        st.error(f'完整稿进度无法读取：{error}')
        return
    st.progress(data['completed']/max(1,data['total']),text=f"已保存 {data['completed']} / {data['total']} 段")
    state=data['state']
    active=next((r for r in data['rows'] if r['id']==state.get('active_segment')), {})
    labels={'running':'执行中','prepared':'准备就绪','stopped':'已停止','blocked':'阻塞','saved':'已保存','paused':'暂停'}
    st.write(f"批次状态 {labels.get(state.get('status'),state.get('status'))} · 当前段 {active.get('id','—')} · 计划时长 {data['minutes']:.1f} 分钟")
    if active.get('prompt_id'):
        st.caption('当前段提交 ID  '+active['prompt_id'])
    home=Path(root)/'data/h3_supervision'
    supervisor=load_supervisor(folder/'supervision' if data['recovery'] else home/'full_script_20261103')
    (st.info if supervisor['protected'] else st.warning)(supervisor['label'])
    if 'heartbeat_age_seconds' in supervisor:
        st.caption(f"调度监护心跳距今 {supervisor['heartbeat_age_seconds']:.0f} 秒 · {supervisor.get('reason') or '—'}")
    try:
        status,fresh,age,reason=service_status(home/'service_8190_20261104')
        (st.info if fresh and status=='ready' else st.warning)(f"8190 服务守护 {status} · 心跳距今 {age:.0f} 秒 · "+ ('进程身份已核对' if fresh else '未确认在线') + f" · {reason or '—'}")
    except (OSError,ValueError,KeyError,TypeError) as error:
        st.warning(f'无法确认服务守护状态：{error}')
    if state.get('error'):
        st.error(state['error'])
    waitfile=folder/'WAIT.json'
    if waitfile.exists():
        try:
            wait=read(waitfile)
            if wait.get('segment')==active.get('id'):
                st.caption(f"最近轮询记录 {wait.get('at')} · {wait.get('reason')}")
        except (OSError,ValueError) as error:
            st.warning(str(error))
    for error in data['errors']:
        st.warning(error)

