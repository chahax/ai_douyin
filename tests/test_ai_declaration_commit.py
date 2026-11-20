"""A failed native check may commit later; repair never toggles it twice."""
import ast
import io
import json
from types import SimpleNamespace

import pytest

import src.platform_adapter.ai_content_declaration as module
from src.platform_adapter.browser_session import _PW_SCRIPT


class Items:
    def __init__(self, values=()): self.values = list(values)
    def count(self): return len(self.values)
    def nth(self, index): return self.values[index]


class Option:
    def __init__(self, *, delay=None, raises=True, connected=True):
        self.checked = False
        self.native_clicks = 0
        self.delay, self.raises, self.connected = delay, raises, connected
        self.labels = []
    def is_visible(self): return True
    def is_checked(self): return self.checked
    def element_handle(self, **_): return self
    def set_checked(self, value, **kwargs):
        assert value is True and not kwargs.get('force')
        self.native_clicks += 1
        if self.delay == 0: self.checked = True
        if self.raises: raise RuntimeError('native private error')
    def evaluate(self, script, original=None):
        if 'el.isConnected' in script: return self.connected
        if 'el === original' in script: return self is original
        if 'el.labels' in script: return list(range(len(self.labels)))
        return False  # Not in a popup.


class Label:
    def __init__(self, option, *, works=True, visible=True, bound=True):
        self.option, self.works, self.visible, self.bound = option, works, visible, bound
        self.clicks = 0
    def is_visible(self): return self.visible
    def evaluate(self, script, original): return self.bound and self.option is original
    def click(self, **kwargs):
        assert not kwargs.get('force')
        self.clicks += 1
        if self.works: self.option.checked = True


class Form:
    def __init__(self, option):
        self.option, self.waits, self.on_wait = option, 0, None
        self.duplicates = []
    def get_by_role(self, role, name=None):
        return Items([self.option, *self.duplicates] if role=='checkbox' else [])
    def get_by_text(self, *_, **__): return Items()
    def locator(self, selector):
        assert selector == 'label'
        return Items(self.option.labels)
    def wait_for_timeout(self, ms):
        assert ms == 200
        self.waits += 1
        if self.option.delay is not None and self.waits >= self.option.delay:
            self.option.checked = True
        if self.on_wait: self.on_wait(self)


def test_native_error_then_delayed_commit_never_uses_second_toggle():
    option = Option(delay=3)
    label = Label(option); option.labels = [label]
    assert module.set_ai_declaration(Form(option))['verified'] is True
    assert option.native_clicks == 1 and label.clicks == 0


def test_clear_unchecked_uses_unique_bound_label_once_then_reads_committed_state():
    option = Option(); label = Label(option); option.labels = [label]
    assert module.set_ai_declaration(Form(option))['verified'] is True
    assert option.native_clicks == label.clicks == 1


@pytest.mark.parametrize('kind', ['none', 'duplicate', 'hidden', 'unbound', 'unresponsive'])
def test_no_effect_or_unknown_label_never_retries_option_or_passes(kind):
    option = Option()
    label = Label(option, visible=kind!='hidden', bound=kind!='unbound', works=kind!='unresponsive')
    option.labels = [] if kind=='none' else [label, Label(option)] if kind=='duplicate' else [label]
    assert module.set_ai_declaration(Form(option))['verified'] is False
    assert option.native_clicks == 1
    assert label.clicks == (1 if kind=='unresponsive' else 0)


@pytest.mark.parametrize('change', ['detached', 'replaced', 'duplicate'])
def test_ambiguous_or_detached_original_stops_before_label(change):
    option = Option(); label = Label(option); option.labels = [label]
    form = Form(option)
    def mutate(form):
        if change == 'detached': option.connected = False
        elif change == 'replaced': form.option = Option()
        else: form.duplicates = [Option()]
    form.on_wait = mutate
    with pytest.raises(ValueError): module.set_ai_declaration(form)
    assert option.native_clicks == 1 and label.clicks == 0


def test_unknown_checked_state_does_not_click():
    option = Option(); option.checked = None
    with pytest.raises(ValueError): module.set_ai_declaration(Form(option))
    assert option.native_clicks == 0


def test_unresponsive_existing_option_does_not_reopen_declaration_entry_to_retry():
    option = Option(); label = Label(option, works=False); option.labels = [label]
    form = Form(option)
    entry = Label(option)
    form.get_by_text = lambda text, **kw: Items([entry]) if text=='自主声明' else Items()
    assert module.set_ai_declaration(form)['verified'] is False
    assert option.native_clicks == label.clicks == 1
    assert entry.clicks == 0


def test_selected_but_unconfirmed_popup_stays_false():
    option = Option(delay=0)
    original = option.evaluate
    option.evaluate = lambda script, original_arg=None: True if 'closest(' in script else original(script, original_arg)
    assert module.set_ai_declaration(Form(option))['verified'] is False
    assert option.native_clicks == 1


def worker_action(page, monkeypatch, *, error=None, selected=True):
    """Execute the actual worker action body, with no browser process or platform."""
    if error:
        monkeypatch.setattr(module, 'set_ai_declaration', lambda _: (_ for _ in ()).throw(error))
    tree = ast.parse(_PW_SCRIPT)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
        and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name)
        and n.test.left.id=='action' and any(isinstance(x, ast.Constant)
        and x.value=='ai_content_declaration' for x in n.test.comparators))
    out = io.StringIO()
    exec(compile(ast.fix_missing_locations(ast.Module(body=node.body, type_ignores=[])), '<worker-action>', 'exec'),
        {'page':page, 'cmd':{'set_selected':selected,'evidence_path':'fixture.png'},
         'sys':SimpleNamespace(stdout=out), 'json':json})
    return json.loads(out.getvalue())['evidence']


def test_worker_helper_exception_saves_actual_failure_screenshot_but_never_claims_verified(monkeypatch):
    option = Option(); form = Form(option); screenshots = []
    form.screenshot = lambda **kw: screenshots.append(kw)
    evidence = worker_action(form, monkeypatch, error=RuntimeError('private error'))
    assert evidence['verified'] is False and evidence['error_type']=='RuntimeError'
    assert evidence['screenshot']=='fixture.png' and len(screenshots)==1
    assert 'private error' not in json.dumps(evidence)


def test_worker_screenshot_error_overrides_otherwise_verified_state(monkeypatch):
    option = Option(); option.checked = True; form = Form(option)
    form.screenshot = lambda **kw: (_ for _ in ()).throw(OSError('private path error'))
    evidence = worker_action(form, monkeypatch, selected=False)
    assert evidence['verified'] is False and evidence['screenshot_error_type']=='OSError'
    assert evidence['observed_before_screenshot']['verified'] is True
    assert 'private path' not in json.dumps(evidence)
