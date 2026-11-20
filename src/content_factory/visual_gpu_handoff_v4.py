"""Idle-Comfy to external-VLM memory handoff, called under both GPU leases.

No inference, service restart or parameter mutation. A POST without a definitive
acknowledgement is retained and blocks successors; it is never automatically sent
again. Comfy's /free acknowledges a flag, so measured headroom is also required.
"""
import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

from . import visual_image_jobs_v3 as jobs
from .visual_shot_binding_v3 import fingerprint
from ..trend_intelligence.content_analysis.resource_policy import probe_resources

POLICY='release_comfy_before_review'
MIN_RAM_GIB=6
MIN_VRAM_GIB=5
WAIT_SECONDS=30
POLL_SECONDS=.25


class GpuHandoffUnknown(ValueError):pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('gpu_handoff_redirect_refused')


def enabled(config):
    value=config.get(POLICY,False)
    if type(value) is not bool:raise ValueError('gpu_handoff_policy_requires_boolean')
    return value


def _scope(config):
    service=jobs.Config(**config['image_service']).normalized()
    binding={k:service[k] for k in ('service_url','input_root','output_root')}
    root=Path(config['gpu_lock_root'])/'GPU_HANDOFF'/fingerprint(binding)[:24]
    return service,binding,root


def _read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def assert_dispatch_allowed(config):
    """Do not load another model after an unresolved release command."""
    if not enabled(config):return
    _,_,root=_scope(config)
    if (root/'UNKNOWN.json').exists():raise GpuHandoffUnknown('gpu_handoff_outcome_unknown_retained')
    if (root/'PENDING.json').exists():raise jobs.JobBusyError('gpu_handoff_waiting_resources_before_dispatch')


def _opener():return urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())


def _get(op,service,route):
    with op.open(service['service_url']+route,timeout=min(service['timeout'],15)) as response:
        raw=response.read(4*1024*1024+1)
    if len(raw)>4*1024*1024:raise ValueError('gpu_handoff_response_too_large')
    return json.loads(raw)


def idle_queue(op,service):
    queue=_get(op,service,'/queue')
    if (not isinstance(queue,dict) or any(type(queue.get(k)) is not list for k in ('queue_running','queue_pending'))
        or any(not isinstance(row,list) or len(row)<3 or not isinstance(row[1],str) or not isinstance(row[2],dict)
               for key in ('queue_running','queue_pending') for row in queue[key])):
        raise ValueError('native_gpu_queue_schema_invalid')
    if queue['queue_running'] or queue['queue_pending']:raise jobs.JobBusyError('native_gpu_queue_busy')
    return queue


def _same_service(op,service):
    stats=_get(op,service,'/system_stats');argv=stats.get('system',{}).get('argv')
    if not isinstance(argv,list) or not all(isinstance(v,str) for v in argv):raise ValueError('gpu_handoff_service_paths_unconfirmed')
    try:
        observed={key:Path(argv[argv.index(flag)+1]).resolve() for key,flag in
            [('input_root','--input-directory'),('output_root','--output-directory')]}
    except (IndexError,ValueError):raise ValueError('gpu_handoff_service_paths_unconfirmed') from None
    if any(observed[k]!=Path(service[k]) for k in observed):raise ValueError('gpu_handoff_wrong_service_paths')


def _resources():
    value=probe_resources()
    if (not isinstance(value,dict) or any(type(value.get(k)) not in (int,float) or not math.isfinite(value[k]) or value[k]<0
        for k in ('available_ram_gib','available_vram_gib'))):
        raise ValueError('gpu_handoff_resource_measurement_unconfirmed')
    return value


def _enough(value):return value['available_ram_gib']>=MIN_RAM_GIB and value['available_vram_gib']>=MIN_VRAM_GIB


def _unknown(root,attempt,binding,reason):
    record=dict(attempt=attempt.name,service_binding_sha256=fingerprint(binding),reason=reason,at=time.time(),outcome_known=False)
    jobs._write(attempt/'STATE.json',dict(status='outcome_unknown',**record))
    if not (root/'UNKNOWN.json').exists():jobs._freeze(root/'UNKNOWN.json',record)


