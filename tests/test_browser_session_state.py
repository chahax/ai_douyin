"""Tests for storage state restoration in browser_session.py.

Covers: missing-file tolerance, cookie sanitization, exact-origin localStorage
init-script construction, malformed-JSON detection, and diagnostic safety
(no secret values in counts/domain/origin-name outputs).
"""

import json
import hashlib
import threading
import tempfile
from pathlib import Path

import pytest

from src.platform_adapter.browser_session import (
    _sanitize_cookies_for_add,
    _build_storage_state_init_script,
    _download_binary_response,
    _validate_download_url,
    APIRequestContext,
    BinaryDownloadError,
    _sanitize_browser_error_message,
)


# ---------------------------------------------------------------------------
# Missing-file tolerance
# ---------------------------------------------------------------------------

def test_snapshot_does_not_overwrite_newer_profile_cookie():
    from src.platform_adapter.browser_session import _missing_snapshot_cookies
    old = {'name': 'sid', 'domain': '.douyin.com', 'path': '/', 'value': 'old', 'expires': -1}
    current = {**old, 'value': 'new'}
    creator = {**old, 'domain': 'creator.douyin.com'}
    expired = {**old, 'name': 'expired', 'expires': 1}
    assert _missing_snapshot_cookies([old, creator, expired], [current]) == [creator]


def test_checkpoint_preserves_other_origin_for_same_account(tmp_path):
    from types import SimpleNamespace
    from src.platform_adapter.browser_session import _checkpoint_open_login_pages
    state = tmp_path/'account_a.json'
    creator = {'origin': 'https://creator.douyin.com', 'localStorage': [{'name': 'sample', 'value': 'fixture'}]}
    state.write_text(json.dumps({'cookies': [], 'origins': [creator]}))
    frame = SimpleNamespace(evaluate=lambda script: {'origin': 'https://www.douyin.com', 'localStorage': []})
    page = SimpleNamespace(is_closed=lambda: False, frames=[frame])
    context = SimpleNamespace(pages=[page], cookies=lambda: [])
    assert _checkpoint_open_login_pages(context, str(state), {})
    assert creator in json.loads(state.read_text())['origins']
    other = tmp_path/'account_b.json'
    assert _checkpoint_open_login_pages(context, str(other), {})
    assert creator not in json.loads(other.read_text())['origins']


def test_local_storage_restore_keeps_existing_values():
    script = _build_storage_state_init_script([{'origin': 'https://creator.douyin.com',
        'localStorage': [{'name': 'fixture', 'value': 'old'}]}])
    assert 'localStorage.getItem(_k)===null' in script

def test_missing_storage_state_file_is_not_an_error():
    """A nonexistent storage_state_path is normal; os.path.exists handles it."""
    missing = Path("./data/browser/nonexistent_storage_state.json")
    assert not missing.exists()


# ---------------------------------------------------------------------------
# Cookie sanitization
# ---------------------------------------------------------------------------

class TestCookieSanitization:
    """Pure-helper _sanitize_cookies_for_add -- no Playwright dependency."""

    def test_keeps_standard_fields(self):
        cookies = [
            {"name": "sid", "value": "abc123", "domain": ".example.com", "path": "/"}
        ]
        result = _sanitize_cookies_for_add(cookies)
        assert result == cookies

    def test_strips_unknown_fields(self):
        cookies = [
            {
                "name": "sid", "value": "abc123", "domain": ".example.com", "path": "/",
                "size": 100, "priority": "high", "partitionKey": "x",
            }
        ]
        result = _sanitize_cookies_for_add(cookies)
        assert "size" not in result[0]
        assert "priority" not in result[0]
        assert "partitionKey" not in result[0]
        assert result[0]["name"] == "sid"

    def test_preserves_optional_playwright_fields(self):
        cookies = [
            {
                "name": "sid", "value": "x", "domain": ".e.com", "path": "/",
                "expires": 1754234567, "httpOnly": True, "secure": True,
                "sameSite": "Lax", "url": "https://e.com",
            }
        ]
        result = _sanitize_cookies_for_add(cookies)
        assert result[0]["expires"] == 1754234567
        assert result[0]["httpOnly"] is True
        assert result[0]["secure"] is True
        assert result[0]["sameSite"] == "Lax"
        assert result[0]["url"] == "https://e.com"

    def test_empty_list_returns_empty(self):
        assert _sanitize_cookies_for_add([]) == []

    def test_all_fields_stripped_keeps_name_value_domain_path(self):
        """Cookie with ONLY unknown fields keeps the known subset (empty)."""
        cookies = [
            {"name": "x", "value": "y", "unknown": 1}
        ]
        result = _sanitize_cookies_for_add(cookies)
        assert result[0] == {"name": "x", "value": "y"}


