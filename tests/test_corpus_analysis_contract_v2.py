from copy import deepcopy
import hashlib

import pytest
from jsonschema import Draft202012Validator, ValidationError

from src.content_factory import corpus_analysis_contract_v2 as contract


def specimen():
    chapters = [
        {"index": 1, "text": "小周是社区值班员。她正在登记维修钥匙。"},
        {"index": 2, "text": "社区办公室在服务中心一楼。门外连着走廊。"},
        {"index": 3, "text": "老陈说，明天再把剩下的钥匙归还。小周点头。"},
    ]
    group = contract.plan_groups(chapters)[0]
    details = [
        ("character", "小周", "小周是社区值班员。", "established", [{"kind": "character", "name": "小周"}]),
        ("location", "社区办公室", "社区办公室在服务中心一楼。", "established", [{"kind": "location", "name": "社区办公室"}]),
        ("event", "老陈", "老陈说，明天再把剩下的钥匙归还。", "planned", [{"kind": "character", "name": "老陈"}]),
    ]
    analysis = {"group_id": group["id"], "chapter_indices": [1, 2, 3], "claims": [], "conflicts": []}
    for number, (kind, subject, quote, status, entities) in enumerate(details, 1):
        analysis["claims"].append({"id": f"G001-C{number:03d}", "kind": kind, "subject": subject,
                                   "statement": quote, "chapter_index": number, "temporal_status": status,
                                   "evidence": [{"chapter_index": number, "quote": quote}], "entities": entities})
    cid = contract.stable_entity_id("character", "小周")
    chen = contract.stable_entity_id("character", "老陈")
    lid = contract.stable_entity_id("location", "社区办公室")
    merge = {
        "world": [],
        "characters": [{"id": cid, "name": "小周", "aliases": [], "claim_ids": ["G001-C001"]},
                       {"id": chen, "name": "老陈", "aliases": [], "claim_ids": ["G001-C003"]}],
        "locations": [{"id": lid, "name": "社区办公室", "aliases": [], "parent_id": "", "claim_ids": ["G001-C002"]}],
        "timeline": [{"id": "T001", "chapter_index": 3, "temporal_status": "planned",
                      "statement": "老陈计划明天归还剩下的钥匙。", "claim_ids": ["G001-C003"],
                      "character_ids": [chen], "location_ids": []}],
        "conflicts": [], "omitted_claims": [], "design_proposals": []}
    return chapters, group, analysis, merge


def test_groups_cover_every_acquired_chapter_once_with_adjacent_context():
    chapters = [{"index": number, "text": "字" * 7} for number in (1, 2, 3, 7, 8)]
    groups = contract.plan_groups(chapters, max_chars=15, context_chars=3)
    assert [row["chapter_indices"] for row in groups] == [[1, 2], [3, 7], [8]]
    assert [row["context_indices"] for row in groups] == [[3], [2, 8], [7]]
    payload = contract.group_payload(chapters, groups[1], "测试")
    assert [row["index"] for row in payload["core_chapters"]] == [3, 7]
    assert [row["excerpt_position"] for row in payload["context_chapters"]] == ["tail", "head"]
    assert all(len(row["text"]) == 3 for row in payload["context_chapters"])


def test_oversized_chapter_stays_whole_and_no_context_means_none():
    chapters = [{"index": 1, "text": "a" * 50}, {"index": 2, "text": "b" * 4}]
    groups = contract.plan_groups(chapters, max_chars=10, context_chars=0)
    assert [g["chapter_indices"] for g in groups] == [[1], [2]]
    assert all(not g["context_indices"] for g in groups)
    assert len(contract.group_payload(chapters, groups[0], "书")["core_chapters"][0]["text"]) == 50


@pytest.mark.parametrize("mutation,match", [
    (lambda rows: rows.append(deepcopy(rows[0])), "source_chapter_invalid"),
    (lambda rows: rows[0].update(sha256="0" * 64), "sha256_mismatch"),
    (lambda rows: rows[0].update(text="  "), "source_chapter_invalid"),
])
def test_invalid_source_is_not_silently_normalized(mutation, match):
    chapters, _, _, _ = specimen()
    mutation(chapters)
    with pytest.raises(ValueError, match=match):
        contract.plan_groups(chapters)


