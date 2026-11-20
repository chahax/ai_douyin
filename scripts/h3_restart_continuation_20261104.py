"""Resume the frozen local H3 manifest across verified Comfy service generations."""
import argparse
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import urllib.error
import xml.etree.ElementTree as ET

import psutil
from PIL import Image

import h3_persistent_supervisor_20261103 as monitor
import h3_service_guard_20261104 as guard
import run_h3_full_script_20261102 as full

h, b = full.h, full.b
OLD = full.RUN
RUN = OLD.parent / 'h3_six_children_full_script_recovery_20261104'
SCRIPT = Path(__file__).resolve()
GUARD = guard.HOME
TASK = 'AI_Douyin_H3_FullScript_Continuation'
PREFIX = 'six_children_recovery_20261104'
FIRST_LOST = 'F0038'
ROLES = {'video': ('images', 'mp4'), 'audio': ('audio', 'flac'), 'first': ('images', 'png'), 'last': ('images', 'png')}


class Blocked(ValueError):
    pass


class Wait(RuntimeError):
    pass


def require(test, reason):
    if not test:
        raise Blocked(reason)


def freeze(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    h.durable(path, value, immutable=True)


def elapsed(timestamp):
    return datetime.fromisoformat(timestamp).timestamp()


def queue_rows(queue):
    require(isinstance(queue, dict) and all(isinstance(queue.get(k), list) for k in ('queue_running','queue_pending')), 'invalid_queue_schema')
    rows = queue['queue_running'] + queue['queue_pending']
    require(all(isinstance(r, list) and len(r) >= 3 and isinstance(r[1], str) for r in rows), 'invalid_queue_row')
    return rows


def accepted(queue, task, graph):
    rows = [row for row in queue_rows(queue) if row[1] == task]
    require(all(row[2] == graph for row in rows), 'queue_graph_mismatch')
    return bool(rows)


def generation():
    config = monitor.assert_config(guard.CONFIG)
    observation = guard.inspect(config)
    if observation['action'] != 'healthy':
        raise Wait(observation['reason'])
    rows = observation['families'][0]
    for path in (GUARD/'attempts').glob('*/PROCESS.json'):
        process = h.read(path)
        if any(r['pid']==process['pid'] and abs(r['create_time']-process['create_time'])<.01 for r in rows):
            claim = h.read(path.parent/'CLAIM.json')
            require(claim['config_sha256']==h.sha(guard.CONFIG) and process['command']==config['command'] and
                    claim['observation']['action']=='launch' and not claim['observation']['families'] and
                    claim['observation']['port']=='closed', 'invalid_new_service_generation')
            return dict(id=path.parent.name, started=process['create_time'], observed_absent=claim['epoch'],
                        identities=[dict(pid=r['pid'], create_time=r['create_time']) for r in rows],
                        receipt=h.binding(path), claim=h.binding(path.parent/'CLAIM.json'))
    raise Wait('guard_verified_generation_receipt_unavailable')


def disappeared(previous, current):
    require(previous['id'] != current['id'] and current['observed_absent'] > previous['started'],
            'same_or_unproven_service_restart')
    for row in previous['identities']:
        try:
            if abs(psutil.Process(row['pid']).create_time()-row['create_time']) < .01:
                raise Blocked('old_service_identity_still_alive')
        except psutil.NoSuchProcess:
            pass


def legacy_binding():
    folder = OLD/FIRST_LOST
    state = h.read(folder/'STATE.json')
    graph = h.read(folder/'workflow_api.json')
    task = state['prompt_id']
    source = h.read(b.SERVICE/'SERVER_STARTED.json')
    initial = h.read(GUARD/'INITIAL_EVIDENCE.json')
    queue = h.read(folder/'QUEUE.latest.json')
    require(state['status']=='submitted' and state['submissions']==1 and accepted(queue['queue'], task, graph) and
            h.read(folder/'SUBMISSION_RESPONSE.json')['prompt_id']==task and h.read(folder/'REQUEST.actual.json')['prompt']==graph and
            initial['original_segment_state']==state and initial['initial_observation']['action']=='launch' and
            initial['initial_observation']['families']==[] and initial['initial_observation']['port']=='closed' and
            elapsed(source['started_at']) < elapsed(queue['at']) < elapsed(initial['at']), 'unproven_original_generation')
    b.validate_frozen(folder)
    return dict(id='original-server-6816', started=elapsed(queue['at']), identities=[], original_process_id=source['pid'],
                old_queue=h.binding(folder/'QUEUE.latest.json'), original_absent=h.binding(GUARD/'INITIAL_EVIDENCE.json'))


def source_receipt(folder):
    state = h.read(folder/'STATE.json')
    receipt = h.read(folder/'receipt.json')
    require(state.get('status')=='saved' and state.get('prompt_id')==receipt.get('prompt_id') and receipt['technical_status']=='succeeded',
            'invalid_saved_segment')
    for file in [receipt['delivery'], *receipt['files'].values()]:
        b.bound_ok(file)
    if (folder/'ARTIFACT_PROOF.json').exists():
        proof = h.read(folder/'ARTIFACT_PROOF.json')
        require(proof['prompt_id']==receipt['prompt_id'], 'artifact_identity_changed')
        b.bound_ok(proof['graph'])
        for role, file in proof['files'].items():
            require(file['sha256']==receipt['files'][role]['sha256'], 'artifact_receipt_hash_changed')
    else:
        b.check_history(h.read(folder/'HISTORY.json'), receipt['prompt_id'], h.read(folder/'workflow_api.json'), complete=True)
    return receipt


def candidates(run, item):
    name = item['id']
    if name == FIRST_LOST:
        yield OLD/name
    else:
        yield run/'A0'/name
    yield run/'A1'/name


def output_graph(item, number):
    graph = h.read(item['graph']['path'])
    for role in ROLES:
        graph['save_'+role]['inputs']['filename_prefix'] = f"{PREFIX}/A{number}/{item['id']}/{role}"
    return graph


def inventory(folder, graph):
    files = {}
    partial = []
    for role, (_, suffix) in ROLES.items():
        prefix = Path(graph['save_'+role]['inputs']['filename_prefix'])
        where = (b.SERVICE/'output'/prefix.parent).resolve()
        require(where.is_relative_to((b.SERVICE/'output').resolve()) and prefix.name==role, 'unsafe_output_prefix')
        matches = list(where.glob(role+'_*.'+suffix))
        require(len(matches)<=1, 'ambiguous_output_files')
        local = folder/f'native_{role}.{suffix}'
        if local.is_file() and matches:
            require(h.sha(local)==h.sha(matches[0]),'conflicting_local_output')
        file = matches[0] if matches else local
        if file.is_file():
            require(file.stat().st_size>0, 'empty_output_requires_review')
            files[role] = h.binding(file)
            partial.append(role)
    return files, partial


def verify_artifacts(files, graph, frames):
    require(set(files)==set(ROLES), 'incomplete_outputs')
    for file in files.values():
        b.bound_ok(file)
    for role in ('first', 'last'):
        with Image.open(files[role]['path']) as image:
            require(image.size==(736,1312) and json.loads(image.info.get('prompt','null'))==graph, 'keyframe_graph_mismatch')
    video, audio = b.streams(h.metadata(files['video']['path']))
    require((video['width'],video['height'],int(video['nb_frames']),video['r_frame_rate'])==(736,1312,frames,'24/1') and
            audio.get('codec_type')=='audio', 'salvage_native_streams_mismatch')
    flac = h.metadata(files['audio']['path'])['streams']
    require(len(flac)==1 and flac[0]['codec_name']=='flac' and
            abs(float(flac[0]['duration'])-frames/24)<.5, 'salvage_audio_mismatch')


def collect_to(folder, graph, state, entry):
    old_prefix = full.PREFIX
    prefix = Path(graph['save_video']['inputs']['filename_prefix']).parent
    require(prefix.name == folder.name, 'segment_prefix_mismatch')
    try:
        full.PREFIX = prefix.parent.as_posix()
        return full.collect(folder, entry, state)
    finally:
        full.PREFIX = old_prefix


def recover_files(target, graph, state, files, frames):
    verify_artifacts(files, graph, frames)
    freeze(target/'ARTIFACT_PROOF.json',dict(prompt_id=state['prompt_id'],graph=h.binding(target/'workflow_api.json'),
           files=files, source='complete_bound_native_files_without_service_history'))
    staging = target/'recovered_files'
    rows = {}
    for role, (field,suffix) in ROLES.items():
        prefix = Path(graph['save_'+role]['inputs']['filename_prefix']).parent
        destination = staging/'output'/prefix/(role+'.'+suffix)
        h.original_copy(files[role]['path'],destination)
        rows['save_'+role]={field:[dict(type='output',subfolder=prefix.as_posix(),filename=destination.name)]}
    service = b.SERVICE
    try:
        b.SERVICE = staging
        return collect_to(target,graph,state,{'outputs':rows})
    finally:
        b.SERVICE = service


def local_target(run, item, source):
    if source.parent != OLD:
        return source
    target=run/'original_capture'/item['id']
    (target/'deliverables').mkdir(parents=True,exist_ok=True)
    h.original_copy(source/'workflow_api.json',target/'workflow_api.json')
    return target


def prepare_attempt(run, item, folder, previous):
    number = int(folder.parent.name[1:])
    (folder/'deliverables').mkdir(parents=True,exist_ok=True)
    freeze(folder/'workflow_api.json', output_graph(item,number))
    h.original_copy(item['prompt']['path'],folder/'PROMPT.txt')
    fields = dict(plan=h.binding(run/'PLAN.json'),original_graph=item['graph'],graph=h.binding(folder/'workflow_api.json'))
    for n,reference in enumerate(item['references']):
        if reference['kind']=='opening':
            source=reference['source']
        else:
            parent = previous[reference['segment']]
            source=source_receipt(parent)['files']['last']
            fields['predecessor_receipt_'+str(n)] = h.binding(parent/'receipt.json')
        b.bound_ok(source)
        target = b.SERVICE/'input'/reference['input_name']
        fields['input_'+str(n)] = h.original_copy(source['path'],target)
        fields['source_'+str(n)] = source
    freeze(folder/'FROZEN_INPUT.json', fields)
    if not (folder/'STATE.json').exists():
        h.durable(folder/'STATE.json',dict(status='prepared',prompt_id=None,submissions=0))
    b.validate_frozen(folder)


def validate_native(folder):
    original = full.c.validate_continuation
    try:
        full.c.validate_continuation = lambda *args, **kwargs: h.read(OLD/'PLAN.json')
        full.c.native_validate(folder)
    finally:
        full.c.validate_continuation = original


def check_scope(run):
    require(run.resolve()==RUN.resolve(), 'wrong_continuation_root')
    plan=monitor.assert_config(run/'PLAN.json')
    full.validate(OLD)
    return plan


def post_once(folder, client, service):
    graph=h.read(folder/'workflow_api.json')
    state=h.read(folder/'STATE.json')
    require(not state.get('prompt_id') and not (folder/'SUBMISSION_CLAIM.json').exists(), 'unknown_claim_without_id')
    if queue_rows(client.get('/queue')):
        raise Wait('queue_busy_before_dispatch')
    if generation()['id']!=service['id']:
        raise Wait('service_changed_before_dispatch')
    request_file=folder/'REQUEST.actual.json'
    request=h.read(request_file) if request_file.exists() else dict(prompt=graph,client_id=str(uuid.uuid4()))
    require(request.get('prompt')==graph and bool(request.get('client_id')), 'frozen_request_mismatch')
    freeze(folder/'REQUEST.actual.json',request)
    freeze(folder/'SUBMISSION_CLAIM.json',dict(at=h.now(),graph=h.binding(folder/'workflow_api.json'),request=h.binding(folder/'REQUEST.actual.json'),generation=service))
    state.update(status='submit_outcome_unknown',submissions=1)
    h.durable(folder/'STATE.json',state)
    response=client.post(request)
    freeze(folder/'SUBMISSION_RESPONSE.json',response)
    require(response.get('prompt_id') and not response.get('node_errors'),'submission_rejected')
    state.update(status='submitted',prompt_id=response['prompt_id'])
    h.durable(folder/'STATE.json',state)


def mirror(run,name,folder,status,task=None):
    marker=run/'segments'/name/'STATE.json'
    marker.parent.mkdir(parents=True,exist_ok=True)
    h.durable(marker,dict(status=status,prompt_id=task,folder=str(folder.resolve())))


def watch(run, item, folder, client):
    state=h.read(folder/'STATE.json')
    task=state.get('prompt_id')
    if not task and (folder/'SUBMISSION_RESPONSE.json').exists():
        response=h.read(folder/'SUBMISSION_RESPONSE.json')
        require(response.get('prompt_id') and not response.get('node_errors'),'submission_rejected')
        task=state['prompt_id']=response['prompt_id']
        state['status']='submitted'
        h.durable(folder/'STATE.json',state)
    require(task, 'unknown_claim_without_id')
    graph=h.read(folder/'workflow_api.json')
    target=local_target(run,item,folder)
    mirror(run,item['id'],target,'submitted',task)
    service=generation()
    history=client.get('/history/'+task)
    queue=client.get('/queue')
    if generation()['id']!=service['id']:
        raise Wait('service_changed_during_check')
    entry=b.check_history(history,task,graph)
    queued=accepted(queue,task,graph)
    if folder.parent!=OLD and (entry or queued):
        claim=h.read(folder/'SUBMISSION_CLAIM.json')
        if claim['generation']['id']==service['id'] and not (folder/'ACCEPTED_GENERATION.json').exists():
            freeze(folder/'ACCEPTED_GENERATION.json',dict(prompt_id=task,graph=h.binding(folder/'workflow_api.json'),
                   generation=service,proof=history if entry else {'queue':queue}))
    for latest in (folder/'HISTORY.json',folder/'HISTORY.latest.json',target/'HISTORY.json'):
        if not entry and latest.is_file():
            entry=b.check_history(h.read(latest),task,graph)
            if entry:history=h.read(latest)
    if entry and entry['status'].get('status_str')=='error':
        raise Blocked('known_native_failure')
    if entry and entry['status'].get('completed'):
        b.check_history(history,task,graph,complete=True)
        freeze(target/'HISTORY.json',history)
        collect_to(target,graph,state,entry)
        return target
    if entry or queued or queue_rows(queue):
        raise Wait('original_or_other_job_active')
    if folder.parent==OLD:
        prior=legacy_binding()
    else:
        evidence=folder/'ACCEPTED_GENERATION.json'
        require(evidence.exists(),'no_proven_generation_for_known_id')
        saved=h.read(evidence)
        b.bound_ok(saved['graph'])
        require(saved['prompt_id']==task,'accepted_id_changed')
        prior=saved['generation']
    if prior['id']==service['id']:
        raise Blocked('id_missing_within_same_service_generation')
    disappeared(prior,service)
    files,partial=inventory(folder,graph)
    if set(files)==set(ROLES):
        recover_files(target,graph,state,files,item['frames'])
        return target
    require(folder.parent.name!='A1','replacement_limit_one_per_segment')
    evidence=run/'loss'/item['id']/'ORIGINAL_LOSS.json'
    if not evidence.exists():
        freeze(evidence,dict(at=h.now(),prompt_id=task,old_generation=prior,new_generation=service,
              source=h.binding(folder/'workflow_api.json'),state=h.binding(folder/'STATE.json'),
              remaining_native_roles=partial,partial_files=files,history=history,queue=queue,provider_outcome='unknown_after_service_exit'))
    return None


def next_segment(run,item,previous,client):
    base,replacement=list(candidates(run,item))
    for folder in (base,replacement):
        if (folder/'receipt.json').exists() and h.read(folder/'STATE.json').get('status')=='saved':
            source_receipt(folder)
            return folder
    captures=run/'original_capture'/item['id']
    if (captures/'receipt.json').exists() and (captures/'STATE.json').exists() and h.read(captures/'STATE.json').get('status')=='saved':
        source_receipt(captures)
        return captures
    active = (replacement,) if (replacement/'SUBMISSION_CLAIM.json').exists() else (base,replacement)
    for folder in active:
        if folder.parent!=OLD:
            prepare_attempt(run,item,folder,previous)
        state=h.read(folder/'STATE.json')
        if state.get('prompt_id') or (folder/'SUBMISSION_CLAIM.json').exists():
            saved=watch(run,item,folder,client)
            if saved:return saved
            continue
        if queue_rows(client.get('/queue')):
            raise Wait('queue_busy_before_native_validation')
        validate_native(folder)
        if folder==replacement:
            # Recheck prior ID, prior output and new generation immediately before its replacement claim.
            recovered=watch(run,item,base,client)
            if recovered:return recovered
        service=generation()
        b.validate_frozen(folder)
        post_once(folder,client,service)
        mirror(run,item['id'],folder,'submitted',h.read(folder/'STATE.json')['prompt_id'])
        return watch(run,item,folder,client)
    raise Blocked('no_permitted_attempt')


def execute(run):
    plan=check_scope(run)
    with h.process_lock(OLD/'.full_script.lock'), h.process_lock(run/'.execute.lock'):
        previous={}
        receipts=[]
        client=h.Client()
        for item in plan['segments']:
            name=item['id']
            if item.get('prior'):
                folder=OLD/name
                b.bound_ok(item['prior'])
                source_receipt(folder)
            else:
                while True:
                    require(not (run/'PAUSE.json').exists(),'manual_pause')
                    h.durable(run/'STATE.json',dict(status='running',active_segment=name,completed=len(receipts),total=len(plan['segments'])))
                    try:
                        folder=next_segment(run,item,previous,client)
                        if folder:break
                    except (Wait,ConnectionError,TimeoutError,urllib.error.URLError) as error:
                        h.durable(run/'WAIT.json',dict(at=h.now(),segment=name,reason=str(error)))
                    time.sleep(25)
                mirror(run,name,folder,'saved',h.read(folder/'STATE.json')['prompt_id'])
            previous[name]=folder
            receipts.append(h.read(folder/'receipt.json'))
        result=full.assemble_all(run,receipts)
        h.durable(run/'STATE.json',dict(status='saved',active_segment=None,completed=len(receipts),total=len(receipts),delivery=result['delivery']))


def runner_arguments(run):
    return ['execute','--run',str(run.resolve())]


def supervise(run):
    config=check_scope(run)
    home=run/'supervision'
    with monitor.lock(home/'.monitor.lock'):
        child=None
        attempt=None
        while True:
            status=h.read(run/'STATE.json')
            if status['status'] in ('saved','blocked') or (run/'PAUSE.json').exists():
                tag='paused' if (run/'PAUSE.json').exists() else ('complete' if status['status']=='saved' else 'blocked')
                monitor.save(home/'STATE.json',dict(status=tag,reason=status.get('error') or tag,heartbeat_epoch=time.time()))
                return
            monitor.assert_config(run/'PLAN.json')
            cmd_args=runner_arguments(run)
            families=monitor.family_groups(monitor.process_rows(SCRIPT,cmd_args))
            old=monitor.process_rows(OLD.parent.parent.parent/'scripts/run_h3_full_script_20261102.py',['execute'])
            require(not old and len(families)<=1,'conflicting_runner_families')
            if child is not None and child.poll() is not None:
                monitor.save(attempt/'EXIT.json',dict(at=h.now(),returncode=child.returncode))
                child=None
            if families or child is not None:
                label='monitoring'
            else:
                progress=(status.get('active_segment'),status.get('completed'))
                attempts=[h.read(p) for p in (home/'attempts').glob('*/CLAIM.json')]
                latest=[a['epoch'] for a in attempts if a['progress']==list(progress)]
                action,until=guard.retry_decision(latest,time.time())
                if action=='restart_exhausted':
                    monitor.save(run/'STATE.json',dict(status='blocked',active_segment=progress[0],completed=progress[1],error='bounded_restarts_exhausted'))
                    continue
                label='backoff'
                if action=='launch':
                    attempt=home/'attempts'/uuid.uuid4().hex
                    freeze(attempt/'CLAIM.json',dict(at=h.now(),epoch=time.time(),progress=list(progress)))
                    command=[config['python'],'-B','-u',str(SCRIPT),*cmd_args]
                    with (attempt/'stdout.log').open('xb') as out,(attempt/'stderr.log').open('xb') as err:
                        child=subprocess.Popen(command,cwd=h.ROOT,creationflags=guard.NO_WINDOW,stdout=out,stderr=err,stdin=subprocess.DEVNULL)
                    monitor.save(attempt/'PROCESS.json',dict(command=command,pid=child.pid,at=h.now(),create_time=psutil.Process(child.pid).create_time()))
                    label='starting'
            monitor.save(home/'STATE.json',dict(status=label,heartbeat_epoch=time.time(),heartbeat_at=h.now(),
                                               supervisor=monitor.identity(psutil.Process()),families=families))
            time.sleep(20)


def prepare(run):
    require(run.resolve()==RUN and not (run/'PLAN.json').exists(),'wrong_or_existing_root')
    source=full.validate(OLD)
    legacy_binding()
    run.mkdir(parents=True,exist_ok=True)
    old=OLD/FIRST_LOST
    bindings=[h.binding(p) for p in [SCRIPT,guard.SCRIPT,monitor.SCRIPT,guard.INSTALL,OLD/'PLAN.json',OLD/'PRIMARY_DISPATCH_REVIEW.json',
              GUARD/'USER_RECOVERY_SCOPE.json',GUARD/'INITIAL_EVIDENCE.json',GUARD/'INCIDENT_LOOKUP.json',
              *[old/n for n in ('QUEUE.latest.json','STATE.json','REQUEST.actual.json','SUBMISSION_CLAIM.json','SUBMISSION_RESPONSE.json','FROZEN_INPUT.json')]]]
    items=copy.deepcopy(source['segments'])
    for item in items[:37]:
        folder=OLD/item['id']
        source_receipt(folder)
        item['prior']=h.binding(folder/'receipt.json')
        bindings.extend([item['prior'],h.binding(folder/'HISTORY.json'),h.binding(folder/'STATE.json')])
    config=dict(schema='h3_restart_continuation/v1',home=str(run),workspace=str(h.ROOT),config_path=str(run/'PLAN.json'),
                original_root=str(OLD),ensure_python=str(monitor.PYTHON.with_name('pythonw.exe')),python=str(monitor.PYTHON),
                user=h.read(guard.CONFIG)['user'],task_name=TASK,segments=items,max_replacement_per_segment=1,bindings=bindings)
    xml=ET.fromstring(monitor.task_xml(config))
    xml.find('.//{*}Arguments').text=f'-B "{SCRIPT}" supervise --run "{run}"'
    (run/'TASK.xml').write_text(ET.tostring(xml,encoding='unicode'),encoding='utf8')
    bindings.append(h.binding(run/'TASK.xml'))
    freeze(run/'PLAN.json',config)
    h.durable(run/'STATE.json',dict(status='prepared',active_segment=FIRST_LOST,completed=37,total=len(items)))
    print(h.sha(run/'PLAN.json'),flush=True)


if __name__=='__main__':
    import urllib.error
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['prepare','execute','supervise'])
    parser.add_argument('--run',type=Path,default=RUN)
    args=parser.parse_args()
    if args.mode=='execute':
        try:execute(args.run)
        except (ValueError,KeyError,subprocess.CalledProcessError) as error:
            state=h.read(args.run/'STATE.json')
            state.update(status='blocked',error=str(error))
            monitor.save(args.run/'STATE.json',state)
            raise
    else:
        globals()[args.mode](args.run)

