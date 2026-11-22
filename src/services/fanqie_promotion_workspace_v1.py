"""Small explicit facade over the existing Fanqie owner and P0 ledgers.

Construction/status never navigate or migrate. Browser/platform actions are
separate named calls; a busy original command is a blocker, not a new request.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from src.operations_accounts.fanqie_account_control import FanqieAccounts,launch_worker
from src.operations_accounts.browser_control import BrowserControlStore,BrowserControlRejected
from src.operations_accounts import fanqie_managed_promotion_v1 as promotion
from .fanqie_review_service import CLOSED_LOOP_DB_PATH
from .fanqie_publication_copy import novel_publication_copy

ROOT=Path(__file__).resolve().parents[2]


def ref(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('工件须位于项目目录')
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def _record(folder,name,value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    path=Path(folder)/(name+'_'+hashlib.sha256(raw).hexdigest()+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        with path.open('xb') as out:out.write(raw)
    return ref(path)


class PromotionWorkspace:
    def __init__(self,path=CLOSED_LOOP_DB_PATH,*,accounts=None,launcher=None,account_resolver=None):
        self.path=Path(path).resolve()
        original=accounts or FanqieAccounts(ledger_path=self.path)
        self.accounts=original.with_ledger(self.path) if hasattr(original,'with_ledger') else original
        self.launcher=launcher or launch_worker;self.account_resolver=account_resolver

    def _candidates(self):
        from .fanqie_h3_candidate_v1 import CandidateLedger
        return CandidateLedger(self.path)

    def _backfill(self):
        from .fanqie_promotion_ledger import PromotionLedger
        return PromotionLedger(self.path)

    def migrate(self,backup_directory):
        from .fanqie_h3_candidate_v1 import migrate
        from .fanqie_promotion_ledger import migrate_ledger
        directory=Path(backup_directory).resolve()
        if not directory.is_relative_to(ROOT/'data'):raise ValueError('备份目录须位于项目data目录')
        if directory.exists():raise ValueError('备份目录已存在，保留原备份')
        directory.mkdir(parents=True)
        return dict(candidate=migrate(self.path,directory/'before_candidates.db'),
                    backfill=migrate_ledger(self.path,directory/'before_backfill.db'))

    def status(self,resource=None):
        result=dict(schema='fanqie_promotion_workspace/v1',read_only=True,candidates=[],resources=[],migration_required=False,
                    ledger_available=True)
        try:
            values=self._candidates().list_candidates()
            for row in values:
                frozen=json.loads(row['frozen_json'])
                item=dict(candidate_id=row['candidate_id'],book_id=frozen['book_id'],
                    book_name=frozen['book_name'],media=frozen['media'],task_id=row['task_id'],video_job_id=row['video_job_id'],
                    publish_id=row['publish_id'],command_id=row['command_id'],dispatch_state=row['dispatch_state'],
                    user_review_recorded=bool(row['review_json']),publication_prepared=bool(row['prepared_json']),
                    prepared_publication=json.loads(row['prepared_json']) if row['prepared_json'] else None)
                if row['command_id']:
                    try:
                        with sqlite3.connect(self.accounts.db.as_uri()+'?mode=ro',uri=True,timeout=2) as db:
                            db.row_factory=sqlite3.Row
                            command=db.execute('SELECT command_id,account_id,binding_version,kind,state,error_code FROM browser_control_commands WHERE command_id=?',(row['command_id'],)).fetchone()
                        if (not command or command['account_id']!=frozen['account']['account_uuid']
                                or command['binding_version']!=frozen['account']['binding_version'] or command['kind']!='publish'):
                            raise ValueError('original_publication_command_unavailable')
                        item['publication_command_state']=command['state'];item['publication_command_error']=command['error_code']
                    except (ValueError,sqlite3.Error,OSError):
                        item['publication_command_state']='unavailable';item['publication_command_error']='原发布任务暂无法核对'
                result['candidates'].append(item)
        except (ValueError,sqlite3.Error,OSError) as error:
            result.update(ledger_available=False,migration_required=str(error)=='explicit_migration_required',
                          ledger_notice=str(error),ledger_unavailable=str(error)!='explicit_migration_required')
        if self.accounts.installed():result['resources']=self.accounts.list()
        if resource:
            result['environment']=self.accounts.get(resource)
            result['original_command']=self.accounts.latest_command(resource)
            result['douyin_status']=self._douyin_status(resource)
            try:
                snapshot=self.latest_snapshot(resource)
                value=promotion._read(snapshot) if snapshot else None
                result['snapshot']=snapshot;result['promotion_rows']=value['rows'] if value else []
                result['snapshot_schema']=value['schema'] if value else None
                from .fanqie_promotion_identity_v2 import selection_key
                result['promotion_options']=[dict(key=selection_key(value,row),label=row['book_name']+' · '+row['alias'],
                    book_id=row['book_id'],alias=row['alias'])
                    for row in value['rows'] if row.get('status')=='ready'] if value else []
            except (ValueError,sqlite3.Error,OSError,BrowserControlRejected) as error:result['snapshot_notice']=str(error)
        return result

    def _douyin_status(self,resource):
        status=dict(available=False,publication_ready=False,account_management_url='/douyin-accounts',active_commands=[])
        try:
            linked=self.accounts.check_association(self.accounts.get(resource));uid=linked['account_uuid']
            control=Path(getattr(self.accounts,'control_db',self.accounts.db.parent/'account_refresh.db')).resolve()
            with sqlite3.connect(control.as_uri()+'?mode=ro',uri=True,timeout=2) as db:
                db.row_factory=sqlite3.Row
                row=db.execute('SELECT state,reason,error_code,updated_at FROM account_controls WHERE account_uuid=?',(uid,)).fetchone()
            if not row:raise ValueError('linked_control_missing')
            with sqlite3.connect(self.accounts.db.as_uri()+'?mode=ro',uri=True,timeout=2) as db:
                db.row_factory=sqlite3.Row
                from src.operations_accounts.publication_autonomous_reconciliation import unresolved
                # Use the same exact settled-snapshot rules as admission. A
                # historical unknown alone is not a new account blocker.
                pending=unresolved(BrowserControlStore,db,uid,('queued','running','paused','waiting_human','outcome_unknown'))
                commands=[{key:c.get(key) for key in ('command_id','kind','state','error_code')}
                          for c in sorted(pending,key=lambda c:c['updated_at'],reverse=True)[:20]]
            manual=any(c['kind']=='manual' for c in pending)
            pending_unknown=any(c['state']=='outcome_unknown' for c in pending)
            status.update(available=True,account_uuid=uid,account_key=linked['account_key'],control_state=row['state'],
                control_error=row['error_code'],active_commands=commands,waiting_original_manual_window=manual,
                waiting_original_identity_check=row['state']!='active',
                publication_ready=row['state']=='active' and not manual and not pending_unknown)
        except (ValueError,TypeError,KeyError,sqlite3.Error,OSError,BrowserControlRejected):status.update(control_state='unavailable',notice='关联抖音账号状态暂无法读取，不能视为可发布')
        return status

    def latest_snapshot(self,resource):
        with self.accounts.connection() as db:
            rows=db.execute("SELECT result FROM browser_control_commands WHERE account_id=? AND kind IN ('fanqie_promotion_list','fanqie_promotion_apply') AND state='succeeded' ORDER BY updated_at DESC",(resource,)).fetchall()
        for row in rows:
            value=json.loads(row[0] or '{}');binding=value.get('promotion_snapshot')
            if binding:
                from .fanqie_promotion_identity_v2 import validate_snapshot
                validate_snapshot(promotion._read(binding));return binding
        return None

    def _queue(self,resource,kind,**kwargs):
        before=self.accounts.latest_command(resource)
        command=self.accounts.queue(resource,kind,**kwargs)
        if command['kind']!=kind:
            return dict(status='blocked_existing_command',requested_kind=kind,command_id=command['command_id'],
                        original_kind=command['kind'],original_state=command['state'],new_request_queued=False)
        if kind=='fanqie_promotion_apply' and command['payload'].get('request')!=kwargs.get('promotion_request'):
            return dict(status='blocked_existing_command',command_id=command['command_id'],new_request_queued=False)
        if kind=='fanqie_promotion_list' and (command['payload'].get('snapshot_version','v1')!=kwargs.get('snapshot_version','v1')
                or kwargs.get('observer_request') is not None and command['payload'].get('observer_request')!=kwargs['observer_request']):
            return dict(status='blocked_existing_command',command_id=command['command_id'],new_request_queued=False)
        original=bool(before and before['command_id']==command['command_id'])
        if command['state']=='queued':launched=self.launcher(command,self.accounts)
        else:launched=dict(status=command['state'],command_id=command['command_id'])
        return dict(status='original_request_preserved' if original else 'queued',command_id=command['command_id'],
                    requested_kind=kind,new_request_queued=not original,launch=launched)

    def sync(self,resource,*,snapshot_version='v1',observer_request=None):
        extra={}
        if snapshot_version!='v1':extra['snapshot_version']=snapshot_version
        if observer_request is not None:extra['observer_request']=observer_request
        return self._queue(resource,'fanqie_promotion_list',**extra)

    def apply(self,resource,*,book_id,book_name,alias,promotion_path,user_statement):
        if not isinstance(user_statement,str) or not user_statement.strip():raise ValueError('请明确确认本次准确书籍、推广词和路径')
        env=self.accounts.get(resource);bound=self.accounts.bindings().get(resource)
        if not bound:raise ValueError('请先绑定番茄真实身份')
        intent=dict(resource_id=resource,binding_version=env['binding_version'],platform_identity_key=bound['platform_identity_key'],
            book_id=book_id.strip(),book_name=book_name.strip(),alias=alias.strip(),promotion_path=promotion_path.strip(),publish_type='AIGC')
        folder=self.accounts.evidence/'workspace_requests'
        auth=_record(folder,'APPLICATION_AUTH',dict(schema='fanqie_promotion_apply_authorization/v1',
            confirmed_by='user',user_statement=user_statement,intent=intent,max_submissions=1))
        request=_record(folder,'APPLICATION',dict(schema='fanqie_promotion_apply_request/v1',authorization=auth,**intent))
        return self._queue(resource,'fanqie_promotion_apply',promotion_request=request)

    def _resource_binding(self,resource):
        env=self.accounts.get(resource);self.accounts.check_association(env)
        bound=self.accounts.bindings().get(resource)
        if not bound or bound['status']!='active':raise ValueError('番茄身份未绑定')
        return dict(resource_id=resource,binding_version=env['binding_version'],environment_key=env['environment_key'],
            platform_identity_key=bound['platform_identity_key'],douyin_account_uuid=env['douyin_account_uuid'],
            account_link_version=env['douyin_binding_sha256'])

    def _promotion(self,resource,platform_task_id=None,*,promotion_key=None):
        binding=self.latest_snapshot(resource)
        if not binding:raise ValueError('请先同步推广任务')
        from .fanqie_promotion_identity_v2 import validate_snapshot,selection_key
        snapshot=validate_snapshot(promotion._read(binding))
        if promotion_key is not None and platform_task_id is not None:raise ValueError('仅接受一种明确推广记录选择')
        if snapshot['schema']=='fanqie_promotion_snapshot/v2' and promotion_key is None:
            raise ValueError('原生推广记录须使用promotion_key，不能伪作平台任务ID')
        key=promotion_key if promotion_key is not None else platform_task_id
        matches=[r for r in snapshot['rows'] if r.get('status')=='ready' and selection_key(snapshot,r)==key]
        if len(matches)!=1:raise ValueError('请选择唯一且已完整核对的推广记录')
        return snapshot,matches[0],self._resource_binding(resource)

    def register_candidate(self,handoff=None,provenance=None,technical_review=None,*,account_key,
                           handoff_path=None,provenance_path=None,technical_review_path=None):
        handoff=handoff or ref(handoff_path);provenance=provenance or ref(provenance_path)
        technical_review=technical_review or ref(technical_review_path)
        if self.account_resolver:binding=self.account_resolver(account_key)
        else:
            from src.operations_accounts.browser_control_runtime import _runtime,binding_version
            context=_runtime().resolve(account_key,require_healthy=False)
            binding=dict(account_uuid=context.account_uuid,account_key=account_key,binding_version=binding_version(context))
        ledger=self._candidates();ledger.ensure_runtime_account(binding,runtime_db=self.accounts.douyin_db)
        return ledger.register_pending(handoff,provenance_ref=provenance,technical_review_ref=technical_review,account_binding=binding)

    def bind_candidate(self,candidate_id,resource,platform_task_id=None,*,promotion_key=None):
        snapshot,row,binding=self._promotion(resource,platform_task_id,promotion_key=promotion_key)
        return self._candidates().bind_promotion(candidate_id,snapshot,row,binding)

    def record_review(self,candidate_id,*,user_statement):
        if not user_statement.strip():raise ValueError('请输入对该实际视频的确认说明')
        ledger=self._candidates();candidate=ledger.get(candidate_id);frozen=json.loads(candidate['frozen_json'])
        handoff=promotion._read(frozen['handoff'])
        review=_record(self.accounts.evidence/'workspace_reviews','REVIEW',dict(schema='fanqie_candidate_user_review/v1',
            media=frozen['media'],decision_source='explicit_user_statement',user_statement=user_statement,
            accepted_for_publication=True,known_findings=handoff.get('known_visual_finding')))
        ledger.record_user_review(candidate_id,review);return review

    def prepare_publish(self,candidate_id,resource,platform_task_id=None,*,promotion_key=None,metadata,user_statement):
        if not user_statement.strip():raise ValueError('请输入对本次发布资料和推广任务的授权说明')
        from dataclasses import asdict
        from src.platform_adapter.models import PublishRequest
        from .fanqie_h3_candidate_v1 import digest
        from .fanqie_promotion_identity_v2 import authorization_subject
        ledger=self._candidates();frozen=json.loads(ledger.get(candidate_id)['frozen_json'])
        ledger.ensure_runtime_account(frozen['account'],runtime_db=self.accounts.douyin_db)
        snapshot,row,binding=self._promotion(resource,platform_task_id,promotion_key=promotion_key)
        # Existing clients can still provide an explicit, caption-only publication.
        # New template requests bind both previewed texts to the selected promotion.
        if 'story_hook' in metadata or 'description' not in metadata or 'comment' in metadata:
            copy=novel_publication_copy(metadata.get('story_hook') or metadata['title'],frozen['book_name'],row['alias'])
            if any(key in metadata and metadata[key]!=value for key,value in copy.items()):
                raise ValueError('书名、推广词或文案已变化，请重新核对发布预览')
            metadata={**metadata,**copy}
        req=PublishRequest(video_path=frozen['media']['path'],title=metadata['title'],description=metadata['description'],
            hashtags=metadata['hashtags'],ai_generated=True,fictional_story=True,extra_metadata={'account_uuid':frozen['account']['account_uuid']})
        authority=dict(candidate_id=candidate_id,media=frozen['media'],
            account_uuid=frozen['account']['account_uuid'],publish_authorized=True,decision_source='explicit_user_statement',
            user_statement=user_statement,metadata_sha256=digest(asdict(req)),
            promotion_subject_sha256=digest(dict(row=authorization_subject(snapshot,row),binding=binding)))
        if snapshot['schema']=='fanqie_promotion_snapshot/v2':authority['schema']='fanqie_publication_authorization/v2'
        if 'comment' in metadata:authority['comment']=metadata['comment']
        auth=_record(self.accounts.evidence/'workspace_authorizations','PUBLISH',authority)
        return ledger.prepare_publish(candidate_id,snapshot=snapshot,row=row,resource_binding=binding,
            metadata=dict(metadata,ai_generated=True,fictional_story=True),authorization_ref=auth)

    def dispatch_publish(self,candidate_id,resource,platform_task_id=None,*,promotion_key=None):
        snapshot,row,binding=self._promotion(resource,platform_task_id,promotion_key=promotion_key)
        ledger=self._candidates();frozen=json.loads(ledger.get(candidate_id)['frozen_json'])
        ledger.ensure_runtime_account(frozen['account'],runtime_db=self.accounts.douyin_db)
        return ledger.dispatch(candidate_id,snapshot=snapshot,row=row,resource_binding=binding,runtime_db=self.accounts.douyin_db)

    def attach_publication(self,candidate_id,command_id,*,metadata_command_id=None):
        kwargs=dict(command_id=command_id,browser_db=self.accounts.db,
            evidence_directory=self.accounts.evidence/'publication_handoffs')
        if metadata_command_id:kwargs['metadata_command_id']=metadata_command_id
        value=self._candidates().attach_publication(candidate_id,**kwargs)
        return _record(self.accounts.evidence/'publication_handoffs','HANDOFF',value)

    def recover_publish_receipt(self,candidate_id):
        return self._candidates().recover_dispatch_receipt(candidate_id,browser_db=self.accounts.db)

    def request_publication_metadata(self,candidate_id):
        return self._candidates().request_publication_metadata(candidate_id,browser_db=self.accounts.db)

    def prepare_backfill(self,publication_handoff,resource,official_template,output_directory):
        from .fanqie_backfill_coordinator import prepare_registered_backfill
        return prepare_registered_backfill(self._backfill(),self.accounts.db,publication_handoff_binding=publication_handoff,
            accounts=self.accounts,resource_id=resource,promotion_snapshot_binding=self.latest_snapshot(resource),
            official_template=official_template,output_directory=output_directory)

    def authorize_backfill(self,binding_uuid,*,manifest_sha256,user_statement):
        if not user_statement.strip():raise ValueError('请输入对应回填资料的确认说明')
        return self._backfill().authorize(binding_uuid,manifest_sha=manifest_sha256,reference=user_statement)

    def dispatch_backfill(self,binding_uuid):
        ledger=self._backfill();ledger.enqueue(binding_uuid)
        command=ledger.dispatch(binding_uuid,BrowserControlStore(self.accounts.db))
        if isinstance(command,str):command=BrowserControlStore(self.accounts.db).get(command)
        return dict(command=command,launch=self.launcher(command,self.accounts) if command['state']=='queued' else None)

    def reconcile_backfill(self,resource,binding_uuid,manifest_sha256):
        return self._queue(resource,'fanqie_backfill_reconcile',binding_uuid=binding_uuid,manifest_sha256=manifest_sha256)

    def backfill_status(self,binding_uuid):
        from .fanqie_backfill_coordinator import BackfillCoordinator
        value=BackfillCoordinator(self._backfill(),self.accounts.db,require_strict_contract=True).inspect(binding_uuid)
        return dict(value,business_status=value['status'])