def test_group_schema_isolated_from_plan_and_repeated_calls():
    _, group, _, _ = specimen()
    schema = contract.group_schema(group)
    schema["properties"]["chapter_indices"]["const"].append(99)
    assert group["chapter_indices"] == [1, 2, 3]
    assert contract.group_schema(group)["properties"]["chapter_indices"]["const"] == [1, 2, 3]


def test_group_accepts_bound_quotes_but_does_not_claim_semantic_approval():
    chapters, group, analysis, _ = specimen()
    assert contract.validate_group(analysis, chapters, group) == analysis
    assert contract.policy()["semantic_review_required"]


@pytest.mark.parametrize("mutation,match", [
    (lambda a: a["claims"].pop(), "coverage_incomplete"),
    (lambda a: a["claims"][0]["evidence"][0].update(quote="原文没有这一句"), "quote_not_in"),
    (lambda a: a["claims"][0]["evidence"][0].update(chapter_index=2, quote="社区办公室在服务中心一楼。"), "own_chapter"),
    (lambda a: a["claims"].append(deepcopy(a["claims"][0])), "duplicate_claim_id"),
])
def test_group_rejects_missing_coverage_invented_quotes_and_duplicates(mutation, match):
    chapters, group, analysis, _ = specimen()
    mutation(analysis)
    with pytest.raises(ValueError, match=match):
        contract.validate_group(analysis, chapters, group)


def test_context_quote_must_be_visible_in_excerpt_and_never_count_as_core():
    chapters = [{"index": 1, "text": "前文独有信息结束尾巴"}, {"index": 2, "text": "第二章本段正文内容"}]
    groups = contract.plan_groups(chapters, max_chars=12, context_chars=4)
    value = {"group_id": "G002", "chapter_indices": [2], "conflicts": [], "claims": [{
        "id": "G002-C001", "kind": "event", "subject": "本段", "statement": "本段事件",
        "chapter_index": 2, "temporal_status": "occurring", "entities": [],
        "evidence": [{"chapter_index": 2, "quote": "第二章本段正文内容"},
                     {"chapter_index": 1, "quote": "前文独有信息"}]}]}
    with pytest.raises(ValueError, match="quote_not_in_supplied_text"):
        contract.validate_group(value, chapters, groups[1])
    value["claims"][0]["evidence"][1]["quote"] = "结束尾巴"
    contract.validate_group(value, chapters, groups[1])
    value["claims"][0]["chapter_index"] = 1
    with pytest.raises(ValidationError):
        contract.validate_group(value, chapters, groups[1])


def test_merge_binds_source_and_preserves_unapproved_state():
    chapters, _, analysis, merge = specimen()
    result = contract.validate_merge(merge, [analysis], {"chapters": chapters, "book_name": "测试"})
    assert result["validation"] == {"structural_pass": True, "semantic_review_required": True,
                                    "unresolved_conflicts": 0, "downstream_ready": False}
    assert result["provenance"]["source_chapters"][0]["sha256"] == hashlib.sha256(chapters[0]["text"].encode()).hexdigest()
    assert result["provenance"]["claim_evidence"]["G001-C003"][0]["chapter_index"] == 3


@pytest.mark.parametrize("mutation,match", [
    (lambda m: m["timeline"][0].update(temporal_status="occurring"), "chapter_or_status_changed"),
    (lambda m: m["timeline"][0].update(chapter_index=1), "chapter_or_status_changed"),
    (lambda m: m["timeline"].clear(), "temporal_claim_missing_timeline"),
    (lambda m: m["locations"][0].update(parent_id=m["locations"][0]["id"]), "parent_cycle"),
    (lambda m: m["characters"][0].update(id="C-FAKE"), "unstable_or_invented"),
    (lambda m: m["characters"][0]["aliases"].append("无来源别名"), "alias_missing_source"),
    (lambda m: m["locations"].clear(), "coverage_incomplete"),
])
def test_merge_rejects_loss_invented_identity_and_future_leakage(mutation, match):
    chapters, _, analysis, merge = specimen()
    mutation(merge)
    with pytest.raises(ValueError, match=match):
        contract.validate_merge(merge, [analysis], chapters)


