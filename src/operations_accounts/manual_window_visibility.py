"""Restore only the original manual page; never create a replacement profile."""
from .browser_control import BrowserControlRejected


METHOD = 'reveal_manual_window'


def restore_native_window(page):
    """Runs inside the existing headed worker, using its original page target."""
    if page.is_closed():
        raise RuntimeError('Original manual tab is closed')
    cdp = page.context.new_cdp_session(page)
    try:
        window = cdp.send('Browser.getWindowForTarget')
        window_id = window['windowId']
        cdp.send('Browser.setWindowBounds', {'windowId': window_id,
            'bounds': {'windowState': 'normal'}})
        # Recover an offscreen window as well as a minimized one. This changes
        # only placement; no navigation, form input or verification is performed.
        cdp.send('Browser.setWindowBounds', {'windowId': window_id,
            'bounds': {'left': 24, 'top': 24, 'width': 1200, 'height': 800}})
        page.bring_to_front()
        bounds = cdp.send('Browser.getWindowBounds', {'windowId': window_id})['bounds']
        visible = page.evaluate('() => document.visibilityState')
        if bounds.get('windowState') != 'normal' or visible != 'visible':
            raise RuntimeError('Original manual window display is unconfirmed')
        return {'restored': True, 'window_state': 'normal', 'page_visibility': 'visible'}
    finally:
        cdp.detach()


def original_command(store, account_id, payload):
    params = payload.get('params')
    if (payload.get('method') != METHOD or payload.get('operation_profile') is not None
            or not isinstance(params, dict)
            or set(params) != {'manual_id', 'owner_id', 'generation', 'tab_id'}):
        raise BrowserControlRejected('manual_display_invalid', '显示请求必须绑定原人工窗口。')
    command = store.get(params['manual_id'])
    result = (command or {}).get('result') or {}
    if (not command or command['account_id'] != account_id or command['kind'] != 'manual'
            or command['state'] != 'waiting_human' or command['owner_id'] != params['owner_id']
            or command['generation'] != params['generation']
            or result.get('tab_id') != params['tab_id'] or not params['tab_id']):
        raise BrowserControlRejected('manual_display_changed', '原窗口任务已变化，未重新打开。')
    return command


def check(ctx, payload):
    command = original_command(ctx.actor.store, ctx.account_id, payload)
    if (command['owner_id'] != ctx.actor.owner_id or command['generation'] != ctx.actor.generation
            or command['binding_version'] != ctx.binding_version
            or ctx.resource.manual_tasks.get(command['command_id']) != payload['params']['tab_id']
            or ctx.resource.session is None or ctx.resource.session.config.headless):
        raise BrowserControlRejected('manual_display_owner_changed', '原窗口不属于当前执行者，未另开环境。')
    return command


def reveal(ctx, payload):
    check(ctx, payload)
    from .interactive_desktop import require_interactive_desktop
    require_interactive_desktop()
    ctx.check_dispatch()
    try:
        result = ctx.resource.session.get_page(payload['params']['tab_id'])._cmd('reveal_manual_window')
    except BrowserControlRejected:
        raise
    except Exception:
        # The only effect of this fixed RPC is window placement. Losing its
        # acknowledgement (for example because the user closes the window)
        # is a failed display confirmation, never an unknown publication or
        # permission to open a replacement browser. The manual task retains
        # its independent native closure/identity gates.
        raise BrowserControlRejected('manual_display_unconfirmed',
            '原窗口显示未确认，可能已关闭；请刷新处理状态，未新建窗口或恢复账号。') from None
    if result.get('restored') is not True:
        raise BrowserControlRejected('manual_display_unconfirmed', '尚未确认原窗口显示，请核对原任务。')
    return {'read_result': {'restored': True, 'manual_id': payload['params']['manual_id'],
        'tab_id': payload['params']['tab_id'], 'account_pause_changed': False,
        'identity_verified': False}}


