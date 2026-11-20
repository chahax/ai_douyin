"""Settle only the proven failed details *read*, retaining its unknown snapshot.

No command is replayed or queued here. Application/backfill/publication tasks
are excluded. The normal stopped original worker, exact snapshots, reviewed
read-only source and immutable UI evidence are required before the local CAS.
"""
import hashlib
import json
from pathlib import Path
import time
import psutil

from .browser_control import BrowserControlStore
from .fanqie_readonly_startup_recovery_v1 import _snapshot, _json, _freeze, _read, _path, bind

ROOT = Path(__file__).resolve().parents[2]
CODE = 'readonly_details_not_observed'
FILES = ('FILLED_DETAILS_CLICK_INTENT.json', 'FILLED_DETAILS_PANEL.json', 'FILLED_DETAILS_PANEL_BEFORE.json',
         'FILLED_DETAILS_ROW.json', 'FILLED_DETAILS_TABLE.json', 'worker.log', 'WORKER_LAUNCH.json', 'WORKER_PROCESS.json')
SOURCE_KEYS = {
    'src/platform_adapter/fanqie_filled_details_v1.py', 'tests/test_fanqie_filled_details_v1.py',
    'src/operations_accounts/fanqie_account_control.py', 'src/operations_accounts/fanqie_managed_promotion_v1.py',
    'src/operations_accounts/fanqie_readonly_startup_recovery_v1.py', 'scripts/run_fanqie_account.py'}


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def _check(accounts, command, owner, intent_ref):
    intent = _read(intent_ref)
    need(intent.get('schema') == 'fanqie_existing_filled_details_read_intent/v1'
         and intent.get('only_read_details') is True and intent.get('uploads_allowed') == 0
         and intent.get('submissions_allowed') == 0, 'original_read_only_intent_required')
    need(command['kind'] == 'fanqie_filled_details' and command['state'] == 'outcome_unknown'
         and command['error_code'] == 'handler_exception:DetailsNotConfirmed'
         and command['result'] == {'error_type': 'DetailsNotConfirmed', 'failure_phase': 'handler', 'handler_started': True}
         and command['account_id'] == intent['resource_id'] and command['binding_version'] == intent['binding_version']
         and owner and owner['state'] in {'active', 'outcome_unknown'}
         and all(owner[k] == command[k] for k in ('account_id', 'binding_version', 'owner_id', 'generation')),
         'exact_original_details_read_failure_required')
    env = accounts.get(command['account_id']); accounts.check_association(env)
    need(env['binding_version'] == intent['binding_version']
         and accounts.bindings().get(command['account_id'])['platform_identity_key'] == intent['expected_platform_identity_key']
         and command['payload'] == dict(environment_key=env['environment_key'], book_id=intent['book_id'],
             book_name=intent['book_name'], lookup_alias=intent['alias']), 'original_details_read_subject_changed')
    folder = accounts.folder(command['command_id'])
    need({p.name for p in folder.iterdir()} == set(FILES), 'unexpected_read_artifacts_require_review')
    artifacts = {name: bind(folder/name) for name in FILES}
    evidence = {name: _read(artifacts[name]) for name in FILES if name.endswith('.json')}
    subject = dict(resource_id=command['account_id'], binding_version=command['binding_version'],
        environment_key=env['environment_key'], platform_identity_key=intent['expected_platform_identity_key'],
        owner_id=command['owner_id'], generation=command['generation'], task_id=command['command_id'])
    for name in FILES:
        if name.startswith('FILLED_DETAILS_'):
            item = evidence[name]
            need(item.get('schema') == 'fanqie_filled_details_step/v1' and item.get('subject') == subject,
                 'readonly_ui_subject_changed')
    row = evidence['FILLED_DETAILS_ROW.json']['observation']
    target = {k: intent[k] for k in ('book_id', 'book_name', 'alias')}
    click = evidence['FILLED_DETAILS_CLICK_INTENT.json']['observation']
    before = evidence['FILLED_DETAILS_PANEL_BEFORE.json']['observation']
    panels = evidence['FILLED_DETAILS_PANEL.json']['observation']
    need(row.get('target') == click.get('target') == before.get('target') == panels.get('target') == target
         and click.get('selected') == row.get('selected') and click.get('details_click_limit') == 1
         and before.get('observation', {}).get('visible_panels') == 0
         and len(panels.get('observations', [])) == 20, 'exact_failed_details_read_evidence_required')
    for panel in panels['observations']:
        need(panel.get('schema') == 'fanqie_filled_details_panel/v1' and panel.get('visible_panels') == 0
             and panel.get('panel_observed') is False and panel.get('submission_performed') is False
             and panel.get('location') == {'origin':'https://kol.fanqieopen.com', 'path':'/page/promotion-list'},
             'details_read_did_not_fail_as_observed')
    process = evidence['WORKER_PROCESS.json']; launch = evidence['WORKER_LAUNCH.json']
    need(process.get('command_id') == launch.get('command_id') == command['command_id']
         and type(process.get('pid')) is int and process['pid'] > 0 and not psutil.pid_exists(process['pid']),
         'original_readonly_owner_not_exited')
    log = (folder/'worker.log').read_text(encoding='utf8')
    need('browser_worker_start stage=ready' in log and 'Browser session stopped.' in log,
         'normal_original_readonly_session_stop_required')
    return artifacts, process