def test_all_analyses_must_cover_corpus_once():
    chapters, _, analysis, merge = specimen()
    chapters.append({"index": 4, "text": "新章不能漏分析。"})
    with pytest.raises(ValueError, match="coverage_incomplete"):
        contract.validate_merge(merge, [analysis], chapters)
    with pytest.raises(ValueError, match="duplicate_group_id"):
        contract.merge_payload([analysis, analysis], chapters[:3])


def test_omissions_require_explicit_reason_and_cannot_double_count():
    chapters, _, analysis, merge = specimen()
    merge["locations"] = []
    merge["omitted_claims"] = [{"claim_id": "G001-C002", "reason": "地点细节暂不用于主线，留待独立复核确认。"}]
    contract.validate_merge(merge, [analysis], chapters)
    merge["omitted_claims"].append({"claim_id": "G001-C001", "reason": "重复"})
    with pytest.raises(ValueError, match="both_omitted_and_used"):
        contract.validate_merge(merge, [analysis], chapters)


def test_conflicts_cannot_be_silently_dropped_or_unblock_downstream():
    chapters, _, analysis, merge = specimen()
    analysis["conflicts"] = [{"claim_ids": ["G001-C001", "G001-C003"], "reason": "示例待核对矛盾"}]
    with pytest.raises(ValueError, match="conflict_silently_removed"):
        contract.validate_merge(merge, [analysis], chapters)
    merge["conflicts"] = deepcopy(analysis["conflicts"])
    summary = contract.validate_merge(merge, [analysis], chapters)
    review = {"decision": "pass", "checked_claim_ids": [c["id"] for c in analysis["claims"]], "issues": []}
    final = contract.validate_global_review(review, summary, [analysis], chapters)
    assert final["semantic_status"] == "machine_review_passed"
    assert not final["validation"]["downstream_ready"]


def test_semantic_review_requires_full_coverage_and_bound_summary():
    chapters, _, analysis, merge = specimen()
    summary = contract.validate_merge(merge, [analysis], chapters)
    review = {"decision": "pass", "checked_claim_ids": [c["id"] for c in analysis["claims"]], "issues": []}
    final = contract.validate_global_review(review, summary, [analysis], chapters)
    assert final["validation"]["downstream_ready"]
    assert contract.global_review_payload(summary, [analysis], chapters)["source_contexts"]
    review["checked_claim_ids"].pop()
    with pytest.raises(ValidationError):
        contract.validate_global_review(review, summary, [analysis], chapters)
    summary["timeline"][0]["statement"] = "篡改成已归还"
    with pytest.raises(ValueError, match="provenance_mismatch"):
        contract.global_review_payload(summary, [analysis], chapters)


def test_semantic_revise_is_returned_as_blocked_not_repaired_automatically():
    chapters, _, analysis, merge = specimen()
    summary = contract.validate_merge(merge, [analysis], chapters)
    review = {"decision": "revise", "checked_claim_ids": [c["id"] for c in analysis["claims"]],
              "issues": [{"claim_ids": ["G001-C003"], "reason": "需要区分计划与实际归还。",
                          "evidence": [{"chapter_index": 3, "quote": "老陈说，明天再把剩下的钥匙归还。"}]}]}
    result = contract.validate_global_review(review, summary, [analysis], chapters)
    assert result["semantic_status"] == "machine_review_revise"
    assert not result["validation"]["downstream_ready"]
    review["issues"][0]["evidence"][0]["quote"] = "不是原文的句子"
    with pytest.raises(ValueError, match="review_evidence"):
        contract.validate_global_review(review, summary, [analysis], chapters)


def test_design_is_explicit_and_does_not_count_as_fact_coverage():
    chapters, _, analysis, merge = specimen()
    merge["design_proposals"] = [{"proposal": "后续可考虑朴素办公室色彩方案。", "basis_claim_ids": ["G001-C002"]}]
    contract.validate_merge(merge, [analysis], chapters)
    merge["locations"] = []
    with pytest.raises(ValueError, match="coverage_incomplete"):
        contract.validate_merge(merge, [analysis], chapters)


def test_stable_identity_ignores_group_or_scene_and_normalizes_width():
    assert contract.stable_entity_id("character", "Ａ明") == contract.stable_entity_id("character", "A明")
    assert contract.stable_entity_id("character", "小周") != contract.stable_entity_id("location", "小周")


