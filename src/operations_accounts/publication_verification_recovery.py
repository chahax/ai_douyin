"""General original-bound, read-only publication recovery.

The original submission claim is never removed. Only independently verified
native work evidence settles its unknown result. No upload/publish/comment API
is reachable from this handler. Historical one-off handoffs retain precedence.
"""
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

from .browser_control import BrowserControlRejected, BrowserCommandResult, _json

ROOT = Path(__file__).resolve().parents[2]
KIND = 'publication_verify'
MAX_ATTEMPTS = 3
RETRY_SECONDS = 300
LIVE = ('running', 'paused', 'waiting_human', 'outcome_unknown')


def _reject(code='publication_proof_changed'):
    raise BrowserControlRejected(code, '原发布、账号绑定或核验依据已变化，保留原记录，不重新发布。')


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _read(ref):
    path = Path(ref['path']).resolve()
    if not path.is_relative_to((ROOT / 'data/publish_runs').resolve()):
        _reject()
    raw = path.read_bytes()
    if len(raw) > 16 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != ref['sha256']:
        _reject()
    return raw


def _ref(path):
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _specialized(db, account_id):
    for table in ('browser_control_reconciliation_handoffs', 'browser_control_autonomous_reconciliation'):
        if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            if db.execute(f'SELECT 1 FROM {table} WHERE account_id=?', (account_id,)).fetchone():
                return True
    return False


def _original(store, db, account_id):
    if _specialized(db, account_id):
        return None
    rows = [store._command(r) for r in db.execute(
        "SELECT * FROM browser_control_commands WHERE account_id=? AND state IN ('running','paused','waiting_human','outcome_unknown')",
        (account_id,))]
    publications = [r for r in rows if r['kind'] == 'publish' and r['state'] == 'outcome_unknown']
    if len(publications) != 1:
        return None
    original = publications[0]
    owner = db.execute('SELECT owner_id,generation FROM browser_control_owners WHERE account_id=?', (account_id,)).fetchone()
    # A human tab belonging to this exact owner is permitted while handling a
    # confirmed challenge. Other unfinished business keeps the fence intact.
    if any(r['command_id'] != original['command_id'] and not (
            r['kind'] == 'manual' and r['state'] == 'waiting_human'
            and owner and r['owner_id'] == owner['owner_id'] and r['generation'] == owner['generation'])
            for r in rows):
        return None
    return original


def _attempts(store, db, original_id):
    return [store._command(r) for r in db.execute(
        "SELECT * FROM browser_control_commands WHERE kind=? AND json_extract(payload,'$.original_command_id')=? ORDER BY created_at,command_id",
        (KIND, original_id))]


def _source(context, original):
    request = original['payload']['request']
    identity = {'platform_identity_key': context.binding.platform_identity_key,
                'video_sha256': original['payload']['video_sha256']}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    lock = ROOT / 'data/publish_runs' / (key + '.submitted.json')
    native = json.loads(lock.read_text(encoding='utf8'))
    journal = Path(native['journal']).resolve()
    if native.get('status') != 'submission_started':
        _reject()
    refs = {'journal': _ref(journal), 'submission_lock': _ref(lock)}
    rows = [json.loads(line) for line in _read(refs['journal']).decode('utf8').splitlines() if line.strip()]
    prepared = [r for r in rows if r.get('stage') == 'prepared']
    if len(prepared) != 1:
        _reject()
    first = prepared[0]
    tags = [v.strip().lstrip('#') for v in request.get('hashtags', []) if v.strip().lstrip('#')]
    if (first.get('account_uuid') != context.account_uuid or first.get('account') != context.account_key
            or first.get('platform_identity_key') != identity['platform_identity_key']
            or first.get('video_sha256') != identity['video_sha256'] or first.get('title') != request['title']
            or first.get('hashtags') != tags
            or first.get('description') != request.get('description', '')
            or first.get('visibility') != request.get('visibility', 'public')
            or Path(first.get('video_path', '')).resolve() != Path(request['video_path']).resolve()
            or type(request.get('ai_generated', True)) is not bool
            or type(request.get('fictional_story', True)) is not bool
            or first.get('ai_declaration_required') != request.get('ai_generated', True)
            or first.get('fiction_declaration_required') != request.get('fictional_story', True)):
        _reject()
    started = datetime.fromisoformat(first['at_bjt']).timestamp()
    if not original['created_at'] - 5 <= started <= original['updated_at'] + 5:
        _reject()
    clicks = [r for r in rows if r.get('stage') == 'publish_click_dispatching']
    reserves = [r for r in rows if r.get('stage') == 'submission_started']
    if len(clicks) != 1 or len(reserves) != 1:
        _reject('publication_submission_unproven')
    return refs


