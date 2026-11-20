"""Isolated BrowserSession acceptance: loopback only, fresh profile, no account.

Run using project Python, passing a new workspace directory for the evidence.
It intentionally does not visit platform pages or read production profiles.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.platform_adapter.browser_session import BrowserSession, Page
from src.platform_adapter.models import BrowserSessionConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root")
    args = parser.parse_args()
    root = Path(args.evidence_root).resolve()
    workspace = Path(__file__).resolve().parents[1]
    if not root.is_relative_to(workspace) or root.exists():
        raise ValueError("evidence_root must be a new directory inside this workspace")
    root.mkdir(parents=True)
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            payload = b'<!doctype html><title>Local tab fixture</title><input id="value"><p>local fixture</p>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:" + str(server.server_port)

    def make_session(name):
        return BrowserSession(BrowserSessionConfig(base_url=url, home_url=url,
            storage_state_path=str(root / name / "state.json"),
            user_data_dir=str(root / name / "profile"), headless=True, timeout_ms=15000))

    owner = make_session("isolated_owner")
    other = make_session("separate_account_fixture")
    evidence = {"schema": "browser_session_local_tabs_acceptance/v1", "checks": {},
        "platform_visited": False, "production_profile_used": False,
        "debug_port_enabled": False, "fresh_profiles": True}
    checks = evidence["checks"]
    try:
        original = owner.open_page(url + "/background")
        pid = owner._proc.pid
        retained = original.locator("#value").first()
        retained.fill("background-before")
        original.evaluate("localStorage.setItem('fixture_shared', 'same-context')")
        publication = owner.new_tab("publication")
        publication.goto(url + "/publication?secret=fixture#hidden")
        checks["same_worker_pid"] = owner._proc.pid == pid
        checks["distinct_fixed_tab_ids"] = original.tab_id != publication.tab_id
        checks["same_context_local_storage"] = publication.evaluate(
            "localStorage.getItem('fixture_shared')") == "same-context"
        publication.locator("#value").fill("publication-value")
        retained.fill("background-resumed")
        checks["original_locator_retained_target"] = original.locator("#value").evaluate(
            "e => e.value") == "background-resumed"
        checks["publication_unchanged_after_resume"] = publication.locator("#value").evaluate(
            "e => e.value") == "publication-value"
        borrowed = SimpleNamespace(tab_id=publication.tab_id,
            _default_tab_id=original.tab_id, cmd=owner.cmd)
        borrowed_page = Page(borrowed)
        borrowed_page.locator("#value").fill("borrowed-publication")
        checks["legacy_page_helper_uses_borrowed_tab"] = (
            borrowed_page.evaluate("document.querySelector('#value').value") == "borrowed-publication"
            and original.locator("#value").evaluate("e => e.value") == "background-resumed")
        checks["default_tab_unchanged"] = owner.get_page().tab_id == original.tab_id
        tabs = owner.list_tabs()
        checks["status_url_redacted"] = all("secret" not in item["url"] and "hidden" not in item["url"] for item in tabs)
        started = time.monotonic()
        status = owner.window_status()
        evidence["status_rpc_seconds"] = time.monotonic() - started
        checks["short_poll_keeps_manual_page_open"] = status["open"] and status["tab_count"] == 2
        stranger = other.open_page(url + "/other")
        checks["separate_context_isolated"] = stranger.evaluate("localStorage.getItem('fixture_shared')") is None
        try:
            Page(other, tab_id=original.tab_id).evaluate("document.title")
        except RuntimeError:
            checks["cross_owner_handle_rejected"] = True
        else:
            checks["cross_owner_handle_rejected"] = False
        owner.close_tab(publication.tab_id)
        checks["close_one_keeps_background"] = owner.window_status()["tab_count"] == 1 and original.locator("#value").evaluate("e => e.value") == "background-resumed"
        try:
            publication.locator("#value").fill("must-not-write")
        except RuntimeError:
            checks["closed_handle_does_not_fall_back"] = True
        else:
            checks["closed_handle_does_not_fall_back"] = False
        owner.close_tab(original.tab_id)
        closed = owner.window_status()
        checks["closed_status_observed"] = closed["closed"] and closed["tab_count"] == 0
        evidence["worker_pid"] = pid
        evidence["tabs_before_close"] = tabs
        evidence["closed_status"] = closed
        evidence["requests"] = requests
        evidence["passed"] = all(checks.values())
    except Exception as exc:
        evidence["passed"] = False
        evidence["error_type"] = type(exc).__name__
        raise
    finally:
        owner.stop()
        other.stop()
        server.shutdown()
        evidence["requests"] = requests
        (root / "RESULT.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if not evidence["passed"]:
        raise AssertionError("local browser tab acceptance failed")
    print(json.dumps({"passed": True, "checks": len(checks), "evidence": str(root / "RESULT.json")}))


if __name__ == "__main__":
    main()
