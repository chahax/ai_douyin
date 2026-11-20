"""Single fresh metadata collection with live bound-identity check, no models/media.

Created for the user's 2026-10-12 background full-script test. A stored plan is
only a related-search seed; all creative observations must come from this run.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.operations_accounts import AccountRuntimeService

USER_QUOTE = "可以测试剧本完整流程了可以再次获取下平台信息了再后台运行"


class IdentityFailed(RuntimeError):
    pass


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def main():
    root, plan = [Path(p).resolve() for p in sys.argv[1:3]]
    if not root.is_relative_to(PROJECT / "data/production_trials") or root == PROJECT / "data/production_trials":
        raise ValueError("fresh collection must use an independent trial directory")
    root.mkdir(parents=True, exist_ok=True)
    # Create before identity/network work. Restart never repeats this collection.
    save(root / "COLLECTION_CLAIM.json", {"at_utc": datetime.now(timezone.utc).isoformat(),
        "user_quote": USER_QUOTE, "user_clarification": "是，采集法律号新数据后跑完整流程",
        "account_key": "account01", "plan_path": str(plan),
        "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "historical_plan_is_search_seed_only": True, "metadata_only": True,
        "no_model_calls": True, "no_media_calls": True, "automatic_retry": False})
    try:
        service = AccountRuntimeService()
        context = service.resolve("account01")
        with service.operation_lease(context, operation="fresh_legal_identity_check",
                                     daily_limit=90, cooldown_seconds=0):
            session = context.create_browser_session(headless=True)
            try:
                checked = service.verify_identity(context, session=session)
            finally:
                session.stop()
            identity = {"healthy": checked.healthy, "status": checked.status,
                "account_key": context.account_key, "profile_version": context.profile.profile_version,
                "expected_public_id": context.binding.public_uid,
                "actual_public_id": checked.actual.public_uid if checked.actual else None,
                "at_utc": datetime.now(timezone.utc).isoformat()}
            save(root / "LIVE_IDENTITY_CHECK.json", identity)
            if not checked.healthy:
                # A failed identity check must not make the account lease count
                # a successful operation or clear its real failure history.
                raise IdentityFailed(checked.status)
        completed = subprocess.run([sys.executable, "scripts/run_account_video_research.py",
            "--account-id", "account01", "--legal-core-plan", str(plan), "--headless",
            "--max-content-candidates", "60", "--authorization-reference",
            "用户2026-10-12明确授权采集法律号新数据后后台测试完整剧本流程"],
            cwd=PROJECT, capture_output=True, text=True, encoding="utf-8")
        (root / "COLLECTION.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (root / "COLLECTION.stderr.log").write_text(completed.stderr, encoding="utf-8")
        payload = json.loads(completed.stdout)
        save(root / "COLLECTION_RESULT.json", {"status": payload.get("status"),
            "exit_code": completed.returncode, "result": payload, "new_model_calls": 0,
            "new_media_calls": 0, "original_request_redispatched": False})
        print(json.dumps({"root": str(root), "status": payload.get("status"),
            "collection_run_id": payload.get("collection_run_id"),
            "sample_gate": payload.get("sample_gate"), "new_model_calls": 0}, ensure_ascii=False))
        return completed.returncode
    except IdentityFailed as exc:
        save(root / "COLLECTION_RESULT.json", {"status": "human_required", "reason": str(exc),
            "identity": identity, "new_model_calls": 0, "collection_submitted": False})
        return 1
    except Exception as exc:
        # Provider/session exceptions can contain private URL fields. Report the
        # type, retain original collector stdout separately, and never retry.
        path = root / "COLLECTION_RESULT.json"
        if not path.exists():
            save(path, {"status": "stopped_exception", "exception_type": type(exc).__name__,
                "new_model_calls": 0, "automatic_retry": False})
        print(json.dumps({"status": "stopped_exception", "exception_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
