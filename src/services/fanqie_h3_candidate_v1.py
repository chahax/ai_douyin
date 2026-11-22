"""Explicit P0 candidate registration and original-publication receipt bridge.

No constructor migration, browser launch, automatic approval or retry of an
uncertain dispatch. All extensions live beside the existing P0 business rows.
"""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid
from zoneinfo import ZoneInfo

from .publication_evidence import PublicationEvidenceReader


VERSION = 'fanqie_h3_candidate/v1'


class CandidateBlocked(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def publication_command_authorization(prepared):
    reference = prepared['authorization']
    if 'comment' in prepared:
        return {**reference, 'comment': prepared['comment']}
    return reference


def read_ref(ref, *, json_content=True):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
        raise CandidateBlocked('file_reference_required')
    path = Path(ref['path']).resolve()
    with path.open('rb') as f:
        sha = hashlib.file_digest(f, 'sha256').hexdigest()
    if sha != ref['sha256']:
        raise CandidateBlocked('artifact_changed')
    return json.loads(path.read_text(encoding='utf8')) if json_content else str(path)


def timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value,str):
        raise CandidateBlocked('explicit_task_validity_required')
    try:
        t=datetime.fromisoformat(value.replace('Z','+00:00'))
        if t.tzinfo is None:t=t.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        return t.timestamp()
    except ValueError as exc:
        raise CandidateBlocked('explicit_task_validity_required') from exc


def task_identity(row, snapshot=None):
    if snapshot is not None:
        from .fanqie_promotion_identity_v2 import authorization_subject
        return authorization_subject(snapshot, row)
    return {k:row[k] for k in ('book_id','platform_task_id','alias_id','alias','promotion_path','publish_type')}


def promotion_intent(snapshot,row,binding):
    result={'row':task_identity(row,snapshot),'binding':binding}
    if snapshot.get('schema')=='fanqie_promotion_snapshot/v2':
        from .fanqie_promotion_identity_v2 import selection_key
        result['selection_key']=selection_key(snapshot,row)
    return result


_ALIAS_INDEX = "CREATE UNIQUE INDEX uq_fanqie_task_active_alias ON fanqie_promotion_tasks(book_id, promotion_alias) WHERE promotion_alias IS NOT NULL AND status NOT IN ('rejected', 'expired', 'completed', 'stopped', 'cancelled')"
_SCOPED_ALIAS_INDEX = _ALIAS_INDEX + ' AND native_identity_scope IS NULL'


def _sql_normal(value):
    return ' '.join(value.strip().rstrip(';').split()).lower()


def _native_schema(db, *, allow_legacy=False):
    columns={r[1]:r for r in db.execute('PRAGMA table_info(fanqie_promotion_tasks)')}
    if columns.get('platform_task_id', [None,None,None,1])[3]:
        raise CandidateBlocked('native_platform_task_id_must_allow_null')
    index=db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_fanqie_task_active_alias'").fetchone()
    mapped=db.execute("SELECT 1 FROM sqlite_master WHERE name='fanqie_native_promotion_identities'").fetchone()
    if 'native_identity_scope' not in columns:
        if (mapped or not index or _sql_normal(index[0])!=_sql_normal(_ALIAS_INDEX)
                or not allow_legacy):
            raise CandidateBlocked('native_identity_explicit_migration_required')
        return False
    if (columns['native_identity_scope'][2].upper()!='TEXT' or columns['native_identity_scope'][3] or columns['native_identity_scope'][4] is not None
            or not index or _sql_normal(index[0])!=_sql_normal(_SCOPED_ALIAS_INDEX)):
        raise CandidateBlocked('native_identity_schema_incompatible')
    scope_index=db.execute("SELECT sql FROM sqlite_master WHERE name='uq_fanqie_task_native_scope'").fetchone()
    expected="CREATE UNIQUE INDEX uq_fanqie_task_native_scope ON fanqie_promotion_tasks(native_identity_scope) WHERE native_identity_scope IS NOT NULL"
    if not scope_index or _sql_normal(scope_index[0])!=_sql_normal(expected):
        raise CandidateBlocked('native_identity_scope_index_incompatible')
    if {r[1] for r in db.execute('PRAGMA table_info(fanqie_native_promotion_identities)')}!={'task_id','platform_identity_key','native_kind','native_record_id','native_identity_scope'}:
        raise CandidateBlocked('native_identity_mapping_incompatible')
    for column in db.execute('PRAGMA table_info(fanqie_native_promotion_identities)'):
        if column[2].upper()!=('INTEGER' if column[1]=='task_id' else 'TEXT') or column[3]!=1 or column[4] is not None:
            raise CandidateBlocked('native_identity_mapping_column_incompatible')
    unique=set()
    for r in db.execute('PRAGMA index_list(fanqie_native_promotion_identities)'):
        if r[2] and not r[4]:
            unique.add(tuple(v[2] for v in db.execute('PRAGMA index_info("'+r[1].replace('"','""')+'")')))
    if not {('task_id',),('native_identity_scope',),('platform_identity_key','native_kind','native_record_id')}<=unique:
        raise CandidateBlocked('native_identity_mapping_uniqueness_missing')
    if {(r[3],r[2],r[4]) for r in db.execute('PRAGMA foreign_key_list(fanqie_native_promotion_identities)')}!={('task_id','fanqie_promotion_tasks','id')}:
        raise CandidateBlocked('native_identity_mapping_fk_incompatible')
    return True


def _required(value, fields):
    if any(not isinstance(value.get(k), str) or not value[k].strip() for k in fields):
        raise CandidateBlocked('missing_required_identity')


