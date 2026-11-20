"""Keep the bound account's search page open for human login/challenge only."""
from pathlib import Path
import json
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.operations_accounts import AccountRuntimeService

JOB_ROOT = PROJECT / "data/production_trials/fresh_legal_full_flow_20261012/round_01"
ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else JOB_ROOT
if ROOT != JOB_ROOT and not ROOT.is_relative_to(JOB_ROOT):
    raise ValueError("verification window records must stay within the current job")


def write(name, value, *, exclusive=False):
    with (ROOT / name).open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    write("HUMAN_VERIFICATION_BROWSER_CLAIM.json", {"at_utc": datetime.now(timezone.utc).isoformat(),
        "account_key": "account01", "purpose": "human search verification only", "collection_allowed": False,
        "model_dispatch_allowed": False, "automatic_restart": False}, exclusive=True)
    service = AccountRuntimeService()
    context = service.resolve("account01")
    with service.operation_lease(context, operation="human_fresh_legal_verification", daily_limit=90,
                                 cooldown_seconds=0, lock_seconds=4200):
        session = context.create_browser_session(headless=False)
        try:
            page = session.open_page("https://www.douyin.com/search/" + quote("劳动争议") + "?type=video")
            write("HUMAN_VERIFICATION_BROWSER_STATE.json", {"status": "page_loaded_waiting_visibility_confirmation",
                "visible_window_confirmed": None, "verification_passed": None,
                "account_key": context.account_key, "expected_public_id": context.binding.public_uid,
                "profile_version": context.profile.profile_version, "url": page.url,
                "new_collection_requests": 0, "new_model_calls": 0})
            deadline = time.monotonic() + 3600
            while not (ROOT / "HUMAN_VERIFICATION_BROWSER_CLOSE.json").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("human verification window expired; no collection resumed")
                session.save_storage_state()
                time.sleep(15)
            session.save_storage_state()
            write("HUMAN_VERIFICATION_BROWSER_STATE.json", {"status": "closed_after_operator_marker",
                "verification_passed": None, "new_collection_requests": 0, "new_model_calls": 0})
        finally:
            session.stop()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        write("HUMAN_VERIFICATION_BROWSER_STATE.json", {"status": "stopped", "exception_type": type(error).__name__,
            "verification_passed": None, "collection_resumed": False})
        raise
