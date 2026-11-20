"""Known form-only topic repair; no uploader, platform or live browser."""
from collections import Counter
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.platform_adapter.publish_workflow as module
from src.platform_adapter.publish_verification import FICTION_NOTICE, declared_description
from src.platform_adapter.models import PublishRequest


class Editor:
    def __init__(self, page):
        self.page, self.generation = page, page.generation

    def evaluate(self, script):
        assert self.generation == self.page.generation, 'stale Slate editor was reused'
        return {'visible': True, 'text': self.page.text(), 'truncated': False,
            'chips': self.page.chips()}

    def inner_text(self):
        return self.page.text()

    def type_hashtag(self, tag, *, selectors):
        assert self.generation == self.page.generation, 'stale Slate editor was reused'
        assert len(selectors) == 1 and ':nth-match(' in selectors[0]
        self.page.typed.append(tag)
        self.page.insert(tag)

    def fill(self, *_):
        pytest.fail('topic repair must not clear or rewrite the description')


class Locator:
    def __init__(self, page):
        self.page = page

    def count(self):
        return 1

    def nth(self, index):
        assert index == 0
        return Editor(self.page)

    def first(self):
        return Editor(self.page)


class Form:
    url = 'https://creator.douyin.com/creator-micro/content/upload'

    def __init__(self, *, mode='plain', loss=None):
        self.description = FICTION_NOTICE+'员工表达真实意愿，保留书面安排。'
        self.tags, self.typed, self.pending = [], [], []
        self.clock, self.generation = 0, 0
        self.mode, self.loss = mode, loss
        self.surface_captures = 0
        self.ai_calls = []

    def text(self):
        if self.mode == 'split_hash':
            labels = ['#\n'+tag for tag in self.tags]
        elif self.mode == 'split_chip_word':
            labels = ['#'+tag[:1]+'\n'+tag[1:] for tag in self.tags]
        elif self.mode == 'bare_topic' or self.mode == 'bare_slate':
            labels = list(self.tags)
        else:
            labels = ['#'+tag for tag in self.tags]
        return self.description+'\n'+'\n'.join(labels)

    def chips(self):
        if self.mode == 'split_chip_word':
            return [{'text': '#'+tag[:1]+'\n'+tag[1:], 'explicit_topic': False} for tag in self.tags]
        if self.mode in {'bare_topic', 'bare_slate'}:
            return [{'text': tag, 'explicit_topic': self.mode == 'bare_topic'} for tag in self.tags]
        return []

    def mutate(self, function):
        function()
        self.generation += 1

    def schedule(self, delay, function):
        self.pending.append((self.clock+delay, function))

    def insert(self, tag):
        if self.loss == 'keyboard_error':
            raise RuntimeError('known failed input')
        actual = '劳动法律' if self.loss == 'prefix_collision' and tag == '劳动法' else tag
        self.schedule(150, lambda: self.mutate(lambda: self.tags.append(actual)))
        if self.loss == 'first_once' and tag == '劳动法' and self.typed.count(tag) == 1:
            self.schedule(350, lambda: self.mutate(lambda: self.tags.remove(actual)))
        if self.loss == 'always' and tag == '劳动法':
            self.schedule(350, lambda: self.mutate(lambda: self.tags.remove(actual)))
        if self.loss == 'description' and tag == '劳动法':
            self.schedule(150, lambda: self.mutate(lambda: setattr(self, 'description', '不同的简介。')))

    def locator(self, selector):
        return Locator(self)

    def wait_for_timeout(self, ms):
        self.clock += ms
        due = sorted((item for item in self.pending if item[0] <= self.clock), key=lambda item: item[0])
        self.pending = [item for item in self.pending if item[0] > self.clock]
        for _, action in due:
            action()

    def evaluate(self, script):
        self.surface_captures += 1
        return {'visible_text': self.text(), 'buttons': [], 'progress': []}

    def _cmd(self, action, **kwargs):
        assert action == 'screenshot'
        Path(kwargs['path']).write_bytes(b'native-visible-form-fixture')
        return {'path': kwargs['path']}

    def ai_content_declaration(self, **kwargs):
        self.ai_calls.append(kwargs)
        if kwargs.get('set_selected') and self.loss == 'after_ai' and '劳动法' in self.tags:
            self.mutate(lambda: self.tags.remove('劳动法'))
        if kwargs.get('set_selected') and self.loss == 'after_ai_description':
            self.mutate(lambda: setattr(self, 'description', self.description.replace('真实意愿', '自愿离职')))
        return {'verified': True}


def workflow(tmp_path):
    value = module.PublishWorkflow(SimpleNamespace())
    value._journal_path = tmp_path / 'original-publish.jsonl'
    return value


def records(value):
    return [json.loads(row) for row in value._journal_path.read_text(encoding='utf-8').splitlines()]


