"""One explicitly approved image successor after a verified service exit.

Never rewrites an original native record, restarts/kills a service, creates a
native HISTORY, or handles an unknown video. Provider outcome remains unknown.
Only the existing v34 root dispatcher can submit the independently prepared job.
"""
from pathlib import Path
from datetime import datetime,timezone
from copy import deepcopy
import re
import time
import os
import stat
import psutil

from . import visual_h3_continuity_input_v33 as core
from . import visual_h3_handoff_v3 as native
from . import visual_image_jobs_v3 as jobs
from . import visual_spatial_stills_v24 as stills

PROJECT=Path(__file__).resolve().parents[2]
SERVICE_HOME=PROJECT/'data/h3_supervision/service_8190_20261104'
OPT='SERVICE_EXIT_RECOVERY.json'
DECISION='allow_one_new_image_successor_after_verified_service_exit'
SCHEMA='h3_service_exit_image_disposition/v35'

class ServiceExitError(ValueError):pass

def _f():
    from . import visual_h3_continuity_minute_v34 as f
    return f
def _now():return time.time()
def _epoch(value):return datetime.fromisoformat(value).timestamp()
def _alive(pid,created):
    try:return abs(psutil.Process(pid).create_time()-created)<.01
    except psutil.NoSuchProcess:return False
    except psutil.AccessDenied as error:raise ServiceExitError('original_service_identity_read_unavailable') from error
def _positive_evidence(value):return isinstance(value,list) and bool(value) and all(isinstance(x,str) and x.strip() for x in value)
def successor_run(run,sid):return Path(run)/'stills'/(Path(run).name+'_'+sid+'_service_exit_v35')
def successor_job(run,sid):return successor_run(run,sid)/'batches'/('reanchor_'+sid)

def _opt_in(run):
    f=_f();run,plan=f._load(run);path=run/OPT
    if not path.exists():
        if any(_local_protection_context(run,sid) for sid in f.IDS):raise ServiceExitError('precise_image_opt_in_missing_new_dispatch_blocked')
        return {}
    value=f.read(path);rows=value.get('dispositions')
    if (value.get('schema')!='h3_service_exit_image_recovery_opt_in/v35' or value.get('minute_plan')!=f.bind(run/'PLAN.json')
            or not isinstance(rows,dict) or len(rows)!=1 or not set(rows)<=set(f.IDS)):
        raise ServiceExitError('one_precise_image_disposition_opt_in_required')
    for sid,binding in rows.items():
        v=core.read(binding)
        if (v.get('schema')!=SCHEMA or v.get('segment')!=sid or v.get('approved_for_successor') is not True
                or v.get('minute_plan')!=f.bind(run/'PLAN.json') or v.get('decision')!=DECISION
                or Path(v.get('original_job','')).resolve()!=f._image_job(run,sid)):
            raise ServiceExitError('root_precise_original_image_disposition_required')
    return rows

def configured(run,sid):return sid in _opt_in(run)

def _strict_entries(folder):
    try:
        with os.scandir(folder) as stream:return list(stream)
    except OSError as error:raise ServiceExitError('original_output_inventory_unavailable:'+str(folder)) from error

def _entry_mode(entry):
    try:info=entry.stat(follow_symlinks=False)
    except OSError as error:raise ServiceExitError('original_output_entry_unavailable:'+str(entry.path)) from error
    if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
        raise ServiceExitError('original_output_reparse_point_not_followed')
    return info.st_mode

def _strict_child(parent,name):
    rows=[entry for entry in _strict_entries(parent) if os.path.normcase(entry.name)==os.path.normcase(name)]
    if len(rows)>1:raise ServiceExitError('original_output_namespace_ambiguous')
    if not rows:return None
    entry=rows[0]
    if not stat.S_ISDIR(_entry_mode(entry)):raise ServiceExitError('original_has_partial_or_complete_output')
    return Path(entry.path)

def _strict_empty_tree(folder):
    for entry in _strict_entries(folder):
        if not stat.S_ISDIR(_entry_mode(entry)):raise ServiceExitError('original_has_partial_or_complete_output')
        _strict_empty_tree(Path(entry.path))