def model_specimen():
    chapters, group, analysis, merge = specimen()
    payload = contract.group_model_payload(chapters, group, "测试")
    raw = deepcopy(analysis)
    for claim in raw["claims"]:
        claim.pop("evidence")
        claim["evidence_ids"] = [row["id"] for row in payload["source_passages"]
                                 if row["chapter_index"] == claim["chapter_index"]]
    return chapters, group, raw, payload


def test_model_payload_has_complete_original_text_once_in_exact_offset_passages():
    chapters = [{"index": 1, "text": "第一段保留‘引号’。\r\n\r\n啊\n第二段保留空白。\n  "},
                {"index": 2, "text": "第三段原文不能被省略。"}]
    group = contract.plan_groups(chapters, max_chars=1000)[0]
    payload = contract.group_model_payload(chapters, group, "测试")
    assert all("text" not in row for row in payload["core_chapters"])
    for chapter in chapters:
        passages = [row for row in payload["source_passages"] if row["chapter_index"] == chapter["index"]]
        assert "".join(row["text"] for row in passages) == chapter["text"]
        assert all(set(row) == {"id", "chapter_index", "scope", "text"} for row in passages)
        assert contract.group_model_payload(chapters, group, "测试") == payload


def test_model_evidence_is_bound_without_mutating_or_retyping_native_output():
    chapters, group, raw, _ = model_specimen()
    native = deepcopy(raw)
    accepted = contract.bind_group_evidence(raw, chapters, group)
    assert raw == native
    assert "evidence_ids" not in accepted["claims"][0]
    assert accepted["claims"][0]["evidence"][0]["quote"] == chapters[0]["text"]
    assert "evidence" not in raw["claims"][0]
    assert contract.validate_group(accepted, chapters, group) == accepted


def test_model_evidence_ids_reject_unknown_duplicate_and_wrong_chapter_refs():
    chapters, group, raw, payload = model_specimen()
    good = deepcopy(raw)
    raw["claims"][0]["evidence_ids"] = ["CH1-S999999-E999999"]
    with pytest.raises(ValidationError):
        contract.bind_group_evidence(raw, chapters, group)
    raw = deepcopy(good)
    raw["claims"][0]["evidence_ids"] *= 2
    with pytest.raises(ValidationError):
        contract.bind_group_evidence(raw, chapters, group)
    raw = deepcopy(good)
    raw["claims"][0]["evidence_ids"] = [row["id"] for row in payload["source_passages"] if row["chapter_index"] == 2]
    with pytest.raises(ValueError, match="own_chapter_evidence"):
        contract.bind_group_evidence(raw, chapters, group)


def test_model_cannot_supply_quote_text_or_claim_context_as_core():
    chapters, group, raw, _ = model_specimen()
    raw["claims"][0]["evidence"] = [{"chapter_index": 1, "quote": "伪造拼接的句子"}]
    with pytest.raises(ValidationError):
        contract.bind_group_evidence(raw, chapters, group)
    groups = contract.plan_groups(chapters, max_chars=25, context_chars=6)
    payload = contract.group_model_payload(chapters, groups[1], "测试")
    assert all("text" not in row for row in payload["context_chapters"])
    internal = {row["id"]: row for row in contract._model_passages(chapters, groups[1])}
    for row in payload["source_passages"]:
        original = next(chapter["text"] for chapter in chapters if chapter["index"] == row["chapter_index"])
        binding = internal[row["id"]]
        assert row["text"] == original[binding["start_offset"]:binding["end_offset"]]
        if row["chapter_index"] not in groups[1]["chapter_indices"]:
            assert len(row["text"]) <= 6


def test_valid_source_id_does_not_assert_claim_semantically_supported():
    chapters, group, raw, _ = model_specimen()
    raw["claims"][0]["statement"] = "小周其实是一位原文没有说明的神仙。"
    accepted = contract.bind_group_evidence(raw, chapters, group)
    assert accepted["claims"][0]["statement"] == raw["claims"][0]["statement"]
    assert contract.policy()["semantic_review_required"]
    assert contract.policy()["model_evidence_format"] == "source_passage_ids"