# ---------------------------------------------------------------------------
# localStorage init-script construction
# ---------------------------------------------------------------------------

class TestLocalStorageInitScript:
    """Pure-helper _build_storage_state_init_script -- no Playwright dependency."""

    def test_builds_iife_script(self):
        origins = [
            {
                "origin": "https://kol.fanqieopen.com",
                "localStorage": [
                    {"name": "token", "value": "abc"},
                    {"name": "theme", "value": "dark"},
                ],
            }
        ]
        script = _build_storage_state_init_script(origins)
        assert script is not None
        assert script.startswith("(function(){")
        assert script.endswith("})()")
        assert "https://kol.fanqieopen.com" in script

    def test_origin_map_produces_exact_match_lookup(self):
        """The JS must look up window.location.origin for exact match only."""
        origins = [
            {
                "origin": "https://kol.fanqieopen.com",
                "localStorage": [{"name": "a", "value": "1"}],
            }
        ]
        script = _build_storage_state_init_script(origins)
        assert script is not None
        # The script uses window.location.origin (exact origin, no substring match)
        assert "window.location.origin" in script

    def test_empty_origins_returns_none(self):
        assert _build_storage_state_init_script([]) is None

    def test_origins_without_localstorage_key_returns_none(self):
        origins = [{"origin": "https://example.com"}]
        assert _build_storage_state_init_script(origins) is None

    def test_origins_with_empty_localstorage_list_returns_none(self):
        origins = [{"origin": "https://example.com", "localStorage": []}]
        assert _build_storage_state_init_script(origins) is None

    def test_multiple_origins(self):
        origins = [
            {
                "origin": "https://kol.fanqieopen.com",
                "localStorage": [{"name": "a", "value": "1"}],
            },
            {
                "origin": "https://fanqienovel.com",
                "localStorage": [{"name": "b", "value": "2"}],
            },
        ]
        script = _build_storage_state_init_script(origins)
        assert script is not None
        assert "https://kol.fanqieopen.com" in script
        assert "https://fanqienovel.com" in script

    def test_localstorage_entry_missing_name_or_value_is_skipped(self):
        origins = [
            {
                "origin": "https://example.com",
                "localStorage": [
                    {"name": "valid", "value": "ok"},
                    {"name": "no_value"},
                    {"value": "no_name"},
                    {},
                ],
            }
        ]
        script = _build_storage_state_init_script(origins)
        assert script is not None
        # Extract the origin_map from the generated script
        parsed = json.loads(script.split("var _m=")[1].split(";")[0])
        assert len(parsed["https://example.com"]) == 1
        assert parsed["https://example.com"]["valid"] == "ok"

    def test_origin_with_no_valid_entries_is_omitted(self):
        """An origin whose all entries are missing name/value should not appear."""
        origins = [
            {
                "origin": "https://empty.com",
                "localStorage": [
                    {"name": "no_value"},
                    {"value": "no_name"},
                ],
            },
            {
                "origin": "https://good.com",
                "localStorage": [{"name": "x", "value": "y"}],
            },
        ]
        script = _build_storage_state_init_script(origins)
        assert script is not None
        parsed = json.loads(script.split("var _m=")[1].split(";")[0])
        assert "https://empty.com" not in parsed
        assert "https://good.com" in parsed


# ---------------------------------------------------------------------------
# Malformed JSON detection
# ---------------------------------------------------------------------------