def _inventory(job,plan):
    root=Path(plan['config']['output_root']).absolute();parts=Path(jobs._relative(plan['config']['allowed_prefix'])).parts+(jobs._slug(plan['job_id']),)
    try:info=os.lstat(root)
    except OSError as error:raise ServiceExitError('original_output_root_unavailable') from error
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
        raise ServiceExitError('original_output_root_not_plain_directory')
    out=root.joinpath(*parts);current=root
    # A missing namespace is proven by an explicit enumeration of its parent,
    # not by Path.exists/rglob suppressing a read error in Python 3.14.
    for part in parts:
        current=_strict_child(current,part)
        if current is None:break
    if current is not None:_strict_empty_tree(current)
    entries=_strict_entries(job)
    if any(e.name in ('RESULT.json','CANDIDATES.json','HISTORY.json') for e in entries):raise ServiceExitError('original_result_or_history_exists')
    artifacts=_strict_child(job,'artifacts')
    if artifacts is not None:_strict_empty_tree(artifacts)
    return out

def _seen(path):
    try:os.lstat(path);return True
    except FileNotFoundError:return False
    except OSError:return True  # Unknown existence is not evidence of absence.

def _protection_path(run,sid):return Path(run)/'segments'/sid/'SERVICE_EXIT_ORIGINAL_PROTECTION.json'
def _local_protection_context(run,sid):
    folder=Path(run)/'segments'/sid
    return any(_seen(path) for path in (_protection_path(run,sid),folder/'SERVICE_EXIT_SUCCESSOR_PREPARED.json',folder/'ROOT_SERVICE_EXIT_DISPOSITION.json',successor_job(run,sid)/'PLAN.json'))

def has_context(run):
    return _seen(Path(run)/OPT) or any(_local_protection_context(run,sid) for sid in _f().IDS)

def original_protection(run,sid):
    """Collection-only frozen marker; never consult current opt-in/approval."""
    f=_f();path=_protection_path(run,sid);seen=_seen(path)
    expected=_local_protection_context(run,sid) or (_seen(Path(run)/OPT) and not any(_local_protection_context(run,s) for s in f.IDS))
    if not seen:return dict(preserve_original=expected,valid=False,error='original_protection_marker_missing' if expected else None)
    try:
        value=f.read(path);job=f._image_job(run,sid)
        original={k:f.bind(job/n) for k,n in [('plan','PLAN.json'),('graph','workflow_api.json'),('request','REQUEST.json'),('claim','CLAIM.json'),('response','RESPONSE.json'),('state','STATE.json')]}
        if (value.get('schema')!='h3_service_exit_original_protection/v35' or value.get('minute_plan')!=f.bind(Path(run)/'PLAN.json')
                or value.get('segment')!=sid or value.get('original_job')!=str(job) or value.get('original')!=original
                or value.get('original_native_id')!=f.read(job/'RESPONSE.json').get('prompt_id') or value.get('dispatch_authorization') is not False):
            raise ServiceExitError('original_protection_marker_changed')
        return dict(preserve_original=True,valid=True,native_id=value['original_native_id'],error=None)
    except (OSError,ValueError,KeyError,TypeError) as error:
        return dict(preserve_original=True,valid=False,error='original_protection_marker_unavailable_or_changed',detail=dict(type=type(error).__name__,message=str(error)))

def _freeze_protection(run,sid,proof):
    f=_f();v=proof['disposition']
    f.freeze(_protection_path(run,sid),dict(schema='h3_service_exit_original_protection/v35',minute_plan=v['minute_plan'],segment=sid,
        original_job=v['original_job'],original_native_id=v['original_native_id'],original=v['original'],disposition=proof['binding'],dispatch_authorization=False))

def _recorded_ownership(audit,service):
    family=audit.get('local_process_exit',{});eligible=family.get('eligible_generation_at_post',[])
    if len(eligible)!=1 or eligible[0].get('process')!=service['process'] or eligible[0].get('exit')!=service['exit']:
        raise ServiceExitError('unique_recorded_owner_generation_required')
    # Open-ended legacy PROCESS records are not silently ignored. Every one
    # excluded by the audit must have a later authoritative absent-launch proof.
    for row in family.get('prior_open_interval_excluded_by_later_proven_absence',[]):
        prior=core.read(row['process']);proofs=row.get('excluded_by',[])
        if not proofs:raise ServiceExitError('unexcluded_prior_generation')
        for proof in proofs:
            c=core.read(proof['absence_claim']);p=core.read(proof['later_process']);obs=c.get('observation',{})
            if (not prior['create_time']<c.get('epoch',0)<p['create_time'] or c.get('source_command')!=prior['command']
                    or p['command']!=prior['command'] or obs.get('families')!=[] or obs.get('port')!='closed' or obs.get('action')!='launch'):
                raise ServiceExitError('prior_generation_absence_not_proven')

