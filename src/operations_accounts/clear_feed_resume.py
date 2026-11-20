"""Bounded handback of a loaded, clear recommendation verification window.

Only requests the existing original-identity recovery; never activates accounts.
"""
import json
import sqlite3
import time
from dataclasses import replace
from pathlib import Path


def clear_loaded_feed(evidence):
    if not isinstance(evidence, dict):
        return False
    challenge, page = evidence.get('challenge', {}), evidence.get('page', {})
    return (challenge.get('version') == 3 and challenge.get('blocking') is False
        and challenge.get('surface_states') == []
        and page.get('host') == 'www.douyin.com' and page.get('path') == '/'
        and page.get('ready_state') == 'complete'
        and isinstance(page.get('feed_cards'), int) and page['feed_cards'] > 0
        and any(isinstance(v, dict) and isinstance(v.get('ready_state'), int)
                and v['ready_state'] >= 2 for v in page.get('videos', [])))


def allowed(account, path):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True) as db:
        row = db.execute('SELECT auto_visible_windows FROM account_browser_preferences WHERE account_uuid=?', (account,)).fetchone()
        return bool(row and row[0] == 2)


def read_control(account, path):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT account_uuid,account_key,state,error_code,revision,updated_at FROM account_controls WHERE account_uuid=?', (account,)).fetchone()
        return dict(row) if row else {}


def reserve(account, command, revision, evidence, path, now):
    with sqlite3.connect(path, timeout=3) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS clear_feed_resumes(command_id TEXT PRIMARY KEY, account_uuid TEXT NOT NULL, revision INTEGER NOT NULL, created_at REAL NOT NULL, evidence_json TEXT NOT NULL, result_json TEXT)')
        if db.execute('SELECT 1 FROM clear_feed_resumes WHERE command_id=?', (command,)).fetchone():
            return False
        if db.execute('SELECT 1 FROM clear_feed_resumes WHERE account_uuid=? AND created_at>?',(account,now-86400)).fetchone():
            # A new explicit user instruction can authorize one exact window;
            # it never erases or resets the automatic 24-hour history.
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='clear_feed_user_authorizations'").fetchone():
                return False
            row=db.execute('SELECT 1 FROM clear_feed_user_authorizations WHERE command_id=? AND account_uuid=? AND revision=? AND consumed_at IS NULL',
                           (command,account,revision)).fetchone()
            if not row:return False
            db.execute('UPDATE clear_feed_user_authorizations SET consumed_at=? WHERE command_id=?',(now,command))
        db.execute('INSERT INTO clear_feed_resumes VALUES(?,?,?,?,?,NULL)', (command,account,revision,now,json.dumps(evidence)))
        return True


def record_observation(account, command, revision, stage, path, now, evidence=None):
    evidence = evidence or {}
    # Deliberately omit frame text, URL parameters and all browser storage.
    safe = {k:evidence[k] for k in ('page','active_feed','video_layout','navigation') if k in evidence}
    challenge=evidence.get('challenge',{})
    safe['challenge']={k:challenge[k] for k in ('version','blocking','surface_states','frame_count') if k in challenge}
    with sqlite3.connect(path,timeout=3) as db:
        db.execute('CREATE TABLE IF NOT EXISTS clear_feed_observations(command_id TEXT PRIMARY KEY,account_uuid TEXT NOT NULL,revision INTEGER,stage TEXT NOT NULL,observed_at REAL NOT NULL,evidence_json TEXT NOT NULL)')
        db.execute('INSERT OR REPLACE INTO clear_feed_observations VALUES(?,?,?,?,?,?)',
                   (command,account,revision,stage,now,json.dumps(safe)))


def latest_observation(account, command, path, now=None):
    now=time.time() if now is None else now
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
        db.row_factory=sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='clear_feed_observations'").fetchone():
            return None
        row=db.execute('SELECT stage,observed_at FROM clear_feed_observations WHERE account_uuid=? AND command_id=?',(account,command)).fetchone()
        if row is None:return None
        return {'stage':row['stage'] if 0<=now-row['observed_at']<=45 else 'observation_stale',
                'observed_at':row['observed_at']}