def test_model_schema_mutation_does_not_pollute_legacy_schema_or_payload():
    chapters, group, raw, payload = model_specimen()
    schema = contract.group_model_schema(group, payload)
    schema["properties"]["claims"]["items"]["properties"]["evidence_ids"]["items"]["enum"].append("fake")
    assert "evidence" in contract.group_schema(group)["properties"]["claims"]["items"]["properties"]
    assert "fake" not in [row["id"] for row in payload["source_passages"]]
    contract.bind_group_evidence(raw, chapters, group)


def test_v22_coalesces_adjacent_paragraphs_without_truncating_core_or_context():
    chapters = [{"index": i, "title": f"第{i}章", "text": (f"第{i}章短段落。\n" * 180)} for i in (1, 2, 3)]
    groups = contract.plan_groups(chapters, max_chars=1000, context_chars=650)
    payload = contract.group_model_payload(chapters, groups[1], "测试")
    assert all(set(row) == {"index", "title"} for row in payload["core_chapters"] + payload["context_chapters"])
    assert len(payload["source_passages"]) < 12
    for index, expected in ((1, chapters[0]["text"][-650:]), (2, chapters[1]["text"]), (3, chapters[2]["text"][:650])):
        actual = "".join(row["text"] for row in payload["source_passages"] if row["chapter_index"] == index)
        assert actual == expected
    core = [row for row in payload["source_passages"] if row["chapter_index"] == 2]
    assert core[0]["id"] == "CH2-P001"
    assert not any("sha256" in row or "start_offset" in row for row in payload["source_passages"])


def test_v22_merge_deduplicates_source_text_and_preserves_all_claims():
    chapters, group, raw, _ = model_specimen()
    for i in range(4, 24):
        copy = deepcopy(raw["claims"][0])
        copy["id"] = f"G001-C{i:03d}"
        raw["claims"].append(copy)
    analysis = contract.bind_group_evidence(raw, chapters, group)
    compact = contract.merge_payload([analysis], chapters)
    assert len(compact["claims"]) == 23
    assert len(compact["evidence_catalog"]) == 3
    assert "analyses" not in compact
    assert all("evidence" not in claim and claim["evidence_ids"] for claim in compact["claims"])
    expected = {claim["id"] for claim in analysis["claims"]}
    assert {claim["id"] for claim in compact["claims"]} == expected
    assert len(str(compact)) < len(str(analysis))


def test_v22_review_omits_provenance_and_duplicate_quotes_but_keeps_every_reference():
    chapters, group, raw, _ = model_specimen()
    analysis = contract.bind_group_evidence(raw, chapters, group)
    _, _, _, merge = specimen()
    summary = contract.validate_merge(merge, [analysis], chapters)
    payload = contract.global_review_payload(summary, [analysis], chapters)
    assert "provenance" not in payload["summary"]
    assert "analyses" not in payload
    assert len(payload["claims"]) == 3
    assert len(payload["source_contexts"]) == 3
    contexts = {row["id"]: row for row in payload["source_contexts"]}
    for evidence in payload["evidence_catalog"]:
        context = contexts[evidence["source_context_id"]]
        start = evidence["start_offset"] - context["start_offset"]
        end = evidence["end_offset"] - context["start_offset"]
        original = next(row["text"] for row in chapters if row["index"] == evidence["chapter_index"])
        assert context["text"][start:end] == original[evidence["start_offset"]:evidence["end_offset"]]
        assert "text" not in evidence


