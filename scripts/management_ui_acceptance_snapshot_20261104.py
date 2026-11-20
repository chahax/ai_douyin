"""Read-only original-ID evidence. Writes only the management audit directory."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'data/development_checkpoints/management_ui_audit_20261104'


def readonly(name):
    db = sqlite3.connect((ROOT / 'data' / name).as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return closing(db)


def main():
    import psutil
    from src.operations_accounts import browser_control_runtime as bridge
    from src.operations_accounts import manual_boot_closure
    pid = int((ROOT / 'data/logs/streamlit_web.pid').read_text().strip())
    backend = psutil.Process(pid)
    expected = ROOT / 'scripts/run_streamlit_web.py'
    assert any(Path(arg).resolve() == expected for arg in backend.cmdline()[1:])
    boot = dict(boot_time=psutil.boot_time(), backend_pid=pid, backend_create_time=backend.create_time())
    account_id = 'account:9e5f9e75192fa45becb945bc'
    command_id = '10b2bcfbba84499b93ad1a9891ec0226'
    store = bridge._store()
    # Only local preview uses the verified canonical backend identity; this does
    # not patch the running backend or invoke the mutating closure function.
    with patch.object(manual_boot_closure, '_boot_evidence', lambda: boot):
        proposal = manual_boot_closure.preview(store, account_id, 'account01', command_id,
                                              bridge._manual_binding_version(account_id, 'account01'))
    with readonly('account_browser_control.db') as db:
        command = dict(db.execute('SELECT command_id,state,updated_at FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone())
        owner = dict(db.execute('SELECT account_id,owner_id,generation,state,heartbeat FROM browser_control_owners WHERE account_id=?', (account_id,)).fetchone())
    result = dict(method='read_only_proposal_not_executed', captured_at=time.time(), account_key='account01',
                  command=command, owner=owner, proof_sha=proposal['proof_sha'], eligible=proposal['available'],
                  boot_evidence=boot, identity_verified=False, account_resumed=False, production_mutation=False)
    (OUT / 'PREBOOT_PLAN_READONLY_FINAL.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'eligible': proposal['available'], 'original_state': command['state'],
                      'production_mutation': False}))


if __name__ == '__main__':
    main()