def inputs(store, command, context):
    payload = command['payload']
    original = store.get(payload['original_command_id'])
    if (not original or original['kind'] != 'publish' or original['state'] != 'outcome_unknown'
            or _digest(original) != payload['original_snapshot_sha256']
            or original['account_id'] != context.account_uuid or payload['account_key'] != context.account_key
            or command['binding_version'] != original['binding_version']
            or command['account_id'] != original['account_id']):
        _reject()
    with store._db() as db:
        titles = [r for r in db.execute("SELECT payload FROM browser_control_commands WHERE account_id=? AND kind='publish'", (context.account_uuid,))
                  if json.loads(r[0]).get('request', {}).get('title') == original['payload']['request']['title']]
        if len(titles) != 1:
            _reject('publication_title_ambiguous')
    source = _source(context, original)
    if source != payload['source']:
        _reject()
    rows = [json.loads(line) for line in _read(source['journal']).decode('utf8').splitlines() if line.strip()]
    return original, rows


def queue_due(store, context, binding_version):
    """One idempotent bounded read attempt; this function never opens a browser."""
    with store._db() as db:
        original = _original(store, db, context.account_uuid)
        if not original or original['binding_version'] != binding_version:
            return None
        # Reused titles in this account cannot establish which submission won.
        same_title = [r for r in db.execute(
            "SELECT payload FROM browser_control_commands WHERE account_id=? AND kind='publish'",
            (context.account_uuid,)) if json.loads(r[0]).get('request', {}).get('title') == original['payload']['request']['title']]
        if len(same_title) != 1:
            return None
        attempts = _attempts(store, db, original['command_id'])
        if any(r['state'] in ('queued', *LIVE) for r in attempts):
            return None
        if len(attempts) >= MAX_ATTEMPTS:
            return None
        if attempts:
            last = attempts[-1]
            if (last.get('result') or {}).get('status') == 'human_required':
                # A closed original manual session is a new user action, never
                # infer challenge completion from a timer or an old login bit.
                handled = db.execute("""SELECT 1 FROM browser_control_commands WHERE account_id=?
                    AND kind='manual' AND state='succeeded' AND updated_at>? LIMIT 1""",
                    (context.account_uuid, last['updated_at'])).fetchone()
                if not handled:
                    return None
            elif (last.get('result') or {}).get('status') != 'verification_pending':
                return None
            if store.clock() - last['updated_at'] < RETRY_SECONDS:
                return None
    try:
        source = _source(context, original)
    except (OSError, ValueError, KeyError, TypeError, BrowserControlRejected):
        return None  # Missing native proof is not permission to guess or retry.
    return store.submit(context.account_uuid, binding_version, KIND,
        f"publication-verify:{original['command_id']}:{len(attempts)+1}",
        {'account_uuid': context.account_uuid, 'account_key': context.account_key,
         'original_command_id': original['command_id'], 'original_snapshot_sha256': _digest(original),
         'source': source, 'attempt': len(attempts)+1}, priority=400)


