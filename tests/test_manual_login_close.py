"""Exercise the worker's close handling without an external browser or login."""
import ast
import io
import json
from types import SimpleNamespace

from src.platform_adapter.browser_session import _PW_SCRIPT, _checkpoint_open_login_pages


def test_close_wait_pumps_events_and_saves_before_context_closes(tmp_path):
    tree = ast.parse(_PW_SCRIPT)
    branch = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                  and ast.unparse(node.test) == "action == 'wait_for_close'")
    events = []

    class Page:
        closed = False
        frames = [SimpleNamespace(evaluate=lambda script: {'origin': 'https://example.test', 'localStorage': []})]

        def is_closed(self):
            return self.closed

        def wait_for_timeout(self, milliseconds):
            events.append('pump')
            self.closed = True

    page = Page()
    def cookies():
        events.append('cookies')
        return []

    context = SimpleNamespace(pages=[page], cookies=cookies)
    target = tmp_path / 'fresh-state.json'
    scope = dict(cmd={'path': str(target)}, storage_state_path='old-state.json',
                 time=SimpleNamespace(time=lambda: 0), sys=SimpleNamespace(stdout=io.StringIO()),
                 context=context, json=json)
    exec(compile(ast.Module(body=branch.body, type_ignores=[]), '<login-close>', 'exec'), scope)
    assert events == ['cookies', 'pump']
    assert json.loads(scope['sys'].stdout.getvalue())['state_saved'] is True
    assert json.loads(target.read_text())['origins'][0]['origin'] == 'https://example.test'


def test_checkpoint_never_opens_pages_and_keeps_captured_origins(tmp_path):
    class Context:
        pages = []

        def cookies(self):
            return [{'name': 'fixture', 'value': 'synthetic'}]

        def storage_state(self, **kwargs):
            raise AssertionError('storage_state can open temporary pages')

        def new_page(self):
            raise AssertionError('must not open pages')

    target = tmp_path / 'state.json'
    context, origins = Context(), {}
    for origin in ('https://first.test', 'https://second.test'):
        frame = SimpleNamespace(evaluate=lambda script: {'origin': origin, 'localStorage': []})
        context.pages = [SimpleNamespace(is_closed=lambda: False, frames=[frame])]
        assert _checkpoint_open_login_pages(context, target, origins)
        assert len(context.pages) == 1
    saved = target.read_text()
    assert len(json.loads(saved)['origins']) == 2
    context.pages = []
    assert not _checkpoint_open_login_pages(context, target, origins)
    assert target.read_text() == saved