def _base(db):
    required = {'fanqie_books': {'id', 'fanqie_book_id', 'book_uuid'},
        'fanqie_promotion_tasks': {'id', 'task_uuid', 'book_id', 'platform_task_id'},
        'fanqie_script_versions': {'id', 'script_uuid', 'task_id', 'content_hash'},
        'fanqie_video_jobs': {'id', 'job_uuid', 'task_id', 'script_id', 'output_sha256'},
        'fanqie_publish_records': {'id', 'publish_uuid', 'task_id', 'video_job_id', 'douyin_video_id'},
        'fanqie_douyin_accounts': {'id', 'account_uuid', 'account_key'},
        'fanqie_operation_events': {'event_uuid', 'task_id', 'event_type', 'payload_json'}}
    for table, fields in required.items():
        if not fields <= {r[1] for r in db.execute('PRAGMA table_info('+table+')')}:
            raise CandidateBlocked('existing_p0_schema_required:'+table)


def _extension(db):
    expected={'candidate_id','identity_key','media_sha','frozen_json','task_id','video_job_id','promotion_json',
              'review_json','prepared_json','dispatch_state','command_id','publish_id','created_at'}
    if {r[1] for r in db.execute('PRAGMA table_info(fanqie_h3_candidates)')}!=expected:
        raise CandidateBlocked('candidate_extension_schema_incompatible')
    uniques=set()
    for r in db.execute('PRAGMA index_list(fanqie_h3_candidates)'):
        if r[2] and not r[4]:
            name='"'+r[1].replace('"','""')+'"'
            uniques.add(tuple(x[2] for x in db.execute('PRAGMA index_info('+name+')')))
    if not {('candidate_id',),('identity_key',),('media_sha',),('command_id',)}<=uniques:
        raise CandidateBlocked('candidate_unique_constraints_missing')
    foreign={(r[3],r[2],r[4]) for r in db.execute('PRAGMA foreign_key_list(fanqie_h3_candidates)')}
    if foreign!={('task_id','fanqie_promotion_tasks','id'),('video_job_id','fanqie_video_jobs','id'),
                 ('publish_id','fanqie_publish_records','id')}:
        raise CandidateBlocked('candidate_foreign_keys_incompatible')


def migrate(path, backup_path):
    path, backup = Path(path).resolve(), Path(backup_path).resolve()
    if not path.is_file() or backup.exists() or path == backup:
        raise CandidateBlocked('existing_database_and_new_backup_required')
    backup.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path.as_uri()+'?mode=rw', uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON')
        _base(db)
        native_installed=_native_schema(db,allow_legacy=True)
        with backup.open('xb'):
            pass
        with sqlite3.connect(backup) as target:
            db.backup(target)
        db.execute('BEGIN IMMEDIATE')
        if _native_schema(db,allow_legacy=True)!=native_installed:
            raise CandidateBlocked('native_schema_changed_during_backup')
        if not native_installed:
            db.execute('ALTER TABLE fanqie_promotion_tasks ADD COLUMN native_identity_scope TEXT')
            db.execute('DROP INDEX uq_fanqie_task_active_alias')
            db.execute(_SCOPED_ALIAS_INDEX)
            db.execute('CREATE UNIQUE INDEX uq_fanqie_task_native_scope ON fanqie_promotion_tasks(native_identity_scope) WHERE native_identity_scope IS NOT NULL')
            db.execute('''CREATE TABLE fanqie_native_promotion_identities (
                task_id INTEGER NOT NULL UNIQUE REFERENCES fanqie_promotion_tasks(id),
                platform_identity_key TEXT NOT NULL, native_kind TEXT NOT NULL,
                native_record_id TEXT NOT NULL, native_identity_scope TEXT NOT NULL UNIQUE,
                UNIQUE(platform_identity_key,native_kind,native_record_id))''')
        _native_schema(db)
        db.execute('''CREATE TABLE IF NOT EXISTS fanqie_h3_candidates (
            candidate_id TEXT PRIMARY KEY, identity_key TEXT UNIQUE NOT NULL,
            media_sha TEXT UNIQUE NOT NULL, frozen_json TEXT NOT NULL,
            task_id INTEGER REFERENCES fanqie_promotion_tasks(id),
            video_job_id INTEGER REFERENCES fanqie_video_jobs(id),
            promotion_json TEXT, review_json TEXT, prepared_json TEXT,
            dispatch_state TEXT NOT NULL DEFAULT 'not_started', command_id TEXT UNIQUE,
            publish_id INTEGER REFERENCES fanqie_publish_records(id), created_at REAL NOT NULL)''')
        _extension(db)
    CandidateLedger(path)
    return {'version': VERSION, 'backup': str(backup)}