def _owner_at_post(at):
    records=[]
    for path in (SERVICE_HOME/'attempts').glob('*/PROCESS.json'):
        p=native.read(path);exit_path=path.parent/'EXIT.json';end=_epoch(native.read(exit_path)['at']) if exit_path.exists() else float('inf')
        if p['create_time']<=at<=end:records.append((path,p))
    eligible=[]
    for path,p in records:
        superseded=False
        for newer in (SERVICE_HOME/'attempts').glob('*/PROCESS.json'):
            n=native.read(newer);cp=newer.parent/'CLAIM.json'
            if not cp.exists():continue
            c=native.read(cp);o=c.get('observation',{})
            if (p['create_time']<c.get('epoch',0)<n['create_time']<=at and n['command']==p['command'] and c.get('source_command')==p['command']
                    and o.get('families')==[] and o.get('port')=='closed' and o.get('action')=='launch'):superseded=True
        if not superseded:eligible.append(path.resolve())
    return eligible

def verify(run,sid,*,live=False):
    f=_f();run,minute=f._load(run);rows=_opt_in(run)
    if sid not in rows:raise ServiceExitError('specific_image_not_disposed')
    v=core.read(rows[sid]);job=f._image_job(run,sid);_,p,g=jobs._load(job);state=jobs.status(job)
    original={k:f.bind(job/name) for k,name in [('plan','PLAN.json'),('graph','workflow_api.json'),('request','REQUEST.json'),('claim','CLAIM.json'),('response','RESPONSE.json'),('state','STATE.json')]}
    if (v.get('original')!=original or v.get('original_native_id')!=state.get('prompt_id') or not state.get('prompt_id')
            or state['status'] not in ('submitted','running','queued','outcome_unknown')
            or v.get('root_authorization')!=minute['authorization'] or v.get('image_authorization')!=minute['image_authorization']
            or v.get('context_spec')!=f.bind(f._folder(run,sid)/'CONTEXT_SPEC.json')
            or v.get('work_order')!=f.bind(f._folder(run,sid)/'REANCHOR_WORK_ORDER.json')
            or v.get('native_provider_outcome')!='unknown_after_service_exit' or v.get('retain_original_unknown') is not True
            or v.get('count_original_submission') is not True or type(v.get('max_new_image_successors')) is not int or v['max_new_image_successors']!=1
            or v.get('ownership_evidence_is_retrospective') is not True or not isinstance(v.get('reviewed_by'),str) or not v['reviewed_by'].strip() or not _positive_evidence(v.get('evidence'))):
        raise ServiceExitError('original_record_or_specific_root_disposition_changed')
    request=f.read(job/'REQUEST.json');response=f.read(job/'RESPONSE.json');claim=f.read(job/'CLAIM.json')
    if request.get('prompt')!=g or response.get('prompt_id')!=v['original_native_id'] or response.get('node_errors') or claim.get('graph_sha256')!=p['graph_sha256']:
        raise ServiceExitError('accepted_original_native_request_required')
    service=v['service'];proc=core.read(service['process']);ex=core.read(service['exit']);launch=core.read(service['claim']);log=core.check(service['stderr'])
    parent=Path(service['process']['path']).resolve().parent
    if (parent.parent!=(SERVICE_HOME/'attempts').resolve() or not re.fullmatch('[a-f0-9]{32}',parent.name)
            or Path(service['exit']['path']).resolve()!=parent/'EXIT.json' or Path(service['claim']['path']).resolve()!=parent/'CLAIM.json'
            or log.resolve()!=parent/'server.stderr.log' or type(ex.get('returncode')) is not int or ex['returncode']==0
            or type(proc.get('pid')) is not int or proc['pid']<1 or type(proc.get('create_time')) not in (int,float)
            or (proc.get('pid'),proc.get('create_time'))!=(ex.get('pid'),ex.get('create_time'))
            or not proc['create_time']<=claim['at']<=_epoch(ex['at'])<=_now()+1
            or proc.get('command')!=launch.get('source_command')):
        raise ServiceExitError('authoritative_matching_service_process_exit_required')
    argv=proc['command']
    for flag,key in [('--input-directory','input_root'),('--output-directory','output_root')]:
        if flag not in argv or Path(argv[argv.index(flag)+1]).resolve()!=Path(p['config'][key]).resolve():raise ServiceExitError('original_service_namespace_changed')
    if '--port' not in argv or argv[argv.index('--port')+1]!='8190':raise ServiceExitError('original_service_endpoint_changed')
    audit=core.read(v['readonly_audit']);_recorded_ownership(audit,service)
    q=audit.get('current_service',{}).get('queue',{})
    if (audit.get('schema')!='service_exit_image_readonly_audit/v35' or audit.get('original_native_id')!=v['original_native_id']
            or Path(audit.get('source_job','')).resolve()!=job or audit.get('current_service',{}).get('history')!={}
            or not all(isinstance(q.get(k),list) and not q[k] for k in ('queue_running','queue_pending'))
            or not _epoch(ex['at'])<=_epoch(audit['sampled_at'])<=_now()+1
            or _owner_at_post(claim['at'])!=[Path(service['process']['path']).resolve()]):
        raise ServiceExitError('bound_original_id_absence_audit_required')
    identities=audit['local_process_exit'].get('old_family',[])
    if not any((r.get('pid'),r.get('original_create_time'))==(proc['pid'],proc['create_time']) for r in identities):raise ServiceExitError('original_service_family_identity_required')
    if any(_alive(r['pid'],r['original_create_time']) for r in identities):raise ServiceExitError('original_service_identity_still_alive')
    text=log.read_text(encoding='utf-8',errors='replace');tail=text.rsplit('got prompt',1)[-1]
    if (any(x not in tail for x in ('AutoencoderKL','Fatal Python error: Aborted','restore_loaded_backups','partially_unload','in encode'))
            or re.search(r'\d+%\|',tail) or 'Prompt executed' in tail):raise ServiceExitError('specific_pre_sampling_vae_abort_not_proven')
    _inventory(job,p)
    if live:
        history=native._http(p['config'],'/history/'+v['original_native_id']);queue=native._http(p['config'],'/queue')
        if not isinstance(history,dict) or not all(isinstance(queue.get(k),list) for k in ('queue_running','queue_pending')):raise ServiceExitError('native_absence_lookup_failed')
        if history or any(len(r)>1 and r[1]==v['original_native_id'] for k in ('queue_running','queue_pending') for r in queue[k]):raise ServiceExitError('original_native_id_has_reappeared')
    return dict(binding=rows[sid],disposition=v,original_native_id=v['original_native_id'],raw_provider_outcome='unknown_after_service_exit',original_claim_still_counted=True)

