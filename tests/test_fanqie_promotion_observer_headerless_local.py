"""Explicit opt-in local transport test; never uses an account/profile/platform.

Production origin stays HTTPS kol. Only this test monkeypatches the origin gate
to an ephemeral loopback server, to exercise native Playwright size metadata.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

import pytest

from src.platform_adapter import fanqie_promotion_observer_v1 as m


@pytest.mark.skipif(os.environ.get('RUN_LOCAL_HEADERLESS_OBSERVER_TEST') != '1',
                    reason='Explicit loopback/fresh headless Chrome opt-in required')
def test_native_headerless_requestfinished_size_gate(tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright, Response
    calls = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'
        def do_GET(self):
            parsed = urlsplit(self.path);calls.append(parsed.path)
            if parsed.path == '/page/promotion-list':
                body = b"<html><script>fetch('/api/promotion/list/v1').then(r=>r.json()).then(()=>window.loaded=true)</script></html>"
                content_type = 'text/html'
            elif parsed.path == '/api/promotion/list/v1':
                body = json.dumps({'data': {'list': [{'book_id': 'fixture-book',
                    'alias': 'fixture-alias', 'word_id': 196}]}}).encode()
                if parsed.query == 'large=1':
                    body = json.dumps({'data': {'list': [{'book_id': 'fixture-book',
                        'unrecognized_padding': 'x' * (m.MAX_BODY_BYTES + 20)}]}}).encode()
                content_type = 'application/json'
            else:
                self.send_error(404);return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Connection', 'close')
            # Intentionally no Content-Length and no Transfer-Encoding.
            self.end_headers();self.wfile.write(body)
            self.close_connection = True
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
    origin = 'http://127.0.0.1:' + str(server.server_port)
    endpoint = '/api/promotion/list/v1'
    native_metadata, body_calls, blocked = [], [], []
    original_body = Response.body
    def body(self):
        body_calls.append(urlsplit(self.url).path + ('?large' if 'large=1' in self.url else ''))
        return original_body(self)
    def local_endpoint(url):
        parsed = urlsplit(url)
        return parsed.path if parsed.scheme == 'http' and parsed.hostname == '127.0.0.1' and parsed.port == server.server_port else None
    monkeypatch.setattr(Response, 'body', body)
    monkeypatch.setattr(m, 'ORIGIN', origin)
    monkeypatch.setattr(m, '_endpoint', local_endpoint)
    monkeypatch.setattr(m, 'RESOURCE_JS', m.RESOURCE_JS.replace('https://kol.fanqieopen.com', origin))
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='chrome', headless=True, args=[
                '--mute-audio', '--disable-background-networking', '--disable-component-update',
                '--no-first-run', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'])
            try:
                context = browser.new_context()
                def route(request_route):
                    if request_route.request.url.startswith(origin + '/'):
                        request_route.continue_()
                    else:
                        blocked.append(urlsplit(request_route.request.url).hostname)
                        request_route.abort()
                context.route('**/*', route)
                page = context.new_page()
                def record(request):
                    if urlsplit(request.url).path == endpoint:
                        response = request.response()
                        native_metadata.append({'content_length_present': response.header_value('content-length') is not None,
                            'response_body_size': request.sizes()['responseBodySize'],
                            'large': 'large=1' in request.url})
                page.on('requestfinished', record)
                page.goto(origin + '/page/promotion-list', wait_until='domcontentloaded', timeout=5000)
                page.wait_for_function('window.loaded===true', timeout=5000)
                subject = dict(resource_id='loopback-test', binding_version='fixture',
                    platform_identity_key='fixture', environment_key='isolated-test',
                    owner_id='test-only', generation=1, task_id='local-only')
                observer = m.PromotionObserver(page, subject, [endpoint], page_id='local-only-page')
                page.reload(wait_until='domcontentloaded', timeout=5000)
                page.wait_for_function('window.loaded===true', timeout=5000)
                page.wait_for_timeout(100)
                assert len(observer.captures) == 1
                first = observer.captures[0]
                assert first['body_size_evidence']['source'] == 'request.sizes.responseBodySize'
                assert first['body_size_evidence']['completion_event'] == 'requestfinished'
                assert first['metadata']['records'][0]['fields']
                assert body_calls == [endpoint]
                page.evaluate("() => fetch('/api/promotion/list/v1?large=1').then(r=>r.text())")
                page.wait_for_timeout(100)
                assert len(observer.captures) == 1
                assert observer.skips['bounded_finished_response_size_required'] == 1
                assert body_calls == [endpoint]  # over-limit native response never body() read
                stopped = observer.stop()
                assert stopped['active'] is False
                assert all(row['content_length_present'] is False for row in native_metadata)
                assert next(row['response_body_size'] for row in native_metadata if row['large']) > m.MAX_BODY_BYTES
                result = {'schema': 'fanqie_headerless_loopback_transport_test/v1',
                    'actual_native_Playwright_API': True, 'production_origin_tested': False,
                    'test_only_loopback_origin_override': True, 'authenticated_profile_used': False,
                    'platform_calls': 0, 'native_body_saved': False, 'native_body_sha256': None,
                    'normal_headerless_capture_count': 1, 'oversize_body_method_calls': 0,
                    'native_size_metadata': native_metadata, 'python_body_method_calls': body_calls,
                    'external_context_requests_blocked': len(blocked), 'server_request_paths': calls,
                    'streaming_memory_hard_limit_proven': False,
                    'limitations': ['Completed encoded transfer-size gate plus decoded length check; body() buffers the decoded response.',
                                    'Production HTTPS kol same-origin gate remains covered by separate CPU tests.']}
                target = tmp_path / 'LOOPBACK_RESULT.json'
                target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                assert hashlib.sha256(target.read_bytes()).hexdigest()
                context.close()
            finally:
                browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        assert not thread.is_alive()