def _validate_pending_v1(handoff_ref, *, provenance_ref, technical_review_ref, account_binding):
    h, p, qa = map(read_ref, (handoff_ref, provenance_ref, technical_review_ref))
    _required(account_binding, ('account_uuid', 'account_key', 'binding_version'))
    if (h.get('schema') != 'novel_promotion_local_candidate/v1'
        or h.get('account_key') != account_binding['account_key']
        or p.get('schema') != 'fanqie_candidate_provenance/v1'
        or p.get('book_id') != h.get('book_id') or p.get('media') != h.get('media_binding')):
        raise CandidateBlocked('candidate_provenance_mismatch')
    read_ref(h['media_binding'], json_content=False)
    for key in ('source_manifest', 'source_generation_manifest', 'technical_proof_binding', 'assembly_receipt_binding'):
        read_ref(h[key])
    if p.get('book_manifest')!=h['source_manifest'] or p.get('assembly_result')!=h['assembly_receipt_binding']:
        raise CandidateBlocked('provenance_source_chain_mismatch')
    manifest=read_ref(p['book_manifest'])
    if str(manifest.get('book_id'))!=h['book_id']:raise CandidateBlocked('source_book_mismatch')
    selections=p.get('script_selections') or ([p['script_selection']] if p.get('script_selection') else [])
    if not selections:raise CandidateBlocked('script_selections_required')
    for ref in selections:read_ref(ref)
    if not p.get('source_cases'):raise CandidateBlocked('source_cases_required')
    generation=read_ref(h['source_generation_manifest'])
    expected_cases=[segment['source_case'] for segment in generation.get('segments',[]) if segment.get('source_case')]
    if not expected_cases or {canonical(r) for r in expected_cases}!={canonical(r) for r in p['source_cases']}:
        raise CandidateBlocked('source_cases_generation_mismatch')
    used_selections=set()
    for case_ref in p['source_cases']:
        case=read_ref(case_ref)
        if not case.get('shots') or any(shot.get('authoritative_script')!=p['script'] for shot in case['shots']):
            raise CandidateBlocked('script_not_bound_in_source_case')
        used_selections.update(canonical(shot.get('script_selection')) for shot in case['shots'])
    if used_selections!={canonical(ref) for ref in selections}:
        raise CandidateBlocked('script_selections_case_mismatch')
    read_ref(p['script'], json_content=False)
    if not p.get('source_code'):
        raise CandidateBlocked('source_code_provenance_required')
    for ref in p['source_code']:
        read_ref(ref, json_content=False)
    if (qa.get('status') != 'technical_cache_review_passed' or qa.get('file') != h['media_binding']
        or qa.get('result') != h['assembly_receipt_binding'] or qa.get('proof') != h['technical_proof_binding']
        or any(qa.get(k) is not True for k in ('all_frame_pixels_and_PTS_cache_revalidated',
            'audio_PCM_and_AAC_metrics_cache_revalidated', 'original_sources_SHA_revalidated'))):
        raise CandidateBlocked('same_media_technical_review_required')
    result = read_ref(h['assembly_receipt_binding'])
    if result.get('file') != h['media_binding'] or result.get('proof') != h['technical_proof_binding']:
        raise CandidateBlocked('assembly_subject_mismatch')
    plan=read_ref(result['plan'])
    if {canonical(r) for r in plan.get('code',[])}!={canonical(r) for r in p['source_code']}:
        raise CandidateBlocked('assembly_source_code_mismatch')
    frozen = dict(handoff=handoff_ref, provenance=provenance_ref, technical_review=technical_review_ref,
                  account=account_binding, book_id=h['book_id'], book_name=h['book_name'], media=h['media_binding'])
    return frozen