@pytest.mark.parametrize('mode', ['plain', 'split_hash', 'split_chip_word', 'bare_topic'])
def test_rendered_exact_topics_and_split_hash_or_semantic_chips_are_confirmed(tmp_path, mode):
    value, page = workflow(tmp_path), Form(mode=mode)
    before = page.description
    value._add_hashtags(page, ['劳动法', '普法知识'], expected_description=before)
    assert Counter(page.typed) == Counter({'劳动法': 1, '普法知识': 1})
    assert page.description == before
    final = records(value)[-1]
    assert final['phase'] == 'complete' and final['missing'] == []
    assert final['description_preserved'] is True
    assert 'actual_text' in final and final['actual_text_sha256']


def test_initial_unsettled_tag_stops_without_typing_more_or_spending_repair(tmp_path):
    value, page = workflow(tmp_path), Form(loss='first_once')
    before = page.description
    with pytest.raises(module.HashtagReadbackError,match='劳动法'):
        value._add_hashtags(page, ['劳动法', '劳动权益', '普法知识'], expected_description=before)
    assert page.typed == ['劳动法'] and page.description == before
    assert not any(row.get('phase')=='repair_once' for row in records(value))


@pytest.mark.parametrize('loss', ['prefix_collision', 'always'])
def test_prefix_collision_or_persistent_loss_stops_initial_input_with_exact_evidence(tmp_path, loss):
    value, page = workflow(tmp_path), Form(loss=loss)
    before = page.description
    with pytest.raises(module.HashtagReadbackError, match='劳动法'):
        value._add_hashtags(page, ['劳动法', '普法知识'], expected_description=before)
    assert page.typed == ['劳动法']
    assert page.description == before
    failed = next(row for row in records(value) if row.get('phase') == 'failed')
    assert failed['missing'] == ['劳动法', '普法知识']
    assert failed['description_preserved'] is True
    assert page.surface_captures == 1
    assert records(value)[-1]['stage'] == 'hashtags_failure_ui'
    assert not value._submission_started


def test_bare_generic_slate_node_does_not_impersonate_a_topic_chip(tmp_path):
    value, page = workflow(tmp_path), Form(mode='bare_slate')
    with pytest.raises(module.HashtagReadbackError):
        value._add_hashtags(page, ['劳动法'], expected_description=page.description)
    assert page.typed == ['劳动法']
    assert records(value)[-2]['missing'] == ['劳动法']


def test_duplicates_and_already_present_topics_are_not_typed_again(tmp_path):
    value, page = workflow(tmp_path), Form()
    page.tags = ['劳动法']
    value._add_hashtags(page, ['劳动法', '普法知识', '劳动法'], expected_description=page.description)
    assert page.typed == ['普法知识']
    assert records(value)[-1]['expected'] == ['劳动法', '普法知识']


def test_late_tag_appearing_before_repair_is_read_again_and_not_duplicated(tmp_path):
    value, page = workflow(tmp_path), Form()
    original_wait = value._wait_hashtag_readback
    final_calls=[]
    def wait(*args,**kwargs):
        if kwargs.get('final') and not final_calls:
            final_calls.append(True)
            page.mutate(lambda:page.tags.remove('劳动法'))
        return original_wait(*args,**kwargs)
    value._wait_hashtag_readback = wait
    original_record = value._record
    def record(stage, **details):
        original_record(stage, **details)
        if details.get('phase') == 'repair_once':
            page.mutate(lambda: page.tags.append('劳动法'))
    value._record = record
    value._add_hashtags(page, ['劳动法'], expected_description=page.description)
    assert page.typed == ['劳动法']
    assert records(value)[-1]['phase'] == 'complete'


def test_new_tag_must_preserve_preexisting_unrequested_topic(tmp_path):
    value,page=workflow(tmp_path),Form()
    page.tags=['原有话题']
    original=page.insert
    def insert(tag):
        original(tag)
        page.schedule(150,lambda:page.mutate(lambda:page.tags.remove('原有话题')))
    page.insert=insert
    with pytest.raises(module.HashtagReadbackError,match='原话题未保留'):
        value._add_hashtags(page,['劳动法','劳动权益'],expected_description=page.description)
    assert page.typed==['劳动法']


def test_late_final_loss_has_exactly_one_missing_only_repair(tmp_path):
    value,page=workflow(tmp_path),Form()
    original=value._wait_hashtag_readback
    calls=[]
    def wait(*args,**kwargs):
        if kwargs.get('final') and not calls:
            calls.append(True)
            page.mutate(lambda:page.tags.remove('劳动法'))
        return original(*args,**kwargs)
    value._wait_hashtag_readback=wait
    value._add_hashtags(page,['劳动法','普法知识'],expected_description=page.description)
    assert page.typed==['劳动法','普法知识','劳动法']
    assert sum(row.get('phase')=='repair_once' for row in records(value))==1


