from __future__ import annotations

import hashlib
import json

import pytest

from src.trend_intelligence.content_analysis.source_synthesis_json import parse_source_synthesis_json


def _reconstruct(raw, metadata):
    repaired = raw
    for offset in reversed(metadata["insertion_offsets"]):
        repaired = repaired[:offset] + metadata["inserted_character"] + repaired[offset:]
    return repaired


def test_valid_json_is_not_repaired_or_normalized():
    raw = ' {"claims":[{"text":"合法\\\"台词\\\"", "evidence_ids":["A0001"]}]} '
    parsed, metadata = parse_source_synthesis_json(raw)
    assert parsed == json.loads(raw)
    assert metadata is None


def test_chinese_words_quotes_and_existing_escapes_are_preserved_exactly():
    raw = r'{"claims":[{"text":"原告说"我没同意"，随后引用\"既有台词\"和\\路径","evidence_ids":["A0001","V0002"]}]}'
    parsed, metadata = parse_source_synthesis_json(raw)
    assert parsed["claims"][0]["text"] == '原告说"我没同意"，随后引用"既有台词"和\\路径'
    assert parsed["claims"][0]["evidence_ids"] == ["A0001", "V0002"]
    repaired = _reconstruct(raw, metadata)
    assert r'\"既有台词\"和\\路径' in repaired
    assert metadata["inserted_escape_count"] == 2
    assert metadata["original_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert metadata["repaired_sha256"] == hashlib.sha256(repaired.encode()).hexdigest()
    assert metadata["semantic_or_schema_validation_performed"] is False
    assert json.loads(repaired) == parsed


def test_multiple_adjacent_text_fields_repair_only_internal_quote_offsets():
    raw = '{"claims":[{"text":"甲说"原句甲"。","evidence_ids":["A0001"]},{"text":"乙说"原句乙"。","evidence_ids":["A0002"]}],"uncertainties":["原片未核验"]}'
    parsed, metadata = parse_source_synthesis_json(raw)
    assert [row["text"] for row in parsed["claims"]] == ['甲说"原句甲"。', '乙说"原句乙"。']
    assert parsed["uncertainties"] == ["原片未核验"]
    assert metadata["inserted_escape_count"] == 4
    assert all(raw[offset] == '"' for offset in metadata["insertion_offsets"])


def test_existing_json_escape_sequence_is_retained_in_repaired_raw():
    raw = r'{"claims":[{"text":"第一行\n第二行说"台词"以及\u5408\u540c","evidence_ids":["A0001"]}]}'
    parsed, metadata = parse_source_synthesis_json(raw)
    assert parsed["claims"][0]["text"] == '第一行\n第二行说"台词"以及合同'
    assert r'第一行\n' in _reconstruct(raw, metadata)
    assert r'\u5408\u540c' in _reconstruct(raw, metadata)


def test_whole_fenced_document_is_preserved_in_repair_provenance():
    raw = '```json\n{"text":"引用"台词"。","evidence_ids":["A0001"]}\n```'
    parsed, metadata = parse_source_synthesis_json(raw)
    repaired = _reconstruct(raw, metadata)
    assert parsed["text"] == '引用"台词"。'
    assert repaired.startswith('```json\n') and repaired.endswith('\n```')
    assert metadata["original_sha256"] == hashlib.sha256(raw.encode()).hexdigest()


@pytest.mark.parametrize("raw", [
    '{"text":"原话"台词"。","unknown":"额外字段","evidence_ids":["A0001"]}',
    '{"text":"原话"台词"，随后是 { JSON } 片段","evidence_ids":["A0001"]}',
    '{"text":"原话"台词"，随后是 [ 数组 ] 片段","evidence_ids":["A0001"]}',
    '{"text":"原话"key":"value"。","evidence_ids":["A0001"]}',
    '{"text":"原话"台词"。","evidence_ids":["A0001"]',
    '{"text":"原话"台词"。","evidence_ids":"A0001"}',
    '{"text":123"台词","evidence_ids":["A0001"]}',
    '{"text":"原话"未闭合。","evidence_ids":["A0001"]}',
    '{"text":"原话" "后续","evidence_ids":["A0001"]}',
    '{"text":"原话" true "后续","evidence_ids":["A0001"]}',
    '{"text":"原话" 123 "后续","evidence_ids":["A0001"]}',
    '{"text":"原话" + "后续","evidence_ids":["A0001"]}',
    '{"text":"原话"English only"后续","evidence_ids":["A0001"]}',
    '{"text":"原话"台词"\n未转义换行","evidence_ids":["A0001"]}',
    '{"goal":"原话"台词"。","evidence_ids":["A0001"]}',
    '{"text":"原话"台词"。","evidence_ids":["A0001"]} 未知尾部',
    '```json\n{"text":"原话"台词"。","evidence_ids":["A0001"]}\n``` 未知尾部',
    '{"text":"原话"台词"。","evidence_ids":["A0001"],"evidence_ids":["V9999"]}',
    '{"text":"原话"台词"。","evidence_ids":["A0001"]} {"extra":true}',
    r'{"text":"原话"台词"以及\q错误转义","evidence_ids":["A0001"]}',
])
def test_ambiguous_cross_field_truncated_or_wrong_type_inputs_are_not_repaired(raw):
    with pytest.raises((json.JSONDecodeError, ValueError)):
        parse_source_synthesis_json(raw)


def test_unknown_fields_outside_repaired_text_survive_for_later_schema_validation():
    raw = '{"claims":[{"text":"引用"台词"。","evidence_ids":["A0001"]}],"unexpected":{"keep":"不能吞掉"}}'
    parsed, metadata = parse_source_synthesis_json(raw)
    assert parsed["unexpected"] == {"keep": "不能吞掉"}
    assert '"unexpected":{"keep":"不能吞掉"}' in _reconstruct(raw, metadata)


def test_unrelated_error_after_repaired_text_still_fails_without_tail_clipping():
    raw = '{"text":"引用"台词"。","evidence_ids":["A0001"],"other":"还有"错误""}'
    with pytest.raises(json.JSONDecodeError):
        parse_source_synthesis_json(raw)
