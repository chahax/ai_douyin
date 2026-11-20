"""Reusable opt-in narration agent: new case → bounded text → fresh SOURCE_CASE.

No dependency on the historical six-call experiment. Native transport is
injectable for offline tests. Unknown calls retain their identity and never
replay. This module does not submit video or change global production defaults.
"""
from pathlib import Path
import json
import subprocess
import sys

from . import narration_placement_policy_v2 as policy
from . import narration_source_case_adapter_v1 as consumer
from . import visual_image_jobs_v3 as jobs

VERSION='narration_prevideo_agent/v1'
MODEL='MiniMax-M3.1-Flash'
ROOT=Path(__file__).resolve().parents[2]


def verify_native_receipt(case,receipt):
    """Authenticate adopted/reused candidate and review against saved responses."""
    calls=receipt.get('native_calls',[])
    if not calls:raise ValueError('native_candidate_and_independent_review_records_required')
    candidate_seen=review_seen=False
    for binding in calls:
        response=policy.read(policy.checked(binding));choices=response.get('choices') or [];usage=response.get('usage') or {}
        if (response.get('model','').lower()!=MODEL.lower() or len(choices)!=1
                or choices[0].get('finish_reason') not in ('stop','length')
                or not all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens','total_tokens'))
                or usage['total_tokens']!=usage['prompt_tokens']+usage['completion_tokens']):
            raise ValueError('native_receipt_response_or_usage_not_known')
        if choices[0]['finish_reason']!='stop':continue
        try:value=json.loads(choices[0]['message']['content'])
        except (ValueError,KeyError,TypeError):continue
        if value==receipt['semantic_review']:review_seen=True
        if isinstance(value,dict) and value.get('schema')==policy.base.DECISIONS:
            try:normalized,_=policy.normalize_native_shape(case,value)
            except (ValueError,TypeError,KeyError,AttributeError):continue
            if normalized==receipt['candidate']:candidate_seen=True
    if not candidate_seen or not review_seen:raise ValueError('receipt_candidate_or_review_differs_from_native_records')


def _prepare_locked(run,spec):
    run=Path(run).resolve();case=policy.read(policy.checked(spec['case']));policy.validate_case(case)
    budget=spec.get('call_budget')
    if type(budget) is not int or not 0<=budget<=12:raise ValueError('explicit_bounded_call_budget_0_to_12_required')
    authority=spec.get('authorization',{})
    if authority.get('max_text_calls',-1)<budget or authority.get('publication') is not False:
        raise ValueError('explicit_text_scope_and_publication_false_required')
    ids=[]
    for source in spec.get('sources',[]):
        if not source.get('id') or not source.get('quote_ids') or not isinstance(source.get('action_span_map'),dict):
            raise ValueError('explicit_source_quote_action_mapping_required')
        if not source['id'].replace('_','').replace('-','').isalnum():raise ValueError('safe_source_scope_id_required')
        policy.checked(source['source_case']);ids.append(source['id'])
    if not ids or len(ids)!=len(set(ids)):raise ValueError('unique_nonempty_source_consumers_required')
    adopted=spec.get('adopted_receipt')
    if adopted is not None:
        receipt=policy.read(policy.checked(adopted));policy.compile_before_video(case,receipt)
        verify_native_receipt(case,receipt)
    policy.freeze(run/'RUN_SPEC.json',spec)
    policy.freeze(run/'PLAN.json',dict(schema=VERSION,spec=policy.bind(run/'RUN_SPEC.json'),case=spec['case'],call_budget=budget,
        authority=authority,model=MODEL,reasoning_effort='medium',thinking='adaptive',sources=spec['sources'],adopted_receipt=adopted,
        code=[policy.bind(path) for path in (__file__,policy.__file__,policy.base.__file__,consumer.__file__,ROOT/'scripts/serial_native_worker_v6.py')],
        global_defaults_changed=False,media_calls=0))
    return dict(status='prepared_no_call',plan=policy.bind(run/'PLAN.json'))


def prepare(run,spec):
    run=Path(run).resolve();run.mkdir(parents=True,exist_ok=True)
    with jobs.run_lock(run,'NARRATION_AGENT.lock'):
        return _prepare_locked(run,spec)


