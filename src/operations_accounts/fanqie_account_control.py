"""Dedicated Fanqie environments using the shared durable owner/command store.

UI and CLI enqueue. A hidden owner process runs only this platform's command;
Douyin identities/profiles are never borrowed or modified.
"""
from contextlib import contextmanager, closing
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

from .browser_control import BrowserControlStore, BrowserControlActor, BrowserControlRejected, BrowserCommandResult
from .platform_bindings import PlatformBindingRepository, install_platform_binding_schema
from src.platform_adapter.fanqie_identity import HOME

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data/account_browser_control.db"
PROFILES = ROOT / "data/browser/fanqie_accounts"
EVIDENCE = ROOT / "data/fanqie_account_control"


def metadata_read(operation, *, evidence_path, stage, deadline_seconds=5, clock=time.monotonic, sleep=time.sleep):
    """Retry only local reads; never repeat navigation, login or submission.

    Persist SQLite's structural code, not exception strings or query payloads.
    A failed check stops the command and must never be interpreted as healthy.
    """
    deadline = clock() + deadline_seconds
    attempts = 0
    while True:
        attempts += 1
        try:
            return operation()
        except sqlite3.Error as exc:
            code = getattr(exc, 'sqlite_errorcode', None)
            busy = isinstance(code, int) and code & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
            write_json(evidence_path, {'stage': stage, 'error_type': type(exc).__name__,
                'sqlite_errorcode': code if isinstance(code, int) else None,
                'sqlite_errorname': sqlite3.errorcode.get(code) if hasattr(sqlite3, 'errorcode') else
                    ('SQLITE_BUSY' if busy and code & 255 == sqlite3.SQLITE_BUSY else 'SQLITE_LOCKED' if busy else 'OTHER'),
                'attempts': attempts, 'observed_at': time.time(), 'read_only_retry': busy})
            if not busy or clock() >= deadline:
                raise BrowserControlRejected('fanqie_metadata_unavailable', '账号管控读取失败，已停止；详见原任务数据库诊断') from exc
            sleep(min(.25, max(0, deadline-clock())))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_bytes(raw)
    os.replace(temp, path)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}