def verified(run,*,live=False):return {sid:verify(run,sid,live=live) for sid in _opt_in(run)}

def disposition_request(run,sid,service_attempt,readonly_audit):
    f=_f();run,minute=f._load(run);job=f._image_job(run,sid);attempt=Path(service_attempt).resolve();state=jobs.status(job)
    return dict(schema=SCHEMA,segment=sid,minute_plan=f.bind(run/'PLAN.json'),root_authorization=minute['authorization'],image_authorization=minute['image_authorization'],
        original_job=str(job),original_native_id=state.get('prompt_id'),original={k:f.bind(job/n) for k,n in [('plan','PLAN.json'),('graph','workflow_api.json'),('request','REQUEST.json'),('claim','CLAIM.json'),('response','RESPONSE.json'),('state','STATE.json')]},
        context_spec=f.bind(f._folder(run,sid)/'CONTEXT_SPEC.json'),work_order=f.bind(f._folder(run,sid)/'REANCHOR_WORK_ORDER.json'),
        service={k:f.bind(attempt/n) for k,n in [('process','PROCESS.json'),('exit','EXIT.json'),('claim','CLAIM.json'),('stderr','server.stderr.log')]},readonly_audit=readonly_audit,
        decision=DECISION,native_provider_outcome='unknown_after_service_exit',retain_original_unknown=True,count_original_submission=True,max_new_image_successors=1,
        ownership_evidence_is_retrospective=True,approved_for_successor=None,reviewed_by=None,evidence=[])

