"""Manual pause/resume of one reviewed H3 batch. No network or media dispatch."""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid



OLD = 'h3_six_children_full_script_20261102'
NEW = 'h3_six_children_full_script_recovery_20261104'


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approved(folder):
    review = load_json(folder/'PRIMARY_REVIEW.json')
    value = digest(folder/'PLAN.json')
    if folder.name != NEW or review.get('approved') is not True or review.get('config_sha256') != value:
        raise ValueError('接续清单与主审回执不匹配')
    return value


def live_runner(folder):
    import psutil
    script = folder.parents[2]/'scripts/h3_restart_continuation_20261104.py'
    for proc in psutil.process_iter(['name']):
        if 'python' not in (proc.info['name'] or '').lower():
            continue
        try:
            args = proc.cmdline()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as error:
            raise PermissionError('无法确认原执行器身份，请稍后刷新') from error
        if str(script) in args and 'execute' in args and str(folder) in args:
            return True
    return False


def fingerprints(folder, segment):
    records = {}
    for parent in ('A0','A1','original_capture'):
        attempt = folder/parent/segment
        state = load_json(attempt/'STATE.json') if (attempt/'STATE.json').is_file() else {}
        response = load_json(attempt/'SUBMISSION_RESPONSE.json') if (attempt/'SUBMISSION_RESPONSE.json').is_file() else {}
        task = state.get('prompt_id') or response.get('prompt_id')
        if state.get('status') in ('failed','request_rejected','cancelled') or (attempt/'SUBMISSION_CLAIM.json').exists() and not task:
            raise ValueError('该分段已有失败或无 ID 的未决提交，保留原状态')
        if response and response.get('prompt_id') != task:
            raise ValueError('原任务 ID 与回执不一致')
        if task:
            records[parent+'/prompt_id'] = task
        for name in ('SUBMISSION_CLAIM.json','SUBMISSION_RESPONSE.json','receipt.json'):
            if (attempt/name).is_file():
                records[parent+'/'+name] = digest(attempt/name)
    return records


def control(folder, action, user, role, expected_pause=None):
    from src.content_factory.assistant_seedance_batch import process_lock, durable
    from src.web.components.auth import has_permission
    if not user or not has_permission(role, 'admin'):
        raise PermissionError('仅已登录管理员可操作')
    folder = Path(folder).resolve()
    plan_hash = approved(folder)
    audit = folder/'dashboard_controls'
    audit.mkdir(exist_ok=True)
    marker = folder/'PAUSE.json'
    with process_lock(audit/'.control.lock'):
        state = load_json(folder/'STATE.json')
        segment = state.get('active_segment')
        if segment not in {s['id'] for s in load_json(folder/'PLAN.json')['segments']}:
            raise ValueError('任务已结束或活动分段不明确')
        if action == 'pause':
            if state.get('status') not in ('running','prepared') or marker.exists():
                raise ValueError('任务当前不能新增暂停')
            pause = dict(id=uuid.uuid4().hex, source='h3_dashboard', plan=plan_hash, segment=segment,
                         actor=user, at=time.time(), before=state, anchors=fingerprints(folder,segment))
            op = audit/pause['id']
            op.mkdir()
            durable(op/'PAUSE_REQUEST.json', pause, immutable=True)
            durable(op/'marker.tmp', pause, immutable=True)
            (op/'marker.tmp').rename(marker)
            return '暂停请求已登记，已提交的 GPU 任务继续运行。'
        if action != 'resume':
            raise ValueError('未知操作')
        pause = load_json(marker)
        if not expected_pause or not isinstance(expected_pause,str) or len(expected_pause)!=32 or any(c not in '0123456789abcdef' for c in expected_pause):
            raise ValueError('缺少有效的原暂停编号')
        op = audit/expected_pause
        if (pause.get('id')!=expected_pause or pause.get('source')!='h3_dashboard' or pause.get('plan')!=plan_hash
                or load_json(op/'PAUSE_REQUEST.json')!=pause):
            raise ValueError('本页只能解除本页签发的同一次暂停')
        with process_lock(folder/'.execute.lock'):
            if live_runner(folder):
                raise ValueError('原执行器正在退出，请稍后刷新')
            state=load_json(folder/'STATE.json')
            if state.get('status')=='saved':
                raise ValueError('完整片已完成')
            if state.get('status')=='blocked' and state.get('error')!='manual_pause':
                raise ValueError('保留其他阻塞或未知任务')
            if state.get('status') not in ('running','prepared','paused','blocked'):
                raise ValueError('当前状态无法从人工暂停恢复')
            now=fingerprints(folder,pause['segment'])
            if any(now.get(k)!=v for k,v in pause['anchors'].items()):
                raise ValueError('原提交或交付回执发生变化')
            active=state.get('active_segment')
            if active != segment:
                raise ValueError('运行状态切换，请刷新')
            fingerprints(folder,active)
            current=dict(state)
            if current.get('status')=='blocked':
                current.update(status='paused')
                current.pop('error')
            record=dict(pause_id=expected_pause,actor=user,at=time.time(),before=state,after=current)
            durable(op/(uuid.uuid4().hex+'_RESUME_INTENT.json'),record,immutable=True)
            if state != current:
                durable(folder/'STATE.json',current)
            marker.rename(op/'RELEASED_PAUSE.json')
            return '已解除这次暂停，等待计划任务接续原进度。'



