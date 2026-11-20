import pytest

from src.services import volcengine_balance as balance


def test_inference_key_is_not_a_management_credential(monkeypatch, tmp_path):
    monkeypatch.setattr(balance, 'ROOT', tmp_path)
    for name in balance.CREDENTIAL_FIELDS:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / '.env').write_text('ARK_API_KEY=private-inference-key\n')
    assert balance.credential_status()['configured'] is False
    with pytest.raises(ValueError, match='VOLCENGINE_ACCESS_KEY'):
        balance.query_account_balance()


def test_sdk_balance_query_preserves_zero_and_missing_fields(monkeypatch):
    billing = pytest.importorskip('volcenginesdkbilling')
    monkeypatch.setattr(balance, '_credentials', lambda: ('private-ak', 'private-sk'))
    def query(self, request, **kwargs):
        assert self.api_client.configuration.ak == 'private-ak'
        assert kwargs['_request_timeout'] == 20
        assert self.api_client.configuration.debug is False
        return billing.QueryBalanceAcctResponse(available_balance='0.00')
    monkeypatch.setattr(billing.BILLINGApi, 'query_balance_acct', query)
    result = balance.query_account_balance()
    assert result['available_balance'] == '0.00' and result['cash_balance'] is None
    assert result['source'] == 'QueryBalanceAcct' and 'private-' not in str(result)


def test_sdk_errors_do_not_echo_credentials(monkeypatch):
    billing = pytest.importorskip('volcenginesdkbilling')
    monkeypatch.setattr(balance, '_credentials', lambda: ('private-ak', 'private-sk'))
    def query(*args, **kwargs):
        raise RuntimeError('private-ak private-sk')
    monkeypatch.setattr(billing.BILLINGApi, 'query_balance_acct', query)
    with pytest.raises(ValueError) as error:
        balance.query_account_balance()
    assert 'private-' not in str(error.value)
