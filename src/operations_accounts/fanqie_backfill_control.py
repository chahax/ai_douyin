"""Opt-in command handler for a separately bound managed Fanqie resource.

Not registered on the Douyin pump. Installation requires the Fanqie resource
provider and stable identity probe; no fallback to a global cached browser.
"""
import json
from pathlib import Path
import sqlite3

from .browser_control import BrowserCommandResult, BrowserControlRejected


class ManagedFanqieGuard:
    def __init__(self, ctx, bindings, ledger, identity_probe, *, accounts=None, environment=None):
        self.ctx, self.bindings, self.ledger, self.identity_probe = ctx, bindings, ledger, identity_probe
        self.accounts, self.environment = accounts, environment

    def check(self, contract):
        ctx = self.ctx
        command = ctx.actor.store.get(ctx.task_id)
        if (not command or command["state"] != "running" or command["kind"] not in {'fanqie_backfill', 'fanqie_backfill_reconcile'}
                or command["owner_id"] != ctx.actor.owner_id or command["generation"] != ctx.actor.generation):
            raise BrowserControlRejected("fanqie_command_fenced", "Original managed Fanqie command required")
        payload = command["payload"]
        row = self.ledger.get(payload["binding_uuid"])
        key = 'fanqie-backfill:' + row['business_key']
        key_ok = command['idempotency_key'] == key if command['kind'] == 'fanqie_backfill' else (
            command['idempotency_key'].startswith('fanqie-backfill-reconcile:' + row['business_key'] + ':')
            and bool(command['idempotency_key'].rsplit(':', 1)[-1]))
        if command['kind']=='fanqie_backfill' and 'preupload_resume' in payload:
            from .fanqie_preupload_resume_v1 import validate_managed_resume
            key_ok=validate_managed_resume(self.ledger,ctx.actor.store,command,contract)
        if (json.loads(row["contract_json"]) != contract or row["manifest_sha"] != payload["manifest_sha256"]
                or command["account_id"] != contract["fanqie_resource_id"]
                or command["binding_version"] != contract["fanqie_binding_version"]
                or not key_ok):
            raise BrowserControlRejected("fanqie_contract_changed", "Original business intent differs")
        if self.accounts is not None:
            env = self.accounts.get(command['account_id'])
            if env != self.environment or contract.get('schema') not in {
                    'fanqie_backfill_contract/v2', 'fanqie_backfill_contract/v3'}:
                raise BrowserControlRejected('fanqie_environment_changed', 'Original dedicated resource differs')
            linked = self.accounts.check_association(env)
            if (contract.get('account_link_version') != env['douyin_binding_sha256']
                    or contract.get('douyin_account_uuid') != linked['account_uuid']
                    or contract.get('douyin_account_key') != linked['account_key']):
                raise BrowserControlRejected('linked_douyin_identity_changed', 'Publication is not owned by this linked account')
        identity = self.identity_probe()
        bound = self.bindings.guard(command["account_id"], command["binding_version"],
            ctx.actor.owner_id, ctx.actor.generation, identity)
        manifest = json.loads(row["manifest_json"])
        if manifest["binding"]["fanqie_account"] != bound["platform_identity_key"]:
            raise BrowserControlRejected("fanqie_account_mismatch", "Backfill account differs from bound identity")


def make_backfill_handler(coordinator, bindings, adapter_factory, probe_factory, *, accounts=None, environment=None):
    """Resource owner supplies adapter/probe for its existing task tab only."""
    def handler(ctx, payload):
        guard = ManagedFanqieGuard(ctx, bindings, coordinator.ledger, probe_factory(ctx),
                                  accounts=accounts, environment=environment)
        row = coordinator.ledger.get(payload["binding_uuid"])
        guard.check(json.loads(row["contract_json"]))
        command = ctx.actor.store.get(ctx.task_id)
        readonly = command['kind'] == 'fanqie_backfill_reconcile'
        method = coordinator.reconcile if readonly else coordinator.execute
        result = method(payload["binding_uuid"], adapter=adapter_factory(ctx), guard=guard)
        business_unknown = False
        if accounts is not None and result['status'] == 'outcome_unknown':
            # Only a completed, still-owned versioned handler may end its command while
            # the separate durable business intent stays unknown. Hard crashes
            # never reach here; lost owners fail this check and retain their lock.
            guard.check(json.loads(row['contract_json']))
            persisted = coordinator.ledger.get(payload['binding_uuid'])
            if (persisted.get('binding_uuid') != payload['binding_uuid']
                    or persisted.get('status') != 'outcome_unknown'
                    or persisted.get('revision') != result.get('revision')
                    or persisted.get('manifest_sha') != payload['manifest_sha256']):
                raise BrowserControlRejected('backfill_unknown_receipt_changed', 'Original business unknown was not persisted')
            business_unknown = True
        state = 'succeeded' if readonly or business_unknown else {"confirmed": "succeeded", "failed_known": "failed",
                 "verify_pending": "succeeded"}.get(result["status"], "outcome_unknown")
        # succeeded + verify_pending means this command ended, not business completion.
        return BrowserCommandResult(state, {"binding_uuid": payload["binding_uuid"],
            "backfill_status": result["status"], "confirmed": result["status"] == "confirmed",
            "batch_id": result.get("batch_id"), 'read_only_reconciliation': readonly,
            'requires_read_only_reconciliation': result['status'] in {'outcome_unknown', 'accepted', 'verify_pending', 'upload_started', 'uploaded', 'submit_started'},
            'business_claim': {k: result.get(k) for k in
                ('binding_uuid', 'business_key', 'manifest_sha', 'revision', 'attempt_count', 'status')},
            'command_finished_does_not_confirm_backfill': result['status'] != 'confirmed'})
    return handler


