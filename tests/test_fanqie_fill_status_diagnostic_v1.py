"""Read-only diagnostic projection; it deliberately does not recognize actions."""
from pathlib import Path

from test_fanqie_fill_status_v1 import browser, collect, read, ref, ROOT
from src.platform_adapter import fanqie_fill_status_v1 as fill
from src.services import fanqie_promotion_identity_v2 as native


def test_roleless_action_records_bounded_public_ancestors_without_changing_status(browser):
    row = collect(browser, '<div class="layout"><span>未填写</span>'
        '<span class="action-label cursor-pointer" style="cursor:pointer;pointer-events:auto" tabindex="0">回填发文</span></div>')
    proof = row['fill_status_evidence']
    assert proof['canonical_status'] is None and proof['controls'] == []
    assert proof['status_texts'] == ['未填写', '回填发文']
    assert fill.normalize_row(row)[0] == '未填写回填发文'
    structure = proof['cell_structure']
    assert structure['react_or_private_state_read'] is False
    assert structure['public_dom_attributes_only'] is True
    leaf = [x for x in structure['leaves'] if x['text'] == '回填发文'][0]
    ancestor = leaf['ancestors'][0]
    assert ancestor['tag'] == 'span' and ancestor['role'] == '' and ancestor['tabindex'] == '0'
    assert ancestor['cursor'] == 'pointer' and ancestor['pointer_events'] == 'auto'
    assert ancestor['class_name'] == 'action-label cursor-pointer'
    assert leaf['boundary_reached'] is True


def test_actual_7814_without_optional_diagnostic_keeps_original_snapshot_semantics():
    path = ROOT / 'data/fanqie_account_control/commands/78141421d64f4457aaba7c7f4d69e1b1/native_alias_sync/native_v2/PROMOTION_SNAPSHOT_V2.json'
    before = ref(path)
    assert before['sha256'] == '9bba047f8d5d443c3edf91d81193dfa69cfbac085f84fef3be5b13d8b78b9edc'
    value = read(path)
    assert native.validate_snapshot(value) == value
    target = value['rows'][0]
    assert 'cell_structure' not in target['fill_status_evidence']
    assert fill.normalize_row(target)[0] == '未填写 回填发文'
    assert target['fill_status_evidence']['canonical_status'] is None
    assert ref(path) == before
