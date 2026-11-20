"""Freeze an explicit account at enqueue time and reject stale bindings on execution."""
from src.operations_accounts import AccountProfileRepository, AccountBindingRepository


def freeze_task_scope(params: dict) -> dict:
    result = dict(params)
    key = result.get('account_key')
    if not key:
        return result
    profiles = AccountProfileRepository()
    profile = profiles.get(key)
    if profile.status != 'active':
        raise ValueError('任务账号已暂停或停用')
    if result.get('account_uuid') and result['account_uuid'] != profile.account_uuid:
        raise ValueError('任务账号标识与 UUID 不一致')
    binding = AccountBindingRepository(profiles.db_path).get_optional(key)
    result['_frozen_account_scope'] = dict(account_uuid=profile.account_uuid, account_key=key,
        profile_version=profile.profile_version,
        platform_identity_key=binding.platform_identity_key if binding else '')
    return result


def validate_task_scope(params: dict) -> dict:
    result = dict(params)
    frozen = result.pop('_frozen_account_scope', None)
    if not result.get('account_key'):
        if frozen:
            raise ValueError('任务账号参数缺失')
        return result
    if not frozen:
        raise ValueError('旧任务缺少账号快照，请核对后重新入队')
    current = freeze_task_scope(result)['_frozen_account_scope']
    if current != frozen:
        raise ValueError('任务账号绑定或策略版本已变化，请核对后重新入队')
    return result