class CandidateLedger:
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = Path(path).resolve(), clock
        with self._db() as db:
            _base(db)
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='fanqie_h3_candidates'").fetchone():
                raise CandidateBlocked('explicit_migration_required')
            _extension(db)
            _native_schema(db,allow_legacy=True)

    @contextmanager
    def _db(self, write=False):
        db = sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True, timeout=3)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _event(self, db, cid, task_id, kind, payload):
        db.execute('''INSERT INTO fanqie_operation_events
            (event_uuid,task_id,event_type,actor_type,actor_id,payload_json,created_at,audit_artifact_hash)
            VALUES(?,?,?,?,?,?,?,?)''', (uuid.uuid4().hex, task_id, kind, 'service', VERSION,
                canonical({'candidate_id': cid, **payload}), datetime.now(timezone.utc).isoformat(), digest(payload)))

    def get(self, candidate_id):
        with self._db() as db:
            r = db.execute('SELECT * FROM fanqie_h3_candidates WHERE candidate_id=?', (candidate_id,)).fetchone()
            if not r:
                raise CandidateBlocked('candidate_missing')
            return dict(r)

    def list_candidates(self):
        with self._db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM fanqie_h3_candidates ORDER BY created_at')]

    def ensure_runtime_account(self, account_binding, *, runtime_db):
        """Explicitly register the exact existing runtime identity, never create one."""
        a=account_binding
        _required(a,('account_uuid','account_key','binding_version'))
        with sqlite3.connect(Path(runtime_db).resolve().as_uri()+'?mode=ro',uri=True) as source:
            source.row_factory=sqlite3.Row
            rows=source.execute('''SELECT b.*,v.profile_version FROM account_runtime_bindings b
                JOIN account_strategy_versions v ON v.account_uuid=b.account_uuid AND v.is_active=1
                JOIN douyin_accounts a ON a.account_uuid=b.account_uuid AND a.status='active'
                WHERE b.account_uuid=? AND b.account_key=? AND b.status='active' AND b.platform='douyin' ''',
                (a['account_uuid'],a['account_key'])).fetchall()
        if len(rows)!=1:raise CandidateBlocked('runtime_account_not_unique_active')
        r=dict(rows[0]);fields=('account_uuid','account_key','platform_identity_key','browser_environment_key',
            'browser_profile_dir','storage_state_path','confirmed_by','created_at','profile_version')
        version=hashlib.sha256(json.dumps({k:r[k] for k in fields},sort_keys=True).encode()).hexdigest()
        if version!=a['binding_version']:raise CandidateBlocked('runtime_binding_version_changed')
        with self._db(True) as db:
            old=db.execute('SELECT * FROM fanqie_douyin_accounts WHERE account_uuid=? OR account_key=?',
                (a['account_uuid'],a['account_key'])).fetchall()
            if old:
                if len(old)!=1 or old[0]['account_uuid']!=a['account_uuid'] or old[0]['account_key']!=a['account_key']:
                    raise CandidateBlocked('p0_account_conflict')
                return old[0]['id']
            return db.execute('''INSERT INTO fanqie_douyin_accounts
                (account_uuid,account_key,status,profile_dir,platform_uid,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)''',(a['account_uuid'],a['account_key'],'active',r['browser_profile_dir'],
                r.get('public_uid') or None,datetime.now(timezone.utc).isoformat(),datetime.now(timezone.utc).isoformat())).lastrowid

    def register_pending(self, handoff_ref, *, provenance_ref, technical_review_ref, account_binding):
        handoff = read_ref(handoff_ref)
        if handoff.get('schema') == 'novel_promotion_local_candidate/v2':
            from .fanqie_composite_candidate_v2 import validate_candidate
            frozen = validate_candidate(handoff_ref, provenance_ref=provenance_ref,
                technical_review_ref=technical_review_ref, account_binding=account_binding)
        else:
            frozen = _validate_pending_v1(handoff_ref, provenance_ref=provenance_ref,
                technical_review_ref=technical_review_ref, account_binding=account_binding)
        return self._persist_pending(frozen)

    def _persist_pending(self, frozen):
        key = digest(frozen)
        with self._db(True) as db:
            old = db.execute('SELECT * FROM fanqie_h3_candidates WHERE media_sha=?', (frozen['media']['sha256'],)).fetchone()
            if old:
                if old['identity_key'] != key:
                    raise CandidateBlocked('media_already_registered_with_other_subject')
                return old['candidate_id']
            cid = uuid.uuid4().hex
            db.execute('INSERT INTO fanqie_h3_candidates(candidate_id,identity_key,media_sha,frozen_json,created_at) VALUES(?,?,?,?,?)',
                       (cid, key, frozen['media']['sha256'], canonical(frozen), self.clock()))
            self._event(db, cid, None, 'h3_candidate_pending', {'identity_key': key})
            return cid

    def _fresh_promotion(self, snapshot, row, binding, frozen):
        from .fanqie_promotion_identity_v2 import validate_snapshot, assert_publishable
        from src.operations_accounts.browser_control import BrowserControlRejected
        try:validate_snapshot(snapshot)
        except BrowserControlRejected as exc:raise CandidateBlocked(exc.code) from exc
        if row not in snapshot['rows'] or row.get('status') != 'ready' or row.get('pending_fields'):
            raise CandidateBlocked('verified_complete_task_required')
        if not 0 <= self.clock()-snapshot['observed_at'] <= 60:
            raise CandidateBlocked('promotion_snapshot_stale')
        native=snapshot.get('schema')=='fanqie_promotion_snapshot/v2'
        if native:
            assert_publishable(snapshot,row,now=self.clock())
            _required(row,('book_id','alias','publish_type','native_kind','native_record_id'))
            if row.get('book_name')!=frozen['book_name']:
                raise CandidateBlocked('native_book_name_mismatch')
        else:
            _required(row, ('book_id', 'platform_task_id', 'alias_id', 'alias', 'promotion_path', 'publish_type'))
        _required(binding, ('resource_id', 'binding_version', 'platform_identity_key', 'environment_key',
                            'douyin_account_uuid', 'account_link_version'))
        if (row['book_id'] != frozen['book_id'] or row['publish_type'] != 'AIGC'
            or binding['douyin_account_uuid'] != frozen['account']['account_uuid']
            or any(snapshot.get(k) != binding[k] for k in ('resource_id', 'binding_version', 'platform_identity_key', 'environment_key'))
            or snapshot.get('identity_verified') is not True or snapshot.get('challenge') is not False
            or snapshot.get('table_ready') is not True or snapshot.get('pagination_complete') is not True):
            raise CandidateBlocked('promotion_identity_or_book_mismatch')
        if row.get('alias_status') not in {'active','正常','有效','推广中','生效中','可推广','可用'} or row.get('book_status') not in {'active','正常','有效','推广中','生效中','可推广','可用'}:
            raise CandidateBlocked('task_not_active')
        if not timestamp(row['valid_from']) <= self.clock() < timestamp(row['valid_until']):
            raise CandidateBlocked('task_outside_validity')
        if native:
            return dict(snapshot=snapshot,row=row,binding=binding)
        evidence=read_ref(snapshot['evidence_ref'])
        from src.operations_accounts.fanqie_managed_promotion_v1 import normalise_snapshot
        subject={k:snapshot[k] for k in ('resource_id','binding_version','platform_identity_key','environment_key','observed_at','identity_verified','challenge')}
        if evidence.get('schema')!='fanqie_promotion_DOM_evidence/v1' or evidence.get('subject')!=subject:
            raise CandidateBlocked('promotion_evidence_subject_mismatch')
        rebuilt=normalise_snapshot(evidence['raw'],**subject,evidence_ref=snapshot['evidence_ref'],
            normalizer_version=snapshot.get('normalizer_version','legacy_v1'))
        if rebuilt!=snapshot:raise CandidateBlocked('promotion_evidence_rows_mismatch')
        return dict(snapshot=snapshot, row=row, binding=binding)

    def bind_promotion(self, candidate_id, snapshot, row, resource_binding):
        current = self.get(candidate_id); frozen = json.loads(current['frozen_json'])
        promotion = self._fresh_promotion(snapshot, row, resource_binding, frozen)
        with self._db(True) as db:
            current = dict(db.execute('SELECT * FROM fanqie_h3_candidates WHERE candidate_id=?', (candidate_id,)).fetchone())
            if current['promotion_json']:
                old = json.loads(current['promotion_json'])
                if task_identity(old['row'],old['snapshot']) != task_identity(row,snapshot) or old['binding'] != resource_binding:
                    raise CandidateBlocked('candidate_task_binding_immutable')
                if snapshot.get('schema')=='fanqie_promotion_snapshot/v2':
                    self.verify_native_task(current['task_id'],snapshot=snapshot,row=row)
                return dict(task_id=current['task_id'], video_job_id=current['video_job_id'])
            book = db.execute('SELECT id FROM fanqie_books WHERE fanqie_book_id=?', (frozen['book_id'],)).fetchone()
            if snapshot.get('schema')=='fanqie_promotion_snapshot/v2' and book:
                if db.execute('SELECT book_name FROM fanqie_books WHERE id=?',(book[0],)).fetchone()[0]!=row['book_name']:
                    raise CandidateBlocked('native_existing_book_name_mismatch')
            bid = book[0] if book else db.execute('INSERT INTO fanqie_books(book_uuid,fanqie_book_id,book_name) VALUES(?,?,?)',
                (uuid.uuid4().hex, frozen['book_id'], frozen['book_name'])).lastrowid
            native=snapshot.get('schema')=='fanqie_promotion_snapshot/v2'
            identity=scope=None
            if native:
                from .fanqie_promotion_identity_v2 import native_identity,native_identity_scope
                _native_schema(db)
                identity=native_identity(snapshot,row);scope=native_identity_scope(snapshot,row)
                existing=db.execute('SELECT t.* FROM fanqie_promotion_tasks t JOIN fanqie_native_promotion_identities n ON n.task_id=t.id WHERE n.native_identity_scope=?',(scope,)).fetchall()
            else:
                existing = db.execute('SELECT * FROM fanqie_promotion_tasks WHERE platform_task_id=?', (row['platform_task_id'],)).fetchall()
            if existing:
                if len(existing)!=1:raise CandidateBlocked('ambiguous_existing_task')
                previous=db.execute('SELECT promotion_json FROM fanqie_h3_candidates WHERE task_id=? AND promotion_json IS NOT NULL LIMIT 1',(existing[0]['id'],)).fetchone()
                if not previous:raise CandidateBlocked('existing_task_requires_explicit_reconciliation')
                previous=json.loads(previous[0])
                if (existing[0]['book_id']!=bid or existing[0]['promotion_alias']!=row['alias']
                    or existing[0]['publish_type']!=row['publish_type']
                    or task_identity(previous['row'],previous['snapshot'])!=task_identity(row,snapshot) or previous['binding']!=resource_binding):
                    raise CandidateBlocked('existing_task_binding_conflict')
                tid=existing[0]['id']
                if native:self.verify_native_task(tid,snapshot=snapshot,row=row)
            else:
                columns='task_uuid,book_id,platform_task_id,promotion_alias,publish_type,status,valid_from,valid_until,application_snapshot_path'
                values=(uuid.uuid4().hex,bid,None if native else row['platform_task_id'],row['alias'],row['publish_type'],'verified',row['valid_from'],row['valid_until'],snapshot['evidence_ref']['path'])
                if native:
                    columns+=',native_identity_scope';values+= (scope,)
                tid=db.execute('INSERT INTO fanqie_promotion_tasks('+columns+') VALUES('+','.join('?' for _ in values)+')',values).lastrowid
                if native:
                    db.execute('INSERT INTO fanqie_native_promotion_identities(task_id,platform_identity_key,native_kind,native_record_id,native_identity_scope) VALUES(?,?,?,?,?)',
                        (tid,identity['platform_identity_key'],identity['native_kind'],identity['native_record_id'],scope))
            p = read_ref(frozen['provenance']); script = read_ref(p['script'], json_content=False)
            original_script=db.execute('SELECT id FROM fanqie_script_versions WHERE task_id=? AND content_hash=?',
                (tid,p['script']['sha256'])).fetchone()
            if original_script:sid=original_script[0]
            else:
                version=db.execute('SELECT coalesce(max(version),0)+1 FROM fanqie_script_versions WHERE task_id=?',(tid,)).fetchone()[0]
                sid = db.execute('''INSERT INTO fanqie_script_versions(script_uuid,task_id,version,script_text,status,content_hash)
                    VALUES(?,?,?,?,?,?)''', (uuid.uuid4().hex,tid,version,Path(script).read_text(encoding='utf8'),'source_frozen',p['script']['sha256'])).lastrowid
            jid = db.execute('''INSERT INTO fanqie_video_jobs(job_uuid,task_id,script_id,video_mode,status,output_path,output_sha256,
                quality_report_path,manifest_path) VALUES(?,?,?,?,?,?,?,?,?)''', (uuid.uuid4().hex,tid,sid,'local_h3','pending_review',
                frozen['media']['path'],frozen['media']['sha256'],frozen['technical_review']['path'],frozen['handoff']['path'])).lastrowid
            db.execute('UPDATE fanqie_h3_candidates SET task_id=?,video_job_id=?,promotion_json=? WHERE candidate_id=?',
                       (tid,jid,canonical(promotion),candidate_id))
            self._event(db,candidate_id,tid,'h3_task_bound',{'video_job_id':jid,'promotion_sha256':digest(promotion)})
            return dict(task_id=tid,video_job_id=jid)

    def verify_native_task(self, task_id, *, snapshot, row):
        """Read-only exact native mapping check, shared by the backfill bridge."""
        from .fanqie_promotion_identity_v2 import validate_snapshot,native_identity,native_identity_scope,authorization_subject
        validate_snapshot(snapshot)
        identity=native_identity(snapshot,row);scope=native_identity_scope(snapshot,row)
        with self._db() as db:
            _native_schema(db)
            found=db.execute('''SELECT n.*,t.platform_task_id,t.native_identity_scope AS task_scope,
                t.promotion_alias,t.publish_type,b.fanqie_book_id,b.book_name
                FROM fanqie_native_promotion_identities n JOIN fanqie_promotion_tasks t ON t.id=n.task_id
                JOIN fanqie_books b ON b.id=t.book_id WHERE n.task_id=?''',(task_id,)).fetchone()
            if (not found or any(found[k]!=v for k,v in identity.items())
                    or found['native_identity_scope']!=scope or found['task_scope']!=scope
                    or found['platform_task_id'] is not None or found['fanqie_book_id']!=row['book_id']
                    or found['book_name']!=row['book_name'] or found['promotion_alias']!=row['alias']
                    or found['publish_type']!=row['publish_type']):
                raise CandidateBlocked('native_task_mapping_mismatch')
        return dict(task_id=task_id,native_identity=identity,native_identity_scope=scope,
                    promotion_subject=authorization_subject(snapshot,row))

    def record_user_review(self, candidate_id, review_ref):
        row = self.get(candidate_id); f = json.loads(row['frozen_json']); review = read_ref(review_ref)
        if (review.get('schema') != 'fanqie_candidate_user_review/v1' or review.get('media') != f['media']
            or review.get('decision_source') != 'explicit_user_statement' or not review.get('user_statement')
            or review.get('accepted_for_publication') is not True
            or review.get('known_findings') != read_ref(f['handoff']).get('known_visual_finding')):
            raise CandidateBlocked('explicit_same_media_review_required')
        with self._db(True) as db:
            old = db.execute('SELECT review_json,prepared_json FROM fanqie_h3_candidates WHERE candidate_id=?',(candidate_id,)).fetchone()
            if old['review_json']==canonical(review_ref):return
            if old['prepared_json'] or (old['review_json'] and old['review_json'] != canonical(review_ref)):
                raise CandidateBlocked('review_already_frozen')
            db.execute('UPDATE fanqie_h3_candidates SET review_json=? WHERE candidate_id=?',(canonical(review_ref),candidate_id))
            self._event(db,candidate_id,row['task_id'],'h3_user_review',{'reference':review_ref,'agent_quality_upgraded':False})

    def prepare_publish(self, candidate_id, *, snapshot, row, resource_binding, metadata, authorization_ref):
        c = self.get(candidate_id); f = json.loads(c['frozen_json'])
        if not c['task_id'] or not c['review_json']:
            raise CandidateBlocked('promotion_and_user_review_required')
        with self._db() as db:
            account=db.execute('SELECT account_uuid,account_key FROM fanqie_douyin_accounts WHERE account_uuid=? OR account_key=?',
                (f['account']['account_uuid'],f['account']['account_key'])).fetchall()
            if len(account)!=1 or dict(account[0])!={k:f['account'][k] for k in ('account_uuid','account_key')}:
                raise CandidateBlocked('p0_account_binding_required_before_publish')
        live = self._fresh_promotion(snapshot,row,resource_binding,f); old = json.loads(c['promotion_json'])
        if snapshot.get('schema')=='fanqie_promotion_snapshot/v2':
            self.verify_native_task(c['task_id'],snapshot=snapshot,row=row)
        if task_identity(old['row'],old['snapshot']) != task_identity(row,snapshot) or old['binding'] != resource_binding:
            raise CandidateBlocked('promotion_changed')
        read_ref(json.loads(c['review_json'])); read_ref(f['media'],json_content=False)
        auth = read_ref(authorization_ref)
        if (auth.get('candidate_id') != candidate_id or auth.get('media') != f['media']
            or auth.get('account_uuid') != f['account']['account_uuid'] or auth.get('publish_authorized') is not True
            or auth.get('decision_source') != 'explicit_user_statement' or not auth.get('user_statement')):
            raise CandidateBlocked('explicit_publication_authorization_required')
        _required(metadata, ('title','description'))
        if metadata.get('ai_generated') is not True or metadata.get('fictional_story') is not True:
            raise CandidateBlocked('ai_and_fiction_declaration_required')
        tags=metadata.get('hashtags')
        if not isinstance(tags,list) or not tags or any(not isinstance(t,str) or not t.strip().lstrip('#') for t in tags):
            raise CandidateBlocked('publication_tags_required')
        from src.platform_adapter.models import PublishRequest
        request=PublishRequest(video_path=f['media']['path'],title=metadata['title'],description=metadata['description'],
            hashtags=tags,ai_generated=True,fictional_story=True,extra_metadata={'account_uuid':f['account']['account_uuid']})
        if (auth.get('metadata_sha256')!=digest(asdict(request))
            or auth.get('promotion_subject_sha256')!=digest({'row':task_identity(row,snapshot),'binding':resource_binding})):
            raise CandidateBlocked('authorization_metadata_or_promotion_mismatch')
        if snapshot.get('schema')=='fanqie_promotion_snapshot/v2' and auth.get('schema')!='fanqie_publication_authorization/v2':
            raise CandidateBlocked('native_publication_authorization_version_required')
        prepared=dict(request=asdict(request),authorization=authorization_ref,promotion=promotion_intent(snapshot,row,resource_binding),review=json.loads(c['review_json']))
        if 'comment' in metadata or 'comment' in auth:
            comment = metadata.get('comment')
            if not isinstance(comment, str) or not comment.strip() or auth.get('comment') != comment:
                raise CandidateBlocked('authorization_comment_mismatch')
            prepared['comment'] = comment
        with self._db(True) as db:
            old=db.execute('SELECT prepared_json FROM fanqie_h3_candidates WHERE candidate_id=?',(candidate_id,)).fetchone()[0]
            if old and old!=canonical(prepared):raise CandidateBlocked('prepared_publication_immutable')
            db.execute('UPDATE fanqie_h3_candidates SET prepared_json=? WHERE candidate_id=?',(canonical(prepared),candidate_id))
            self._event(db,candidate_id,c['task_id'],'h3_publish_prepared',{'prepared_sha256':digest(prepared)})
        return prepared

    def dispatch(self, candidate_id, *, snapshot, row, resource_binding, runtime_db=None, queue=None):
        c=self.get(candidate_id); f=json.loads(c['frozen_json'])
        if not c['prepared_json']:raise CandidateBlocked('publication_not_prepared')
        if queue is None and runtime_db is None:raise CandidateBlocked('runtime_binding_recheck_required')
        if runtime_db is not None:self.ensure_runtime_account(f['account'],runtime_db=runtime_db)
        p=json.loads(c['prepared_json'])
        self._fresh_promotion(snapshot,row,resource_binding,f)
        if p['promotion']!=promotion_intent(snapshot,row,resource_binding):raise CandidateBlocked('promotion_changed')
        authority = read_ref(p['authorization'])
        if 'comment' in p and authority.get('comment') != p['comment']:
            raise CandidateBlocked('authorization_comment_mismatch')
        read_ref(p['review']);read_ref(f['media'],json_content=False)
        with self._db(True) as db:
            c=dict(db.execute('SELECT * FROM fanqie_h3_candidates WHERE candidate_id=?',(candidate_id,)).fetchone())
            if c['command_id']:return c['command_id']
            if c['dispatch_state']!='not_started':raise CandidateBlocked('dispatch_unknown_no_replay')
            db.execute("UPDATE fanqie_h3_candidates SET dispatch_state='dispatch_started' WHERE candidate_id=?",(candidate_id,))
        # Durable intent precedes external dispatch; a crash keeps unknown, never blind retries.
        if queue is None:
            from src.operations_accounts.browser_control_runtime import queue_publish_request
            queue=queue_publish_request
        from src.platform_adapter.models import PublishRequest
        command=queue(f['account']['account_key'],PublishRequest(**p['request']),authorization=publication_command_authorization(p))
        if not isinstance(command.get('command_id'),str):raise CandidateBlocked('dispatch_receipt_missing')
        with self._db(True) as db:
            db.execute("UPDATE fanqie_h3_candidates SET command_id=?,dispatch_state='queued' WHERE candidate_id=?",(command['command_id'],candidate_id))
            self._event(db,candidate_id,c['task_id'],'h3_publish_queued',{'command_id':command['command_id']})
        return command['command_id']

    def attach_publication(self, candidate_id, *, command_id, browser_db, evidence_directory, metadata_command_id=None, evidence_root=None):
        c=self.get(candidate_id); f=json.loads(c['frozen_json']); a=f['account']
        if not c['prepared_json'] or c['command_id'] not in (None,command_id):raise CandidateBlocked('original_command_mismatch')
        read_ref(f['media'],json_content=False)
        reader=PublicationEvidenceReader(browser_db,evidence_root=evidence_root)
        receipt=reader.read(command_id,a['account_uuid'],a['binding_version'])
        with sqlite3.connect(Path(browser_db).resolve().as_uri()+'?mode=ro',uri=True) as db:
            original=db.execute('SELECT payload,result FROM browser_control_commands WHERE command_id=?',(command_id,)).fetchone()
            raw=original[0];result=json.loads(original[1])
        payload=json.loads(raw); prepared=json.loads(c['prepared_json'])
        if payload.get('video_sha256')!=f['media']['sha256'] or payload.get('request')!=prepared['request'] or payload.get('authorization')!=publication_command_authorization(prepared):
            raise CandidateBlocked('publication_media_or_metadata_mismatch')
        from .publication_time_evidence_v1 import read_publication_time
        try:
            time_evidence=read_publication_time(browser_db,command_id,a['account_uuid'],a['binding_version'],
                metadata_command_id=metadata_command_id,evidence_root=evidence_root)
        except ValueError as exc:raise CandidateBlocked(str(exc)) from exc
        published_at=time_evidence['published_at']
        promotion=json.loads(c['promotion_json'])
        native=promotion['snapshot'].get('schema')=='fanqie_promotion_snapshot/v2'
        native_facts={}
        if native:
            native_facts=self.verify_native_task(c['task_id'],snapshot=promotion['snapshot'],row=promotion['row'])
            native_facts.pop('task_id')
            if prepared['promotion']['row']!=native_facts['promotion_subject']:
                raise CandidateBlocked('publication_native_subject_mismatch')
        evidence=dict(schema='fanqie_h3_publication_evidence/v1',book_id=f['book_id'],media=f['media'],
            command_id=command_id,account_uuid=a['account_uuid'],account_key=a['account_key'],binding_version=a['binding_version'],
            published_at=published_at,time_evidence=time_evidence,request_sha256=digest(payload),**receipt)
        if native:evidence.update(schema='fanqie_h3_publication_evidence/v2',**native_facts)
        folder=Path(evidence_directory).resolve();folder.mkdir(parents=True,exist_ok=True)
        target=folder/(candidate_id+'_'+command_id+'_PUBLICATION.json');raw_e=canonical(evidence).encode()
        if target.exists() and target.read_bytes()!=raw_e:raise CandidateBlocked('publication_evidence_conflict')
        if not target.exists():
            with target.open('xb') as handle:handle.write(raw_e)
        evidence_ref={'path':str(target),'sha256':hashlib.sha256(raw_e).hexdigest()}
        handoff=dict(schema='fanqie_h3_publication_handoff/v1',candidate_id=candidate_id,book_id=f['book_id'],media=f['media'],
            command_id=command_id,account_uuid=a['account_uuid'],account_key=a['account_key'],binding_version=a['binding_version'],
            published_at=published_at,time_evidence=time_evidence,publication_evidence=evidence_ref)
        if native:handoff.update(schema='fanqie_h3_publication_handoff/v2',**native_facts)
        with self._db(True) as db:
            old=db.execute('SELECT publish_id,command_id FROM fanqie_h3_candidates WHERE candidate_id=?',(candidate_id,)).fetchone()
            if old['publish_id']:
                if old['command_id']!=command_id:raise CandidateBlocked('different_post_already_attached')
                return {'task_id':c['task_id'],'video_job_id':c['video_job_id'],'publish_id':old['publish_id'],**receipt,**handoff}
            account=db.execute('SELECT id,account_key FROM fanqie_douyin_accounts WHERE account_uuid=?',(a['account_uuid'],)).fetchone()
            if not account or account['account_key']!=a['account_key']:raise CandidateBlocked('p0_account_binding_required')
            if db.execute('SELECT 1 FROM fanqie_publish_records WHERE douyin_video_id=?',(receipt['post_id'],)).fetchone():
                raise CandidateBlocked('post_already_bound')
            req=prepared['request']
            pid=db.execute('''INSERT INTO fanqie_publish_records(publish_uuid,task_id,video_job_id,douyin_account_id,status,
                title_snapshot,description_snapshot,hashtags_json,douyin_video_id,douyin_video_url,published_at,platform_response_path) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                (uuid.uuid4().hex,c['task_id'],c['video_job_id'],account['id'],'published',req['title'],req['description'],canonical(req['hashtags']),receipt['post_id'],receipt['publish_url'],published_at,str(target))).lastrowid
            db.execute("UPDATE fanqie_h3_candidates SET publish_id=?,command_id=?,dispatch_state='published' WHERE candidate_id=?",(pid,command_id,candidate_id))
            self._event(db,candidate_id,c['task_id'],'h3_publish_verified',receipt)
            return {'task_id':c['task_id'],'video_job_id':c['video_job_id'],'publish_id':pid,**receipt,**handoff}

    def recover_dispatch_receipt(self, candidate_id, *, browser_db):
        c=self.get(candidate_id); f=json.loads(c['frozen_json'])
        if not c['prepared_json'] or c['dispatch_state']=='not_started':
            raise CandidateBlocked('dispatch_not_started')
        p=json.loads(c['prepared_json'])
        with sqlite3.connect(Path(browser_db).resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            rows=db.execute('''SELECT command_id,account_id,binding_version,kind,state,payload FROM browser_control_commands
                WHERE account_id=? AND idempotency_key=?''',(f['account']['account_uuid'],'publish:'+f['media']['sha256'])).fetchall()
        if not rows:return {'status':'outcome_unknown','command_id':None}
        if len(rows)!=1:raise CandidateBlocked('ambiguous_original_dispatch')
        r=dict(rows[0]);payload=json.loads(r['payload'])
        if (r['kind']!='publish' or r['binding_version']!=f['account']['binding_version']
            or payload.get('video_sha256')!=f['media']['sha256'] or payload.get('request')!=p['request']
            or payload.get('authorization')!=publication_command_authorization(p)):raise CandidateBlocked('original_dispatch_mismatch')
        with self._db(True) as db:
            current=db.execute('SELECT command_id FROM fanqie_h3_candidates WHERE candidate_id=?',(candidate_id,)).fetchone()[0]
            if current and current!=r['command_id']:raise CandidateBlocked('different_command_already_bound')
            db.execute('UPDATE fanqie_h3_candidates SET command_id=?,dispatch_state=? WHERE candidate_id=?',
                (r['command_id'],r['state'],candidate_id))
            self._event(db,candidate_id,c['task_id'],'h3_dispatch_recovered',{'command_id':r['command_id'],'state':r['state']})
        return {'command_id':r['command_id'],'status':r['state']}

    def request_publication_metadata(self, candidate_id, *, browser_db, queue=None):
        """Queue only existing managed sync_videos, bound to the original post."""
        c=self.get(candidate_id);f=json.loads(c['frozen_json']);a=f['account']
        if not c['command_id']:raise CandidateBlocked('original_publication_command_required')
        receipt=PublicationEvidenceReader(browser_db).read(c['command_id'],a['account_uuid'],a['binding_version'])
        base='h3-publication-metadata:'+c['command_id']+':'+receipt['post_id']
        with sqlite3.connect(Path(browser_db).resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            candidates=[dict(r) for r in db.execute('''SELECT * FROM browser_control_commands
                WHERE account_id=? AND kind='read' ORDER BY created_at,command_id''',(a['account_uuid'],))
                if r['idempotency_key']==base or r['idempotency_key'].startswith(base+':after:')]
        pending=[r for r in candidates if r['state'] in {'queued','running','waiting_human','paused','outcome_unknown'}]
        if len(pending)>1:raise CandidateBlocked('ambiguous_publication_metadata_commands')
        previous=pending[0] if pending else candidates[-1] if candidates else None
        key=base
        if previous:
            payload=json.loads(previous['payload'])
            if (previous['binding_version']!=a['binding_version'] or payload.get('method')!='sync_videos'
                or payload.get('params')!={}):raise CandidateBlocked('publication_metadata_intent_changed')
            if pending:return {'command_id':previous['command_id'],'state':previous['state'],'reused':True}
            from .publication_time_evidence_v1 import read_publication_time
            try:
                read_publication_time(browser_db,c['command_id'],a['account_uuid'],a['binding_version'],
                    metadata_command_id=previous['command_id'])
            except ValueError:
                # Explicit refresh after a terminal observation may see a delayed post.
                # Concurrent refreshes derive the same key from the same terminal ID.
                key=base+':after:'+previous['command_id']
            else:return {'command_id':previous['command_id'],'state':previous['state'],'reused':True}
        if queue is None:
            from src.operations_accounts.browser_control_runtime import _submit
            queue=_submit
        # Broker idempotency protects clicks and receipt loss; no custom collector.
        return queue(a['account_key'],'read',{'method':'sync_videos','params':{},'operation_profile':None},
                     key,10)
