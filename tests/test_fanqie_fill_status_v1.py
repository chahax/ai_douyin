"""Actual historical evidence replay plus isolated Chrome cell semantics."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.operations_accounts import fanqie_managed_promotion_v1 as managed
from src.platform_adapter import fanqie_fill_status_v1 as fill
from src.services import fanqie_promotion_identity_v2 as native

ROOT = Path(__file__).resolve().parents[1]
ACTUAL = ROOT / 'data/fanqie_account_control/commands/09aef92272cb4bbaab0ed734d449c3d8/native_evidence_001'


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def ref(path):
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    return ref(path)


@pytest.fixture(scope='module')
def browser(tmp_path_factory):
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(tmp_path_factory.mktemp('chrome')),
            channel='chrome', headless=True, args=['--mute-audio', '--disable-background-networking'])
        context.route('**/*', lambda route: route.abort())
        yield context
        context.close()


def collect(browser, cell):
    page = browser.new_page()
    try:
        page.set_content('''<table><thead><tr><th>关键词</th><th>书本信息</th><th>发文类型</th>
            <th>别名状态</th><th>书籍状态</th><th>发文详情</th><th>有效期</th></tr></thead><tbody><tr>
            <td>从旧饭桌开始改命</td><td><span class="book-name-test">你敢惹我？我有六个反派儿子</span>
            <span>id: 7302660145530539062</span></td><td>AIGC</td><td>生效中</td><td>可用</td><td>'''
            + cell + '</td><td>2026-11-17～ 2027-05-16</td></tr></tbody></table>')
        raw = page.evaluate(managed.LIST_JS)
        assert raw['table_ready'] is True and len(raw['items']) == 1
        return raw['items'][0]
    finally:
        page.close()


@pytest.mark.parametrize('cell,expected', [
    ('<span>未填写</span> <a href="javascript:void(0)">回填发文</a>', '未填写'),
    ('未填写', '未填写'),
    ('未填写 回填发文', None),
    ('<span>未填写</span><span>已填写</span><button>回填发文</button>', None),
    ('<span>未填写</span><span>未填写</span><button>回填发文</button>', None),
    ('<span>未填写</span><button>删除</button>', None),
    ('<span hidden>未填写</span><button>回填发文</button>', None),
    ('<span>未填写</span><button>回填发文</button><button>回填发文</button>', None),
])
def test_real_chrome_status_and_button_are_separate(browser, cell, expected):
    row = collect(browser, cell)
    proof = row['fill_status_evidence']
    assert proof['canonical_status'] == expected
    assert fill.validate_evidence(proof) == expected
    status, normalized = fill.normalize_row(row)
    assert normalized == proof
    assert status == (expected if expected is not None else proof['raw_visible_text'])
    if expected is None:
        assert status != '未填写'


def test_actual_e582_raw_replays_legacy_snapshot_without_new_semantics():
    raw_path, legacy_path = ACTUAL / 'LIST_BEFORE_RAW.json', ACTUAL / 'LEGACY_SNAPSHOT_V1.json'
    assert ref(raw_path)['sha256'] == 'e58286b05801ed7364c7c83ba4b2d71d4e1d091177ca982e7aea0f34c28d8581'
    envelope, frozen = read(raw_path), read(legacy_path)
    replay = managed.normalise_snapshot(envelope['raw'], **envelope['subject'],
        evidence_ref=frozen['evidence_ref'], normalizer_version=envelope['normalizer_version'])
    assert replay == frozen
    row = replay['rows'][0]
    assert row['fill_status'] == '未填写 回填发文' and 'fill_status_evidence' not in row
    assert managed.validate_snapshot(frozen) == frozen


def test_actual_da9_native_snapshot_preserves_original_digest_and_rows():
    path = ACTUAL / 'native_v2/PROMOTION_SNAPSHOT_V2.json'
    before = ref(path)
    assert before['sha256'] == 'da9ad909ac63683d8d962dd8b31d69e3cf4dadf59dcacc5086f1545f2a6dbecc'
    value = read(path)
    assert native.validate_snapshot(value) == value
    assert value['rows'][0]['fill_status'] == '未填写 回填发文'
    assert 'fill_status_evidence' not in value['rows'][0]
    assert ref(path) == before


def test_python_rejects_forged_or_unbound_status_proof(browser):
    hidden = collect(browser, '<div hidden>未填写</div>')
    assert hidden['fill_status_evidence']['canonical_status'] is None
    assert hidden['fill_status_evidence']['raw_visible_text'] == '未填写'
    assert hidden['fill_status'] == '未确认'
    assert fill.normalize_row(hidden)[0] == '未确认'
    row = collect(browser, '<span>未填写</span><button>回填发文</button>')
    for mutate in (
        lambda value: value['fill_status_evidence'].update(raw_visible_text='已填写 回填发文'),
        lambda value: value['fill_status_evidence'].update(status_texts=['未填写', '已填写']),
        lambda value: value['fill_status_evidence']['controls'][0].update(text='删除'),
        lambda value: value.update(fill_status='未知状态'),
    ):
        forged = deepcopy(row)
        mutate(forged)
        with pytest.raises(ValueError):fill.normalize_row(forged)


def test_new_proof_roundtrips_collector_legacy_and_native_v2(browser, tmp_path):
    fresh_row = collect(browser, '<span>未填写</span> <a role="link">回填发文</a>')
    original = read(ACTUAL / 'LIST_BEFORE_RAW.json')
    original_target = original['raw']['items'][0]
    assert fresh_row['alias'] == original_target['alias'] and fresh_row['book_id'] == original_target['book_id']
    # This is explicitly a private mixed fixture: actual account/native join
    # structure plus a new isolated Chrome cell, never a production observation.
    fixture = deepcopy(original)
    for item in [fixture['raw']['items'][0], fixture['raw']['pages'][0]['items'][0]]:
        item['fill_status'] = fresh_row['fill_status']
        item['fill_status_evidence'] = fresh_row['fill_status_evidence']
    raw_ref = put(tmp_path / 'RAW.json', fixture)
    legacy = managed.normalise_snapshot(fixture['raw'], **fixture['subject'], evidence_ref=raw_ref,
        normalizer_version=fixture['normalizer_version'])
    legacy_ref = put(tmp_path / 'LEGACY.json', legacy)
    assert managed.validate_snapshot(legacy) == legacy
    original_native_evidence = read(ACTUAL / 'native_v2/NATIVE_ALIAS_EVIDENCE_V2.json')
    result_ref = native.prepare_snapshot(legacy_ref, original_native_evidence['observation'], tmp_path / 'native',
        managed_subject=original_native_evidence['managed_subject'])
    result = read(Path(result_ref['path']))
    assert native.validate_snapshot(result) == result
    target = result['rows'][0]
    assert target['native_record_id'] == '7708816622072381502'
    assert target['fill_status'] == '未填写' and target['published_links'] == []
    assert target['fill_status_evidence'] == fresh_row['fill_status_evidence']
    assert target['publishable'] is True
