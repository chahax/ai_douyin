from copy import deepcopy
import hashlib

import pytest

from src.content_factory import corpus_production_contract_v3 as contract


def inputs():
    texts = ["林月也叫阿月，住在小镇老屋。老屋里有厨房。她与弟弟林河共同生活。",
             "林河回到老屋，把钥匙交给林月。林月接过钥匙，问起修门的事。",
             "林月告诉林河明天再修门。此刻钥匙仍在林月手中。",
             "第二天林河修好了老屋的门。林月把钥匙收进抽屉。"]
    chapters, passages, coverage = [], [], []
    for index, text in enumerate(texts, 1):
        sha = hashlib.sha256(text.encode()).hexdigest()
        chapter = {"index": index, "title": str(index), "text": text, "sha256": sha}
        chapters.append(chapter)
        passage = {"id": f"CH{index}-P001", "chapter_index": index, "start_offset": 0,
                   "end_offset": len(text), "text": text, "sha256": sha, "chapter_sha256": sha}
        passages.append(passage)
        coverage.append({"chapter_index": index, "sha256": sha,
                         "selected_core_passage_ids": [passage["id"]]})
    pack = {"book_name": "合成钥匙故事", "selected_core_passages": passages,
            "chapter_coverage": coverage, "classification_index": [], "source_digest": "fixture"}
    raw = {"world": [{"text": "故事发生在小镇。", "source_passage_ids": ["CH1-P001"]}],
           "characters": [
               {"id": "C1", "name": "林月", "aliases": ["阿月"],
                "relationships": [{"text": "林河是林月的弟弟。", "source_passage_ids": ["CH1-P001"]}],
                "source_passage_ids": ["CH1-P001"]},
               {"id": "C2", "name": "林河", "aliases": [], "relationships": [],
                "source_passage_ids": ["CH1-P001"]}],
           "locations": [{"id": "L1", "name": "老屋", "parent_id": "", "description": "居住地。", "source_passage_ids": ["CH1-P001"]},
                         {"id": "L2", "name": "厨房", "parent_id": "L1", "description": "老屋内部。", "source_passage_ids": ["CH1-P001"]}],
           "mainline": [{"chapter_indices": [i], "text": texts[i-1], "source_passage_ids": [f"CH{i}-P001"]} for i in range(1, 5)],
           "selected_chapter_indices": [2, 3], "selection_reason": "钥匙交接是一个可完整呈现的事件。",
           "episode_arc": {"opening": "林河回屋。", "development": "交钥匙。", "turning_point": "说明修门计划。", "ending": "林月保管钥匙。", "source_passage_ids": ["CH2-P001", "CH3-P001"]},
           "limitations": ["精选原文不代表全书事实充分性已经证明。"]}
    return raw, pack, chapters


def review_for(artifact, pack, chapters, *, problem=None):
    result = {"reviewed_artifact_sha256": contract.digest(artifact), "decision": "pass",
              "checked_source_passage_ids": [p["id"] for p in pack["selected_core_passages"]],
              "checked_chapter_indices": [c["index"] for c in chapters],
              "checks": {key: "pass" for key in contract.CHECKS}, "issues": [], "summary": "测试用审核。"}
    if problem:
        result["decision"] = "revise"
        result["checks"][problem] = "fail"
        result["issues"] = [{"category": problem, "location": "人物关系", "reason": "测试问题。",
                             "source_evidence": [{"source_passage_id": "CH1-P001",
                                                  "exact_quote": pack["selected_core_passages"][0]["text"][:4]}]}]
    return result


def approved():
    raw, pack, chapters = inputs()
    framework = contract.validate_framework(raw, pack, chapters)
    review = review_for(raw, pack, contract.selected_original_chapters(framework, chapters))
    return contract.validate_framework_review(review, framework, pack, chapters), pack, chapters


