"""A frequent control admission read must not contend for a business write lock."""
import sqlite3

from src.operations_accounts import AccountProfile, AccountProfileRepository, AccountBindingRepository, stable_account_uuid


def setup_repo(tmp_path):
    db = tmp_path/'accounts.db'
    profiles = AccountProfileRepository(db)
    profile = profiles.save(AccountProfile(account_uuid=stable_account_uuid('fixture'),
        account_key='fixture', display_name='fixture', domain_strategy_id='legal_services',
        seed_keywords=['法律'], domain_config={'practice_areas':['婚姻家事']}))
    return AccountBindingRepository(db), profile.account_uuid


def test_existing_runtime_state_is_readable_while_another_writer_holds_lock(tmp_path):
    repo, account = setup_repo(tmp_path)
    initial = repo.get_runtime_state(account)
    with sqlite3.connect(repo.db_path) as writer:
        writer.execute('BEGIN IMMEDIATE')
        writer.execute('UPDATE account_runtime_state SET daily_runs=17 WHERE account_uuid=?', (account,))
        observed = repo.get_runtime_state(account)
        assert observed.daily_runs == initial.daily_runs
        writer.rollback()
    assert repo.get_runtime_state(account) == initial


def test_missing_runtime_state_is_initialized_once_and_existing_state_preserved(tmp_path):
    repo, account = setup_repo(tmp_path)
    first = repo.get_runtime_state(account)
    second = repo.get_runtime_state(account)
    assert first == second
    with repo.connection() as db:
        assert db.execute('SELECT count(*) FROM account_runtime_state WHERE account_uuid=?', (account,)).fetchone()[0] == 1
