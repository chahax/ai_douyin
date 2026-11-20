"""Durable single-stage dispatch with immutable journals and unknown protection.

Handlers are application code, not shell commands supplied by a model. Recovery
only inspects a reserved stage's native terminal state; it never resubmits it.
"""
from pathlib import Path
import hashlib
from .contracts import digest
from ..corpus_screenplay_v1 import read,freeze
from ..serial_story_runtime_v2 import run_lock


def _save(root,state):
    journal=root/'journal';journal.mkdir(exist_ok=True)
    entries=sorted(journal.glob('*.json'))
    freeze(journal/f'{len(entries):06}.json',{'previous_sha256':digest(read(entries[-1])) if entries else None,'state':state})


def inspect(root):
    root=Path(root);previous=None;state=None
    for path in sorted((root/'journal').glob('*.json')):
        entry=read(path)
        if entry['previous_sha256']!=previous:raise ValueError('session_journal_changed')
        previous=digest(entry);state=entry['state']
    if state is None:raise ValueError('session_not_prepared')
    plan=read(root/'SESSION.json')
    if state['plan_sha256']!=digest(plan):raise ValueError('session_plan_changed')
    for item in state['completed']:
        for name,sha in item['artifacts'].items():
            if digest(read(root/item['directory']/name))!=sha:raise ValueError('completed_stage_artifact_changed')
    failed=state.get('failure_evidence')
    if failed:
        for name,sha in failed['artifacts'].items():
            path=root/failed['directory']/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
                raise ValueError('failed_stage_evidence_changed')
    return state


def prepare(root,stages,baseline,max_calls):
    root=Path(root)
    if baseline['pending'] is not None or baseline['status'] in ('prepared','running','outcome_unknown'):raise ValueError('baseline_unsettled')
    if max_calls<baseline['calls_started']:raise ValueError('session_budget_regressed')
    names=[s['name'] for s in stages]
    if not names or len(names)!=len(set(names)) or any(not n.replace('_','').isalnum() for n in names):raise ValueError('session_stage_names')
    root.mkdir(exist_ok=False,parents=True)
    plan={'stages':stages,'baseline':baseline,'max_calls':max_calls,'media':False}
    freeze(root/'SESSION.json',plan)
    _save(root,{'plan_sha256':digest(plan),'status':'ready','completed':[],'pending_stage':None,
                'calls_started':baseline['calls_started'],'reported_tokens':baseline['reported_tokens']})
    return inspect(root)


def _reconcile(root,state,plan):
    index=state['pending_stage'];spec=plan['stages'][index];folder=root/f'{index:02}_{spec["name"]}'
    native_path=folder/'STATE.json'
    if not native_path.exists():return {**state,'status':'pending_execution_outcome'}
    native=read(native_path)
    if (native['calls_started']<state['calls_started'] or native['reported_tokens']<state['reported_tokens']
            or native['calls_started']>plan['max_calls']):raise ValueError('stage_accounting_invalid')
    if native['pending'] is not None or native['status'] in ('running','prepared','outcome_unknown'):
        # Dispatch may have consumed a call even without a complete receipt.
        # Persist that count while preserving the reservation and unknown usage.
        waiting={**state,'status':'pending_execution_outcome',
                 'calls_started':native['calls_started'],'reported_tokens':native['reported_tokens'],
                 'pending_native_status':native['status'],'pending_call_id':native['pending'],
                 'usage_complete':native['pending'] is None and native['status']!='outcome_unknown'}
        if waiting!=state:_save(root,waiting)
        return waiting
    state={k:v for k,v in state.items() if k not in ('pending_native_status','pending_call_id','usage_complete')}
    state={**state,'calls_started':native['calls_started'],'reported_tokens':native['reported_tokens']}
    if native['status'] not in spec['success_states']:
        artifacts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*.json'))}
        state.update(status='needs_attention',pending_stage=None,failed_stage=index,
                     failure_evidence={'directory':folder.name,'artifacts':artifacts})
        _save(root,state);return state
    artifacts={'STATE.json':digest(native)}
    for name in spec['artifacts']:
        # Flat, fixed artifact names only, never arbitrary file references.
        if Path(name).name!=name:raise ValueError('invalid_stage_artifact_name')
        if not (folder/name).exists():return {**state,'status':'pending_artifact_finalization'}
        artifacts[name]=digest(read(folder/name))
    state={**state,'completed':state['completed']+[{'name':spec['name'],'directory':folder.name,'artifacts':artifacts}],
           'pending_stage':None,'status':'ready'}
    if len(state['completed'])==len(plan['stages']):state['status']='stages_complete_awaiting_acceptance'
    _save(root,state);return state


def step(root,handlers):
    root=Path(root)
    with run_lock(root):
        state=inspect(root);plan=read(root/'SESSION.json')
        if state['pending_stage'] is not None:return _reconcile(root,state,plan)
        if state['status']!='ready':return state
        if state['calls_started']>=plan['max_calls']:return {**state,'status':'engineering_window_exhausted'}
        index=len(state['completed']);spec=plan['stages'][index]
        if spec['name'] not in handlers:raise ValueError('stage_handler_missing')
        state={**state,'pending_stage':index,'status':'executing'};_save(root,state)
        folder=root/f'{index:02}_{spec["name"]}'
        # Reservation is durable BEFORE dispatch. Exceptions leave it pending.
        handlers[spec['name']](folder,dict(state),plan)
        return _reconcile(root,state,plan)