def poll(actor, resource):
    """Runs on the owner thread between handlers, at most once per 15 seconds."""
    from src.scheduler import account_refresh as backend
    from .browser_control_runtime import binding_version
    if len(resource.manual_tasks) != 1 or getattr(resource, 'console_tasks', {}):
        return
    now = time.time()
    if now < getattr(resource, '_clear_feed_next_check', 0):
        return
    resource._clear_feed_next_check = now + 15
    command_id, tab_id = next(iter(resource.manual_tasks.items()))
    command = actor.store.get(command_id)
    # A user may authorize a handling window without authorizing recovery. The
    # immutable request scope wins over the saved automatic handback preference.
    if command and command.get('payload', {}).get('allow_automatic_resume') is False:
        return
    if (not command or command['state'] != 'waiting_human'
            or command.get('result', {}).get('target', {}).get('source') != 'recommend_feed'
            or command['account_id'] != resource.account_uuid):
        return
    if not allowed(resource.account_uuid, backend.DB):
        return
    control = read_control(resource.account_uuid, backend.DB)
    if (control.get('state') != 'paused' or control.get('account_key') != resource.account_key
            or control.get('error_code') not in {'human_required','verification_ui_unconfirmed','feed_not_ready'}
            or control.get('updated_at', now+1) > command['created_at']):
        return
    current = replace(resource.context, profile=resource.runtime.profiles.get(resource.account_key),
                      binding=resource.runtime.bindings.get(resource.account_key))
    if current.profile.status != 'active' or binding_version(current) != actor.binding_version:
        return
    actor._check_owner()
    page = resource.session.get_page(tab_id)
    evidence = page._cmd('inspect_feed_surface').get('evidence', {})
    if (evidence.get('challenge',{}).get('blocking') is False
            and evidence.get('page',{}).get('host')=='www.douyin.com'
            and evidence.get('page',{}).get('path')=='/jingxuan'
            and getattr(resource,'_feed_navigation_attempted',None)!=command_id):
        resource._feed_navigation_attempted=command_id
        actor._check_owner()
        from src.platform_adapter.recommendation_entry import enter_recommendation
        evidence['navigation']=enter_recommendation(page)
        record_observation(resource.account_uuid,command_id,control['revision'],
                           'recommendation_navigation',backend.DB,now,evidence)
        resource._clear_feed_observation=None
        return
    ready=clear_loaded_feed(evidence)
    stage=('ready_for_confirmation' if ready else 'challenge_present' if evidence.get('challenge',{}).get('blocking') is True else 'feed_not_loaded')
    record_observation(resource.account_uuid,command_id,control['revision'],stage,backend.DB,now,evidence)
    if not ready:
        resource._clear_feed_observation = None
        return
    previous = getattr(resource, '_clear_feed_observation', None)
    resource._clear_feed_observation = (command_id, control['revision'], now)
    if not previous or previous[:2] != (command_id, control['revision']) or not 3 <= now-previous[2] <= 60:
        return
    # Persist admission before any closure: interruption cannot repeat this attempt.
    proof = {'two_loaded_clear_observations': True, 'first_at': previous[2], 'last_at': now,
             'feed_cards': evidence['page']['feed_cards'], 'identity_verified': False}
    actor._check_owner()
    if not reserve(resource.account_uuid, command_id, control['revision'], proof, backend.DB, now):
        record_observation(resource.account_uuid,command_id,control['revision'],'resume_already_attempted',backend.DB,now,evidence)
        return
    resource.session.save_storage_state()
    from .retained_feed_session import enabled as retain_enabled, retain
    retained=retain_enabled(resource.account_uuid,backend.DB)
    if retained:
        retain(resource,page,tab_id)
    else:
        resource.session.close_tab(tab_id)
    actor.store.complete_waiting(command_id, actor.owner_id, actor.generation,
        result=dict(command['result'], automatic_clear_feed_handback=proof,
                    window_closed=not retained, window_minimized=retained, original_feed_tab_preserved=retained))
    resource.manual_tasks.pop(command_id)
    if not retained:
        resource.shutdown()
        resource.headless = True
    result = backend.complete_account_handling(resource.account_uuid, resource.account_key,
        handled_by='system:loaded-clear-feed:'+command_id, plan_kinds=('playback',),
        expected_revision=control['revision'])
    with sqlite3.connect(backend.DB, timeout=3) as db:
        db.execute('UPDATE clear_feed_resumes SET result_json=? WHERE command_id=?', (json.dumps(result),command_id))
