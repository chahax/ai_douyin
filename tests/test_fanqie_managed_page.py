"""Actual worker and Chrome, only a loopback fixture and isolated profile."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import BrowserSessionConfig
from src.platform_adapter.fanqie_managed_page import FanqieManagedPage


def test_role_scope_file_upload_and_reload_through_real_worker(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write('''<!doctype html><meta charset="utf-8">
              <button onclick="window.wrong=true">提交更多</button>
              <div role="dialog" aria-label="批量上传发文-番茄小说">
                <input type="file" onchange="document.querySelector('#submit').disabled=false">
                <button disabled id="submit" onclick="window.submitted=(window.submitted||0)+1">提交</button>
              </div>'''.encode())
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}/'
    session=BrowserSession(BrowserSessionConfig(base_url=url,home_url=url,
        storage_state_path=str(tmp_path/'state.json'),user_data_dir=str(tmp_path/'profile'),
        headless=True,mute_audio=True,browser_channel='chrome'))
    try:
        original=session.open_page(url)
        page=FanqieManagedPage(original)
        dialog=page.get_by_role('dialog',name='批量上传发文-番茄小说',exact=True)
        assert dialog.count()==1 and dialog.is_visible()
        button=dialog.get_by_role('button',name='提交',exact=True)
        assert button.count()==1 and not button.is_enabled()
        file=tmp_path/'fixture.txt';file.write_text('test only')
        dialog.locator('input[type=file]').set_input_files(str(file))
        assert button.is_enabled()
        button.click()
        assert page.evaluate('() => window.submitted')==1
        assert page.evaluate('() => !!window.wrong') is False
        page.reload()
        assert page.url==url and original.tab_id==page.page.tab_id
        assert page.evaluate('() => window.submitted || 0')==0
    finally:
        session.stop()
        server.shutdown();server.server_close()