def prepare_recovery(accounts, command_id, intent_ref, output_directory):
    with accounts.connection() as db:
        command, owner = _snapshot(db, command_id)
    artifacts, process = _check(accounts, command, owner, intent_ref)
    intent = _read(intent_ref); acceptance = _read(intent['source_acceptance'])
    need(set(acceptance['sources']) == SOURCE_KEYS, 'exact_reviewed_details_source_set_required')
    folder = _path(output_directory)
    need(not folder.exists(), 'new_technical_disposition_directory_required')
    sources = {}
    for key, ref in acceptance['sources'].items():
        need(Path(ref['path']).resolve() == (ROOT/key).resolve() and bind(ref['path']) == ref,
             'reviewed_readonly_source_changed')
        destination = folder/'source_snapshot'/key
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream: stream.write(Path(ref['path']).read_bytes())
        sources[key] = dict(original=ref, frozen=bind(destination))
    return _freeze(folder/'PLAN.json', dict(schema='fanqie_readonly_details_disposition/v1',
        database=str(accounts.db.resolve()), command_snapshot=command, owner_snapshot=owner,
        original_snapshot_sha256=hashlib.sha256(_json(command).encode()).hexdigest(), intent=intent_ref,
        source_acceptance=intent['source_acceptance'], sources=sources, artifacts=artifacts,
        process_pid=process['pid'], code=bind(__file__), prepared_at=time.time(),
        disposition=CODE, original_request_replay_allowed=False, business_writes_permitted=False))


def settle_recovery(accounts, plan_ref):
    plan = _read(plan_ref)
    need(plan.get('schema') == 'fanqie_readonly_details_disposition/v1' and plan.get('code') == bind(__file__)
         and plan.get('database') == str(accounts.db.resolve()) and plan.get('disposition') == CODE
         and plan.get('original_request_replay_allowed') is False and plan.get('business_writes_permitted') is False
         and plan.get('original_snapshot_sha256') == hashlib.sha256(_json(plan['command_snapshot']).encode()).hexdigest(),
         'technical_details_disposition_plan_changed')
    for ref in plan['artifacts'].values(): _read(ref) if ref['path'].endswith('.json') else need(bind(ref['path']) == ref, 'original_read_artifact_changed')
    for record in plan['sources'].values():
        need(bind(record['frozen']['path']) == record['frozen'] and record['frozen']['sha256'] == record['original']['sha256'],
             'readonly_source_snapshot_changed')
    with accounts.connection(True) as db:
        command, owner = _snapshot(db, plan['command_snapshot']['command_id'])
        if command['state'] == 'failed' and (command.get('result') or {}).get('technical_disposition_plan') == plan_ref:
            return command
        need(command == plan['command_snapshot'] and owner == plan['owner_snapshot'], 'original_readonly_snapshot_changed')
        for record in plan['sources'].values(): need(bind(record['original']['path']) == record['original'], 'readonly_code_changed_before_disposition')
        artifacts, process = _check(accounts, command, owner, plan['intent'])
        need(artifacts == plan['artifacts'] and process['pid'] == plan['process_pid'], 'original_details_evidence_changed')
        need(not db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND command_id!=? AND state IN ('queued','running','paused','waiting_human','outcome_unknown') LIMIT 1",
                            (command['account_id'], command['command_id'])).fetchone(), 'other_pending_task_requires_review')
        now = time.time()
        result = dict(reason=CODE, original_unknown_record_retained=True, before_snapshot=command,
            before_snapshot_sha256=plan['original_snapshot_sha256'], technical_disposition_plan=plan_ref,
            platform_reads_started=True, details_not_observed=True, original_request_replayed=False,
            business_writes_performed=False, settled_at=now)
        db.execute("UPDATE browser_control_commands SET state='failed',error_code=?,result=?,updated_at=? WHERE command_id=?",
                   (CODE, _json(result), now, command['command_id']))
        db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=? AND owner_id=? AND generation=?",
                   (now, command['account_id'], command['owner_id'], command['generation']))
        return BrowserControlStore._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',
                                                      (command['command_id'],)).fetchone())