def prepare_successor(run,sid):
    f=_f();run,minute=f._load(run,current=True);proof=verify(run,sid);_freeze_protection(run,sid,proof);folder=f._folder(run,sid);spec=core.read(minute['spec']);spatial=spec['spatial']
    result=core.prepare_reanchor(f.bind(folder/'CONTEXT_SPEC.json'),sid,successor_run(run,sid),handoff=core.check(spatial['handoff']),
        render_result=core.check(spatial['render_result']),inputs=core.check(spatial['inputs']),authorization=core.check(minute['image_authorization']),
        config=core.check(spatial['config']),item_id=spec['stage_items'][sid],source_binding_review=f.bind(folder/'SOURCE_STATE_REVIEW.json'))
    old=f._image_job(run,sid);new=successor_job(run,sid)
    def signature(job):
        p=f.read(job/'PLAN.json');g=deepcopy(f.read(job/'workflow_api.json'));inputs={i['input_name']:i for i in p['inputs']}
        for node in g.values():
            if node['class_type']=='LoadImage':node['inputs']['image']={k:inputs[node['inputs']['image']][k] for k in ('path','sha256')}
            elif node['class_type']=='SaveImage':node['inputs']['filename_prefix']='new_native_scope_only'
        return f.digest(g)
    if signature(old)!=signature(new):raise ServiceExitError('successor_changed_original_pixels_prompt_seed_or_recipe')
    f.budget(run)
    f.freeze(folder/'SERVICE_EXIT_SUCCESSOR_PREPARED.json',dict(schema='h3_service_exit_successor_prepared/v35',disposition=_opt_in(run)[sid],
        original_native_id=jobs.status(old)['prompt_id'],native_plan=f.bind(new/'PLAN.json'),same_generation_recipe_sha256=signature(new),original_claim_retained=True))
    state=jobs.status(new)
    return dict(status='service_exit_image_prepared' if state['status']=='prepared' else state['status'],shot_id=sid,
        native_job=f.bind(new/'PLAN.json'),native_state=state,model_calls=0)

def _candidate(run,sid):
    f=_f();job=successor_job(run,sid);p=f.read(job/'BATCH.json');result=f.read(job/'RESULT.json')
    if jobs.status(job)['status']!='saved' or len(p['item_ids'])!=1:raise ServiceExitError('real_saved_image_successor_required')
    name=p['item_ids'][0];matches=[x for x in result['images'] if x['save_node']==name+'__save']
    if len(matches)!=1 or matches[0]['dimensions']!=[f.WIDTH,f.HEIGHT]:raise ServiceExitError('successor_geometry_changed')
    selected=dict(id=name,image={k:matches[0][k] for k in ('path','sha256')},save_node=matches[0]['save_node'],prompt_id=result['prompt_id'],production_approved=False)
    f.freeze(job/'CANDIDATES.json',dict(schema=stills.SCHEMA,batch=f.bind(job/'BATCH.json'),native_result=f.bind(job/'RESULT.json'),items=[selected],
        content_status='root_visual_review_required_before_video_guide',production_approved=False))
    return selected

def collect_known(run):
    """Collect already accepted successor IDs even if approval/source changes."""
    f=_f();run,_=f._load(run)
    for sid in f.IDS:
        job=successor_job(run,sid)
        if not (job/'PLAN.json').exists():continue
        state=jobs.status(job)
        if state.get('prompt_id') and state['status'] not in ('saved','failed','interrupted','rejected','cancelled'):
            if state['status']!='native_complete':state=jobs.poll(job)
            if state['status']=='native_complete':jobs.collect(job);state=jobs.status(job)
        if state['status']=='saved':_candidate(run,sid)
        f._remember(run,sid,'image_service_exit',state,job)

def view(run,sid):
    job=successor_job(run,sid)
    return jobs.status(job) if (job/'PLAN.json').exists() else None