class FanqieAccounts:
    def __init__(self, db=DB, profiles=PROFILES, evidence=EVIDENCE, douyin_db=None,*,ledger_path=None,control_db=None):
        self.db, self.profiles, self.evidence = map(lambda p: Path(p).resolve(), (db, profiles, evidence))
        self.douyin_db = Path(douyin_db or ROOT / "data/douyin.db").resolve()
        from src.services.fanqie_review_service import CLOSED_LOOP_DB_PATH
        self.ledger_path=self._ledger_path(ledger_path or CLOSED_LOOP_DB_PATH)
        self.control_db=Path(control_db or self.db.parent/'account_refresh.db').resolve()

    @staticmethod
    def _ledger_path(value):
        value=Path(value).resolve()
        if not value.is_relative_to(ROOT/'data'):raise ValueError('业务台账必须位于项目data目录')
        return value

    def with_ledger(self,value):
        from copy import copy
        configured=copy(self);configured.ledger_path=self._ledger_path(value)
        return configured

    @contextmanager
    def connection(self, write=False):
        with closing(sqlite3.connect(self.db.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            with db:
                if write:
                    db.execute("BEGIN IMMEDIATE")
                yield db

    def installed(self):
        if not self.db.exists():
            return False
        with self.connection() as db:
            return db.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('platform_identity_bindings','platform_browser_environments')").fetchone()[0] == 2

    def install(self):
        if self.installed():
            return {"status": "already_installed"}
        backup = self.evidence / ("schema_backup_" + uuid.uuid4().hex + ".db")
        # Consistent backup precedes additive migration; no old rows are edited.
        with self.connection() as db:
            binding_exists = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='platform_identity_bindings'").fetchone())
        if not binding_exists:
            install_platform_binding_schema(self.db, backup)
        else:
            backup.parent.mkdir(parents=True, exist_ok=True)
            with self.connection() as source, closing(sqlite3.connect(backup)) as dest:
                source.backup(dest)
        with self.connection(True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS platform_browser_environments (
                resource_id TEXT PRIMARY KEY, label TEXT NOT NULL, environment_key TEXT UNIQUE NOT NULL,
                profile_dir TEXT UNIQUE NOT NULL, storage_state_path TEXT UNIQUE NOT NULL,
                binding_version TEXT NOT NULL, douyin_account_uuid TEXT NOT NULL,
                douyin_binding_sha256 TEXT NOT NULL, created_at REAL NOT NULL)""")
        return {"status": "installed", "backup": str(backup)}

    def douyin_binding(self, key):
        with closing(sqlite3.connect(self.douyin_db.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT account_uuid,account_key,platform_identity_key,browser_environment_key,browser_profile_dir,created_at FROM account_runtime_bindings WHERE account_key=? AND platform='douyin' AND status='active'", (key,)).fetchone()
        if not row:
            raise ValueError("请先绑定目标抖音运营账号")
        value = dict(row)
        value["sha256"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        return value

    def create(self, label, douyin_account_key):
        if not self.installed():
            raise ValueError("番茄账号管控尚未安装")
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise ValueError("请输入不超过80字的环境名称")
        target = self.douyin_binding(douyin_account_key)
        resource = "fanqie:" + uuid.uuid4().hex
        folder = self.profiles / resource.split(":")[1]
        with self.connection(True) as db:
            # Repeated UI clicks reuse the already provisioned environment.
            old = db.execute("SELECT * FROM platform_browser_environments WHERE douyin_account_uuid=?", (target["account_uuid"],)).fetchall()
            if old:
                if len(old) != 1 or old[0]["douyin_binding_sha256"] != target["sha256"]:
                    raise ValueError("原账号关联已变化，不能自动换绑或新建绕过")
                return dict(old[0])
            db.execute("INSERT INTO platform_browser_environments VALUES(?,?,?,?,?,?,?,?,?)", (resource,
                label.strip(), resource + ":browser", str(folder / "profile"), str(folder / "storage_state.json"),
                uuid.uuid4().hex, target["account_uuid"], target["sha256"], time.time()))
        return self.get(resource)

    def list(self):
        if not self.installed():
            return []
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM platform_browser_environments ORDER BY created_at")]

    def get(self, resource):
        with self.connection() as db:
            row = db.execute("SELECT * FROM platform_browser_environments WHERE resource_id=?", (resource,)).fetchone()
        if not row:
            raise ValueError("未登记的番茄专属环境")
        value = dict(row)
        folder = self.profiles / resource.removeprefix("fanqie:")
        if (not resource.startswith("fanqie:") or not folder.is_relative_to(self.profiles)
                or Path(value["profile_dir"]).resolve() != folder / "profile"
                or Path(value["storage_state_path"]).resolve() != folder / "storage_state.json"):
            raise ValueError("专属环境路径不匹配")
        return value

    def check_association(self, env):
        with closing(sqlite3.connect(self.douyin_db.as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute("SELECT account_key FROM account_runtime_bindings WHERE account_uuid=? AND status='active'", (env["douyin_account_uuid"],)).fetchone()
        target = self.douyin_binding(row[0]) if row else None
        if not target or target["sha256"] != env["douyin_binding_sha256"]:
            raise BrowserControlRejected("linked_douyin_identity_changed", "关联抖音账号已变化，不能自动换绑")
        return target

    def bindings(self):
        return PlatformBindingRepository(self.db, evidence_root=self.evidence, profile_root=self.profiles)

    def queue(self, resource, kind="fanqie_login", *, book_name=None, chapters=0, promotion_request=None,
              binding_uuid=None, manifest_sha256=None,observer_request=None,snapshot_version='v1',book_id=None,locate=False,
              lookup_alias=None,lookup_request=None,retained_url=None):
        if kind not in {"fanqie_login", "fanqie_catalog", "fanqie_book_inspect",'fanqie_promotion_list',
                        'fanqie_promotion_apply','fanqie_backfill_reconcile','fanqie_promotion_preflight','fanqie_promotion_lookup',
                        'fanqie_filled_details','fanqie_filled_details_controls','fanqie_backfill_editor_inspect','fanqie_new_publication_backfill','fanqie_cleanup_rebind'}:
            raise ValueError("本入口仅支持登录核验和已绑定账号的目录读取")
        if type(locate) is not bool or locate and kind != 'fanqie_promotion_preflight':
            raise ValueError('准确书籍搜索仅适用于显式推广预检')
        if kind == 'fanqie_book_inspect' and (not isinstance(book_name, str) or not book_name.strip() or len(book_name)>120):
            raise ValueError('书籍读取必须指定准确书名')
        if kind in {'fanqie_promotion_lookup','fanqie_filled_details','fanqie_filled_details_controls','fanqie_backfill_editor_inspect'}:
            from src.platform_adapter.fanqie_promotion_lookup_v1 import validate_lookup_target
            validate_lookup_target(book_id,book_name,lookup_alias)
            if chapters!=0:raise ValueError('推广查询不读取章节')
            if kind in {'fanqie_filled_details','fanqie_filled_details_controls','fanqie_backfill_editor_inspect'} and lookup_request is not None:
                raise ValueError('发文详情读取不接受搜索或写入请求')
        elif lookup_alias is not None or lookup_request is not None:
            raise ValueError('查询参数仅适用于只读推广查询')
        if kind == 'fanqie_promotion_preflight':
            from src.platform_adapter.fanqie_promotion_preflight_v1 import validate_target
            validate_target(book_id,book_name)
            if chapters != 0:raise ValueError('推广预检不读取章节')
        elif book_id is not None and kind not in {'fanqie_promotion_lookup','fanqie_filled_details','fanqie_filled_details_controls','fanqie_backfill_editor_inspect'}:
            raise ValueError('书籍ID仅适用于明确只读推广预检')
        if kind not in {'fanqie_book_inspect','fanqie_promotion_preflight','fanqie_promotion_lookup','fanqie_filled_details','fanqie_filled_details_controls','fanqie_backfill_editor_inspect'} and book_name is not None:
            raise ValueError('当前任务不接受书名')
        if kind=='fanqie_backfill_editor_inspect':
            if (not isinstance(retained_url,str) or not re.fullmatch(r'https://www\.douyin\.com/video/\d{1,25}',retained_url)):
                raise ValueError('回填表单观察必须绑定原已填公开链接')
        elif retained_url is not None:raise ValueError('原链接参数仅适用于回填表单观察')
        if type(chapters) is not int or not 0 <= chapters <= 50000:
            raise ValueError('章节数须为非负整数，0表示全部可读章节')
        env = self.get(resource)
        self.check_association(env)
        bound=self.bindings().get(resource)
        if kind != "fanqie_login" and not bound:
            raise ValueError("先在专属窗口登录并确认真实番茄身份")
        extra={}
        if kind=='fanqie_promotion_preflight':extra.update(book_id=book_id,book_name=book_name)
        if kind in {'fanqie_promotion_lookup','fanqie_filled_details','fanqie_filled_details_controls','fanqie_backfill_editor_inspect'}:
            extra.update(book_id=book_id,book_name=book_name,lookup_alias=lookup_alias)
            if kind=='fanqie_backfill_editor_inspect':extra['retained_url']=retained_url
            if lookup_request is not None:
                from src.platform_adapter.fanqie_promotion_lookup_v1 import validate_request
                validate_request(lookup_request,{k:(bound if k=='platform_identity_key' else env)[k]for k in
                    ('resource_id','binding_version','platform_identity_key','environment_key')},
                    book_id=book_id,book_name=book_name,alias=lookup_alias)
                extra['lookup_request']=lookup_request
        if locate:extra['locate']=True
        if snapshot_version not in ('v1','v2') or snapshot_version!='v1' and kind!='fanqie_promotion_list':
            raise ValueError('原生身份版本仅适用于显式只读推广列表')
        if snapshot_version=='v2':extra['snapshot_version']='v2'
        if observer_request is not None:
            if kind!='fanqie_promotion_list':raise ValueError('被动响应诊断仅接受只读推广列表任务')
            from .fanqie_managed_promotion_v1 import _read
            from src.platform_adapter.fanqie_promotion_observation_diagnostic_v1 import validate_request_scope
            _read(observer_request)  # Bind project-local evidence before queueing.
            validate_request_scope(observer_request,{k:(bound if k=='platform_identity_key' else env)[k]
                for k in ('resource_id','binding_version','platform_identity_key','environment_key')})
            extra['observer_request']=observer_request
        if kind=='fanqie_promotion_apply':
            from .fanqie_managed_promotion_v1 import application_request
            application_request(promotion_request,env,bound)
            extra['request']=promotion_request
        elif kind=='fanqie_new_publication_backfill':
            from . import fanqie_new_publication_backfill_v1 as new_backfill
            new_request=new_backfill.validate_request(promotion_request,accounts=self,env=env,binding=bound)
            extra['request']=promotion_request
            new_key=new_backfill.idempotency_key(new_request)
            with self.connection() as db:
                existing=db.execute('SELECT command_id FROM browser_control_commands WHERE account_id=? AND idempotency_key=?',
                    (resource,new_key)).fetchone()
            if existing:return BrowserControlStore(self.db).get(existing['command_id'])
            new_backfill.need(not Path(new_request['submit_claim_path']).exists(),'global_submission_already_claimed')
        elif kind=='fanqie_cleanup_rebind':
            from . import fanqie_cleanup_rebind_v1 as cleanup
            if chapters!=0:raise ValueError('清理重建不读取章节')
            new_request=cleanup.validate_request(promotion_request,accounts=self,env=env,binding=bound)
            extra['request']=promotion_request;new_key=cleanup.idempotency_key(new_request)
            with self.connection() as db:
                existing=db.execute('SELECT command_id FROM browser_control_commands WHERE account_id=? AND idempotency_key=?',(resource,new_key)).fetchone()
            if existing:return BrowserControlStore(self.db).get(existing['command_id'])
            cleanup.require_unclaimed(new_request)
        elif promotion_request is not None:
            raise ValueError('仅推广申请接受固定请求')
        if kind=='fanqie_backfill_reconcile':
            from src.services.fanqie_promotion_ledger import PromotionLedger
            ledger=PromotionLedger(self.ledger_path)
            row=ledger.get(binding_uuid)
            contract=json.loads(row['contract_json'])
            if (row['manifest_sha']!=manifest_sha256 or contract['fanqie_resource_id']!=resource
                    or contract['fanqie_binding_version']!=env['binding_version']):
                raise ValueError('回填核对必须绑定当前环境原契约')
            extra.update(binding_uuid=binding_uuid,manifest_sha256=manifest_sha256)
        elif binding_uuid is not None or manifest_sha256 is not None:
            raise ValueError('当前任务不接受回填契约参数')
        store = BrowserControlStore(self.db)
        with self.connection() as db:
            pending = db.execute("SELECT command_id FROM browser_control_commands WHERE account_id=? AND state IN ('queued','running','paused','waiting_human','outcome_unknown') ORDER BY created_at LIMIT 1", (resource,)).fetchone()
        if pending:
            return store.get(pending["command_id"])
        # Concurrent clicks after the same terminal command share one immutable key.
        previous = self.latest_command(resource)
        if previous and previous["state"] in {"queued", "running", "paused", "waiting_human", "outcome_unknown"}:
            return previous
        key = (new_key if kind in {'fanqie_new_publication_backfill','fanqie_cleanup_rebind'} else
               "fanqie-backfill-reconcile:"+row['business_key']+":"+(previous['command_id'] if previous else 'initial')
               if kind=='fanqie_backfill_reconcile' else "fanqie-step:" + (previous["command_id"] if previous else "initial"))
        try:
            return store.submit(resource, env["binding_version"], kind, key,
                                {"environment_key": env["environment_key"], **extra,
                                 **({'book_name':book_name.strip(),'chapters':chapters} if kind=='fanqie_book_inspect' else {})}, priority=10)
        except BrowserControlRejected as exc:
            if exc.code != "idempotency_conflict":
                raise
            if kind in {'fanqie_new_publication_backfill','fanqie_cleanup_rebind'}:
                with self.connection() as db:
                    original=db.execute('SELECT command_id FROM browser_control_commands WHERE account_id=? AND idempotency_key=?',(resource,key)).fetchone()
                if original:return store.get(original['command_id'])
                raise
            return self.latest_command(resource)

    def latest_command(self, resource):
        with self.connection() as db:
            row = db.execute("SELECT command_id FROM browser_control_commands WHERE account_id=? ORDER BY created_at DESC LIMIT 1", (resource,)).fetchone()
        return BrowserControlStore(self.db).get(row[0]) if row else None

    def folder(self, command_id):
        if not isinstance(command_id, str) or not command_id.isalnum():
            raise ValueError("无效原命令ID")
        return self.evidence / "commands" / command_id

    def request_close(self, command_id):
        command = BrowserControlStore(self.db).get(command_id)
        if not command or command["kind"] != "fanqie_login" or command["state"] != "running":
            raise ValueError("仅能关闭正在运行的原番茄登录窗口")
        self.get(command["account_id"])
        write_json(self.folder(command_id) / "CLOSE_REQUEST.json", {"command_id": command_id, "requested_at": time.time()})

    def confirm(self, command_id, expected_identity, user):
        command = BrowserControlStore(self.db).get(command_id)
        if not command or command["kind"] != "fanqie_login" or command["state"] != "succeeded":
            raise ValueError("登录窗口尚未保存关闭并完成身份核验")
        env = self.get(command["account_id"])
        self.check_association(env)
        proof = command["result"]["probe_evidence"]
        value = self.bindings()._evidence(proof)
        if value.get("platform_identity_key") != expected_identity or not str(user).strip():
            raise ValueError("确认的账号与原身份不一致")
        old = self.bindings().get(env["resource_id"])
        if old:
            if old["platform_identity_key"] != expected_identity:
                raise ValueError("原番茄身份不同，不能自动换绑")
            return old
        reference = write_json(self.folder(command_id) / ("CONFIRM_" + uuid.uuid4().hex + ".json"), {
            "schema": "platform_identity_confirmation/v1", "platform": "fanqie",
            **{k: env[k] for k in ("resource_id", "binding_version", "environment_key", "profile_dir")},
            "platform_identity_key": expected_identity, "probe_evidence": proof,
            "decision_source": "explicit_user_confirmation", "user_statement": f"{user}确认将窗口显示的番茄身份{expected_identity}绑定到所选环境",
        })
        return self.bindings().confirm(reference)


def launch_worker(command, accounts):
    """Spawn one hidden owner process, without opening a terminal window."""
    if accounts.db != DB.resolve() or accounts.profiles != PROFILES.resolve() or accounts.evidence != EVIDENCE.resolve():
        raise ValueError("独立进程入口仅接受项目登记的生产路径")
    if command["state"] != "queued":
        return {"status": command["state"], "command_id": command["command_id"]}
    if command['kind']=='fanqie_login':
        from .interactive_desktop import require_interactive_desktop
        require_interactive_desktop()
    ledger=accounts._ledger_path(accounts.ledger_path)
    folder = accounts.folder(command["command_id"])
    folder.mkdir(parents=True, exist_ok=True)
    claim = folder / "WORKER_LAUNCH.json"
    try:
        with claim.open("x", encoding="utf-8") as handle:
            json.dump({"command_id": command["command_id"], "created_at": time.time()}, handle)
    except FileExistsError:
        return {"status": "original_launch_preserved", "command_id": command["command_id"]}
    with (folder / "worker.log").open("ab") as log:
        proc = subprocess.Popen([sys.executable, str(ROOT / "scripts/run_fanqie_account.py"), "worker",
            "--resource", command["account_id"], '--ledger-path',str(ledger)], cwd=ROOT, stdout=log, stderr=log,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    write_json(folder / "WORKER_PROCESS.json", {"pid": proc.pid, "command_id": command["command_id"]})
    return {"status": "launched", "pid": proc.pid, "command_id": command["command_id"]}


def run_owner(resource, accounts=None, session_factory=None, max_login_seconds=1800):
    from .fanqie_completion import FanqieControlStore
    accounts = accounts or FanqieAccounts()
    env = accounts.get(resource)
    store = FanqieControlStore(accounts.db)
    sessions = []
    managed={}

    def navigate(ctx,page,url):
        from urllib.parse import urlsplit
        from src.platform_adapter.browser_session import BrowserNavigationTimeout
        try:
            page.goto(url,wait_until='domcontentloaded')
        except (BrowserNavigationTimeout,TimeoutError) as error:
            facts=getattr(error,'navigation_evidence',{}) or {}
            write_json(accounts.folder(ctx.task_id)/('NAVIGATION_TIMEOUT_'+uuid.uuid4().hex+'.json'),
                dict(error_type=type(error).__name__,navigation_repeated=False,
                    evidence={k:v for k,v in facts.items() if k in ('target_matched','navigation_committed','ready_state')}))
        # Never use Page.url's cached fallback for this decision.
        current=page._cmd('current_url').get('url','')
        parsed=urlsplit(current)
        if parsed.scheme!='https' or parsed.netloc!='kol.fanqieopen.com':
            raise BrowserControlRejected('fanqie_page_origin_changed','当前任务页已离开番茄官方页面')

    def managed_state(ctx):
        ctx.check_dispatch()
        if ctx.task_id not in managed:
            from src.platform_adapter.browser_session import BrowserSession
            from src.platform_adapter.models import BrowserSessionConfig
            config=BrowserSessionConfig(base_url='https://kol.fanqieopen.com',home_url=HOME,
                user_data_dir=env['profile_dir'],storage_state_path=env['storage_state_path'],
                headless=True,browser_channel='chrome',mute_audio=True,timeout_ms=20000)
            session=(session_factory or BrowserSession)(config);sessions.append(session)
            page=session.get_page();page._cmd('fanqie_identity',reset=True)
            managed[ctx.task_id]=dict(session=session,page=page,identity_page=None)
            navigate(ctx,page,HOME)
        return managed[ctx.task_id]

    def probe_provider(ctx):
        state=managed_state(ctx);ctx.check_dispatch()
        page=state['page'];probe=page._cmd('fanqie_identity').get('evidence',{})
        if probe.get('page_location',{}).get('origin')!='https://kol.fanqieopen.com':
            raise BrowserControlRejected('fanqie_page_origin_changed','当前任务页已离开番茄官方页面')
        if probe.get('challenge'):raise BrowserControlRejected('fanqie_verification_required','番茄需要平台验证')
        if not probe.get('verified') or not 0<=time.time()-probe.get('observed_at',0)<=45:
            if state['identity_page'] is None:state['identity_page']=state['session'].new_tab('managed-identity-refresh')
            page=state['identity_page'];probe=page._cmd('fanqie_identity').get('evidence',{})
            if not probe.get('verified') or not 0<=time.time()-probe.get('observed_at',0)<=45:
                page._cmd('fanqie_identity',reset=True);navigate(ctx,page,HOME)
                for _ in range(12):
                    ctx.check_dispatch();probe=page._cmd('fanqie_identity').get('evidence',{})
                    if probe.get('challenge') or probe.get('verified'):break
                    page.wait_for_timeout(250)
        probe=dict(probe,platform='fanqie',environment_key=env['environment_key'])
        accounts.check_association(env)
        accounts.bindings().guard(resource,env['binding_version'],ctx.actor.owner_id,ctx.actor.generation,probe)
        return probe

    def page_provider(ctx,url):
        from urllib.parse import urlsplit
        from src.platform_adapter.fanqie_managed_page import FanqieManagedPage
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.netloc!='kol.fanqieopen.com':
            raise BrowserControlRejected('fanqie_page_origin_invalid','仅允许当前番茄官方页面')
        state=managed_state(ctx);probe_provider(ctx);ctx.check_dispatch()
        navigate(ctx,state['page'],url)
        return FanqieManagedPage(state['page'])

    def native_snapshot_provider(ctx,*,phase='preflight',force_refresh=False):
        from .fanqie_managed_promotion_v1 import capture_native_snapshot,_read
        from src.platform_adapter.fanqie_managed_page import FanqieManagedPage
        from src.services import fanqie_promotion_identity_v2 as native
        if phase not in ('preflight','pre_submit','post_submit','reconcile'):
            raise ValueError('unknown_native_observation_phase')
        state=managed_state(ctx);probe=probe_provider(ctx);ctx.check_dispatch()
        subject={key:env[key] for key in ('resource_id','binding_version','environment_key')}
        subject.update(platform_identity_key=probe['platform_identity_key'],owner_id=ctx.actor.owner_id,
                       generation=ctx.actor.generation,task_id=ctx.task_id)
        cached=state.get('native_snapshot')
        force_refresh=force_refresh or phase in ('pre_submit','post_submit','reconcile')
        if cached and not force_refresh and state.get('native_subject')==subject:
            snapshot=native.validate_snapshot(_read(cached))
            if 0<=time.time()-snapshot['observed_at']<=45:return cached
        if state.get('native_page') is None:
            state['native_page']=state['session'].new_tab('native-promotion-evidence')
        page=state['native_page']
        from .fanqie_managed_promotion_v1 import LIST_URL
        navigate(ctx,page,LIST_URL)
        index=state.get('native_observation_count',0)+1;state['native_observation_count']=index
        def identity():
            ctx.check_dispatch();return probe_provider(ctx)
        def guard():identity()
        receipt=capture_native_snapshot(FanqieManagedPage(page),env=env,managed_subject=subject,
            identity=identity,guard=guard,evidence_directory=accounts.folder(ctx.task_id)/f'native_evidence_{index:03d}')
        state.update(native_snapshot=receipt,native_subject=subject)
        return receipt

    def admission(ctx, phase):
        def check():
            accounts.check_association(env)
            if accounts.get(resource) != env or ctx.binding_version != env["binding_version"]:
                raise BrowserControlRejected("fanqie_environment_changed", "原环境绑定已变化")
            legacy_backfill=(ctx.command['kind']=='fanqie_backfill' and 'environment_key' not in ctx.command['payload'])
            if not legacy_backfill and ctx.command["payload"].get("environment_key") != env["environment_key"]:
                raise BrowserControlRejected("fanqie_environment_changed", "请求环境不匹配")
        metadata_read(check, evidence_path=accounts.folder(ctx.task_id)/'DATABASE_DIAGNOSTIC.json', stage='admission')

    def handler(ctx, payload):
        from src.platform_adapter.browser_session import BrowserSession
        from src.platform_adapter.models import BrowserSessionConfig
        def read(operation, stage):
            return metadata_read(operation, evidence_path=accounts.folder(ctx.task_id)/'DATABASE_DIAGNOSTIC.json', stage=stage)
        config = BrowserSessionConfig(base_url="https://kol.fanqieopen.com", home_url=HOME,
            user_data_dir=env["profile_dir"], storage_state_path=env["storage_state_path"],
            headless=ctx.command["kind"] != "fanqie_login", browser_channel="chrome", mute_audio=True, timeout_ms=20000)
        session = (session_factory or BrowserSession)(config)
        sessions.append(session)
        page = session.get_page()
        page._cmd("fanqie_identity", reset=True)
        read(ctx.check_dispatch, 'before_navigation')
        try:
            page.goto(HOME, wait_until="domcontentloaded")
        except Exception as exc:
            # A navigation timeout may still leave the original page usable.
            if "Timeout" not in type(exc).__name__:
                raise
        end = time.monotonic() + (max_login_seconds if ctx.command["kind"] == "fanqie_login" else 25)
        last = None
        window_open = True
        saved_observation = None
        while time.monotonic() < end:
            read(ctx.check_dispatch, 'window_guard')
            window_open = session.window_status()["open"]
            if not window_open:
                break
            last = page._cmd("fanqie_identity").get("evidence", {})
            last.update(schema="platform_identity_probe/v1", platform="fanqie", environment_key=env["environment_key"])
            write_json(accounts.folder(ctx.task_id) / "LATEST_PROBE.json", last)
            if last.get("verified") and last.get("observed_at") != saved_observation:
                session.save_storage_state()
                saved_observation = last.get("observed_at")
            bound = read(lambda: accounts.bindings().get(resource), 'identity_binding_read')
            if last.get("verified") and bound and last.get("platform_identity_key") != bound["platform_identity_key"]:
                return BrowserCommandResult("failed", {"reason": "platform_identity_mismatch"})
            if ctx.command['kind'] == 'fanqie_book_inspect' and last.get('verified'):
                from src.platform_adapter.fanqie_book_inspect import inspect_book, BookInspectionStopped
                proof = dict(last)
                identity_page = None
                def book_guard():
                    nonlocal proof, identity_page
                    read(ctx.check_dispatch, 'book_dispatch')
                    current = page._cmd('fanqie_identity').get('evidence', {})
                    if current.get('challenge') or current.get('page_location',{}).get('origin') != 'https://kol.fanqieopen.com':
                        raise BookInspectionStopped('book_page_requires_verification')
                    if not current.get('verified') and current.get('reason') != 'identity_not_observed':
                        raise BookInspectionStopped('book_identity_unverified')
                    if current.get('verified') and current.get('platform_identity_key') != proof['platform_identity_key']:
                        raise BookInspectionStopped('book_identity_changed')
                    if time.time() - proof['observed_at'] > 30:
                        identity_page = identity_page or session.new_tab('book-identity-refresh')
                        identity_page._cmd('fanqie_identity', reset=True)
                        identity_page.goto(HOME, wait_until='domcontentloaded')
                        fresh = {}
                        for _ in range(20):
                            read(ctx.check_dispatch, 'book_identity_refresh')
                            fresh = identity_page._cmd('fanqie_identity').get('evidence', {})
                            if fresh.get('challenge'):
                                raise BookInspectionStopped('identity_refresh_challenge')
                            if fresh.get('verified'): break
                            identity_page.wait_for_timeout(500)
                        if not fresh.get('verified') or fresh.get('platform_identity_key') != proof['platform_identity_key']:
                            raise BookInspectionStopped('identity_refresh_failed')
                        proof = dict(fresh, platform='fanqie', environment_key=env['environment_key'])
                        write_json(accounts.folder(ctx.task_id)/'LATEST_PROBE.json', proof)
                    read(lambda: accounts.bindings().guard(resource, env['binding_version'], ctx.actor.owner_id, ctx.actor.generation, proof, ttl=90), 'book_guard')
                path = accounts.folder(ctx.task_id) / 'BOOK_INSPECTION.json'
                try:
                    count = payload.get('chapters',1)
                    value = inspect_book(page, payload['book_name'], book_guard, lambda value: write_json(path, value), chapters=min(count or 1,3))
                    if count == 0 or count > 3:
                        from src.platform_adapter.fanqie_book_corpus import collect_corpus
                        value = collect_corpus(page, value, book_guard, lambda value: write_json(path,value),
                            accounts.evidence/'books'/value['book_id'], limit=count,
                            resource_id=resource, command_id=ctx.task_id)
                except BookInspectionStopped as exc:
                    return BrowserCommandResult('failed', {'reason': str(exc), 'partial_evidence_path': str(path)})
                return BrowserCommandResult('succeeded', {'book_evidence': write_json(path, value)})
            if ctx.command["kind"] == "fanqie_catalog" and last.get("verified"):
                read(lambda: accounts.bindings().guard(resource, env["binding_version"], ctx.actor.owner_id, ctx.actor.generation, last, ttl=90), 'catalog_guard')
                text = page.evaluate("() => document.body.innerText")
                artifact = write_json(accounts.folder(ctx.task_id) / "CATALOG.json", {"url": HOME,
                    "observed_at": time.time(), "platform_identity_key": last["platform_identity_key"], "text": text[:100000]})
                return BrowserCommandResult("succeeded", {"catalog_evidence": artifact})
            if (accounts.folder(ctx.task_id) / "CLOSE_REQUEST.json").exists():
                session.save_storage_state()
                break
            page.wait_for_timeout(1000)
        if ctx.command["kind"] == "fanqie_login" and last and last.get("verified") and 0 <= time.time() - last.get("observed_at", 0) <= 300:
            proof = write_json(accounts.folder(ctx.task_id) / "IDENTITY_PROBE.json", last)
            if window_open:
                session.save_storage_state()
            return BrowserCommandResult("succeeded", {"probe_evidence": proof, "identity": last["platform_identity_key"], "binding_confirmed": bool(read(lambda: accounts.bindings().get(resource), 'final_binding_read'))})
        return BrowserCommandResult("failed", {"reason": "identity_unverified", "challenge": (last or {}).get("challenge")})

    from .fanqie_managed_promotion_v1 import make_handlers
    handlers={"fanqie_login":handler,"fanqie_catalog":handler,"fanqie_book_inspect":handler,
              **make_handlers(accounts,env,page_provider=page_provider,probe_provider=probe_provider)}
    def backfill_handler(ctx,payload):
        from .fanqie_backfill_control import build_managed_backfill_handlers
        return build_managed_backfill_handlers(accounts,env,page_provider=page_provider,
            probe_provider=probe_provider,ledger_path=accounts.ledger_path,
            native_snapshot_provider=native_snapshot_provider)[ctx.command['kind']](ctx,payload)
    handlers.update(fanqie_backfill=backfill_handler,fanqie_backfill_reconcile=backfill_handler)
    # Only these explicitly listed read commands can prove a local failure before a browser
    # worker existed. Login, application and backfill retain unknown handling.
    from .fanqie_readonly_startup_recovery_v1 import READONLY_KINDS,readonly_startup_handler
    for readonly_kind in READONLY_KINDS:
        handlers[readonly_kind]=readonly_startup_handler(handlers[readonly_kind],accounts=accounts,sessions=sessions)
    actor = BrowserControlActor(store, resource, env["binding_version"], "fanqie-owner:" + uuid.uuid4().hex,
        handlers, admission=admission)
    try:
        original = accounts.latest_command(resource)
        for attempt in range(5):
            outcome = actor.run_next()
            if outcome is not None or not original:
                return outcome
            current = store.get(original['command_id'])
            if not current or current['state'] != 'queued':
                return outcome
            # run_next returns None on rolled-back contention before claiming;
            # only that original queued request may wait, never a handler result.
            write_json(accounts.folder(original['command_id'])/f'ADMISSION_WAIT_{attempt+1}.json',
                {'command_id':original['command_id'],'state':current['state'],
                 'observed_at':time.time(),'platform_handler_replayed':False})
            if attempt < 4:
                time.sleep(1)
        return None
    finally:
        for session in sessions:
            session.stop()
        if actor.generation is not None:
            try:
                actor.close()
            except (BrowserControlRejected, sqlite3.Error):
                actor.stop_heartbeat()  # Preserve unknown command and owner, never replay.