def build_managed_backfill_handlers(accounts, env, *, page_provider, probe_provider, ledger_path=None,
                                    native_snapshot_provider=None):
    """Lazy handlers for the existing dedicated owner; no startup/migration here.

    Providers are application-owned closures, never module names in a payload.
    A missing ledger/schema blocks only the backfill command, never login.
    """
    def handler(ctx, payload):
        from src.services.fanqie_promotion_ledger import PromotionLedger
        from src.services.fanqie_backfill_coordinator import BackfillCoordinator
        from src.services.fanqie_review_service import CLOSED_LOOP_DB_PATH
        from src.platform_adapter.fanqie_backfill import FanqieBatchPageAdapter, PROMOTION_LIST_URL
        from src.services.fanqie_backfill_workflow import BackfillBlocked
        if (not isinstance(payload, dict) or not isinstance(payload.get('binding_uuid'), str)
                or not isinstance(payload.get('manifest_sha256'), str)):
            raise BrowserControlRejected('backfill_payload_required', 'Original binding and manifest digest required')
        try:
            ledger = PromotionLedger(ledger_path or CLOSED_LOOP_DB_PATH)
            coordinator = BackfillCoordinator(ledger, accounts.db, require_strict_contract=True)
            # Validate publication/media/task before opening or navigating a task tab.
            _registered, _manifest, _binding, contract = coordinator._inputs(payload['binding_uuid'])
            if contract.get('schema') == 'fanqie_backfill_contract/v3' and not callable(native_snapshot_provider):
                raise BackfillBlocked('capability_missing:managed_native_snapshot_provider_required')
        except (BackfillBlocked, sqlite3.Error, KeyError, ValueError) as error:
            return BrowserCommandResult('failed', dict(confirmed=False, backfill_completed=False,
                reason=str(error), status='backfill_preflight_blocked', external_write_started=False))

        def adapter_factory(current):
            page = page_provider(current, PROMOTION_LIST_URL)
            def identity(_page):
                value = probe_provider(current)
                return dict(account=value.get('platform_identity_key'), verified=value.get('verified'),
                            challenge=value.get('challenge'), observed_at=value.get('observed_at'))
            base = FanqieBatchPageAdapter(page, identity_probe=identity, require_fresh_identity=True)
            if contract.get('schema') == 'fanqie_backfill_contract/v3':
                from src.services.fanqie_backfill_native_v3 import NativeSnapshotAdapter
                return NativeSnapshotAdapter(base,
                    lambda **kwargs: native_snapshot_provider(current, **kwargs),
                    readonly=current.command['kind'] == 'fanqie_backfill_reconcile')
            return base

        wrapped = make_backfill_handler(coordinator, accounts.bindings(), adapter_factory,
            lambda current: lambda: probe_provider(current), accounts=accounts, environment=env)
        try:
            return wrapped(ctx, payload)
        except BackfillBlocked as error:
            # This branch is before any uncertain operation or a guarded known
            # rejection. The coordinator records post-upload failures itself.
            return BrowserCommandResult('failed', dict(confirmed=False, reason=str(error),
                capability_missing=str(error).startswith('capability_missing:'),
                binding_uuid=payload['binding_uuid'], backfill_completed=False))
    return {'fanqie_backfill': handler, 'fanqie_backfill_reconcile': handler}