def test_bound_repeated_passage_keeps_second_occurrence_context_and_rejects_bad_offsets():
    block = "重复原文。" + "甲" * 500 + "\n"
    chapters = [{"index": 1, "text": block * 3}]
    group = contract.plan_groups(chapters)[0]
    passages = contract.group_model_payload(chapters, group, "测试")["source_passages"]
    assert passages[0]["text"] == passages[1]["text"]
    raw = {"group_id": group["id"], "chapter_indices": [1], "conflicts": [], "claims": [{
        "id": "G001-C001", "kind": "world", "subject": "世界", "statement": "重复原文。",
        "chapter_index": 1, "temporal_status": "established", "entities": [],
        "evidence_ids": [passages[1]["id"]]}]}
    analysis = contract.bind_group_evidence(raw, chapters, group)
    evidence = analysis["claims"][0]["evidence"][0]
    assert evidence["start_offset"] == len(block)
    merge = {"world": [{"statement": "重复原文。", "claim_ids": ["G001-C001"]}],
             "characters": [], "locations": [], "timeline": [], "conflicts": [], "omitted_claims": [], "design_proposals": []}
    summary = contract.validate_merge(merge, [analysis], chapters)
    review = contract.global_review_payload(summary, [analysis], chapters)
    assert review["evidence_catalog"][0]["start_offset"] == len(block)
    assert review["source_contexts"][0]["start_offset"] == len(block) - 300
    damaged = deepcopy(analysis)
    damaged["claims"][0]["evidence"][0]["start_offset"] += 1
    with pytest.raises(ValueError, match="offset_quote_mismatch"):
        contract.validate_group(damaged, chapters, group)
    legacy = deepcopy(analysis)
    legacy["claims"][0]["evidence"][0] = {"chapter_index": 1, "quote": block}
    contract.validate_group(legacy, chapters, group)
    with pytest.raises(ValueError, match="ambiguous_without_offset"):
        contract.merge_payload([legacy], chapters)


def test_review_overlapping_contexts_are_merged_without_discarding_evidence():
    block = "原文段落" + "乙" * 500 + "\n"
    chapters = [{"index": 1, "text": block + block.replace("乙", "丙") + block.replace("乙", "丁")}]
    group = contract.plan_groups(chapters)[0]
    passages = contract.group_model_payload(chapters, group, "测试")["source_passages"]
    raw = {"group_id": group["id"], "chapter_indices": [1], "conflicts": [], "claims": [{
        "id": "G001-C001", "kind": "world", "subject": "世界", "statement": "原文段落",
        "chapter_index": 1, "temporal_status": "established", "entities": [],
        "evidence_ids": [passages[0]["id"], passages[1]["id"]]}]}
    analysis = contract.bind_group_evidence(raw, chapters, group)
    merge = {"world": [{"statement": "原文段落", "claim_ids": ["G001-C001"]}],
             "characters": [], "locations": [], "timeline": [], "conflicts": [], "omitted_claims": [], "design_proposals": []}
    summary = contract.validate_merge(merge, [analysis], chapters)
    review = contract.global_review_payload(summary, [analysis], chapters)
    assert len(review["source_contexts"]) == 1
    assert len(review["evidence_catalog"]) == 2
    assert len(review["claims"][0]["evidence_ids"]) == 2


def test_v23_context_remains_visible_but_cannot_be_selected_as_claim_evidence():
    chapters, _, _, _ = specimen()
    group = contract.plan_groups(chapters, max_chars=25, context_chars=2000)[1]
    payload = contract.group_model_payload(chapters, group, "测试")
    core = [row for row in payload["source_passages"] if row["scope"] == "core"]
    context = [row for row in payload["source_passages"] if row["scope"] == "context"]
    assert core and context
    schema = contract.group_model_schema(group, payload)
    allowed = schema["properties"]["claims"]["items"]["properties"]["evidence_ids"]["items"]["enum"]
    assert set(allowed) == {row["id"] for row in core}
    assert not set(allowed) & {row["id"] for row in context}
    for chapter in chapters:
        assert "".join(row["text"] for row in payload["source_passages"] if row["chapter_index"] == chapter["index"]) == chapter["text"]
    raw = {"group_id": group["id"], "chapter_indices": group["chapter_indices"], "conflicts": [], "claims": [{
        "id": "G002-C001", "kind": "character", "subject": "小周", "statement": "错误归属第一章的人物事实",
        "chapter_index": 2, "temporal_status": "established", "entities": [],
        "evidence_ids": [context[0]["id"]]}]}
    with pytest.raises(ValueError, match="context_evidence_not_allowed") as caught:
        contract.bind_group_evidence(raw, chapters, group)
    error = str(caught.value)
    assert "G002-C001" in error and context[0]["id"] in error
    assert '"chapter_index":2' in error and '"chapter_index":1' in error
    assert "删除" in error and "无关核心证据ID" in error


