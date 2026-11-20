"""Only an authorized exact work receives one UI comment submit."""
from types import SimpleNamespace
import pytest

from src.operations_accounts.publication_comment import post_authorized_publication_comment

POST = '7681138441245269931'


class Page:
    url = f'https://www.douyin.com/video/{POST}'
    def __init__(self, *, uncertain=False):
        self.text = ''; self.clicks = 0; self.uncertain = uncertain
    def locator(self, selector):
        page = self
        class Locator:
            def count(self): return 0 if selector == '[data-e2e="video-detail"]' else 1
            def fill(self, text): page.text = text
            def click(self):
                page.clicks += 1
                if page.uncertain: raise TimeoutError('unknown click outcome')
            def evaluate(self, script):
                if script.startswith('n =>'): return page.text
                if 'data-e2e="comment-item"' in script:
                    return [{'text':page.text, 'id':'fixture-comment'}] if page.clicks else []
                if 'return {found:' in script: return {'found':True}
                return True
        return Locator()
    def wait_for_timeout(self, ms): pass


def adapter_for(page):
    return SimpleNamespace(runtime_context=SimpleNamespace(account_key='account01', account_uuid='fixture:one'),
        _require_runtime_identity=lambda **kw: None, session=SimpleNamespace(open_page=lambda url: page))


def command():
    return {'account_key':'account01', 'account_uuid':'fixture:one', 'authorization':'explicit_fixture_user',
            'comment':'剧情含义说明', 'publish_evidence':{'verified':True, 'expected_post_id':POST}}


def test_visible_comment_has_one_durable_submit_and_repeat_only_returns_receipt(tmp_path):
    page = Page(); adapter = adapter_for(page)
    first = post_authorized_publication_comment(adapter, command(), POST, receipt_dir=tmp_path)
    second = post_authorized_publication_comment(adapter, command(), POST, receipt_dir=tmp_path)
    assert first == second and first['status'] == 'sent_visible'
    assert first['submission_lock_retained'] and page.clicks == 1


def test_uncertain_click_keeps_claim_and_never_clicks_again(tmp_path):
    page = Page(uncertain=True); adapter = adapter_for(page)
    first = post_authorized_publication_comment(adapter, command(), POST, receipt_dir=tmp_path)
    second = post_authorized_publication_comment(adapter, command(), POST, receipt_dir=tmp_path)
    assert first == second and first['status'] == 'outcome_unknown'
    assert first['submitted'] is None and page.clicks == 1


@pytest.mark.parametrize('change', [{'account_uuid':'fixture:other'}, {'authorization':''},
                                   {'publish_evidence':{'verified':True,'post_id':'other'}}])
def test_comment_requires_exact_approval_account_and_work_before_browser(change, tmp_path):
    frozen = {**command(), **change}
    adapter = adapter_for(Page())
    adapter.session.open_page = lambda url: pytest.fail('Must reject before platform navigation')
    with pytest.raises(ValueError):
        post_authorized_publication_comment(adapter, frozen, POST, receipt_dir=tmp_path)