def _plan(run):
    plan=policy.read(run/'PLAN.json')
    if plan.get('spec')!=policy.bind(run/'RUN_SPEC.json'):raise ValueError('frozen_run_spec_binding_changed')
    spec=policy.read(policy.checked(plan['spec']));budget=spec.get('call_budget');authority=spec.get('authorization',{})
    if (plan.get('schema')!=VERSION or type(budget) is not int or not 0<=budget<=12
            or authority.get('max_text_calls',-1)<budget or authority.get('publication') is not False
            or any(plan.get(a)!=spec.get(b) for a,b in [('case','case'),('call_budget','call_budget'),('sources','sources'),('authority','authorization'),('adopted_receipt','adopted_receipt')])
            or plan.get('model')!=MODEL or plan.get('reasoning_effort')!='medium' or plan.get('thinking')!='adaptive'):
        raise ValueError('plan_must_match_frozen_spec_and_authorized_budget')
    for code in plan['code']:policy.checked(code)
    return plan


def stream_transport(folder,request):
    """Existing configured MiniMax native stream worker; never writes a key."""
    from .creative_workflow_roles import role_config
    from .serial_story_transport_v6 import selected_endpoint
    config=role_config('writer');endpoint=selected_endpoint('writer',config,None)
    native=Path(folder)/'native';native.mkdir(exist_ok=False)
    policy.freeze(native/'REQUEST.json',dict(role='writer',base_url=endpoint,args=request['args']))
    try:
        process=subprocess.run([sys.executable,str(ROOT/'scripts/serial_native_worker_v6.py'),str(native)],cwd=ROOT,capture_output=True,timeout=420)
    except subprocess.TimeoutExpired:raise TimeoutError('specific_native_worker_timeout') from None
    if process.returncode or not (native/'RESPONSE.json').exists():raise TimeoutError('native_outcome_unknown')
    return policy.read(native/'RESPONSE.json')


def _call(run,case,phase,candidate,issues,transport):
    plan=_plan(run)
    previous=sorted((run/'calls').glob('C*/START.json')) if (run/'calls').exists() else []
    if len(previous)>=plan['call_budget']:raise ValueError('actual_started_calls_reach_authorized_budget')
    for started in previous:
        result=started.parent/'RESULT.json'
        if not result.exists() or policy.read(result).get('status')!='completed':
            return dict(status='outcome_unknown',folder=str(started.parent),replay=False)
    folder=run/'calls'/('C%03d'%(len(previous)+1));folder.mkdir(parents=True,exist_ok=False)
    args=dict(model=MODEL,messages=policy.messages(case,phase=phase,candidate=candidate,issues=issues),
        max_completion_tokens=12000,reasoning_effort='medium',extra_body=dict(thinking=dict(type='adaptive'),reasoning_split=True),
        stream=True,stream_options=dict(include_usage=True))
    request=dict(schema=VERSION,phase=phase,case_sha256=policy.digest(case),args=args)
    policy.freeze(folder/'REQUEST.json',request)
    policy.freeze(folder/'START.json',dict(status='in_flight',unknown_replay=False,call_id=folder.name))
    try:response=transport(folder,request)
    except Exception as error:
        policy.freeze(folder/'ERROR.json',dict(status='outcome_unknown',type=type(error).__name__,retry=False))
        return dict(status='outcome_unknown',folder=str(folder))
    policy.freeze(folder/'RESPONSE.json',response)
    usage=response.get('usage') or {};choices=response.get('choices') or []
    choice=choices[0] if len(choices)==1 else {};finish=choice.get('finish_reason')
    usage_known=all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens','total_tokens'))
    usage_known=usage_known and usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens']
    known=usage_known and finish in ('stop','length')
    if not known:
        policy.freeze(folder/'RESULT.json',dict(status='outcome_unknown',phase=phase,reason='native_completion_or_usage_not_known'))
        return dict(status='outcome_unknown',folder=str(folder))
    value=None;fault=None
    if response.get('model','').lower()!=MODEL.lower() or finish!='stop':fault='known_native_response_rejected'
    else:
        try:value=json.loads(choice['message']['content'])
        except (ValueError,KeyError,TypeError):fault='invalid_native_JSON_needs_repair'
    result=dict(status='completed',phase=phase,value=value,fault=fault,usage=usage,response=policy.bind(folder/'RESPONSE.json'))
    policy.freeze(folder/'RESULT.json',result);return result