def _pending(root,binding):
    path=root/'PENDING.json'
    if not path.exists():return None
    record=_read(path)
    if record.get('service_binding_sha256')!=fingerprint(binding):raise ValueError('gpu_handoff_pending_scope_changed')
    name=record.get('attempt')
    if not isinstance(name,str) or len(name)!=32 or any(c not in '0123456789abcdef' for c in name):
        raise ValueError('gpu_handoff_pending_attempt_changed')
    attempt=root/'attempts'/name
    claim=_read(attempt/'CLAIM.json')
    if claim.get('service_binding_sha256')!=fingerprint(binding):raise ValueError('gpu_handoff_claim_scope_changed')
    if not (attempt/'RESPONSE.json').exists():
        _unknown(root,attempt,binding,'claim_without_definitive_response')
        raise GpuHandoffUnknown('gpu_handoff_outcome_unknown_retained')
    response=_read(attempt/'RESPONSE.json')
    if response.get('http_status')!=200 or response.get('request_sha256')!=claim.get('request_sha256'):
        raise ValueError('gpu_handoff_response_binding_changed')
    return attempt


def ensure_review_ready(config):
    """Caller holds GPU.lock and VISUAL_GPU.lock through this and VLM execution."""
    if not enabled(config):return
    service,binding,root=_scope(config)
    if (root/'UNKNOWN.json').exists():raise GpuHandoffUnknown('gpu_handoff_outcome_unknown_retained')
    op=_opener();idle_queue(op,service)
    attempt=_pending(root,binding)
    if attempt is None:
        before=_resources()
        if _enough(before):return
        _same_service(op,service);idle_queue(op,service)
        root.mkdir(parents=True,exist_ok=True);attempt=root/'attempts'/uuid.uuid4().hex;attempt.mkdir(parents=True)
        payload=dict(unload_models=True,free_memory=True);request_sha=fingerprint(payload)
        jobs._freeze(attempt/'REQUEST.json',dict(route='/free',payload=payload,service=binding))
        jobs._freeze(attempt/'CLAIM.json',dict(service_binding_sha256=fingerprint(binding),request_sha256=request_sha,
            resources_before=before,at=time.time()))
        jobs._freeze(root/'PENDING.json',dict(attempt=attempt.name,service_binding_sha256=fingerprint(binding)))
        request=urllib.request.Request(service['service_url']+'/free',data=json.dumps(payload).encode(),
            headers={'Content-Type':'application/json'})
        try:
            with op.open(request,timeout=min(service['timeout'],15)) as response:
                status=response.getcode();response.read(65537)
            if status!=200:raise ValueError('gpu_handoff_free_ack_unconfirmed')
            jobs._freeze(attempt/'RESPONSE.json',dict(http_status=200,request_sha256=request_sha,at=time.time()))
        except urllib.error.HTTPError as error:
            if error.code in (400,404,422):
                jobs._freeze(attempt/'REJECTED.json',dict(http_status=error.code,request_sha256=request_sha,at=time.time()))
                jobs._write(attempt/'STATE.json',dict(status='request_rejected',http_status=error.code))
                (root/'PENDING.json').unlink()
                raise ValueError('gpu_handoff_free_rejected:'+str(error.code)) from error
            _unknown(root,attempt,binding,type(error).__name__)
            raise GpuHandoffUnknown('gpu_handoff_free_outcome_unknown') from error
        except Exception as error:
            _unknown(root,attempt,binding,type(error).__name__)
            raise GpuHandoffUnknown('gpu_handoff_free_outcome_unknown') from error
    deadline=time.monotonic()+WAIT_SECONDS
    while True:
        idle_queue(op,service)
        resources=_resources()
        jobs._write(attempt/'STATE.json',dict(status='resources_observed' if _enough(resources) else 'waiting_resources',
            resources=resources,at=time.time(),acknowledgement_is_not_resource_completion=True))
        if _enough(resources):
            (root/'PENDING.json').unlink();return
        if time.monotonic()>=deadline:raise jobs.JobBusyError('gpu_handoff_resource_wait_timeout')
        time.sleep(POLL_SECONDS)
