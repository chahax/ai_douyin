"""Pure presentation of accepted completion requests, never a page/identity probe."""
import math
import time


def feedback(data, account, key, *, now=None):
    now = time.time() if now is None else now
    rows = [r for r in data.get('handling_requests', [])
            if r.get('account_uuid')==account and r.get('account_key')==key
            and type(r.get('requested_at')) in (int,float) and math.isfinite(r['requested_at'])]
    if not rows:
        return None
    request = max(rows,key=lambda r:r['requested_at'])
    status=request.get('status')
    finished=request.get('finished_at')
    endpoint=finished if type(finished) in (int,float) and math.isfinite(finished) else now
    elapsed=max(0,int(endpoint-request['requested_at']))
    if status=='requested':
        message=f'完成请求已受理 · 等待后台核验调度 · 已等待 {elapsed} 秒。请勿重复点击。'
    elif status=='probing':
        message=f'正在核验原账号身份（含原浏览器队列等待）· 本次已用 {elapsed} 秒。核验通过后才会继续。'
    elif status=='completed':
        message=f'本次原身份核验已通过 · 共用 {elapsed} 秒。计划已按原请求接续；实际播放结果另行记录。'
    elif status in ('failed','invalidated'):
        message='本次核验未放行 · '+str(request.get('message') or '请查看原请求记录，账号尚未恢复。')
    else:
        return None
    if status in ('requested','probing') and elapsed>=30:
        message+=' 等待较久；原请求保留，尚未收到结束回执，不表示验证码失败。'
    return {'request_id':request['request_id'],'status':status,'elapsed_seconds':elapsed,'message':message}
