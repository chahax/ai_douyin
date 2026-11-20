"""Creation-only naming rules; old flow reads never become new submissions."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace as NS

import pytest

from src.services.fanqie_alias_flow_v1 import AliasFlow, VERSION, validate_candidate_aliases


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('prepare/status must never start external work')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    binding = dict(resource_id='fanqie:prepare-test', binding_version='v',
        platform_identity_key='uid:test', environment_key='env',
        douyin_account_uuid='account:test', account_link_version='link')
    media = save(tmp_path/'media.mp4', 'protocol fixture only; no codecs')
    frozen = dict(book_id='1234567890123456780', book_name='测试小说',
        account=dict(account_uuid='account:test'), media=media)
    calls = []
    def queue(*args, **kwargs):
        calls.append((args, kwargs))
        forbidden()
    workspace = NS(path=tmp_path/'p0.db', accounts=NS(db=tmp_path/'browser.db'),
        _resource_binding=lambda resource: binding,
        _candidates=lambda: NS(get=lambda cid: dict(frozen_json=json.dumps(frozen))),
        sync=queue, apply=queue)
    def spec(aliases, observed=None):
        intent = dict(resource_binding=binding, backend=dict(ledger_path=str(workspace.path.resolve()),
            browser_db=str(workspace.accounts.db.resolve())),
            book=dict(book_id=frozen['book_id'], book_name=frozen['book_name'],
                publish_type='AIGC', promotion_path='别名推广'),
            aliases=aliases, observe_aliases=observed or [],
            candidate=dict(candidate_id='fixture-candidate', media=media), original_records=[])
        auth = save(tmp_path/'AUTH.json', dict(schema='fanqie_alias_flow_authorization/v1',
            confirmed_by='user', user_statement='isolated fixture', intent=intent,
            max_submissions=len(aliases)))
        return save(tmp_path/'SPEC.json', dict(schema=VERSION, authorization=auth, **intent))
    def flow(name='flow'):
        return AliasFlow(tmp_path/name, workspace=workspace, command_reader=forbidden)
    return NS(root=tmp_path, spec=spec, flow=flow, calls=calls)


@pytest.mark.parametrize('alias', ['甲乙丙丁', '甲乙丙丁戊己庚辛', '1234', '12345678', '甲乙12'])
def test_four_eight_and_ascii_digit_candidates_prepare_without_any_queue(fixture, alias):
    assert validate_candidate_aliases([alias]) == [alias]
    state = fixture.flow().prepare(fixture.spec([alias]))
    assert state['phase'] == 'need_sync' and state['operations'] == []
    assert fixture.calls == []


@pytest.mark.parametrize('alias', ['六双筷子的改命日记', '甲乙丙', '甲乙丙。', 'ABCD', '１２３４', '甲乙 丙丁'])
def test_invalid_new_candidates_leave_no_plan_state_or_queue(fixture, alias):
    binding = fixture.spec([alias])
    with pytest.raises(ValueError, match='alias_candidates_require_4_to_8_common_Han_or_ASCII_digits'):
        fixture.flow().prepare(binding)
    assert not (fixture.root/'flow/PLAN.json').exists()
    assert not (fixture.root/'flow/STATE.json').exists()
    assert fixture.calls == []


def test_observe_only_alias_can_retain_nine_characters_without_new_application(fixture):
    state = fixture.flow().prepare(fixture.spec(['甲乙丙丁'], ['六双筷子的改命日记']))
    assert state['operations'] == [] and fixture.calls == []


def test_preexisting_nine_character_plan_status_and_prepare_reentry_stay_readonly(fixture):
    # An actual old schema v1 allowed these words. Model its persisted record,
    # without trying to create the now-disallowed word under the new policy.
    binding = fixture.spec(['六双筷子的改命日记'])
    historical = dict(schema=VERSION, spec=binding, phase='outcome_unknown',
        alias_index=0, operations=[], reconciliation=True, last_application=None,
        media_calls=0, published=False, updated_at=1000)
    save(fixture.root/'flow/PLAN.json', dict(schema=VERSION, spec=binding))
    # Existing immutable PLAN bytes were written in the historical formatter.
    (fixture.root/'flow/PLAN.json').write_bytes(json.dumps(dict(schema=VERSION, spec=binding),
        ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8'))
    save(fixture.root/'flow/STATE.json', historical)
    before = (fixture.root/'flow/STATE.json').read_bytes()
    assert fixture.flow().status() == historical
    assert fixture.flow().prepare(binding) == historical
    assert (fixture.root/'flow/STATE.json').read_bytes() == before
    assert fixture.calls == []
