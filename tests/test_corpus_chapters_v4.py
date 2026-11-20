from copy import deepcopy
import hashlib

import pytest
from jsonschema import Draft202012Validator

from src.content_factory import corpus_chapters_v4 as material


def chapters(count=3, text=None):
    result = []
    for index in range(1, count + 1):
        value = text if text is not None else f"第{index}章 城里的旧屋。\r\n母亲走进屋里。\n\n孩子放下书。\n"
        result.append({"index": index, "title": f"第{index}章", "text": value,
                       "sha256": hashlib.sha256(value.encode()).hexdigest()})
    return result


def raw_chapter(source, plan, importance="supporting"):
    payload = material.chapter_payload(source, plan, "测试小说")
    return {"chapter_id": plan["id"], "chapter_index": plan["chapter_index"],
            "assignments": [{"passage_id": row["id"], "categories": ["character", "event"],
                             "importance": importance}
                            for row in payload["paragraph_index"] if row["scope"] == "core"]}


def index_fixture(count=3, importance="supporting"):
    source = chapters(count)
    plans = material.plan_chapters(source)
    analyses = [material.validate(raw_chapter(source, plan, importance), source, plan) for plan in plans]
    return source, plans, analyses, material.materials_index(analyses, source, plans, "测试小说")


@pytest.mark.parametrize("text", ["甲" * 15001, "甲\r\n\n乙\n" * 4,
                                  "\n\n  首段🙂𠮷\r\n第二段\t末尾\n\n", "无换行的小章节",
                                  "第一段。\u2028第二段。\n"],
                         ids=["long_unsplit", "blank_lines", "unicode_crlf", "one_paragraph", "unicode_newline"])
def test_natural_paragraphs_retain_all_original_characters(text):
    source = chapters(1, text)[0]
    passages = material.chapter_passages(source)
    assert "".join(row["text"] for row in passages) == text
    offset = 0
    for row in passages:
        assert row["start_offset"] == offset
        assert text[row["start_offset"]:row["end_offset"]] == row["text"]
        assert row["sha256"] == hashlib.sha256(row["text"].encode()).hexdigest()
        assert row["chapter_sha256"] == source["sha256"]
        offset = row["end_offset"]


def test_long_natural_paragraph_is_never_split_at_600_or_10000():
    source = chapters(1, "长" * 21000 + "\n另一段\n")[0]
    passages = material.chapter_passages(source)
    assert len(passages) == 2
    assert len(passages[0]["text"]) == 21001


def test_duplicate_paragraph_text_keeps_distinct_positions():
    passages = material.chapter_passages(chapters(1, "完全相同。\n" * 3)[0])
    assert len(passages) == 3
    assert len({row["sha256"] for row in passages}) == 1
    assert len({row["id"] for row in passages}) == 3
    assert len({row["start_offset"] for row in passages}) == 3


def test_one_author_chapter_per_plan_regardless_of_length():
    source = chapters(3, "正文" * 10000)
    plans = material.plan_chapters(source)
    assert [plan["chapter_indices"] for plan in plans] == [[1], [2], [3]]
    assert [plan["context_indices"] for plan in plans] == [[2], [1, 3], [2]]
    assert material.chapter_payload(source, plans[1])["core_chapter"]["text"] == source[1]["text"]


