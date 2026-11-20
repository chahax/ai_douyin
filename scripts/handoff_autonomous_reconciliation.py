"""Exact project-owner retirement and durable original-maintenance continuation.

Only the explicitly frozen autonomous original-work authority is accepted.
"""
import argparse
from datetime import datetime,timezone
import hashlib,json,os,sqlite3,sys
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import handoff_publication_reconciliation as v1
from src.operations_accounts.browser_control import BrowserControlStore,_json
from src.scheduler.deployment_maintenance import hold_queued
AUTH_SHA='9dbe372c8a4168d838791fa1b3437023beadb3d13045c9232686e25e88a66447'
MAINTENANCE_ID='0c749a24cb094863a8078b13531a8444'
REFRESH_ID='a201f22b8c8e4df38826e820285c730f'


def project_browser_children(proc, profile_dir, script_sha256):
    """Prove one project profile family; visible windows are explicitly allowed."""
    profile = Path(profile_dir).resolve()
    if not profile.is_relative_to(ROOT) or profile == ROOT:
        raise RuntimeError('Original browser profile must be inside the project')
    children = proc.children(recursive=True)
    if not 4 <= len(children) <= 40:
        raise RuntimeError('Unexpected idle headless family size')
    expected_python = (ROOT / '.venv/Scripts/pythonw.exe').resolve()
    driver = ROOT / '.local_py/site-packages/playwright/driver'
    expected_chrome = (Path(os.environ['ProgramFiles']) / 'Google/Chrome/Application/chrome.exe').resolve()
    python_ids, node_ids, console_ids, chrome_ids = set(), set(), set(), set()
    evidence, commands = [], {}
    for child in children:
        if child.create_time() < proc.create_time():
            raise RuntimeError('Child predates original service')
        name, command = child.name().lower(), child.cmdline()
        commands[child.pid] = command
        if name == 'pythonw.exe':
            if (len(command) != 4 or command[1:3] != ['-S', '-c']
                    or Path(command[0]).resolve() != expected_python
                    or hashlib.sha256(command[3].encode()).hexdigest() != script_sha256):
                raise RuntimeError('Not the exact original project pythonw worker')
            python_ids.add(child.pid)
        elif name == 'node.exe':
            if (len(command) != 3 or Path(command[0]).resolve() != (driver/'node.exe').resolve()
                    or Path(command[1]).resolve() != (driver/'package/cli.js').resolve()
                    or command[2] != 'run-driver' or Path(child.exe()).resolve() != (driver/'node.exe').resolve()):
                raise RuntimeError('Not the unique project Playwright driver')
            node_ids.add(child.pid)
        elif name == 'conhost.exe':
            if Path(child.exe()).resolve() != (Path(os.environ['SystemRoot'])/'System32/conhost.exe').resolve():
                raise RuntimeError('Unexpected console child')
            console_ids.add(child.pid)
        elif name == 'chrome.exe':
            if (not command or Path(command[0]).resolve() != expected_chrome
                    or Path(child.exe()).resolve() != expected_chrome):
                raise RuntimeError('Unexpected Chrome executable')
            profiles = [v.split('=', 1)[1] for v in command if v.startswith('--user-data-dir=')]
            if len(profiles) != 1 or Path(profiles[0]).resolve() != profile:
                raise RuntimeError('Chrome is not the original account profile')
            chrome_ids.add(child.pid)
        else:
            raise RuntimeError('Unrecognized or visible child; no stop performed')
        evidence.append({'pid': child.pid, 'ppid': child.ppid(), 'name': name,
                         'create_time': child.create_time()})
    by_pid = {r['pid']: r for r in evidence}
    if (len(by_pid) != len(children) or len(python_ids) not in {1, 2}
            or len(node_ids) != 1 or len(console_ids) > 1 or not chrome_ids):
        raise RuntimeError('Not a single project browser family')
    worker_roots = [pid for pid in python_ids if by_pid[pid]['ppid'] == proc.pid]
    worker_leaves = [pid for pid in python_ids if not any(by_pid[p]['ppid'] == pid for p in python_ids)]
    if len(worker_roots) != 1 or len(worker_leaves) != 1:
        raise RuntimeError('Worker ancestry is not one chain')
    if any(by_pid[p]['ppid'] not in python_ids|{proc.pid} for p in python_ids):
        raise RuntimeError('Worker parent mismatch')
    node_id = next(iter(node_ids))
    if by_pid[node_id]['ppid'] != worker_leaves[0] or any(by_pid[p]['ppid'] != node_id for p in console_ids):
        raise RuntimeError('Driver or console parent mismatch')
    chrome_roots = [p for p in chrome_ids if not any(v.startswith('--type=') for v in commands[p])]
    if len(chrome_roots) != 1 or by_pid[chrome_roots[0]]['ppid'] != node_id:
        raise RuntimeError('Not exactly one Chrome root under the original driver')
    chrome_root = chrome_roots[0]
    command = commands[chrome_root]
    headless = [v for v in command if v == '--headless' or v.startswith('--headless=')]
    if (len(headless) > 1 or (headless and headless[0] not in {'--headless', '--headless=new'})
            or '--remote-debugging-pipe' not in command or '--enable-automation' not in command):
        raise RuntimeError('An unproven Chrome context remains')
    for pid in chrome_ids-{chrome_root}:
        types = [v.split('=',1)[1] for v in commands[pid] if v.startswith('--type=')]
        if len(types) != 1 or types[0] not in {'renderer','gpu-process','utility','crashpad-handler','zygote'}:
            raise RuntimeError('Unexpected Chrome child type')
        cursor, visited = pid, set()
        while cursor != chrome_root:
            if cursor in visited or cursor not in chrome_ids:
                raise RuntimeError('Chrome descendant is outside the original root')
            visited.add(cursor)
            cursor = by_pid[cursor]['ppid']
    for item in evidence:
        parent = by_pid.get(item['ppid'])
        if parent and item['create_time'] < parent['create_time']:
            raise RuntimeError('Child identity or ancestry changed')
    return children, evidence