def test_source_framework_and_independent_review():
    framework, pack, chapters = approved()
    assert framework["validation"]["downstream_ready"]
    assert not framework["validation"]["core_extraction_proves_fact_sufficiency"]
    assert framework["provenance"]["source_chapter_indices"] == [1, 2, 3, 4]


@pytest.mark.parametrize("mutation,error", [
    (lambda raw: raw["characters"].append(deepcopy(raw["characters"][0])), "character_id_duplicate"),
    (lambda raw: raw["characters"][1]["aliases"].append("阿月"), "character_alias_assigned_twice"),
    (lambda raw: raw["characters"][0]["aliases"].extend(["阿月"]), "character_alias_duplicate"),
    (lambda raw: raw["characters"][0].update(name="不存在的名字"), "character_name_not_in_cited_source"),
    (lambda raw: raw["locations"][0].update(parent_id="L2"), "location_parent_cycle"),
    (lambda raw: raw["locations"][0].update(parent_id="L99"), "location_parent_unknown"),
    (lambda raw: raw["mainline"].pop(), "mainline_chapter_coverage_incomplete"),
    (lambda raw: raw["mainline"][0].update(source_passage_ids=["CH2-P001"]), "mainline_chapter_evidence_mismatch"),
    (lambda raw: raw.update(selected_chapter_indices=[1, 3]), "episode_chapters_not_contiguous"),
    (lambda raw: raw["episode_arc"].update(source_passage_ids=["CH4-P001"]), "episode_arc_source_outside_selection"),
])
def test_rejects_identity_source_scope_and_space_errors(mutation, error):
    raw, pack, chapters = inputs()
    mutation(raw)
    with pytest.raises(ValueError, match=error):
        contract.validate_framework(raw, pack, chapters)


def test_names_are_not_required_to_be_separate_entities():
    raw, pack, chapters = inputs()
    # The canonical person and sourced nickname belong to one identity.
    result = contract.validate_framework(raw, pack, chapters)
    assert len(result["characters"]) == 2
    assert result["characters"][0]["aliases"] == ["阿月"]


@pytest.mark.parametrize("field,value,error", [
    ("text", "被改写的正文", "core_source_span_invalid"),
    ("start_offset", 1, "core_source_span_invalid"),
    ("chapter_sha256", "wrong", "core_source_original_mismatch"),
])
def test_core_original_binding_rejects_changed_source(field, value, error):
    raw, pack, chapters = inputs()
    pack["selected_core_passages"][0][field] = value
    with pytest.raises(ValueError, match=error):
        contract.validate_framework(raw, pack, chapters)


def test_review_requires_all_core_passages_and_full_context_chapters():
    raw, pack, chapters = inputs()
    framework = contract.validate_framework(raw, pack, chapters)
    review = review_for(raw, pack, chapters)
    review["checked_chapter_indices"] = [2, 3]
    with pytest.raises(ValueError, match="production_schema_invalid"):
        contract.validate_framework_review(review, framework, pack, chapters)


def test_review_revise_blocks_downstream():
    raw, pack, chapters = inputs()
    framework = contract.validate_framework(raw, pack, chapters)
    review = review_for(raw, pack, chapters, problem="source_fidelity")
    result = contract.validate_framework_review(review, framework, pack, chapters)
    assert not result["validation"]["downstream_ready"]


def test_review_quotes_use_exact_offsets():
    raw, pack, chapters = inputs()
    framework = contract.validate_framework(raw, pack, chapters)
    review = review_for(raw, pack, chapters, problem="source_fidelity")
    review["issues"][0]["source_evidence"][0]["exact_quote"] = "并不存在的句子"
    with pytest.raises(ValueError, match="review_original_evidence_mismatch"):
        contract.validate_framework_review(review, framework, pack, chapters)


