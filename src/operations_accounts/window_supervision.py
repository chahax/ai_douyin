"""Opt-in supervision of the existing owner window; no task or recovery dispatch."""
import sqlite3
import os
import time
from contextlib import closing
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / 'data/account_window_supervision.db'


def rollout_enabled():
    # Deployment gate, independent of per-account display preferences. Native
    # QA enables it only inside its own process; production remains opt-out.
    return os.environ.get('AI_DOUYIN_WINDOW_SUPERVISION', '').strip().lower() in {'1','true','yes'}


def preference(account, path=None):
    target = Path(path or DB).resolve()
    if not target.exists():
        return {'enabled': False, 'mode': 'background', 'revision': 0}
    with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='window_preferences'").fetchone():
            return {'enabled': False, 'mode': 'background', 'revision': 0}
        row = db.execute('SELECT account_key,enabled,mode,revision,display_owner,display_generation,display_binding FROM window_preferences WHERE account_uuid=?', (account,)).fetchone()
        return dict(row) if row else {'enabled': False, 'mode': 'background', 'revision': 0}


def save(account, key, enabled, mode, *, actor, expected_revision, path=None, control_path=None, target=None):
    """Internal store API. Web callers use the authenticated wrapper below."""
    if not account or not key or not actor or type(enabled) is not bool or mode not in ('background', 'watch'):
        raise ValueError('Invalid supervision preference')
    if mode == 'watch' and not target:
        raise ValueError('Viewing requires the current original owner')
    from src.scheduler.account_refresh import DB as controls
    with closing(sqlite3.connect(Path(control_path or controls).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        binding = db.execute('SELECT account_key FROM account_controls WHERE account_uuid=?', (account,)).fetchone()
        if not binding or binding[0] != key:
            raise ValueError('Account binding changed')
    with closing(sqlite3.connect(Path(path or DB), timeout=3)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("CREATE TABLE IF NOT EXISTS window_preferences(account_uuid TEXT PRIMARY KEY,account_key TEXT NOT NULL,enabled INTEGER NOT NULL,mode TEXT NOT NULL,revision INTEGER NOT NULL,display_owner TEXT NOT NULL,display_generation INTEGER NOT NULL,display_binding TEXT NOT NULL)")
        db.execute('CREATE TABLE IF NOT EXISTS window_preference_audit(id INTEGER PRIMARY KEY,account_uuid TEXT NOT NULL,revision INTEGER NOT NULL,enabled INTEGER NOT NULL,mode TEXT NOT NULL,actor TEXT NOT NULL,changed_at REAL NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS window_runtime(account_uuid TEXT PRIMARY KEY,owner_id TEXT NOT NULL,generation INTEGER NOT NULL,binding_version TEXT NOT NULL,applied_revision INTEGER NOT NULL,headed INTEGER NOT NULL,muted INTEGER NOT NULL,window_open INTEGER NOT NULL,observed_at REAL NOT NULL,protocol INTEGER NOT NULL)')
        old = db.execute('SELECT account_key,enabled,mode,revision,display_owner,display_generation,display_binding FROM window_preferences WHERE account_uuid=?', (account,)).fetchone()
        revision = old[3] if old else 0
        if revision != expected_revision or old and old[0] != key:
            raise ValueError('Window preference changed; refresh before saving')
        bound = (str(target['owner_id']), int(target['generation']), str(target['binding_version'])) if target else ('', 0, '')
        if old and (old[1], old[2], *old[4:]) == (int(enabled), mode, *bound):
            return revision  # Repeated clicks do not re-show or re-minimize.
        revision += 1
        db.execute('INSERT INTO window_preferences VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(account_uuid) DO UPDATE SET enabled=excluded.enabled,mode=excluded.mode,revision=excluded.revision,display_owner=excluded.display_owner,display_generation=excluded.display_generation,display_binding=excluded.display_binding', (account, key, int(enabled), mode, revision, *bound))
        db.execute('INSERT INTO window_preference_audit(account_uuid,revision,enabled,mode,actor,changed_at) VALUES(?,?,?,?,?,?)', (account, revision, int(enabled), mode, actor, time.time()))
        return revision


def save_from_web(account, key, enabled, mode, *, expected_revision, display=False):
    from src.web.components.auth import get_current_user, get_current_role, has_permission
    user = get_current_user()
    if not user or not has_permission(get_current_role(), 'admin'):
        raise PermissionError('Only a signed-in administrator can change supervision')
    if not rollout_enabled():
        raise RuntimeError('Window supervision has not been enabled for this backend')
    target = live_runtime(account) if display else None
    if display and not target:
        raise ValueError('Original window is not confirmed online')
    return save(account, key, enabled, mode, actor=str(user), expected_revision=expected_revision, target=target)


def runtime_snapshot(account, *, path=None, now=None):
    target = Path(path or DB).resolve()
    if not target.exists():
        return None
    with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT * FROM window_runtime WHERE account_uuid=?', (account,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result['fresh'] = 0 <= (time.time() if now is None else now) - result['observed_at'] <= 45
    return result


def enabled(resource):
    account = getattr(resource, 'account_uuid', None)
    return rollout_enabled() and isinstance(account, str) and bool(account) and bool(preference(account)['enabled'])


def live_runtime(account):
    if not rollout_enabled():
        return None
    state = runtime_snapshot(account)
    if not state or not state['fresh'] or not state['headed'] or not state['muted'] or not state['window_open'] or state['protocol']!=1:
        return None
    from .browser_control_runtime import DB as owner_db
    with closing(sqlite3.connect(Path(owner_db).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        owner = db.execute('SELECT owner_id,generation,binding_version,state,heartbeat FROM browser_control_owners WHERE account_id=?', (account,)).fetchone()
    if (not owner or owner[3] != 'active' or not 0 <= time.time() - owner[4] <= 90
            or tuple(owner[:3]) != (state['owner_id'], state['generation'], state['binding_version'])):
        return None
    return state


def takeover_ready(account, *, control_path=None, owner_path=None, runtime_path=None):
    """Paused is necessary, but an outstanding task/lock still forbids handover."""
    from src.scheduler.account_refresh import DB as control_db
    from .browser_control_runtime import DB as owner_db
    paths = ((control_path or control_db, 'SELECT state FROM account_controls WHERE account_uuid=?'),
             (owner_path or owner_db, "SELECT command_id FROM browser_control_commands WHERE account_id=? AND state IN ('running','paused','outcome_unknown')"),
             (runtime_path or Path(DB).parent/'douyin.db', "SELECT account_uuid FROM account_runtime_state WHERE account_uuid=? AND lock_owner IS NOT NULL AND lock_owner!=''"))
    results = []
    for path, sql in paths:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
            results.append(db.execute(sql, (account,)).fetchall())
    return bool(results[0] and results[0][0][0] == 'paused' and not results[1] and not results[2])


def pause_from_web(account, key):
    from src.web.components.auth import get_current_user, get_current_role, has_permission
    if not get_current_user() or not has_permission(get_current_role(), 'admin'):
        raise PermissionError('Only an administrator can request handover')
    from src.scheduler.account_refresh import pause_account
    pause_account(account, key, '管理员申请暂停自动操作以人工接管', preserve_existing_pause=True)


def keep_idle_window(resource):
    # Missing, closed, headless or unstarted resources cannot become "online".
    return bool(resource.session and not resource.session.config.headless
                and getattr(resource.session, '_proc', None) is not None
                and getattr(resource.session, '_supervision_protocol', 0)==1 and enabled(resource))


def synchronize(resource, actor):
    """Owner-thread safe point, also called between task RPCs. Never launches Chrome."""
    if not rollout_enabled():
        return
    now = time.monotonic()
    if now < getattr(resource, '_supervision_next', 0):
        return
    resource._supervision_next = now + 1
    pref = preference(resource.account_uuid)
    if not pref['enabled'] or not resource.session or getattr(resource.session, '_proc', None) is None:
        return
    actor._check_owner()
    headed = not resource.session.config.headless
    muted = bool(resource.session.config.mute_audio)
    compatible = getattr(resource.session, '_supervision_protocol', 0)==1
    state = resource.session.window_status()
    opened = state.get('open') is True and state.get('context_closed') is not True
    applied = getattr(resource, '_supervision_applied', 0)
    target_matches = not pref.get('display_owner') or (
        pref['display_owner'], pref['display_generation'], pref['display_binding']) == (
        actor.owner_id, actor.generation, actor.binding_version)
    if headed and opened and muted and compatible and target_matches and applied != pref['revision']:
        tabs = [r for r in state.get('tabs', []) if not r.get('closed')]
        if tabs:
            # Display only. No navigation, focus/keyboard injection or account recovery.
            resource.session.get_page(tabs[-1]['tab_id'])._cmd('supervision_window', mode=pref['mode'])
            actor._check_owner()
            resource._supervision_applied = applied = pref['revision']
    with closing(sqlite3.connect(DB, timeout=2)) as db, db:
        db.execute('INSERT INTO window_runtime VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_uuid) DO UPDATE SET owner_id=excluded.owner_id,generation=excluded.generation,binding_version=excluded.binding_version,applied_revision=excluded.applied_revision,headed=excluded.headed,muted=excluded.muted,window_open=excluded.window_open,observed_at=excluded.observed_at,protocol=excluded.protocol',
                   (resource.account_uuid, actor.owner_id, actor.generation, actor.binding_version, applied, int(headed), int(muted), int(opened), time.time(), int(compatible)))


def set_window(page, mode):
    """Restore/minimize this browser only, without bring_to_front or global input."""
    if mode not in ('watch', 'background'):
        raise ValueError('Invalid window mode')
    import sys
    if sys.platform == 'win32':
        from .window_noactivate import set_owned_window
        return set_owned_window(page, mode)
    desired = 'normal' if mode == 'watch' else 'minimized'
    cdp = page.context.new_cdp_session(page)
    try:
        window = cdp.send('Browser.getWindowForTarget')['windowId']
        cdp.send('Browser.setWindowBounds', {'windowId': window, 'bounds': {'windowState': desired}})
        actual = cdp.send('Browser.getWindowBounds', {'windowId': window})['bounds']['windowState']
        if actual != desired:
            raise RuntimeError('Window state not confirmed')
        return {'window_state': actual}
    finally:
        cdp.detach()


def window_state(page):
    cdp = page.context.new_cdp_session(page)
    try:
        window = cdp.send('Browser.getWindowForTarget')['windowId']
        return {'window_state': cdp.send('Browser.getWindowBounds', {'windowId': window})['bounds']['windowState']}
    finally:
        cdp.detach()


def window_state(page):
    cdp = page.context.new_cdp_session(page)
    try:
        window = cdp.send('Browser.getWindowForTarget')['windowId']
        return {'window_state': cdp.send('Browser.getWindowBounds', {'windowId': window})['bounds']['windowState']}
    finally:
        cdp.detach()