def read_inputs(path,sha,maintenance_path,maintenance_sha):
    if sha!=AUTH_SHA:raise RuntimeError('Exact autonomous authority required')
    ref={'path':str(Path(path).resolve()),'sha256':sha}
    auth=json.loads(v1._read_reference(ref))
    if (auth.get('schema')!='publication_autonomous_reconciliation_authorization/v2'
            or auth.get('project_browser_process_termination_authorized') is not True
            or auth.get('backend_restart_authorized') is not True
            or auth.get('baseline_daily_runs')!=34 or auth.get('active_control_revision')!=43
            or auth.get('allowed_reconciliation_control_state')!='paused'
            or auth.get('allowed_reconciliation_control_revision')!=43):
        raise RuntimeError('Autonomous deployment scope mismatch')
    originals=[json.loads(v1._read_reference(auth[name])) for name in ('original_command','prior_reconciliation')]
    maintenance_ref={'path':str(Path(maintenance_path).resolve()),'sha256':maintenance_sha}
    refs=json.loads(v1._read_reference(maintenance_ref))
    frozen={name:json.loads(v1._read_reference(refs[name])) for name in ('maintenance_command','refresh_run','refresh_account')}
    if frozen['maintenance_command']['command_id']!=MAINTENANCE_ID or frozen['refresh_run']['run_id']!=REFRESH_ID:
        raise RuntimeError('Only the specified original queued maintenance may continue')
    return auth,ref,originals,maintenance_ref,frozen


def current_source(browser,auth,reference):
    from src.operations_accounts import publication_autonomous_reconciliation as authority
    previous=authority.row(browser,auth['account_uuid'])
    if previous:
        if json.loads(previous['authorization'])!=reference or not previous['new_owner_id'] or previous['new_generation'] is None:
            raise RuntimeError('A prior autonomous handoff has no live reviewed successor')
        owner_id=previous['new_owner_id'];generation=previous['new_generation']
        created=previous['new_owner_create_time'];pid=int(owner_id.split(':')[1])
        if not isinstance(created,(float,int)) or created<=0:raise RuntimeError('Successor process identity missing')
    else:
        owner_id=auth['source_owner_id'];generation=auth['source_generation']
        created=auth['source_backend_create_time'];pid=auth['source_backend_pid']
    return {'owner_id':owner_id,'generation':generation,'original_backend_pid':pid,'original_backend_create_time':created}


