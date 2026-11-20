"""Real actor/runtime-resource/browser combination with loopback-only handlers.

The admission and account identity are explicitly local fixtures. This does not
exercise or bypass a production account gate and never invokes a platform task.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore
from src.operations_accounts import browser_control_runtime as bridge
from src.platform_adapter.browser_session import BrowserSession, Page
from src.platform_adapter.models import BrowserSessionConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root")
    args = parser.parse_args()
    root = Path(args.evidence_root).resolve()
    workspace = Path(__file__).resolve().parents[1]
    if not root.is_relative_to(workspace) or root.exists():
        raise ValueError("evidence_root must be a new workspace directory")
    root.mkdir(parents=True)
    requests, events, admissions = [], [], []
    checks = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body = b'<!doctype html><title>Isolated actor fixture</title><input id="value">'
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:" + str(server.server_port)
    context = SimpleNamespace(account_key="local-fixture", account_uuid="isolated-local-account")
    # Explicit fixture injection: the production resource implementation itself
    # is used; its session builder and real account database are never called.
    resource = bridge.AccountBrowserResource(context, runtime=None, headless=True)
    resource.session = BrowserSession(BrowserSessionConfig(url, url,
        str(root / "fixture_state.json"), str(root / "fresh_profile"),
        headless=True, timeout_ms=15000))
    owner = resource.session
    store = BrowserControlStore(root / "isolated_control.db", owner_ttl=120)
    known = {}
    cursor = {"completed_items": ["local-item-1"], "next_item": "local-item-2"}

    def event(name):
        events.append({"name": name, "thread_id": threading.get_ident()})

    def admission(ctx, phase):
        # No real identity/pause/authorization is claimed by this local policy.
        assert ctx.account_id == context.account_uuid
        assert ctx.binding_version == "isolated-binding-v1"
        assert ctx.resource is resource
        assert Path(owner.config.user_data_dir).is_relative_to(root)
        admissions.append({"task_id": ctx.task_id, "phase": phase})
        return True

    @bridge._with_active
    def publish_fixture(ctx, payload):
        event("publication-start")
        saved = store.get(known["background_id"])
        checks["cursor_durable_before_priority_handler"] = saved["state"] == "paused" and saved["cursor"] == cursor
        borrowed = bridge.borrow_session(context.account_key, headless=True)
        page = Page(borrowed)  # Same construction used by legacy helpers.
        page.goto(url + "/publication-fixture")
        checks["priority_task_same_context_storage"] = page.evaluate(
            "localStorage.getItem('resume_fixture')") == "same-account-context"
        checks["priority_task_same_worker"] = owner._proc.pid == known["worker_pid"]
        checks["priority_task_has_own_tab"] = page.tab_id != known["background_tab"]
        page.locator("#value").fill("publication-fixture-complete")
        known["publication_tab"] = page.tab_id
        borrowed.stop()
        status = owner.window_status()
        checks["borrowed_stop_keeps_owner_and_background"] = (
            owner._proc.pid == known["worker_pid"] and status["open"]
            and any(t["tab_id"] == known["background_tab"] and not t["closed"] for t in status["tabs"]))
        event("publication-end")
        return {"local_fixture_completed": True, "platform_published": False}

    @bridge._with_active
    def background_fixture(ctx, payload):
        event("background-start")
        borrowed = bridge.borrow_session(context.account_key, headless=True)
        page = Page(borrowed)
        page.goto(url + "/background-fixture")
        locator = page.locator("#value").first()
        locator.fill("background-item-1")
        page.evaluate("localStorage.setItem('resume_fixture','same-account-context')")
        known.update(worker_pid=owner._proc.pid, background_tab=page.tab_id)
        queued = store.submit(context.account_uuid, "isolated-binding-v1", "publish",
            "one-local-priority-fixture", {"local_fixture_only": True}, priority=100)
        known["publication_id"] = queued["command_id"]
        event("background-checkpoint")
        bridge.background_safe_point(cursor)
        event("background-resumed")
        checks["priority_succeeded_before_resume"] = store.get(known["publication_id"])["state"] == "succeeded"
        checks["resume_uses_original_locator_state"] = locator.evaluate("e => e.value") == "background-item-1"
        locator.fill("background-item-2")
        checks["resumed_original_locator_writes_original_tab"] = page.evaluate(
            "document.querySelector('#value').value") == "background-item-2"
        checks["resume_same_worker_and_page"] = owner._proc.pid == known["worker_pid"] and page.tab_id == known["background_tab"]
        borrowed.stop()
        checks["all_borrowers_returned_owner_alive"] = owner.window_status()["open"]
        event("background-end")
        return {"completed_items": ["local-item-1", "local-item-2"], "resumed_from": cursor}

    actor = BrowserControlActor(store, context.account_uuid, "isolated-binding-v1", "isolated-owner",
        {"background": background_fixture, "publish": publish_fixture}, admission=admission,
        context=resource, heartbeat_seconds=20)
    evidence = {"schema": "browser_control_local_combination_acceptance/v1", "checks": checks,
        "events": events, "admissions": admissions, "known": known,
        "production_admission_used": False, "admission_is_explicit_fixture": True,
        "production_account_or_profile_used": False, "actual_platform_visited": False,
        "actual_upload_publish_comment": False, "real_components": ["BrowserControlStore",
            "BrowserControlActor", "AccountBrowserResource", "BorrowedSession", "BrowserSession", "Playwright Chrome worker"]}
    started = False
    try:
        command = store.submit(context.account_uuid, "isolated-binding-v1", "background",
            "one-background-fixture", {"local_fixture_only": True}, priority=0)
        known["background_id"] = command["command_id"]
        actor.start()
        started = True
        result = actor.run_next()
        evidence["background_result"] = result
        evidence["snapshot"] = store.snapshot(context.account_uuid)
        checks["both_commands_succeeded_once"] = (result["state"] == "succeeded" and
            len(evidence["snapshot"]["commands"]) == 2 and
            all(c["state"] == "succeeded" for c in evidence["snapshot"]["commands"]))
        checks["saved_cursor_preserved_after_completion"] = result["cursor"] == cursor
        checks["serial_background_priority_resume_order"] = [e["name"] for e in events] == [
            "background-start", "background-checkpoint", "publication-start", "publication-end",
            "background-resumed", "background-end"]
        checks["one_handler_thread"] = len({e["thread_id"] for e in events}) == 1
        checks["admission_rechecked_before_resume_and_io"] = (
            any(a["phase"] == "resume" for a in admissions)
            and any(a["phase"] == "dispatch" for a in admissions))
        evidence["passed"] = bool(checks) and all(checks.values())
        if not evidence["passed"]:
            raise AssertionError("combined local browser control acceptance failed")
        actor.close()
        started = False
    except Exception as exc:
        evidence["passed"] = False
        evidence["error_type"] = type(exc).__name__
        raise
    finally:
        if started:
            actor.stop_heartbeat()  # Unknown is retained; no implicit re-dispatch.
        resource.shutdown()
        server.shutdown()
        evidence["requests"] = requests
        (root / "RESULT.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "checks": len(checks), "evidence": str(root / "RESULT.json")}))


if __name__ == "__main__":
    main()