def test_review_cannot_fabricate_pass_over_failure():
    raw, pack, chapters = inputs()
    framework = contract.validate_framework(raw, pack, chapters)
    review = review_for(raw, pack, chapters, problem="source_fidelity")
    review["decision"] = "pass"
    with pytest.raises(ValueError, match="review_decision_mismatch"):
        contract.validate_framework_review(review, framework, pack, chapters)


def test_framework_changed_after_validation_rejected():
    raw, pack, chapters = inputs()
    framework = contract.validate_framework(raw, pack, chapters)
    framework["world"][0]["text"] = "已被修改。"
    with pytest.raises(ValueError, match="framework_provenance_changed"):
        contract.validate_framework_review(review_for(contract.framework_raw(framework), pack, chapters), framework, pack, chapters)


def test_design_review_and_context_keep_clean_new_inputs():
    framework, pack, chapters = approved()
    design = "新的世界和画风设计，环境与原文一致，服装是明示的创作补足。"
    result = contract.validate_design_review(review_for(design, pack, chapters), design, framework, pack, chapters)
    assert result["downstream_ready"] and not result["media_generated"]
    context = contract.build_episode_context(framework, design, pack, chapters)
    assert context["global_bible"] == contract.framework_raw(framework)
    assert context["visual_world_design"] == design
    assert context["episode_brief"]["chapter_indices"] == [2, 3]
    assert [c["index"] for c in context["selected_original_chapters"]] == [1, 2, 3, 4]
    assert "previous_draft" not in context and "provenance" not in context["global_bible"]


def test_forged_framework_ready_flag_does_not_unlock_design():
    raw, pack, chapters = inputs()
    framework = contract.validate_framework(raw, pack, chapters)
    framework["validation"]["downstream_ready"] = True
    with pytest.raises(ValueError, match="reviewed_framework_required"):
        contract.build_episode_context(framework, "设计稿", pack, chapters)


def test_accepted_framework_cannot_be_changed_before_design_review():
    framework, pack, chapters = approved()
    framework["world"][0]["text"] = "修改后的世界。"
    with pytest.raises(ValueError, match="framework_provenance_changed"):
        contract.validate_design_review(review_for("设计稿", pack, chapters), "设计稿", framework, pack, chapters)


def test_source_review_cannot_cite_unprovided_text_from_other_chapter():
    raw, pack, chapters = inputs()
    raw["selected_chapter_indices"] = [1]
    raw["episode_arc"]["source_passage_ids"] = ["CH1-P001"]
    passage = pack["selected_core_passages"][3]
    passage.update(text=passage["text"][:4], end_offset=4)
    passage["sha256"] = hashlib.sha256(passage["text"].encode()).hexdigest()
    framework = contract.validate_framework(raw, pack, chapters)
    provided_chapters = contract.selected_original_chapters(framework, chapters)
    review = review_for(raw, pack, provided_chapters, problem="source_fidelity")
    review["issues"][0]["source_evidence"] = [{"source_passage_id": "CH4-P001",
                                              "exact_quote": chapters[3]["text"][6:10]}]
    with pytest.raises(ValueError, match="review_original_evidence_mismatch"):
        contract.validate_framework_review(review, framework, pack, chapters)


class Call:
    def __init__(self, failures=None):
        self.calls = []
        self.failures = failures or {}
        self.raw, self.pack, self.chapters = inputs()

    def __call__(self, name, role, prompt, context, json_output=True):
        self.calls.append({"name": name, "role": role, "prompt": prompt, "context": context,
                           "json_output": json_output})
        if name in self.failures and isinstance(self.failures[name], Exception):
            raise self.failures[name]
        if name in self.failures:
            return deepcopy(self.failures[name])
        if name.startswith("FRAMEWORK_REVIEW"):
            return review_for(context["framework"], self.pack, context["full_source_chapters"])
        if name.startswith("FRAMEWORK"):
            return deepcopy(self.raw)
        if name.startswith("VISUAL_WORLD_DESIGN"):
            return "世界背景、画风、小环境、角色和当时状态的自然设计稿。"
        if name.startswith("DESIGN_REVIEW"):
            return review_for(context["visual_world_design"], self.pack, context["full_source_chapters"])
        raise AssertionError(name)