def test_payload_contains_complete_chapters_once_and_metadata_only_paragraphs():
    source = chapters(3)
    plan = material.plan_chapters(source)[1]
    payload = material.chapter_payload(source, plan)
    assert payload["core_chapter"]["text"] == source[1]["text"]
    assert payload["core_chapter"]["scope"] == "core"
    assert [row["text"] for row in payload["context_chapters"]] == [source[0]["text"], source[2]["text"]]
    assert all(row["scope"] == "context" for row in payload["context_chapters"])
    assert all("text" not in row for row in payload["paragraph_index"])
    assert all(row["scope"] == "core" and row["chapter_index"] == 2 for row in payload["paragraph_index"])
    assert all("sha256" not in row and "chapter_sha256" not in row for row in payload["paragraph_index"])
    def text_values(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "text":
                    yield child
                else:
                    yield from text_values(child)
        elif isinstance(value, list):
            for child in value:
                yield from text_values(child)
    assert sorted(text_values(payload)) == sorted(row["text"] for row in source)


def test_no_context_and_noncontiguous_author_indices_keep_source_order():
    source = chapters(3)
    source[1]["index"], source[2]["index"] = 7, 18
    plans = material.plan_chapters(source)
    assert plans[1]["context_indices"] == [1, 18]
    no_context = material.plan_chapters(source, context_neighbors=0)
    assert all(plan["context_indices"] == [] for plan in no_context)
    assert not material.chapter_payload(source, no_context[1])["context_chapters"]


def test_schema_exact_coverage_no_selection_requirement_and_no_shared_mutation():
    source = chapters(1, "自然段。\n" * 12)
    plan = material.plan_chapters(source)[0]
    payload = material.chapter_payload(source, plan)
    raw = raw_chapter(source, plan)
    schema = material.chapter_schema(plan, payload)
    Draft202012Validator(schema).validate(raw)
    assert len(raw["assignments"]) == 12
    assert "selected_core_passage_ids" not in schema["properties"]
    assert "selection_limit" not in payload
    assert schema["properties"]["assignments"]["maxItems"] == 12
    schema["properties"]["chapter_id"]["const"] = "changed"
    assert material.chapter_schema(plan, payload)["properties"]["chapter_id"]["const"] == plan["id"]
    assert material.validate(raw, source, plan)["validation"]["complete_author_chapter_classified"]


@pytest.mark.parametrize("mutation,match", [
    (lambda raw: raw["assignments"].pop(), "chapter_schema_invalid"),
    (lambda raw: raw["assignments"].append(deepcopy(raw["assignments"][0])), "duplicate_passage_assignment"),
    (lambda raw: raw["assignments"][0].update(passage_id="CH999-P001"), "unknown_passage_id"),
    (lambda raw: raw["assignments"][0].update(categories=["invented"]), "chapter_schema_invalid"),
    (lambda raw: raw["assignments"][0].update(categories=["world", "world"]), "chapter_schema_invalid"),
    (lambda raw: raw["assignments"][0].update(importance="discard"), "chapter_schema_invalid"),
    (lambda raw: raw.update(summary="虚构关系"), "chapter_schema_invalid"),
    (lambda raw: raw.update(chapter_index=2), "chapter_schema_invalid"),
])
def test_bad_or_extra_classification_is_rejected(mutation, match):
    source = chapters(3)
    plan = material.plan_chapters(source)[0]
    raw = raw_chapter(source, plan)
    mutation(raw)
    with pytest.raises(ValueError, match=match):
        material.validate(raw, source, plan)


def test_neighbour_cannot_be_classified_as_current_chapter():
    source = chapters(3)
    plan = material.plan_chapters(source)[1]
    raw = raw_chapter(source, plan)
    raw["assignments"][0]["passage_id"] = "CH1-P001"
    with pytest.raises(ValueError, match="context_passage_cannot_be_assigned"):
        material.validate(raw, source, plan)


def test_all_supporting_is_valid_and_cloud_still_contains_every_original_character():
    source, _, analyses, index = index_fixture(3)
    assert all(row["importance"] == "supporting" for item in analyses for row in item["assignments"])
    pack = material.cloud_input(index)
    assert pack["priority_passage_ids"] == []
    assert pack["limits"]["omitted_chars"] == 0
    assert pack["limits"]["compression_performed"] is False
    for chapter in source:
        assert "".join(row["text"] for row in pack["selected_core_passages"]
                       if row["chapter_index"] == chapter["index"]) == chapter["text"]


def test_importance_only_changes_priority_not_source_selection():
    source, plans, analyses, _ = index_fixture(2)
    raw = raw_chapter(source, plans[0])
    raw["assignments"][0]["importance"] = "core"
    analyses[0] = material.validate(raw, source, plans[0])
    index = material.materials_index(analyses, source, plans)
    pack = material.cloud_input(index)
    assert pack["priority_passage_ids"] == [raw["assignments"][0]["passage_id"]]
    assert len(pack["selected_core_passages"]) == 6
    assert pack["source_chars"] == sum(len(row["text"]) for row in source)


def test_all_69_chapters_produce_69_distinct_requests_and_lossless_pack():
    source, plans, _, index = index_fixture(69)
    assert len(plans) == 69
    assert sum(len(plan["chapter_indices"]) for plan in plans) == 69
    pack = material.cloud_input(index)
    assert pack["source_chapter_count"] == 69
    assert pack["limits"]["selected_core_chars"] == sum(len(row["text"]) for row in source)
    assert {row["chapter_index"] for row in pack["selected_core_passages"]} == set(range(1, 70))


@pytest.mark.parametrize("mutation", [
    lambda index: index["passage_catalog"][0].update(text="变造"),
    lambda index: index["passage_catalog"][0].update(start_offset=1),
    lambda index: index["classification_index"][0].update(chapter_id="wrong"),
    lambda index: index["classification_index"][0].update(included_in_cloud=False),
    lambda index: index["classification_index"].pop(),
    lambda index: index["selected_core_passage_ids"].pop(),
    lambda index: index["model_core_passage_ids"].append("CH1-P001"),
    lambda index: index["chapter_coverage"][0].update(source_chars=1),
    lambda index: index.update(source_digest="0" * 64),
    lambda index: index["policy"].update(compression_performed=True),
])
def test_tampered_index_cannot_enter_cloud(mutation):
    _, _, _, index = index_fixture()
    mutation(index)
    with pytest.raises(ValueError):
        material.cloud_input(index)


def test_cannot_omit_or_repeat_a_chapter_analysis():
    source, plans, analyses, _ = index_fixture()
    with pytest.raises(ValueError, match="chapter_set_mismatch"):
        material.materials_index(analyses[:-1], source, plans)
    with pytest.raises(ValueError, match="chapter_set_mismatch"):
        material.materials_index([*analyses, analyses[0]], source, plans)
    with pytest.raises(ValueError, match="coverage_incomplete"):
        material.materials_index(analyses[:-1], source, plans[:-1])


def test_analysis_original_binding_cannot_be_changed():
    source, plans, analyses, _ = index_fixture()
    analyses[0]["passage_catalog"][0]["text"] = "伪造正文"
    with pytest.raises(ValueError, match="materials_binding_mismatch"):
        material.materials_index(analyses, source, plans)


def test_over_capacity_rejects_without_truncating_any_original_text():
    source = chapters(3, "长段内容" * 5000)
    plan = material.plan_chapters(source)[1]
    payload = material.chapter_payload(source, plan)
    schema = material.chapter_schema(plan, payload)
    frozen_source, frozen_payload = deepcopy(source), deepcopy(payload)
    with pytest.raises(ValueError, match="complete_chapter_over_capacity"):
        material.ensure_capacity(payload, schema, context_tokens=65536)
    assert source == frozen_source and payload == frozen_payload
    assert len(payload["core_chapter"]["text"]) == 20000
    assert len([row for row in payload["paragraph_index"] if row["scope"] == "core"]) == 1


def test_capacity_success_reports_conservative_bound_not_measured_tokens():
    source = chapters(1)
    plan = material.plan_chapters(source)[0]
    payload = material.chapter_payload(source, plan)
    result = material.ensure_capacity(payload, material.chapter_schema(plan, payload), context_tokens=65536)
    assert result["required_bound"] <= 65536
    assert result["truncated"] is False
    assert "input_utf8_byte_bound" in result


def test_pack_remains_compatible_with_v3_source_bound_framework():
    from src.content_factory.corpus_production_contract_v3 import _source, framework_schema
    source, _, _, index = index_fixture()
    pack = material.cloud_input(index)
    passages, indices, originals = _source(pack, source)
    assert indices == [1, 2, 3]
    assert len(passages) == 9
    assert set(originals) == {1, 2, 3}
    assert "world" in framework_schema(pack)["properties"]


@pytest.mark.parametrize("mutation", [
    lambda source: source[0].update(sha256="bad"),
    lambda source: source[0].update(index=True),
    lambda source: source[0].update(text="  \n"),
    lambda source: source.append(deepcopy(source[0])),
])
def test_invalid_source_rejected_before_payload(mutation):
    source = chapters()
    mutation(source)
    with pytest.raises(ValueError):
        material.plan_chapters(source)


def test_nonadjacent_context_or_modified_plan_is_rejected():
    source = chapters(4)
    plan = material.plan_chapters(source)[0]
    plan["context_indices"] = [4]
    with pytest.raises(ValueError, match="chapter_plan_source_mismatch"):
        material.chapter_payload(source, plan)


def test_lookup_returns_independent_exact_originals():
    _, _, _, index = index_fixture()
    part = material.lookup_passages(index, ["CH1-P001"])[0]
    assert part == index["passage_catalog"][0]
    part["text"] = "changed"
    assert index["passage_catalog"][0]["text"] != part["text"]
    with pytest.raises(ValueError, match="unknown_lookup_passage_id"):
        material.lookup_passages(index, ["no-such-id"])