def check_idle(control,browser,auth,reference,originals,frozen):
    if not control.in_transaction or not browser.in_transaction:raise RuntimeError('Both writer fences required')
    owners=[dict(row) for row in browser.execute("SELECT * FROM browser_control_owners WHERE state!='released'")]
    source=current_source(browser,auth,reference)
    if len(owners)!=1 or any(owners[0][k]!=v for k,v in {'account_id':auth['account_uuid'],
            'owner_id':source['owner_id'],'generation':source['generation'],
            'binding_version':auth['binding_version'],'state':'active'}.items()):raise RuntimeError('Exact source owner changed')
    commands=[BrowserControlStore._command(row) for row in browser.execute('SELECT * FROM browser_control_commands')]
    by_id={c['command_id']:c for c in commands};expected={c['command_id']:c for c in originals}
    if any(by_id.get(key)!=value for key,value in expected.items()):raise RuntimeError('Original unknown snapshots changed')
    from src.operations_accounts import publication_autonomous_reconciliation as authority
    allowed=authority._allowed_unresolved(browser,auth,reference)
    unresolved=[c for c in commands if c['state'] not in {'queued','succeeded','failed'}]
    if any(c['account_id']!=auth['account_uuid'] or c['state']!='outcome_unknown' or c['command_id'] not in allowed for c in unresolved):
        raise RuntimeError('Another running, protected or unknown command remains')
    if by_id.get(MAINTENANCE_ID)!=frozen['maintenance_command']:raise RuntimeError('Original queued maintenance changed')
    controls=[dict(row) for row in control.execute('SELECT * FROM account_controls')]
    matching=[c for c in controls if c['account_uuid']==auth['account_uuid']]
    frozen_control=json.loads(v1._read_reference(auth['control_snapshot']))
    if (len(matching)!=1 or matching[0]!=frozen_control or matching[0]['account_key']!=auth['account_key'] or matching[0]['state']!='paused'
            or matching[0]['revision']!=43 or matching[0].get('error_code')!='outcome_unknown'
            or any(c['state']!='paused' for c in controls if c['account_uuid']!=auth['account_uuid'])
            or any(c['recovery_requested_at'] is not None or c['recovery_lease_until'] or c['recovery_token'] for c in controls)):
        raise RuntimeError('Original control/recovery gate changed')
    for kind in ('refresh','smart','playback'):
        accounts=[dict(row) for row in control.execute(f'SELECT * FROM {kind}_accounts')]
        runs=[dict(row) for row in control.execute(f'SELECT * FROM {kind}_runs')]
        if kind=='refresh' and (not any(row==frozen['refresh_account'] for row in accounts)
                or not any(row==frozen['refresh_run'] for row in runs)):
            raise RuntimeError('Frozen refresh cursor or run is absent')
        for row in accounts:
            if kind=='refresh' and row['account_uuid']==auth['account_uuid']:
                if row!=frozen['refresh_account']:raise RuntimeError('Original refresh cursor changed')
            elif row['run_id'] is not None or row['lease_until']:raise RuntimeError('Other scheduled lease remains')
        for row in runs:
            if kind=='refresh' and row['run_id']==REFRESH_ID:
                if row!=frozen['refresh_run']:raise RuntimeError('Original refresh run changed')
            elif row['finished_at'] is None or row['status'] in {'running','starting','claimed','outcome_unknown'}:
                raise RuntimeError('Other scheduled work remains')
    if control.execute("SELECT 1 FROM account_handling_requests WHERE status IN ('requested','probing')").fetchone():raise RuntimeError('Identity handling remains')
    with sqlite3.connect((ROOT/'data/douyin.db').as_uri()+'?mode=ro',uri=True) as db:
        if db.execute("SELECT 1 FROM account_runtime_state WHERE coalesce(lock_owner,'')<>'' OR coalesce(lock_expires_at,'')<>''").fetchone():raise RuntimeError('Business lease remains')
        rows=db.execute('SELECT day_key,daily_runs FROM account_runtime_state WHERE account_uuid=?',(auth['account_uuid'],)).fetchall()
        profile=db.execute('SELECT browser_profile_dir FROM account_runtime_bindings WHERE account_uuid=?',(auth['account_uuid'],)).fetchall()
    if len(rows)!=1 or type(rows[0][1]) is not int or rows[0][1]<0:raise RuntimeError('Daily counter is unreadable')
    if len(profile)!=1 or Path(profile[0][0]).resolve()!=Path(auth['browser_profile']).resolve():raise RuntimeError('Original profile changed')
    manual=ROOT/'data/account_manual_windows.db'
    if manual.exists():
        with sqlite3.connect(manual.as_uri()+'?mode=ro',uri=True) as db:
            if db.execute("SELECT 1 FROM manual_window_jobs WHERE state NOT IN ('closed','failed')").fetchone():raise RuntimeError('Legacy manual window remains')
    return owners[0],{c['command_id']:hashlib.sha256(_json(c).encode()).hexdigest() for c in unresolved},source,{'day_key':rows[0][0],'daily_runs':rows[0][1]}