def claim(store, db, account_id, binding_version, owner_id, generation, *, allowed_kinds=None):
    original = _original(store, db, account_id)
    if not original:
        return None
    attempts = _attempts(store, db, original['command_id'])
    if any(r['state'] in ('running', 'paused', 'waiting_human', 'outcome_unknown') for r in attempts):
        return None
    queued = [r for r in attempts if r['state'] == 'queued'
              and (allowed_kinds is None or r['kind'] in allowed_kinds)]
    command = queued[0] if queued else None
    if (command is None and attempts and (attempts[-1].get('result') or {}).get('status') == 'human_required'
            and (allowed_kinds is None or 'manual' in allowed_kinds)):
        command = store._command(db.execute("""SELECT * FROM browser_control_commands WHERE account_id=?
            AND kind='manual' AND state='queued' ORDER BY created_at LIMIT 1""", (account_id,)).fetchone())
    if not command or command['binding_version'] != binding_version:
        return None
    if command['kind'] == KIND and command['payload']['original_snapshot_sha256'] != _digest(original):
        return None
    if command['kind'] == KIND and 'discovery_diagnostic' in command['payload']:
        # A diagnostic must not fall through to the old non-observing handler
        # when its separately reviewed, actor-local installation is not ready.
        try:
            from .publication_discovery_diagnostic_v1 import handler_ready
            if not handler_ready(command, owner_id, generation):
                return None
        except Exception:
            return None  # No claim or host retirement on missing read evidence.
    policy_directory = ROOT / 'data/publication_locator_provider_v1/policies'
    target = original['command_id']
    if command['kind'] == KIND and any((policy_directory / (target + suffix)).exists()
            for suffix in ('.json', '.required.json')):
        try:
            from .publication_locator_provider_v1 import provider_ready
            if not provider_ready(command, owner_id, generation):
                return None
        except Exception:
            return None
    db.execute("UPDATE browser_control_commands SET state='running',owner_id=?,generation=?,updated_at=? WHERE command_id=?",
        (owner_id, generation, store.clock(), command['command_id']))
    from .browser_execution_journal import record
    current = store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (command['command_id'],)).fetchone())
    record(db, current, 'admission_pending', store.clock())
    return current


def release_previous_boot(store, account_id, expected_owner):
    """A reboot proves old processes ended. TTL/process absence alone does not."""
    from .browser_boot_recovery import _boot_evidence
    evidence = _boot_evidence()
    if not evidence or not expected_owner:
        return False
    boot = evidence['boot_time']
    if (not 0 < boot <= evidence['backend_create_time'] <= store.clock()
            or expected_owner['heartbeat'] >= boot-5 or expected_owner['updated_at'] >= boot-5):
        return False
    with store._db(write=True) as db:
        owner = db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (account_id,)).fetchone()
        original = _original(store, db, account_id)
        if not owner or dict(owner) != expected_owner or not original:
            return False
        attempts = _attempts(store, db, original['command_id'])
        if not any(c['state'] == 'queued' and c['binding_version'] == owner['binding_version']
                and c['payload']['original_snapshot_sha256'] == _digest(original) for c in attempts):
            return False
        lineage = None
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_verification_handoffs'").fetchone():
            lineage = db.execute('SELECT * FROM publication_verification_handoffs WHERE account_id=?', (account_id,)).fetchone()
        original_owner = original['owner_id'] == owner['owner_id'] and original['generation'] == owner['generation']
        read_owner = (lineage and lineage['new_owner_id'] == owner['owner_id'] and lineage['new_generation'] == owner['generation']
                      and lineage['original_snapshot_sha256'] == _digest(original))
        if (not (original_owner or read_owner) or original['updated_at'] >= boot-5
                or not owner['owner_id'].startswith('backend:')):
            return False
        if db.execute("""SELECT 1 FROM browser_control_commands WHERE account_id=? AND command_id!=?
                AND state IN ('running','paused','waiting_human','outcome_unknown') LIMIT 1""",
                (account_id,original['command_id'])).fetchone():
            return False
        db.execute('''CREATE TABLE IF NOT EXISTS publication_verification_handoffs(
            account_id TEXT PRIMARY KEY, original_owner TEXT NOT NULL, boot_evidence TEXT NOT NULL,
            original_snapshot_sha256 TEXT NOT NULL, released_at REAL NOT NULL,new_owner_id TEXT,new_generation INTEGER)''')
        db.execute('''CREATE TABLE IF NOT EXISTS publication_verification_handoff_audit(
            audit_id INTEGER PRIMARY KEY,account_id TEXT NOT NULL,original_owner TEXT NOT NULL,
            boot_evidence TEXT NOT NULL,original_snapshot_sha256 TEXT NOT NULL,released_at REAL NOT NULL)''')
        values = (account_id, _json(expected_owner), _json(evidence), _digest(original), store.clock())
        db.execute('INSERT INTO publication_verification_handoff_audit(account_id,original_owner,boot_evidence,original_snapshot_sha256,released_at) VALUES(?,?,?,?,?)',values)
        db.execute('INSERT OR REPLACE INTO publication_verification_handoffs VALUES(?,?,?,?,?,NULL,NULL)',values)
        db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=?", (store.clock(), account_id))
        return True


