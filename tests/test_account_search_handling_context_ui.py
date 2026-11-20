from types import SimpleNamespace

import pytest

from src.web import account_exception_notice as notice


def test_search_context_renders_same_bound_resolver_result(monkeypatch):
    calls, captions = [], []
    row = {'account_uuid': 'account:a', 'account_key': 'account01'}
    data = {'controls': []}
    def resolve(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(source='recorded_research_keyword',
            message='已记录关键词入口；不是精确失败查询。')
    monkeypatch.setattr('src.operations_accounts.manual_handling.resolve_manual_handling_target', resolve)
    monkeypatch.setattr(notice.st, 'caption', captions.append)
    notice._render_handling_context(row, data)
    assert calls == [dict(account_uuid='account:a', account_key='account01', snapshot=data)]
    assert '不是精确失败查询' in captions[0]
    assert '原搜索仍可能' in captions[1]


def test_context_read_failure_does_not_claim_search_or_healthy(monkeypatch):
    captions = []
    def fail(**kwargs):
        raise OSError('receipt unavailable')
    monkeypatch.setattr('src.operations_accounts.manual_handling.resolve_manual_handling_target', fail)
    monkeypatch.setattr(notice.st, 'caption', captions.append)
    notice._render_handling_context({'account_uuid':'account:a','account_key':'account01'}, {})
    assert captions == ['原异常处理停点暂不可读取；当前无法确认具体失败页面，请核对后台记录。']


def test_new_incident_explains_prior_successful_completion(monkeypatch):
    captions = []
    monkeypatch.setattr(notice.st, 'caption', captions.append)
    notice._render_previous_recovery({'account_uuid':'account:a','account_key':'account01','created_at':200},
        {'handling_requests':[dict(account_uuid='account:a',account_key='account01',status='completed',finished_at=100)]})
    assert len(captions) == 1 and '通过原身份核验' in captions[0] and '该请求之后' in captions[0]


@pytest.mark.parametrize('change', [dict(account_uuid='account:b'), dict(account_key='account02'),
    dict(status='probing'), dict(finished_at=300), dict(finished_at=float('nan')),dict(finished_at=True)])
def test_prior_success_needs_same_account_completed_earlier_request(monkeypatch, change):
    captions = []
    monkeypatch.setattr(notice.st, 'caption', captions.append)
    request = dict(account_uuid='account:a',account_key='account01',status='completed',finished_at=100)
    request.update(change)
    notice._render_previous_recovery({'account_uuid':'account:a','account_key':'account01','created_at':200},
        {'handling_requests':[request]})
    assert not captions
