from types import SimpleNamespace

import pytest

from src.platform_adapter.ai_content_declaration import read_ai_declaration, set_ai_declaration
from src.platform_adapter.models import PublishRequest
from src.platform_adapter.publish_workflow import PublishWorkflow, AIDeclarationUnverified


class Locator:
    def __init__(self, values=()):
        self.values = list(values)

    def count(self):
        return len(self.values)

    def nth(self, index):
        return self.values[index]


class Control:
    def __init__(self, name="内容由AI生成", *, checked=False, popup=False, stick=True):
        self.name, self.checked, self.popup, self.stick = name, checked, popup, stick
        self.clicks = 0

    def is_visible(self):
        return True

    def is_checked(self):
        return self.checked

    def get_attribute(self, name):
        return str(self.checked).lower() if name == 'aria-checked' else None

    def set_checked(self, value, **kwargs):
        self.clicks += 1
        if self.stick:
            self.checked = value

    def click(self, **kwargs):
        self.set_checked(True)

    def evaluate(self, script):
        return self.popup


class Form:
    def __init__(self, controls=(), role='checkbox'):
        self.controls, self.role = list(controls), role

    def get_by_role(self, role, name=None):
        return Locator(c for c in self.controls if role == self.role and name.fullmatch(c.name))

    def get_by_text(self, text, exact=True):
        return Locator()  # A caption/help string does not manufacture a form control.

    def wait_for_timeout(self, ms):
        pass


@pytest.mark.parametrize('role', ['checkbox', 'radio', 'switch'])
def test_select_and_read_back_idempotently(role):
    control = Control()
    form = Form([control], role)
    assert set_ai_declaration(form)['verified'] is True
    assert control.checked and control.clicks == 1
    assert set_ai_declaration(form)['verified'] is True
    assert control.clicks == 1


def test_unchecked_or_uncommitted_option_is_not_a_declaration():
    assert read_ai_declaration(Form([Control()]))['verified'] is False
    assert read_ai_declaration(Form([Control(checked=True, popup=True)]))['verified'] is False


def test_caption_platform_badge_and_failed_click_do_not_pass():
    assert set_ai_declaration(Form())['verified'] is False
    assert set_ai_declaration(Form([Control('作品含AI生成内容', checked=True)]))['verified'] is False
    assert set_ai_declaration(Form([Control(stick=False)]))['verified'] is False


def test_ambiguous_options_are_not_clicked():
    controls = [Control(), Control()]
    with pytest.raises(ValueError, match='不唯一'):
        set_ai_declaration(Form(controls))
    assert not any(c.clicks for c in controls)


@pytest.mark.parametrize('verified', [False, True])
def test_workflow_requires_declaration_before_submission(tmp_path, monkeypatch, verified):
    import src.platform_adapter.publish_workflow as module
    monkeypatch.setattr(module, '__file__', str(tmp_path/'src/platform_adapter/publish_workflow.py'))
    video = tmp_path/'test.mp4'; video.write_bytes(b'fixture')
    request = PublishRequest(video_path=str(video), title='AI fixture', fictional_story=False, extra_metadata={
        'account_key':'A', 'platform_identity_key':'douyin:A'})
    workflow = PublishWorkflow(SimpleNamespace(start=lambda:None, is_authenticated=lambda:True))
    seen = []
    def declaration(**kwargs):
        seen.append(('declaration', kwargs['set_selected']))
        return {'verified':verified, 'label':'内容由AI生成'}
    page = SimpleNamespace(url='https://creator.douyin.com/creator-micro/content/publish',
                           ai_content_declaration=declaration)
    workflow._open_upload_page = lambda:page
    for method in ('_upload_video_file','_fill_title','_set_visibility'):
        setattr(workflow, method, lambda *args:None)
    workflow._wait_for_upload_complete = lambda *args, **kwargs:True
    workflow._click_publish = lambda *args, **kwargs:seen.append(('publish', True))
    workflow._wait_for_publish_result = lambda *args, **kwargs:('123', 'https://www.douyin.com/video/123')
    result = workflow.publish(request)
    if verified:
        assert result.success
        assert seen == [('declaration', True), ('declaration', False), ('publish', True)]
        assert workflow._submission_lock.exists()
    else:
        assert result.status == 'ai_declaration_unverified' and not result.success
        assert not workflow._submission_lock.exists()
        assert not any(item[0]=='publish' for item in seen)


def test_last_moment_unchecked_declaration_blocks_publish_click():
    workflow = PublishWorkflow(SimpleNamespace())
    page = SimpleNamespace(ai_content_declaration=lambda **kwargs:{'verified':False})
    with pytest.raises(AIDeclarationUnverified):
        workflow._click_publish(page)


def test_ai_flag_is_enabled_by_default_and_rejects_string(tmp_path):
    path=tmp_path/'test.mp4';path.write_bytes(b'fixture')
    request=PublishRequest(video_path=str(path), title='fixture')
    assert request.ai_generated is True
    request.ai_generated='false'
    assert '布尔值' in PublishWorkflow(SimpleNamespace())._validate_request(request)