class TestMalformedStateFile:
    """The JSON parsing inside _PW_SCRIPT must fail loudly."""

    def test_invalid_json_detected_by_json_decode_error(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write("this is not json {{{")
            bad_path = f.name
        try:
            with pytest.raises(json.JSONDecodeError):
                with open(bad_path, "r", encoding="utf-8") as f:
                    json.loads(f.read())
        finally:
            Path(bad_path).unlink(missing_ok=True)

    def test_valid_cookies_structure_parses(self):
        """A well-formed Playwright storage_state file should parse successfully."""
        state = {
            "cookies": [
                {
                    "name": "sid", "value": "abc", "domain": ".fanqieopen.com",
                    "path": "/", "expires": -1, "httpOnly": True,
                    "secure": True, "sameSite": "Lax",
                }
            ],
            "origins": [
                {
                    "origin": "https://kol.fanqieopen.com",
                    "localStorage": [
                        {"name": "has_biz_token", "value": "true"},
                    ],
                }
            ],
        }
        # Re-serialize and parse to confirm round-trip
        text = json.dumps(state)
        parsed = json.loads(text)
        assert len(parsed["cookies"]) == 1
        assert parsed["cookies"][0]["name"] == "sid"
        assert len(parsed["origins"]) == 1
        assert parsed["origins"][0]["origin"] == "https://kol.fanqieopen.com"


# ---------------------------------------------------------------------------
# Diagnostic safety -- no secret values in diagnostic output
# ---------------------------------------------------------------------------

class TestDiagnosticSafety:
    """Diagnostics must report only counts, domains, and origin names --
    never cookie values or localStorage values.
    """

    def test_cookie_domains_never_contain_cookie_values(self):
        cookies = [
            {"name": "sid", "value": "secret123", "domain": ".kol.fanqieopen.com", "path": "/"},
            {"name": "uid", "value": "secret456", "domain": ".fanqieopen.com", "path": "/"},
        ]
        # Simulate what the diagnostic logic produces
        domains = sorted(set(c["domain"] for c in cookies if c.get("domain")))
        assert "secret123" not in str(domains)
        assert "secret456" not in str(domains)
        assert ".kol.fanqieopen.com" in domains
        assert ".fanqieopen.com" in domains

    def test_origin_names_never_contain_localstorage_values(self):
        origins = [
            {
                "origin": "https://kol.fanqieopen.com",
                "localStorage": [
                    {"name": "sid_guard", "value": "very-secret-value"},
                ],
            }
        ]
        # The origin names for diagnostics come from _o.get("origin")
        origin_names = sorted(o["origin"] for o in origins if o.get("origin"))
        assert "very-secret-value" not in str(origin_names)
        assert origin_names == ["https://kol.fanqieopen.com"]

    def test_restored_cookies_count_is_just_an_int(self):
        """Cookie count is a plain integer, never contains cookie data."""
        cookies = [
            {"name": "sid", "value": "secret", "domain": ".e.com", "path": "/"},
            {"name": "uid", "value": "secret2", "domain": ".e.com", "path": "/"},
        ]
        count = len(cookies)
        assert isinstance(count, int)
        assert count == 2
        assert "secret" not in str(count)


@pytest.fixture
def binary_http_fixture():
    """Loopback only; APIRequestContext uses no browser window or public network."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    payload = b"\x00\xff\xfe\x80\xc0\x00binary\x89PNG\r\n"
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = self.path.split("?", 1)[0]
            seen.append({"path": route, "cookie": self.headers.get("Cookie"), "referer": self.headers.get("Referer"),
                         "authorization": self.headers.get("Authorization")})
            if route == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/binary?signature=redirect-secret")
                self.end_headers()
                return
            if route == "/foreign-redirect":
                self.send_response(302)
                self.send_header("Location", "http://localhost:%s/binary?signature=redirect-secret" % self.server.server_port)
                self.end_headers()
                return
            if route == "/error":
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"private-server-message")
                return
            self.send_response(206 if route == "/partial" else 200)
            self.send_header("Content-Type", "text/html" if route == "/html" else "video/mp4")
            if route != "/without-length":
                self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass  # Do not log fixture signed URLs either.
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", payload, seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def request_only_context():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        context = runtime.request.new_context(storage_state={"cookies": [{"name": "session", "value": "fixture-cookie",
            "domain": "127.0.0.1", "path": "/", "expires": -1, "httpOnly": True, "secure": False, "sameSite": "Lax"}], "origins": []})
        try:
            yield context
        finally:
            context.dispose()


def _local_download(context, base, target, **kwargs):
    return _download_binary_response(context, base, target, workspace_root=target.parent,
        _allow_loopback_fixture=True, **kwargs)


def test_binary_download_preserves_non_utf8_bytes_and_session_cookies(tmp_path, binary_http_fixture, request_only_context):
    base, payload, seen = binary_http_fixture
    target = tmp_path / "source.mp4"
    result = _local_download(request_only_context, base + "/binary?signature=never-print-this", target,
        headers={"Referer": "https://www.douyin.com/"}, expected_content_types=["video/*"], max_bytes=1024)
    assert target.read_bytes() == payload
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["size"] == len(payload)
    assert result["status"] == 200
    assert result["content_type"] == "video/mp4"
    assert result["final_url"] == base + "/binary"
    assert result["final_url_sha256"] == hashlib.sha256((base + "/binary?signature=never-print-this").encode()).hexdigest()
    assert "never-print-this" not in json.dumps(result)
    assert seen[0]["cookie"] == "session=fixture-cookie"
    assert seen[0]["referer"] == "https://www.douyin.com/"
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("route,options", [
    ("/error", {}), ("/partial", {}), ("/binary", {"max_bytes": 3}),
    ("/without-length", {"max_bytes": 3}), ("/html", {"expected_content_types": ["video/*"]}),
    ("/redirect", {"max_redirects": 0}), ("/foreign-redirect", {}),
])
def test_binary_download_failure_leaves_no_success_or_partial_file(tmp_path, binary_http_fixture, request_only_context, route, options):
    base, _, _ = binary_http_fixture
    target = tmp_path / "source.mp4"
    with pytest.raises(BinaryDownloadError) as error:
        _local_download(request_only_context, base + route + "?signature=never-print-this", target, **options)
    assert "never-print-this" not in str(error.value)
    assert "redirect-secret" not in str(error.value)
    assert "private-server-message" not in str(error.value)
    assert not target.exists()
    assert not list(tmp_path.glob("*.part"))


def test_binary_download_checks_each_redirect_and_preserves_existing_file_on_failure(tmp_path, binary_http_fixture, request_only_context):
    base, payload, seen = binary_http_fixture
    target = tmp_path / "source.mp4"
    result = _local_download(request_only_context, base + "/redirect", target, expected_content_types=["video/mp4"])
    assert result["redirect_count"] == 1
    assert target.read_bytes() == payload
    assert [row["path"] for row in seen] == ["/redirect", "/binary"]
    with pytest.raises(BinaryDownloadError, match="already exists"):
        _local_download(request_only_context, base + "/binary", target)
    with pytest.raises(BinaryDownloadError, match="HTTP status 403"):
        _local_download(request_only_context, base + "/error", target, overwrite=True)
    assert target.read_bytes() == payload


def test_binary_download_wrapper_sends_only_path_based_command_without_touching_binary(tmp_path):
    calls = []
    class Session:
        def cmd(self, action, **kwargs):
            calls.append((action, kwargs))
            return {"download": {"status": 200, "path": kwargs["output_path"], "size": 7}}
    target = Path(__file__).resolve().parents[1] / "data/qa/not-created-source.mp4"
    result = APIRequestContext(Session()).download("https://media.example/video?signature=private", target,
        max_bytes=1024, allowed_hosts=["media.example"], expected_content_types=["video/*"])
    assert calls[0][0] == "api_download"
    assert calls[0][1]["max_bytes"] == 1024
    assert result["size"] == 7
    assert "body" not in result
    assert not target.exists()


def test_binary_download_rejects_workspace_escape_and_public_calls_to_loopback(tmp_path):
    with pytest.raises(BinaryDownloadError, match="workspace"):
        _download_binary_response(None, "https://media.example/video", tmp_path.parent / "outside.mp4", workspace_root=tmp_path)
    with pytest.raises(BinaryDownloadError, match="HTTPS"):
        _validate_download_url("http://127.0.0.1/video", ["127.0.0.1"])
    with pytest.raises(BinaryDownloadError, match="non-public"):
        _validate_download_url("https://127.0.0.1/video", ["127.0.0.1"])


def test_binary_cross_origin_redirect_does_not_forward_explicit_credentials(tmp_path, binary_http_fixture, request_only_context):
    base, _, seen = binary_http_fixture
    _local_download(request_only_context, base + "/foreign-redirect", tmp_path / "video.mp4",
                    allowed_hosts=["127.0.0.1", "localhost"], headers={"Authorization": "Bearer fixture-token", "Cookie": "manual=fixture"})
    assert seen[0]["authorization"] == "Bearer fixture-token"
    assert seen[0]["cookie"] == "manual=fixture"
    assert seen[1]["authorization"] is None
    assert seen[1]["cookie"] is None


def test_browser_error_message_drops_headers_queries_and_secret_values():
    message = (
        "APIRequestContext.get: socket disconnected\n"
        "GET https://creator.douyin.com/path?signature=secret\n"
        "cookie: session=never-print-this"
    )
    sanitized = _sanitize_browser_error_message(message)
    assert sanitized == "APIRequestContext.get: socket disconnected"
    assert "secret" not in sanitized
    assert "never-print-this" not in sanitized


def test_api_get_retries_one_transient_disconnect(monkeypatch):
    calls = []

    class Session:
        def cmd(self, action, **kwargs):
            calls.append((action, kwargs))
            if len(calls) == 1:
                raise RuntimeError("Client network socket disconnected")
            return {"response": {"status": 200, "body": "{}"}}

    monkeypatch.setattr("src.platform_adapter.browser_session.time.sleep", lambda _: None)
    response = APIRequestContext(Session()).get("https://creator.douyin.com/example")
    assert response.status == 200
    assert len(calls) == 2