def main():
    parser=argparse.ArgumentParser()
    for name in ('authorization-path','authorization-sha256','maintenance-refs','maintenance-refs-sha256','worker-source','worker-script-sha256','evidence'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    # The v1 helpers are reused without changing their historical contract.
    auth,ref,originals,maintenance_ref,frozen=read_inputs(args.authorization_path,args.authorization_sha256,args.maintenance_refs,args.maintenance_refs_sha256)
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    with sqlite3.connect(store.path) as browser:
        browser.row_factory=sqlite3.Row
        owner_auth=current_source(browser,auth,ref)
    process=v1.exact_backend(owner_auth)
    worker=v1.browser_proof.worker_source_evidence(args.worker_source,args.worker_script_sha256)
    target=Path(args.evidence).resolve();retirement=target.with_name(target.stem+'.RETIREMENT.json')
    if not target.is_relative_to(ROOT) or target.exists() or retirement.exists():raise RuntimeError('New project evidence paths required')
    target.parent.mkdir(parents=True,exist_ok=True)
    record={'schema':'autonomous_reconciliation_handoff_run/v2','authorization':ref,'maintenance_references':maintenance_ref,
        'worker_source':worker,'phase':'checking','termination_requested':False,'parent_exited':False,'handoff_committed':False}
    v1.exclusive_json(target,record)
    try:
        with sqlite3.connect(ROOT/'data/account_refresh.db',timeout=2) as control,sqlite3.connect(store.path,timeout=2) as browser:
            control.row_factory=sqlite3.Row;browser.row_factory=sqlite3.Row
            control.execute('BEGIN IMMEDIATE');browser.execute('BEGIN IMMEDIATE')
            owner,digests,source,counter=check_idle(control,browser,auth,ref,originals,frozen)
            if source!=owner_auth:raise RuntimeError('Original source owner changed')
            from src.operations_accounts.publication_autonomous_reconciliation import validate_authorization
            validate_authorization(ref)
            v1.preflight_chrome_readability()
            process=v1.exact_backend(owner_auth)
            children,observed=project_browser_children(process,auth['browser_profile'],args.worker_script_sha256)
            held=hold_queued(control,browser,authorization=ref,command_id=MAINTENANCE_ID,run_id=REFRESH_ID,
                account_uuid=auth['account_uuid'],account_key=auth['account_key'],browser_path=store.path)
            # Durable pause first. Reacquire the scheduler fence and recheck every
            # gate before stopping. A failure leaves an explicit hold, no fake result.
            control.commit();control.execute('BEGIN IMMEDIATE')
            final_owner,final_digests,final_source,final_counter=check_idle(control,browser,auth,ref,originals,frozen)
            if (final_owner,final_digests,final_source,final_counter)!=(owner,digests,source,counter):raise RuntimeError('Deployment boundary changed')
            if read_inputs(args.authorization_path,args.authorization_sha256,args.maintenance_refs,args.maintenance_refs_sha256)!=(auth,ref,originals,maintenance_ref,frozen):raise RuntimeError('Frozen deployment input changed')
            process=v1.exact_backend(owner_auth)
            _,latest=project_browser_children(process,auth['browser_profile'],args.worker_script_sha256)
            if sorted(latest,key=lambda c:c['pid'])!=sorted(observed,key=lambda c:c['pid']):raise RuntimeError('Project process family changed')
            record.update(phase='termination_requested',termination_requested=True,original_owner=owner,maintenance_hold=held,
                observed_children=observed,unresolved_snapshots_sha256=digests,original_runtime_counter=counter)
            target.write_text(_json(record),encoding='utf8')
            process.terminate();process.wait(timeout=5)  # Exact backend only; EOF closes its context.
            record.update(parent_exited=True,phase='parent_exited')
            gone,alive=psutil.wait_procs(children,timeout=30)
            record.update(gone_child_ids=sorted(p.pid for p in gone),alive_child_ids=sorted(p.pid for p in alive))
            if alive:raise RuntimeError('Project children have not naturally exited; no release')
            v1.browser_proof.assert_profile_exited(auth['browser_profile'])
            checks=v1.check_original_processes_exited(owner_auth,observed)
            dead={'schema':'publication_reconciliation_retirement/20261019/v1','account_uuid':auth['account_uuid'],
                'original_command_id':auth['original_command_id'],'owner_id':source['owner_id'],'generation':source['generation'],
                'original_backend_pid':source['original_backend_pid'],'original_backend_create_time':source['original_backend_create_time'],
                'parent_exited':True,'descendants_exited':True,'observed_children':observed,'gone_child_ids':record['gone_child_ids'],
                'alive_child_ids':[],'pid_identity_checks':checks,'finished_at':datetime.now(timezone.utc).timestamp()}
            deadref=v1.exclusive_json(retirement,dead)
            audit=store.handoff_publication_reconciliation_v2(owner_id=source['owner_id'],generation=source['generation'],
                authorization=ref,expected_snapshots_sha256=digests,retirement_evidence=deadref,connection=browser)
            browser.commit()
            record.update(phase='handoff_committed',handoff_committed=True,retirement_evidence=deadref,core_handoff=audit)
            target.write_text(_json(record),encoding='utf8')
    except BaseException as exc:
        record.update(phase='stopped_without_handoff' if record['parent_exited'] else 'stop_unconfirmed' if record['termination_requested'] else 'rejected_before_stop',error_type=type(exc).__name__)
        target.write_text(_json(record),encoding='utf8');raise
    print(_json({'handoff_committed':True,'maintenance_wait_preserved':True,'evidence':str(target)}))


if __name__=='__main__':main()