def acquire_owner(store, account_id, binding_version, owner_id):
    with store._db(write=True) as db:
        original = _original(store, db, account_id)
        owner = db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (account_id,)).fetchone()
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_verification_handoffs'").fetchone()
        proof = db.execute('SELECT * FROM publication_verification_handoffs WHERE account_id=?', (account_id,)).fetchone() if exists else None
        if (not original or not owner or owner['state'] != 'released' or not proof
                or json.loads(proof['original_owner'])['owner_id'] != owner['owner_id']
                or json.loads(proof['original_owner'])['generation'] != owner['generation']
                or original['binding_version'] != binding_version or owner['binding_version'] != binding_version
                or proof['original_snapshot_sha256'] != _digest(original)):
            _reject('publication_owner_recovery_blocked')
        generation = owner['generation'] + 1
        now = store.clock()
        db.execute("UPDATE browser_control_owners SET owner_id=?,generation=?,state='active',heartbeat=?,updated_at=? WHERE account_id=?",
            (owner_id, generation, now, now, account_id))
        db.execute('UPDATE publication_verification_handoffs SET new_owner_id=?,new_generation=? WHERE account_id=?',
            (owner_id,generation,account_id))
        return dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (account_id,)).fetchone())


def needs_owner(store, account_id):
    with store._db() as db:
        original = _original(store, db, account_id)
        return bool(original and any(c['state'] == 'queued' for c in _attempts(store, db, original['command_id'])))


def has_unknown_publication(store, account_id):
    with store._db() as db:
        return _original(store, db, account_id) is not None


def queue_blocker(store, account_id):
    """Safe small diagnostics for UI; no payload, title, or authenticated URL."""
    with store._db() as db:
        owner = db.execute('SELECT state,heartbeat FROM browser_control_owners WHERE account_id=?', (account_id,)).fetchone()
        unknown = db.execute("""SELECT command_id,kind FROM browser_control_commands
            WHERE account_id=? AND state='outcome_unknown' ORDER BY created_at LIMIT 1""", (account_id,)).fetchone()
        if unknown:
            attempts = _attempts(store,db,unknown['command_id']) if unknown['kind'] == 'publish' else []
            latest = attempts[-1] if attempts else None
            status = (latest.get('result') or {}).get('status') if latest else None
            phase = ((latest.get('cursor') or {}).get('phase') if latest else None)
            reason = ('publication_human_required' if status == 'human_required' else
                      'publication_verification_pending' if unknown['kind'] == 'publish' else 'original_outcome_unknown')
            return {'queue_blocker': reason, 'blocking_command_id': unknown['command_id'],
                    'verification_attempts': len(attempts),
                    'verification_status': status or 'not_started',
                    'verification_phase': phase if phase in {'identity_check','work_discovery','detail_verification','saving_result'} else '',
                    'verification_state': latest['state'] if latest else 'not_queued',
                    'owner_stale': bool(owner and store.clock()-owner['heartbeat'] > store.owner_ttl)}
        if owner and owner['state'] != 'released' and store.clock()-owner['heartbeat'] > store.owner_ttl:
            return {'queue_blocker': 'owner_recovery_blocked', 'owner_stale': True}
    return {}


def public_status(store):
    """Bounded authenticated-dashboard summary, independent of old incidents."""
    with store._db() as db:
        rows = db.execute("""SELECT command_id,account_id,payload,state,cursor,result,error_code
            FROM browser_control_commands WHERE kind=? AND created_at>? ORDER BY created_at DESC,command_id DESC LIMIT 30""",
            (KIND,store.clock()-86400)).fetchall()
        output=[]; seen=set()
        has_projection=db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_verified_work_outbox'").fetchone()
        for row in rows:
            payload=json.loads(row['payload']); original_id=payload['original_command_id']
            if original_id in seen:
                continue
            seen.add(original_id)
            result=json.loads(row['result']) if row['result'] else {}
            cursor=json.loads(row['cursor']) if row['cursor'] else {}
            projection=db.execute('SELECT state,error_code FROM publication_verified_work_outbox WHERE original_command_id=?',
                (original_id,)).fetchone() if has_projection else None
            output.append({'account_key':payload['account_key'],'original_command_id':original_id,
                'command_id':row['command_id'],'state':row['state'],'phase':cursor.get('phase',''),
                'status':result.get('status',''),'post_id':result.get('post_id',''),'attempt':payload['attempt'],
                'projection_state':projection['state'] if projection else '',
                'projection_error':projection['error_code'] if projection else ''})
        return output