def test_v23_wrong_core_chapter_error_identifies_claim_and_selected_chapter():
    chapters, group, raw, payload = model_specimen()
    raw["claims"][0]["evidence_ids"] = [row["id"] for row in payload["source_passages"] if row["chapter_index"] == 2]
    with pytest.raises(ValueError, match="claim_missing_own_chapter_evidence") as caught:
        contract.bind_group_evidence(raw, chapters, group)
    error = str(caught.value)
    assert "G001-C001" in error and "CH2-P001" in error
    assert '"chapter_index":1' in error and '"chapter_index":2' in error
    assert "不要修改章号" in error


def test_v23_model_schema_uses_actual_core_chapter_membership_not_scope_label():
    chapters, _, _, _ = specimen()
    group = contract.plan_groups(chapters, max_chars=25, context_chars=2000)[1]
    payload = contract.group_model_payload(chapters, group, "测试")
    for row in payload["source_passages"]:
        row["scope"] = "core"
    schema = contract.group_model_schema(group, payload)
    allowed = schema["properties"]["claims"]["items"]["properties"]["evidence_ids"]["items"]["enum"]
    assert all(identifier.startswith("CH2-") for identifier in allowed)


def test_merge_reads_real_source_manifest_book_name_without_overriding_explicit_name():
    chapters, _, analysis, _ = specimen()
    source = {"manifest": {"book_name": "原书名"}, "chapters": chapters}
    assert contract.merge_payload([analysis], source)["book_name"] == "原书名"
    source["book_name"] = "明确书名"
    assert contract.merge_payload([analysis], source)["book_name"] == "明确书名"


def test_v24_dynamic_merge_schema_limits_world_to_actual_world_claims():
    _, _, analysis, merge = specimen()
    schema = contract.merge_schema([analysis])
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["world"]["maxItems"] == 0
    Draft202012Validator(schema).validate(merge)
    merge["world"] = [{"statement": "小周是值班员", "claim_ids": ["G001-C001"]}]
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(merge)
    analysis["claims"][0]["kind"] = "world"
    schema = contract.merge_schema([analysis])
    assert schema["properties"]["world"]["items"]["properties"]["claim_ids"]["items"] == {"enum": ["G001-C001"]}
    Draft202012Validator(schema).validate(merge)
    merge["world"][0]["claim_ids"] = ["G001-C003"]
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(merge)


def test_v24_world_error_identifies_row_claim_kind_and_correct_destination():
    chapters, _, analysis, merge = specimen()
    merge["world"] = [{"statement": "老陈明天还钥匙，这是世界规则", "claim_ids": ["G001-C003"]}]
    with pytest.raises(ValueError, match="world_requires_world_claims") as caught:
        contract.validate_merge(merge, [analysis], chapters)
    error = str(caught.value)
    assert '"world_row":1' in error
    assert '"id":"G001-C003"' in error and '"kind":"event"' in error
    assert "timeline" in error and "不得修改原claim的kind" in error
    assert "G001-C003" == analysis["claims"][2]["id"]
    assert "event" == analysis["claims"][2]["kind"]


def test_v24_dynamic_schema_references_match_existing_validator_without_overrestricting_entities():
    _, _, analysis, merge = specimen()
    schema = contract.merge_schema([analysis])
    # An event can establish an actor's presence; do not incorrectly require character-kind evidence.
    Draft202012Validator(schema).validate(merge)
    assert merge["characters"][1]["claim_ids"] == ["G001-C003"]
    wrong = deepcopy(merge)
    wrong["timeline"][0]["claim_ids"] = ["G999-C001"]
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(wrong)
    wrong = deepcopy(merge)
    wrong["timeline"][0]["character_ids"] = ["C-invented"]
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(wrong)
    wrong = deepcopy(merge)
    wrong["timeline"][0]["chapter_index"] = 999
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(wrong)


def test_v24_dynamic_merge_schema_does_not_mutate_legacy_or_other_input_contracts():
    _, _, analysis, _ = specimen()
    changed = contract.merge_schema([analysis])
    changed["properties"]["world"]["items"]["properties"]["claim_ids"]["items"]["enum"].append("fake")
    assert "maxItems" not in contract.merge_schema()["properties"]["world"]
    assert "fake" not in contract.merge_schema([analysis])["properties"]["world"]["items"]["properties"]["claim_ids"]["items"]["enum"]