def test_changed_description_stops_without_rewriting_or_typing_remaining_topics(tmp_path):
    value, page = workflow(tmp_path), Form(loss='description')
    before = page.description
    with pytest.raises(module.HashtagReadbackError, match='简介'):
        value._add_hashtags(page, ['劳动法', '普法知识'], expected_description=before)
    assert page.typed == ['劳动法']
    assert page.description == '不同的简介。'
    failed = next(row for row in records(value) if row.get('phase') == 'failed')
    assert failed['description_preserved'] is False
    assert page.surface_captures == 1


def test_keyboard_rpc_error_does_not_trigger_automatic_repair_and_saves_evidence(tmp_path):
    value, page = workflow(tmp_path), Form(loss='keyboard_error')
    with pytest.raises(module.HashtagReadbackError, match='操作未完成'):
        value._add_hashtags(page, ['劳动法'], expected_description=page.description)
    assert page.typed == ['劳动法']
    assert not any(row.get('phase') == 'repair_once' for row in records(value))
    assert page.surface_captures == 1


def test_word_boundary_does_not_accept_longer_unicode_word_or_format_character_collision():
    value = module.PublishWorkflow(SimpleNamespace())
    snapshot = {'text': '#劳动法律 #劳动法2 #劳动法\u200b律 #\n普法知识', 'chips': []}
    tokens = value._hashtag_tokens(snapshot)
    assert '劳动法' not in tokens
    assert '劳动法律' in tokens and '普法知识' in tokens


@pytest.mark.parametrize('loss', ['after_ai', 'after_ai_description'])
def test_final_readonly_confirmation_cannot_repair_again_after_ai_control_rerenders(tmp_path, monkeypatch, loss):
    monkeypatch.setattr(module, '__file__', str(tmp_path/'src/platform_adapter/publish_workflow.py'))
    page = Form(loss=loss)
    value = module.PublishWorkflow(SimpleNamespace(start=lambda: None, is_authenticated=lambda: True))
    video = tmp_path/'original.mp4'
    video.write_bytes(b'original-video-fixture')
    request = PublishRequest(str(video), '原标题', description=page.description,
        hashtags=['劳动法', '普法知识'], extra_metadata={'account_key': 'A', 'platform_identity_key': 'douyin:A'})
    uploads = []
    value._open_upload_page = lambda: page
    value._upload_video_file = lambda *_: uploads.append('selected-once')
    value._wait_for_upload_complete = lambda *_a, **_k: True
    value._fill_title = lambda *_: None
    value._fill_description = lambda _page, text: setattr(_page, 'description', text)
    value._set_visibility = lambda *_: None
    value._click_publish = lambda *_a, **_k: pytest.fail('must not publish missing topics')
    result = value.publish(request)
    assert result.success is False and result.status == 'error'
    assert uploads == ['selected-once']
    assert Counter(page.typed) == Counter({'劳动法': 1, '普法知识': 1})
    if loss == 'after_ai_description':
        assert '自愿离职' in page.description
        assert page.description != declared_description(request.description, request.fictional_story)
    else:
        assert page.description == declared_description(request.description, request.fictional_story)
    assert any(call.get('set_selected') for call in page.ai_calls)
    assert any(row['stage'] == 'fiction_declaration_verified' for row in records(value))
    assert not value._submission_started and not value._submission_lock.exists()
    assert 'submission_started' not in [row['stage'] for row in records(value)]


def test_observed_slate_zero_width_spaces_do_not_change_visible_description():
    expected = declared_description('剧情虚构，非真实事件。店里提出减人，为什么要员工写“个人原因”？'
        '桂芳的一句话，把离职意愿说清楚。AI剧情演绎，劳动法律知识分享。', True)
    actual = expected.replace(FICTION_NOTICE, FICTION_NOTICE+'\u200b', 1)+'\u200b\n#劳动法'
    assert module.PublishWorkflow._description_preserved({'text': actual}, expected) is True


@pytest.mark.parametrize('original,replacement', [('减人', '裁人'), ('？', '。')])
def test_visible_word_or_punctuation_change_is_not_hidden_by_slate_normalization(original, replacement):
    expected = FICTION_NOTICE+'店里提出减人，为什么要员工写“个人原因”？'
    actual = expected.replace(original, replacement)+'\u200b'
    assert module.PublishWorkflow._description_preserved({'text': actual}, expected) is False


def test_other_format_characters_are_not_arbitrarily_removed_from_description():
    expected = FICTION_NOTICE+'劳动法律知识分享。'
    actual = expected.replace('知识', '知\u200d识')
    assert module.PublishWorkflow._description_preserved({'text': actual}, expected) is False
