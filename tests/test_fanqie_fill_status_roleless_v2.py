"""Only the observed public Arco div.link shape; historical v1 is unchanged."""
from copy import deepcopy
from pathlib import Path

import pytest

from test_fanqie_fill_status_v1 import browser, put, read, ref, ROOT
from src.operations_accounts import fanqie_managed_promotion_v1 as managed
from src.platform_adapter import fanqie_fill_status_v1 as fill
from src.services import fanqie_promotion_identity_v2 as native

ACTUAL = ROOT / 'data/fanqie_account_control/commands/7e2314a74ce442fd8685f4574ec8234c'


def collect(browser, *, action_class='link', cursor='pointer', events='auto', shared=True):
    status = '<div>未填写</div>'
    action = '<div class="' + action_class + '" style="cursor:' + cursor + ';pointer-events:' + events + '">回填发文</div>'
    wrap = lambda body: '<span class="arco-table-cell-wrap-value">' + body + '</span>'
    body = wrap(status + action) if shared else wrap(status) + wrap(action)
    page = browser.new_page()
    try:
        page.set_content('<table><thead><tr><th>关键词</th><th>书本信息</th><th>发文类型</th><th>别名状态</th>'
            '<th>书籍状态</th><th>发文详情</th></tr></thead><tbody><tr><td>从旧饭桌开始改命</td>'
            '<td><div class="book-name-test">你敢惹我？我有六个反派儿子</div>id:7302660145530539062</td>'
            '<td>AIGC</td><td>生效中</td><td>可用</td><td class="arco-table-td"><div class="arco-table-cell">'
            + body + '</div></td></tr></tbody></table>')
        return page.evaluate(managed.LIST_JS)['items'][0]
    finally:
        page.close()


def test_observed_roleless_div_link_requires_exact_public_proof(browser):
    row = collect(browser)
    proof = row['fill_status_evidence']
    assert proof['schema'] == 'fanqie_fill_status_evidence/v2'
    assert proof['canonical_status'] == row['fill_status'] == '未填写'
    assert proof['status_texts'] == ['未填写']
    assert proof['controls'] == [{'tag': 'div', 'role': '', 'text': '回填发文', 'visible': True}]
    assert fill.normalize_row(row)[0] == '未填写'
    for mutate in (
        lambda p: p['roleless_action_evidence'][0]['action_leaf']['ancestors'][0].update(cursor='auto'),
        lambda p: p['roleless_action_evidence'][0].update(shared_status_parent=False),
        lambda p: p['roleless_action_evidence'][0]['status_leaf']['ancestors'][1].update(class_name='different'),
    ):
        changed = deepcopy(proof)
        mutate(changed)
        with pytest.raises(ValueError):fill.validate_evidence(changed)


def test_roleless_text_class_cursor_events_or_other_parent_do_not_get_guessed(browser):
    for updates in ({'action_class': 'other'}, {'cursor': 'auto'}, {'events': 'none'}, {'shared': False}):
        row = collect(browser, **updates)
        assert row['fill_status_evidence']['canonical_status'] is None
        assert fill.normalize_row(row)[0] != '未填写'


def test_actual_7e23_v1_proof_remains_unrecognized_on_full_native_replay():
    path = ACTUAL / 'native_alias_sync/native_v2/PROMOTION_SNAPSHOT_V2.json'
    before = ref(path)
    assert before['sha256'] == '13225b74cd829710fe61f8a71b0d0b1ddff6d09559dc403acf0ea7c484670c9e'
    value = read(path)
    assert native.validate_snapshot(value) == value
    row = value['rows'][0]
    assert row['fill_status_evidence']['schema'] == fill.SCHEMA
    assert row['fill_status_evidence']['canonical_status'] is None
    assert fill.normalize_row(row)[0] == '未填写 回填发文'
    assert ref(path) == before


def test_new_v2_roleless_proof_roundtrips_native_join_without_rewriting_history(browser, tmp_path):
    fresh = collect(browser)
    fixture = deepcopy(read(ACTUAL / 'LIST_BEFORE_RAW.json'))
    for item in (fixture['raw']['items'][0], fixture['raw']['pages'][0]['items'][0]):
        item['fill_status'], item['fill_status_evidence'] = fresh['fill_status'], fresh['fill_status_evidence']
    raw_ref = put(tmp_path / 'PRIVATE_RAW.json', fixture)
    legacy = managed.normalise_snapshot(fixture['raw'], **fixture['subject'], evidence_ref=raw_ref,
        normalizer_version=fixture['normalizer_version'])
    legacy_ref = put(tmp_path / 'PRIVATE_LEGACY.json', legacy)
    assert managed.validate_snapshot(legacy) == legacy
    old_native = read(ACTUAL / 'native_alias_sync/native_v2/NATIVE_ALIAS_EVIDENCE_V2.json')
    result_ref = native.prepare_snapshot(legacy_ref, old_native['observation'], tmp_path / 'native',
        managed_subject=old_native['managed_subject'])
    value = read(Path(result_ref['path']))
    assert native.validate_snapshot(value) == value
    row = value['rows'][0]
    assert row['native_record_id'] == '7708816622072381502' and row['fill_status'] == '未填写'
    assert row['fill_status_evidence']['schema'] == fill.SCHEMA_V2
    assert row['published_links'] == [] and row['publishable'] is True
