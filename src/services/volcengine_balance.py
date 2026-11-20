"""Read-only account money balance, separate from Ark inference token usage."""
import importlib.util
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
CREDENTIAL_FIELDS = ('VOLCENGINE_ACCESS_KEY', 'VOLCENGINE_SECRET_KEY')


def _credentials():
    values = {**dotenv_values(ROOT / '.env'), **os.environ}
    return tuple(str(values.get(key) or '').strip() for key in CREDENTIAL_FIELDS)


def credential_status():
    return {'configured': all(_credentials()),
            'sdk_installed': importlib.util.find_spec('volcenginesdkbilling') is not None}


def credential_scope():
    """Opaque cache scope; changing billing identity must not reuse another balance."""
    return hashlib.sha256('\0'.join(_credentials()).encode()).hexdigest()


def query_account_balance():
    ak, sk = _credentials()
    if not ak or not sk:
        raise ValueError('请在项目 .env 填写 VOLCENGINE_ACCESS_KEY 和 VOLCENGINE_SECRET_KEY；ARK_API_KEY 不能代替它们。')
    try:
        import volcenginesdkcore
        from volcenginesdkbilling import BILLINGApi, QueryBalanceAcctRequest
    except ImportError:
        raise ValueError('尚未安装余额查询 SDK：运行 pip install -r requirements-volcengine.txt') from None
    config = volcenginesdkcore.Configuration()
    config.ak, config.sk, config.region = ak, sk, 'cn-beijing'
    config.debug = False
    config.auto_retry = False
    client = volcenginesdkcore.ApiClient(config)
    try:
        response = BILLINGApi(client).query_balance_acct(QueryBalanceAcctRequest(), _request_timeout=20)
        values = response.to_dict()
    except Exception as exc:
        code = None
        try:
            body = json.loads(getattr(exc, 'body', '') or '{}')
            code = body.get('ResponseMetadata', {}).get('Error', {}).get('Code')
        except (ValueError, AttributeError):
            pass
        detail = f'HTTP {getattr(exc, "status", "未知")} / {code or type(exc).__name__}'
        detail = detail.replace(ak, '[redacted]').replace(sk, '[redacted]')
        raise ValueError(f'账户余额查询失败：{detail}。如无权限，请检查费用中心只读权限。') from None
    finally:
        client.rest_client.pool_manager.clear()
    fields = ('account_id', 'available_balance', 'cash_balance', 'arrears_balance', 'credit_limit', 'freeze_amount')
    return {'schema': 'volcengine_account_balance/v1', 'source': 'QueryBalanceAcct',
            'queried_at': datetime.now(timezone.utc).isoformat(),
            **{name: values.get(name) for name in fields}}
