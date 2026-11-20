"""Submission click dispatch is single-shot even when its outcome is unknown."""
import json
from types import SimpleNamespace as NS

import pytest

from src.platform_adapter.models import PublishRequest
from src.platform_adapter.publish_workflow import PublishWorkflow, AIDeclarationUnverified


class Buttons:
    def __init__(self, counts=(1, 1), text='发布', error=None):
        self.counts, self.text, self.error = iter(counts), text, error
        self.clicks = []

    def count(self): return next(self.counts)
    def inner_text(self): return self.text
    def click(self, **options):
        self.clicks.append(options)
        if self.error: raise self.error


class Page:
    def __init__(self, button, wait_error=None):
        self.button, self.wait_error = button, wait_error
        self.selectors, self.waits = [], []

    def locator(self, selector):
        self.selectors.append(selector)
        return self.button

    def wait_for_timeout(self, ms):
        self.waits.append(ms)
        if self.wait_error: raise self.wait_error

    def click_button_by_text(self, *args):
        pytest.fail('candidate-loop helper must never dispatch publication')


def workflow():
    value = PublishWorkflow(NS())
    value._ai_declaration_required = False
    value._fiction_declaration_required = False
    return value


@pytest.mark.parametrize('label', ['发布', '立即发布', '确认发布'])
def test_one_precise_button_one_click_rpc(label):
    button = Buttons(text=label)
    page = Page(button)
    workflow()._click_publish(page)
    assert button.clicks == [{'timeout': 15000}] and page.waits == [1000]
    assert len(page.selectors) == 1
    assert ':visible:enabled' in page.selectors[0] and 'normalize-space' in page.selectors[0]


@pytest.mark.parametrize('counts,text', [((0,), '发布'), ((2,), '发布'), ((1,2), '发布'), ((1,), '发布作品')])
def test_missing_ambiguous_or_changed_button_never_clicks(counts, text):
    button = Buttons(counts=counts, text=text)
    page = Page(button)
    with pytest.raises(RuntimeError, match='未执行点击'): workflow()._click_publish(page)
    assert button.clicks == [] and page.waits == [] and len(page.selectors) == 1


@pytest.mark.parametrize('stage', ['click', 'post_click_wait'])
def test_click_or_postclick_timeout_never_falls_back(stage):
    error = TimeoutError('unknown browser delivery')
    button = Buttons(error=error if stage == 'click' else None)
    page = Page(button, wait_error=error if stage == 'post_click_wait' else None)
    with pytest.raises(TimeoutError) as caught: workflow()._click_publish(page)
    assert caught.value is error
    assert len(button.clicks) == len(page.selectors) == 1


def test_ai_declaration_failure_precedes_any_button_inspection():
    value = workflow()
    value._ai_declaration_required = True
    value._require_ai_declaration = lambda *a: (_ for _ in ()).throw(AIDeclarationUnverified('not committed'))
    page = Page(Buttons())
    with pytest.raises(AIDeclarationUnverified): value._click_publish(page)
    assert page.selectors == [] and page.button.clicks == []


def test_actual_publish_error_keeps_original_submission_lock_and_unknown(tmp_path):
    value = workflow()
    value.session = NS(start=lambda: None, is_authenticated=lambda: True)
    video = tmp_path / 'original.mp4'
    video.write_bytes(b'isolated film')
    def journal(request):
        value._submission_lock = tmp_path / 'original.submitted.json'
        value._journal_path = tmp_path / 'original.jsonl'
    value._start_journal = journal
    page = Page(Buttons(error=TimeoutError('unknown click')))
    def prepared(request, interactive=False):
        value._reserve_submission()
        value._click_publish(page)
        pytest.fail('unknown click must stop original flow')
    value._do_publish = prepared
    result = value.publish(PublishRequest(str(video), 'original', ai_generated=False, fictional_story=False))
    assert result.status == 'submission_unknown' and result.success is False
    assert value._submission_lock.exists()
    assert json.loads(value._submission_lock.read_text())['status'] == 'submission_started'
    assert len(page.button.clicks) == 1
    stages = [json.loads(line)['stage'] for line in value._journal_path.read_text().splitlines()]
    assert 'publish_click_outcome_unknown' in stages and stages[-1] == 'submission_unknown'