def run(call, limit=24, revision=None):
    records = {}
    def cycle(callable_, context, stats, **kwargs):
        assert kwargs["initial_draft"] is None
        assert context["visual_world_design"]
        assert "previous_draft" not in context
        assert context["global_bible"]["characters"]
        return "自然剧本测试产物", {"draft_sha256": "fixture"}
    result = contract.run_production(call, {"chapters": call.chapters}, call.pack,
                                     {"target_seconds": 90, "visual_storytelling": {}},
                                     revision_cycle=revision or cycle, revision_policy={"version": "fixture"},
                                     stats=lambda draft: {}, record=lambda n, v: records.update({n: v}),
                                     remaining_calls=lambda: limit-len(call.calls))
    return result, records


def test_production_uses_minimax_design_then_independent_review_before_v4():
    call = Call()
    result, records = run(call)
    assert [(row["name"], row["role"]) for row in call.calls] == [
        ("FRAMEWORK_0", "director"), ("FRAMEWORK_REVIEW_0", "director"),
        ("VISUAL_WORLD_DESIGN_0", "writer"), ("DESIGN_REVIEW_0", "director")]
    assert call.calls[2]["json_output"] is False
    assert result["selected_chapters"] == [2, 3]
    assert "FRAMEWORK_ACCEPTED" in records and "WRITER_CONTEXT_BINDING" in records


def test_all_director_prompts_explicitly_request_json_for_native_adapter():
    call = Call()
    run(call)
    for row in call.calls:
        if row["role"] == "director":
            assert "JSON" in row["prompt"].upper()
            assert row["context"]["output_schema"]["type"] == "object"


def test_transport_failure_is_not_a_protocol_retry():
    call = Call({"FRAMEWORK_0": TimeoutError("unknown")})
    with pytest.raises(TimeoutError):
        run(call)
    assert len(call.calls) == 1


def test_known_schema_error_has_one_protocol_repair():
    call = Call({"FRAMEWORK_0": {"malformed": True}})
    run(call)
    assert [row["name"] for row in call.calls[:2]] == ["FRAMEWORK_0", "FRAMEWORK_0_PROTOCOL_REPAIR"]


def test_framework_semantic_failure_blocks_design_and_writer():
    call = Call()
    failed = review_for(call.raw, call.pack, call.chapters, problem="identity_and_relationships")
    call.failures.update(FRAMEWORK_REVIEW_0=failed, FRAMEWORK_REVIEW_1=failed)
    with pytest.raises(ValueError, match="framework_semantic_revision_limit_reached"):
        run(call)
    assert not any(row["role"] == "writer" for row in call.calls)


def test_design_semantic_revision_receives_issues_without_failed_prose():
    call = Call()
    text = "世界背景、画风、小环境、角色和当时状态的自然设计稿。"
    call.failures["DESIGN_REVIEW_0"] = review_for(text, call.pack, call.chapters, problem="creative_boundary")
    run(call)
    revised = next(row for row in call.calls if row["name"] == "VISUAL_WORLD_DESIGN_1")
    assert revised["context"]["required_design_corrections"]
    assert "previous_draft" not in revised["context"] and "visual_world_design" not in revised["context"]


def test_remaining_capacity_checked_before_first_cloud_request():
    call = Call()
    with pytest.raises(ValueError, match="insufficient_capacity"):
        run(call, limit=7)
    assert not call.calls


def test_review_source_text_deduplicates_full_chapters_and_core_excerpts():
    _, pack, chapters = inputs()
    payload = contract.review_source_payload(pack, chapters)
    assert sum(len(row["text"]) for row in payload["source_contexts"]) == sum(len(row["text"]) for row in chapters)
    assert len(payload["source_contexts"]) == 4
    assert "text" not in payload["source_passages"][0]
    assert "CH2-P001" in {row["id"] for row in payload["source_passages"]}
    assert "FULL-CH2-P001" in {row["id"] for row in payload["source_passages"]}