def _consume(run,plan,case,receipt):
    policy.compile_before_video(case,receipt);verify_native_receipt(case,receipt);results=[]
    for source in plan['sources']:
        result=consumer.materialize(run/'sources'/source['id'],source['source_case'],plan['case'],policy.bind(run/'RECEIPT.json'),
            source['quote_ids'],action_span_map=source['action_span_map'])
        results.append(dict(id=source['id'],result=result))
    value=dict(schema=VERSION,status='source_consumption_complete',receipt=policy.bind(run/'RECEIPT.json'),sources=results,
        local_calls_started=len(list((run/'calls').glob('C*/START.json'))) if (run/'calls').exists() else 0,
        text_execution='adopted_verified_real_receipt_no_new_call' if plan.get('adopted_receipt') else 'bounded_local_agent_calls',
        media_dispatch_allowed=False,global_defaults_changed=False)
    policy.freeze(run/'RESULT.json',value);return value


def _execute_locked(run,*,transport=None):
    run=Path(run).resolve();plan=_plan(run)
    case=policy.read(policy.checked(plan['case']));policy.validate_case(case)
    if (run/'RECEIPT.json').exists():return _consume(run,plan,case,policy.read(run/'RECEIPT.json'))
    if plan.get('adopted_receipt') is not None:
        receipt=policy.read(policy.checked(plan['adopted_receipt']));policy.compile_before_video(case,receipt)
        policy.freeze(run/'RECEIPT.json',receipt);return _consume(run,plan,case,receipt)
    transport=transport or stream_transport
    candidate=None;issues=None;phase='judge';review=None
    calls=sorted((run/'calls').glob('C*')) if (run/'calls').exists() else []
    # Restore only known results. A START without an accepted native completion
    # blocks new dispatch, whether its original process is alive or has exited.
    results=[]
    for folder in calls:
        if not (folder/'RESULT.json').exists():return dict(status='outcome_unknown',blocked_call=folder.name,replay=False)
        result=policy.read(folder/'RESULT.json')
        if result['status']=='outcome_unknown':return dict(status='outcome_unknown',blocked_call=folder.name,replay=False)
        results.append(result)
    index=0
    while True:
        if index<len(results):result=results[index]
        else:
            if index>=plan['call_budget']:
                value=dict(status='needs_semantic_repair',reason='explicit_call_budget_exhausted',candidate=candidate,issues=issues,
                    calls_started=index,media_dispatch_allowed=False,manual_confirmation_requested=False)
                policy.freeze(run/'UNRESOLVED.json',value);return value
            result=_call(run,case,phase,candidate,issues,transport)
            if result['status']=='outcome_unknown':return dict(result,replay=False)
        index+=1
        if result['phase']!=phase:raise ValueError('restored_call_phase_does_not_match_case_state')
        if phase=='review':
            review=result.get('value');issues=[result['fault']] if result.get('fault') else policy.validate_review(case,candidate,review)
            if not issues:
                receipt=dict(schema=policy.base.RECEIPT,placement_contract=policy.VERSION,status='accepted',case_sha256=policy.digest(case),
                    candidate=candidate,semantic_review=review,native_calls=[policy.bind(p) for p in sorted((run/'calls').glob('C*/RESPONSE.json'))],
                    media_dispatch_allowed=False,global_defaults_changed=False)
                policy.freeze(run/'RECEIPT.json',receipt);return _consume(run,plan,case,receipt)
            phase='repair'
        else:
            native=result.get('value');candidate=native
            if result.get('fault'):issues=[result['fault']]
            else:
                try:
                    candidate,normalization=policy.normalize_native_shape(case,native)
                    folder=run/'calls'/('C%03d'%index)
                    policy.freeze(folder/'NORMALIZATION.json',normalization);policy.freeze(folder/'CANDIDATE.json',candidate)
                    issues=policy.validate_decisions(case,candidate)
                except (ValueError,TypeError,KeyError,AttributeError):issues=['native_shape_or_semantics_needs_independent_repair']
            phase='repair' if issues else 'review'


def execute(run,*,transport=None):
    run=Path(run).resolve()
    try:
        with jobs.run_lock(run,'NARRATION_AGENT.lock'):
            return _execute_locked(run,transport=transport)
    except jobs.JobBusyError:
        return dict(status='busy_existing_narration_owner',new_calls_started=0,replay=False)
