"""Add the requested novel-account Fanqie environment; never confirm its identity."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.operations_accounts.fanqie_account_control import FanqieAccounts, write_json


def snapshot(accounts):
    with closing(sqlite3.connect(accounts.douyin_db.as_uri()+'?mode=ro',uri=True)) as db:
        rows=db.execute('SELECT account_uuid,account_key,platform_identity_key,browser_environment_key,browser_profile_dir,created_at,status FROM account_runtime_bindings ORDER BY account_uuid').fetchall()
    return {'bindings':rows,'sha256':hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()}


if __name__=='__main__':
    a=FanqieAccounts()
    before=snapshot(a)
    migration=a.install()
    env=a.create('小说号番茄专属环境','novel_account_02')
    after=snapshot(a)
    if before!=after:
        raise RuntimeError('Douyin bindings changed during provisioning; inspect before continuing')
    result={'migration':migration,'environment':env,'douyin_bindings_unchanged':True,
            'douyin_bindings':before,'fanqie_binding':a.bindings().get(env['resource_id']),
            'platform_operations':0,'model_calls':0}
    write_json(a.evidence/'PROVISION_20261024.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