def test_review_binds_native_id_and_quote_without_changing_native_review():
    raw, pack, chapters = inputs()
    framework = contract.validate_framework(raw, pack, chapters)
    review = review_for(raw, pack, chapters, problem="source_fidelity")
    before = deepcopy(review)
    review["issues"][0]["source_evidence"][0] = {"source_passage_id": "FULL-CH2-P001", "exact_quote": "把钥匙交给林月"}
    before = deepcopy(review)
    accepted = contract.validate_framework_review(review, framework, pack, chapters)
    binding = accepted["review_source_bindings"][0]
    assert binding["chapter_index"] == 2
    assert chapters[1]["text"][binding["start_offset"]:binding["end_offset"]] == "把钥匙交给林月"
    assert accepted["review"] == before and review == before


def test_review_repeated_quote_in_passage_requires_longer_unique_evidence():
    raw, pack, chapters = inputs()
    chapters[0]["text"] += "林月也叫阿月。"
    sha = hashlib.sha256(chapters[0]["text"].encode()).hexdigest()
    chapters[0]["sha256"] = sha
    pack["chapter_coverage"][0]["sha256"] = sha
    pack["selected_core_passages"][0].update(text=chapters[0]["text"], end_offset=len(chapters[0]["text"]), sha256=sha, chapter_sha256=sha)
    framework = contract.validate_framework(raw, pack, chapters)
    review = review_for(raw, pack, chapters, problem="source_fidelity")
    review["issues"][0]["source_evidence"][0]["exact_quote"] = "林月也叫阿月"
    with pytest.raises(ValueError, match="review_evidence_ambiguous"):
        contract.validate_framework_review(review, framework, pack, chapters)


def test_v4_fact_contract_receives_episode_scope_without_replacing_original_source():
    call = Call()
    captured = {}
    original = call.__class__.__call__
    def delegated(name, role, prompt, payload, json_output=True):
        if name == "FACT_CONTRACT":
            captured.update(deepcopy(payload))
            return {"ok": True}
        return original(call, name, role, prompt, payload, json_output)
    class Proxy:
        pack, chapters, calls = call.pack, call.chapters, call.calls
        def __call__(self, *args, **kwargs):
            return delegated(*args, **kwargs)
    def cycle(delegated_call, context, stats, **kwargs):
        base = {"selected_original_chapters": context["selected_original_chapters"], "source_sha256": "fixture"}
        delegated_call("FACT_CONTRACT", "director", "事实整理JSON", base)
        assert captured["selected_original_chapters"] == base["selected_original_chapters"]
        assert captured["source_sha256"] == "fixture"
        assert captured["episode_brief"]["chapter_indices"] == [2, 3]
        assert set(captured["global_background"]) == {"world", "characters", "locations"}
        assert "mainline" not in captured["global_background"]
        return "自然剧本测试产物", {"draft_sha256": "fixture"}
    run(Proxy(), revision=cycle)


def test_source_scope_distinguishes_full_original_from_partial_core_extraction():
    _, pack, chapters = inputs()
    full_text, full = contract.source_scope(pack, chapters)
    assert full["all_original_text_included"] and "全部原文保留，本轮未压缩" in full_text
    passage = pack["selected_core_passages"][-1]
    passage.update(text=passage["text"][:-4], end_offset=passage["end_offset"]-4)
    passage["sha256"] = hashlib.sha256(passage["text"].encode()).hexdigest()
    partial_text, partial = contract.source_scope(pack, chapters)
    assert partial["omitted_original_chars"] == 4 and not partial["all_original_text_included"]
    assert "未纳入4字符" in partial_text and "本轮未压缩" not in partial_text
    assert partial["model_written_summary"] is False