def selection(run,sid):
    f=_f();run,minute=f._load(run,current=True);proof=verify(run,sid);folder=f._folder(run,sid);job=successor_job(run,sid)
    if (f._video_run(run,sid)/'PLAN.json').exists() and not (folder/'SERVICE_EXIT_SELECTED_ANCHOR.json').exists():raise ServiceExitError('frozen_video_anchor_cannot_be_replaced')
    candidate=_candidate(run,sid)
    if candidate['prompt_id']==proof['original_native_id']:raise ServiceExitError('fresh_successor_native_id_required')
    review=folder/'SERVICE_EXIT_ANCHOR_REVIEW.json'
    if not review.exists():return None
    report=f.prepare_context_entry(run,sid);entry=deepcopy(core._entries(f.bind(folder/'CONTEXT_SPEC.json'))[0]);spec=core.read(minute['spec'])
    receipt=dict(kind='spatial_still_v24',run=str(successor_run(run,sid)),batch_id='reanchor_'+sid,item_id=spec['stage_items'][sid],
        candidates=f.bind(job/'CANDIDATES.json'),source_binding_review=f.bind(folder/'SOURCE_STATE_REVIEW.json'))
    receipt_path=folder/'SERVICE_EXIT_SUCCESSOR_RECEIPT.json';f.freeze(receipt_path,receipt)
    entry['reanchor']=dict(image=candidate['image'],coverage_review=f.bind(review),work_order_sha256=report['work_order_sha256'],generation_receipt=receipt)
    result=core.evaluate(entry)
    if result['status']!='ready':raise ServiceExitError('same_source_successor_not_reviewed_ready')
    value=dict(schema='h3_service_exit_selected_anchor/v35',disposition=proof['binding'],context_spec=f.bind(folder/'CONTEXT_SPEC.json'),
        work_order_sha256=report['work_order_sha256'],receipt=f.bind(receipt_path),coverage_review=f.bind(review),image=candidate['image'],native_id=candidate['prompt_id'],
        native_result=f.bind(job/'RESULT.json'),original_provider_outcome='unknown_after_service_exit',original_claim_retained=True,automatic_retry=False,production_approved=False)
    f.freeze(folder/'SERVICE_EXIT_SELECTED_ANCHOR.json',value);return value

def advance(run,sid):
    f=_f();verify(run,sid);job=successor_job(run,sid)
    if not (job/'PLAN.json').exists():return prepare_successor(run,sid)
    state=jobs.status(job)
    if state['status']=='prepared':return dict(status='service_exit_image_prepared',shot_id=sid,model_calls=0)
    if state['status']=='saved':
        selected=selection(run,sid)
        return dict(status='service_exit_selection_ready' if selected else 'service_exit_anchor_review_required',shot_id=sid,selection=selected,candidate=_candidate(run,sid),model_calls=0)
    return dict(status=state['status'],shot_id=sid,model_calls=0)

def image_approval_request(run,sid):
    f=_f();run,plan=f._load(run);verify(run,sid);job=successor_job(run,sid)
    return dict(schema='h3_service_exit_successor_image_approval/v35',segment=sid,minute_plan=f.bind(run/'PLAN.json'),root_authorization=plan['authorization'],
        disposition=_opt_in(run)[sid],prepared=f.bind(f._folder(run,sid)/'SERVICE_EXIT_SUCCESSOR_PREPARED.json'),native_plan=f.bind(job/'PLAN.json'),graph=f.bind(job/'workflow_api.json'),
        approved_for_dispatch=None,reviewed_by=None,evidence=[])

def submit_successor(run,sid):
    f=_f();run,plan=f._load(run,current=True);verify(run,sid,live=True);f._launch(run,plan);f.budget(run)
    expected=image_approval_request(run,sid);value=f.read(f._folder(run,sid)/'ROOT_SERVICE_EXIT_IMAGE_APPROVAL.json')
    for key in expected:
        if key not in ('approved_for_dispatch','reviewed_by','evidence') and value.get(key)!=expected[key]:raise ServiceExitError('root_successor_image_approval_changed')
    if value.get('approved_for_dispatch') is not True or not value.get('reviewed_by') or not _positive_evidence(value.get('evidence')):raise ServiceExitError('root_successor_image_review_required')
    job=successor_job(run,sid);state=jobs.status(job)
    if state['status']!='prepared':return state
    state=stills.tick(successor_run(run,sid),'reanchor_'+sid);f._remember(run,sid,'image_service_exit',state,job);return state