def settle(ctx, original, evidence, source):
    """One SQLite transaction binds new native proof and retains the old result."""
    from src.platform_adapter.publish_verification import video_id
    from .publication_reconciliation import _active_ai_source
    store = ctx.actor.store
    request = original['payload']['request']
    lock = json.loads(_read(source['submission_lock']))
    if lock != {'journal':source['journal']['path'],'status':'submission_started'}:
        _reject()
    rows = [json.loads(line) for line in _read(source['journal']).decode('utf8').splitlines() if line.strip()]
    if (evidence.get('verified') is not True or not evidence.get('post_id')
            or video_id(evidence.get('publish_url', '')) != evidence['post_id']
            or evidence.get('expected_title') != request['title'] or evidence.get('title_verified') is not True
            or evidence.get('expected_hashtags') != [v.strip().lstrip('#') for v in request.get('hashtags', []) if v.strip().lstrip('#')]
            or evidence.get('hashtags_verified') is not True or evidence.get('review_status') != 'clear'
            or (request.get('ai_generated', True) and not _active_ai_source(rows))):
        _reject('publication_evidence_incomplete')
    player = evidence.get('player') or {}
    if (player.get('ready') is not True or player.get('error') is not False or player.get('duration') is not True
            or (request.get('ai_generated', True) and evidence.get('ai_label_visible') is not True)
            or (request.get('fictional_story', True) and evidence.get('fiction_notice_visible') is not True)):
        _reject('publication_evidence_incomplete')
    result = {'status': 'published', 'success': True, 'post_id': evidence['post_id'],
        'publish_url': evidence['publish_url'], 'post_verified': True, 'publish_evidence': evidence,
        'original_unknown_snapshot': original, 'reconciliation_command_id': ctx.task_id,
        'source': source, 'submission_lock_retained': True,
        'comment_pending': bool(isinstance(original['payload'].get('authorization'), dict)
                                and original['payload']['authorization'].get('comment')),
        'comment': {'status': 'not_submitted_by_readonly_recovery'}}
    with store._db(write=True) as db:
        current = store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (original['command_id'],)).fetchone())
        task = store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (ctx.task_id,)).fetchone())
        store._owner(db, ctx.account_id, ctx.actor.owner_id, ctx.actor.generation, ctx.binding_version)
        if (current != original or not task or task['state'] != 'running' or task['kind'] != KIND
                or task['owner_id'] != ctx.actor.owner_id or task['generation'] != ctx.actor.generation
                or task['payload']['original_snapshot_sha256'] != _digest(original) or task['payload']['source'] != source):
            _reject()
        # Both records commit together. A crash cannot mark a verified original
        # while leaving a running verifier that would be re-entered on restart.
        db.execute("UPDATE browser_control_commands SET state='succeeded',result=?,error_code=NULL,updated_at=? WHERE command_id=?",
            (_json(result), store.clock(), original['command_id']))
        receipt = {'status': 'verified_published', 'post_id': evidence['post_id'], 'publish_url': evidence['publish_url'],
                   'original_command_id': original['command_id'], 'publish_evidence': evidence, 'comment_submitted': False}
        db.execute("UPDATE browser_control_commands SET state='succeeded',result=?,error_code=NULL,updated_at=? WHERE command_id=?",
            (_json(receipt), store.clock(), ctx.task_id))
        db.execute('''CREATE TABLE IF NOT EXISTS publication_verified_work_outbox(
            original_command_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, payload TEXT NOT NULL,
            state TEXT NOT NULL,error_code TEXT NOT NULL,updated_at REAL NOT NULL)''')
        projection = {'account_uuid':ctx.account_id, 'account_key':ctx.command['payload']['account_key'],
            'command_id':original['command_id'], 'post_id':evidence['post_id'], 'title':request['title'],
            'description':request.get('description','')}
        db.execute('INSERT INTO publication_verified_work_outbox VALUES(?,?,?,?,?,?)',
            (original['command_id'],ctx.account_id,_json(projection),'pending','',store.clock()))
        from .browser_execution_journal import finish
        finish(db, task, 'succeeded', None, store.clock())
    return receipt