def queue(account_uuid, account_key):
    import uuid
    from .browser_control_runtime import _store, _window_commands, _submit
    store = _store()
    rows = _window_commands(account_key, 'manual')
    command = max(rows, key=lambda row: row['created_at']) if rows else None
    if not command or command['account_id'] != account_uuid:
        raise BrowserControlRejected('manual_display_changed', '没有可显示的原账号处理窗口。')
    payload = {'method': METHOD, 'operation_profile': None, 'params': {
        'manual_id': command['command_id'], 'owner_id': command['owner_id'],
        'generation': command['generation'], 'tab_id': (command.get('result') or {}).get('tab_id')}}
    original_command(store, account_uuid, payload)
    # Double clicks while queued/running reuse the same display request.
    for row in store.commands_of_kind(account_uuid, 'read'):
        if row['state'] in {'queued', 'running', 'paused', 'outcome_unknown'} and row['payload'] == dict(
                payload, account_key=account_key, account_uuid=account_uuid):
            return row
    return _submit(account_key, 'read', payload, 'manual-display:' + uuid.uuid4().hex, 300)


def reconcile_closed_display(db, command_id, now):
    """Settle only a legacy display fence backed by its exact native close receipt.

    Caller supplies a writer transaction. Never covers a business/identity read,
    missing closure evidence, a changed request, or an unrelated tab/owner.
    """
    import hashlib
    from .browser_control import BrowserControlStore, _json
    command = BrowserControlStore._command(db.execute(
        'SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone())
    if not command or command['kind'] != 'read' or command['state'] != 'outcome_unknown':
        return False
    payload = command['payload']
    params = payload.get('params')
    if (set(payload) != {'account_key','account_uuid','method','operation_profile','params'}
            or payload.get('method') != METHOD or payload.get('operation_profile') is not None
            or payload.get('account_uuid') != command['account_id']
            or not isinstance(params,dict)
            or set(params) != {'manual_id','owner_id','generation','tab_id'}
            or command['owner_id'] != params['owner_id'] or command['generation'] != params['generation']
            or command['cursor'] is not None):
        return False
    def unchanged(item):
        return hashlib.sha256(_json([item['account_id'],item['binding_version'],item['kind'],
            item['payload'],item['priority']]).encode()).hexdigest() == item['request_sha']
    if not unchanged(command):
        return False
    manual = BrowserControlStore._command(db.execute(
        'SELECT * FROM browser_control_commands WHERE command_id=?', (params['manual_id'],)).fetchone())
    closed = (manual or {}).get('result') or {}
    if (not manual or manual['kind'] != 'manual' or manual['state'] != 'succeeded'
            or manual['account_id'] != command['account_id'] or manual['binding_version'] != command['binding_version']
            or manual['owner_id'] != params['owner_id'] or manual['generation'] != params['generation']
            or manual['payload'].get('account_key') != payload['account_key'] or not unchanged(manual)
            or closed.get('window_closed') is not True or closed.get('identity_verified') is not False
            or closed.get('closed_tab_id') != params['tab_id'] or not params['tab_id']):
        return False
    db.execute('''CREATE TABLE IF NOT EXISTS manual_display_close_reconciliations(
        command_id TEXT PRIMARY KEY, original_command TEXT NOT NULL,
        original_manual TEXT NOT NULL, reconciled_at REAL NOT NULL)''')
    db.execute('INSERT INTO manual_display_close_reconciliations VALUES(?,?,?,?)',
        (command_id,_json(command),_json(manual),now))
    from .browser_execution_journal import finish
    finish(db,command,'failed','manual_window_closed',now)
    db.execute("UPDATE browser_control_commands SET state='failed',error_code='manual_window_closed',result=?,updated_at=? WHERE command_id=? AND state='outcome_unknown'",
        (_json({'display_confirmed':False,'original_window_closed':True,'manual_id':params['manual_id'],
                'closed_tab_id':params['tab_id'],'identity_verified':False,'account_pause_changed':False,
                'prior_unknown_result':command['result']}),now,command_id))
    return True


def reconcile_closed_displays(store, account_id):
    with store._db() as db:
        ids=[r[0]for r in db.execute("SELECT command_id FROM browser_control_commands WHERE account_id=? AND kind='read' AND state='outcome_unknown'",(account_id,))]
    for command_id in ids:
        with store._db(write=True) as db:
            reconcile_closed_display(db,command_id,store.clock())
