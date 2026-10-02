from types import SimpleNamespace

import pytest

from src.platform_adapter.models import PublishRequest
from src.platform_adapter.publish_verification import FICTION_NOTICE, declared_description, video_id, inspect_published_video
from src.platform_adapter.publish_workflow import PublishWorkflow, FictionDeclarationUnverified


def test_notice_is_visible_prefix_idempotent_and_opt_out():
    description = declared_description('回家的故事', True)
    assert description.startswith(FICTION_NOTICE)
    assert declared_description(description, True) == description
    assert declared_description('纪实', False) == '纪实'
    assert declared_description('', True) == FICTION_NOTICE


@pytest.mark.parametrize('url', ['https://evil.example/video/123', 'https://douyin.com.evil.example/video/123',
                                    'https://creator.douyin.com/manage?aweme_id=123', 'http://www.douyin.com/video/123'])
def test_non_work_urls_cannot_verify(url):
    assert not video_id(url)
    assert not inspect_published_video(SimpleNamespace(url=url), '123')['verified']


def test_wrong_work_cannot_verify():
    assert not inspect_published_video(SimpleNamespace(url='https://www.douyin.com/video/456'), '123')['verified']


class Collection:
    def __init__(self, items): self.items = items
    def count(self): return len(self.items)
    def nth(self, i): return self.items[i]
    def first(self): return self.items[0]
    def filter(self, **kwargs): return self


@pytest.mark.parametrize('ai,fiction,marker,ready,expected', [
    (True,True,'',True,True), (False,True,'',True,False),
    (True,False,'',True,False), (True,True,'审核中',True,False),
    (True,True,'审核不通过',True,False), (True,True,'',False,False)])
def test_work_display_checks(ai, fiction, marker, ready, expected):
    player = SimpleNamespace(evaluate=lambda script:dict(ready=ready, error=False, duration=True))
    work = SimpleNamespace(is_visible=lambda:True,
        locator=lambda selector:Collection([player]),
        inner_text=lambda: (FICTION_NOTICE if fiction else '') + marker,
        get_by_text=lambda pattern:Collection([SimpleNamespace(is_visible=lambda:True)] if ai else []))
    page = SimpleNamespace(url='https://www.douyin.com/video/123',
        get_by_role=lambda role:Collection([work]), locator=lambda selector:None)
    assert inspect_published_video(page, '123')['verified'] is expected


def test_fiction_must_survive_editor_changes_before_click():
    workflow = PublishWorkflow(SimpleNamespace())
    workflow._ai_declaration_required = False
    workflow._fiction_declaration_required = True
    page = SimpleNamespace(locator=lambda selector:Collection([SimpleNamespace(inner_text=lambda:'声明被删掉了')]))
    with pytest.raises(FictionDeclarationUnverified):
        workflow._click_publish(page)


@pytest.mark.parametrize('post_verified', [False, True])
def test_full_flow_persists_declarations_and_pending_lock(tmp_path, monkeypatch, post_verified):
    import src.platform_adapter.publish_workflow as module
    monkeypatch.setattr(module, '__file__', str(tmp_path/'src/platform_adapter/publish_workflow.py'))
    video = tmp_path/'v.mp4'; video.write_bytes(b'fixture')
    request = PublishRequest(video_path=str(video), title='test', extra_metadata={
        'account_key':'A', 'platform_identity_key':'douyin:A'})
    workflow = PublishWorkflow(SimpleNamespace(start=lambda:None, is_authenticated=lambda:True))
    description = []
    page = SimpleNamespace(url='https://www.douyin.com/video/123',
        ai_content_declaration=lambda **kwargs:{'verified':True},
        locator=lambda selector:Collection([SimpleNamespace(inner_text=lambda:description[0])]),
        goto=lambda *args,**kwargs:None, wait_for_timeout=lambda ms:None,
        inspect_published_video=lambda *args,**kwargs:{'verified':post_verified})
    workflow._open_upload_page = lambda:page
    for method in ('_upload_video_file','_fill_title','_set_visibility','_click_publish'):
        setattr(workflow, method, lambda *args,**kwargs:None)
    workflow._fill_description = lambda page,text:description.append(text)
    workflow._wait_for_upload_complete = lambda *args,**kwargs:True
    workflow._wait_for_publish_result = lambda *args,**kwargs:('123',page.url)
    result = workflow.publish(request)
    assert result.success  # Accepted submission, not permission to repeat an uncertain upload.
    assert result.status == ('published' if post_verified else 'post_publish_verification_pending')
    assert description == [FICTION_NOTICE]
    assert workflow._submission_lock.exists()
    assert not workflow.publish(request).success


def test_inspection_error_is_pending_not_failed_upload():
    workflow = PublishWorkflow(SimpleNamespace())
    page = SimpleNamespace(goto=lambda *args,**kwargs: (_ for _ in ()).throw(TimeoutError('timeout')))
    assert not workflow._verify_published_work(page, '123', 'https://www.douyin.com/video/123', PublishRequest('x','x'))['verified']