def project_verified_works(store, account_id):
    """Durable local projection retry; never repeats any browser operation."""
    with store._db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_verified_work_outbox'").fetchone():
            return
        rows = [dict(r) for r in db.execute("""SELECT * FROM publication_verified_work_outbox
            WHERE account_id=? AND state='pending' AND (error_code='' OR updated_at<?) LIMIT 10""",
            (account_id,store.clock()-RETRY_SECONDS))]
    from src.services.video_service import bind_verified_publication
    for row in rows:
        original = store.get(row['original_command_id'])
        value = json.loads(row['payload'])
        result = (original.get('result') or {}) if original else {}
        if (not original or original['account_id'] != account_id or original['state'] != 'succeeded'
                or result.get('status') != 'published' or result.get('post_verified') is not True
                or result.get('post_id') != value['post_id'] or value['account_uuid'] != account_id
                or original['payload']['request']['title'] != value['title']):
            error = 'original_projection_evidence_changed'
        else:
            try:
                bind_verified_publication(**value)
                error = ''
            except Exception as exc:
                error = type(exc).__name__  # No private SQL/payload/exception text.
        with store._db(write=True) as db:
            db.execute("UPDATE publication_verified_work_outbox SET state=?,error_code=?,updated_at=? WHERE original_command_id=? AND payload=? AND state='pending'",
                ('pending' if error else 'completed',error,store.clock(),row['original_command_id'],row['payload']))


def run(ctx, session):
    from .publication_reconciliation import MANAGE
    from src.platform_adapter.publish_verification import video_id, wait_for_published_video
    original, rows = inputs(ctx.actor.store, ctx.command, ctx.resource.context)
    request = original['payload']['request']
    def progress(phase):
        ctx.actor.store.transition(ctx.task_id,ctx.actor.owner_id,ctx.actor.generation,'running',cursor={'phase':phase})
    progress('identity_check')
    ctx.check_dispatch()
    identity = ctx.resource.runtime.verify_identity(ctx.resource.context, session=session)
    if not identity.healthy:
        return BrowserCommandResult('failed', {'status': 'human_required', 'reason': 'original_identity_unverified'})
    progress('work_discovery')
    page = session.open_page(MANAGE)
    discovery = {}
    deadline=time.monotonic()+90
    for index in range(30):
        if time.monotonic()>=deadline:
            break
        ctx.check_dispatch()
        discovery = page.discover_published_work(request['title'])
        if discovery.get('verified') is True or discovery.get('reason') not in {
                'manage_loading', 'title_candidate_missing', 'canonical_id_missing', 'independent_card_unbound'}:
            break
        if index<29:
            page.wait_for_timeout(min(3000,max(1,int((deadline-time.monotonic())*1000))))
    if (discovery.get('reason') == 'observed_cover_human_required'
            or (discovery.get('diagnostic') or {}).get('native_popup_resolution', {}).get('human_required') is True):
        return BrowserCommandResult('failed', {'status': 'human_required', 'reason': 'platform_verification_required'})
    post_id = discovery.get('post_id')
    url = discovery.get('publish_url', '')
    if discovery.get('verified') is not True or not post_id or video_id(url) != post_id:
        return BrowserCommandResult('failed', {'status': 'verification_pending', 'reason': discovery.get('reason', 'work_not_found')})
    ctx.check_dispatch()
    progress('detail_verification')
    page.goto(url)
    tags = [v.strip().lstrip('#') for v in request.get('hashtags', []) if v.strip().lstrip('#')]
    evidence = wait_for_published_video(page, post_id, ai_required=request.get('ai_generated', True),
        fiction_required=request.get('fictional_story', True), required_hashtags=tags,
        expected_title=request['title'], dispatch_guard=ctx.check_dispatch)
    if evidence.get('human_required') is True:
        return BrowserCommandResult('failed', {'status': 'human_required', 'reason': 'platform_verification_required'})
    if evidence.get('verified') is not True:
        return BrowserCommandResult('failed', {'status': 'verification_pending', 'reason': evidence.get('reason', 'detail_unverified')})
    evidence.update(post_id=post_id, publish_url=url)
    # Finish browser IO before the atomic settlement changes the original fence.
    session.stop()
    ctx.check_dispatch()
    progress('saving_result')
    return settle(ctx, original, evidence, ctx.command['payload']['source'])
