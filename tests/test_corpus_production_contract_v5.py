"""Offline routing and evidence contracts, not model content acceptance."""
from copy import deepcopy
import json

import pytest

from src.content_factory import corpus_chapter_facts_v5 as material
from src.content_factory import corpus_production_contract_v5 as flow
from src.content_factory.screenplay_review_cycle_v2 import CHECKS
from tests.test_corpus_chapter_facts_v5 import pass_review
from tests.test_corpus_episode_state_v5 import episode_fixture
from tests.test_corpus_production_contract_v4 import generic_pass


def fixture():
    chapters, library, raw = episode_fixture()
    source = {"book_name": library["book_name"], "chapters": chapters}
    return source, library["analyses"], material.cloud_input(library), raw


def framework(pack):
    by_chapter = {}
    for row in pack["selected_core_passages"]:
        by_chapter.setdefault(row["chapter_index"], row["id"])
    return {"world": [], "characters": [{"id": "lin", "name": "林青", "aliases": [],
             "relationships": [{"text": "林青是小明的继母", "source_passage_ids": ["CH1-P002"]}],
             "source_passage_ids": ["CH1-P001"]}], "locations": [],
            "mainline": [{"chapter_indices": [idx], "text": "该章原文事件", "source_passage_ids": [pid]}
                         for idx, pid in by_chapter.items()],
            "selected_chapter_indices": [1], "selection_reason": "完整的交接钥匙事件",
            "episode_arc": {"opening": "小明拿着钥匙", "development": "递出钥匙", "turning_point": "林青接住",
                            "ending": "小明点头", "source_passage_ids": ["CH1-P003"]},
            "limitations": ["来源语义由独立审核判断，非程序证明"]}


DRAFT = ('世界背景：普通家庭。\n人物：林青、小明。\n'
         'scene_id: scene_1\nstate_ids: adult_room,child_room,key_child,key_adult,relation\n'
         '### 【0—10秒】\n小明把钥匙交给林青，林青接住，小明点头。\n小明：“钥匙给你。”\n')
DESIGN = "普通家庭设计稿；林青和小明在客厅交接钥匙，日间自然光。服装和家具属于创作补足。"


class Fake:
    def __init__(self, source, analyses, pack, snapshot, root_stage=None, broken_stage=None, unknown_stage=None):
        self.source, self.analyses, self.pack, self.snapshot = source, analyses, pack, snapshot
        self.calls = []
        self.prompts = []
        self.root_stage, self.broken_stage, self.unknown_stage = root_stage, broken_stage, unknown_stage
        self.broken_once = False

    def __call__(self, name, role, prompt, payload, json_output=True):
        self.calls.append((name, role, deepcopy(payload)))
        self.prompts.append((name, prompt))
        if self.unknown_stage and name.startswith(self.unknown_stage):
            raise RuntimeError("transport_outcome_unknown")
        if self.broken_stage and name.startswith(self.broken_stage) and not self.broken_once:
            self.broken_once = True
            return "unformatted script" if name.startswith("SCREENPLAY") else {}
        if name.startswith("MATERIAL_REVIEW"):
            return pass_review(payload)
        if name.startswith(("FRAMEWORK_LOCAL", "SNAPSHOT_LOCAL", "DESIGN_LOCAL")):
            return generic_pass(payload)
        if name.startswith("FRAMEWORK_CONSISTENCY"):
            return {"reviewed_artifact_sha256": payload["reviewed_artifact_sha256"], "decision": "pass", "issues": [], "summary": "consistent"}
        if name.startswith("FRAMEWORK_"):
            return framework(self.pack)
        if name.startswith("EPISODE_SNAPSHOT"):
            return deepcopy(self.snapshot)
        if name.startswith("VISUAL_DESIGN"):
            return DESIGN
        if name.startswith("FACTS"):
            return {"source_sha256": payload["source_sha256"], "facts": [{"id": "f1", "kind": "relationship",
                    "statement": "林青是小明的继母", "source_evidence": [{"chapter_index": 1, "quote": "林青是小明的继母。"}]}]}
        if name.startswith("SCREENPLAY"):
            return DRAFT
        if name.startswith("FINAL_"):
            fail = self.root_stage and name == "FINAL_CONTENT_00"
            result = {"reviewed_draft_sha256": payload["reviewed_draft_sha256"],
                      "reviewed_chapter_indices": payload["required_reviewed_chapter_indices"],
                      "whole_draft_reviewed": True, "decision": "revise" if fail else "pass",
                      "checks": {key: "pass" for key in CHECKS}, "blocking_issues": [], "non_blocking_notes": [],
                      "timing_assessment": [{"segment": "0—10", "spoken_estimate_seconds": 1.2,
                                              "serial_actions": [], "parallel_actions": ["交钥匙"], "reason": "fixture"}],
                      "summary": "fixture"}
            if fail:
                result["checks"]["character_relationships"] = "fail"
                result["blocking_issues"] = [{"check": "character_relationships", "location": "首段",
                    "draft_quote": "小明把钥匙交给林青，林青接住，小明点头。", "reason": "fixture responsibility issue",
                    "required_change": "修责任层后重新生成", "source_evidence": [{"chapter_index": 1, "quote": "林青是小明的继母。"}]}]
            if name.startswith("FINAL_TIMING"):
                result["segment_timing"] = [{"range": row["range"], "serial_actions": [],
                                             "parallel_actions": [{"evidence_id": row["evidence"][0]["id"], "seconds": 2}],
                                             "reason": "动作与对白同时"} for row in payload["measured_segments"]]
            return result
        if name.startswith("ROOT_CAUSE"):
            stage = self.root_stage
            paths = {"framework": ("characters.0.relationships.0.text", "林青是小明的继母"),
                     "snapshot": ("snapshot.beats.0.purpose", "交代道具转移"),
                     "design": ("", "普通家庭设计稿"), "facts": ("facts.0.statement", "林青是小明的继母"),
                     "screenplay": ("", "小明把钥匙交给林青"),
                     "materials": ("CH001.facts.1.statement", "林青是小明的继母")}
            path, quote = paths[stage]
            return {"reviewed_issues_sha256": payload["reviewed_issues_sha256"], "decision": "diagnosed", "reason": "fixture proof",
                    "diagnoses": [{"final_issue_index": 0, "layer": "character", "responsible_stage": stage,
                                   "chapter_index": 1 if stage == "materials" else 0,
                                   "cause": "该阶段产生错误", "required_change": "从责任层重建",
                                   "source_evidence": [{"chapter_index": 1, "quote": "林青是小明的继母。"}],
                                   "artifact_evidence": [{"artifact_name": stage, "artifact_sha256": payload["artifact_hashes"][stage],
                                                          "field_path": path, "evidence_kind": "present", "quote": quote}]}]}
        raise AssertionError(name)


def run(fake, source, analyses, pack, **kwargs):
    records = {}
    result = flow.run_production(fake, source, pack, {"target_seconds": 10, "root_repair_limit": 2},
                                stats=lambda _: {}, record=lambda key, value: records.__setitem__(key, value),
                                remaining_calls=lambda: 1000-len(fake.calls), chapter_materials=analyses, **kwargs)
    return result, records


def test_clean_route_only_final_reviews_use_deepseek_and_preserve_bindings():
    source, analyses, pack, snapshot = fixture()
    fake = Fake(source, analyses, pack, snapshot)
    result, records = run(fake, source, analyses, pack)
    assert result["draft"] == DRAFT
    assert result["binding"]["source_pack_sha256"] == flow.digest(pack)
    assert result["binding"]["media_acceptance"] is False
    assert "snapshot" in result["binding"]["artifact_hashes"]
    assert {name for name, role, _ in fake.calls if role == "director"} == {"FINAL_CONTENT_00", "FINAL_TIMING_00"}
    names = [name for name, _, _ in fake.calls]
    assert names.index("MATERIAL_REVIEW_00_CH003_A0") < names.index("FRAMEWORK_00")
    assert names.index("SNAPSHOT_LOCAL_00_CH001") < names.index("VISUAL_DESIGN_00")
    assert records["SCRIPT_STATE_BINDING_00"]["scene_bindings"][0]["scene_id"] == "scene_1"
    assert len(fake.calls) < flow.minimum_calls(3)["total"]  # Conservative maximum source scope.


def test_actual_writing_and_design_payloads_exclude_whole_book_future_state():
    source, analyses, pack, snapshot = fixture()
    fake = Fake(source, analyses, pack, snapshot)
    run(fake, source, analyses, pack)
    for name, _, payload in fake.calls:
        if not name.startswith(("EPISODE_SNAPSHOT", "VISUAL_DESIGN", "FACTS", "SCREENPLAY", "FINAL_", "DESIGN_LOCAL")):
            continue
        encoded = json.dumps(payload, ensure_ascii=False)
        assert "第三天，林青带小明去了学校。" not in encoded
        assert "第二天，林青和小明在客厅。" not in encoded
        assert "CH3-F001" not in encoded
        assert "global_bible" not in payload and "planning_framework" not in payload
        if not name.startswith("EPISODE_SNAPSHOT"):
            assert "episode_state_plan" in payload
        assert [row["index"] for row in payload["selected_original_chapters"]] == [1]
        assert payload["episode_selection_brief"]["episode_arc"] == framework(pack)["episode_arc"]
        assert "selection_reason" not in payload["episode_selection_brief"]


@pytest.mark.parametrize("stage", ["framework", "snapshot", "design", "facts", "screenplay", "materials"])
def test_root_repair_rebuilds_snapshot_and_all_dependent_complete_artifacts(stage):
    source, analyses, pack, snapshot = fixture()
    fake = Fake(source, analyses, pack, snapshot, root_stage=stage)
    repairs = []
    def repair(index, issues, attempt):
        repairs.append((index, attempt))
        changed = deepcopy(analyses)
        raw = material.raw_candidate(changed[0])
        raw["facts"][1]["categories"] = ["character", "world"]
        changed[0] = material.validate(raw, source["chapters"], changed[0]["chapter_plan"])
        updated = material.cloud_input(material.facts_catalog(changed, source["chapters"], book_name=pack["book_name"]))
        fake.pack = updated
        return {"pack": updated, "chapter_materials": changed}
    result, records = run(fake, source, analyses, pack, repair_materials=repair)
    assert result["binding"]["root_repairs"] == 1
    assert records["INVALIDATION_00"]["invalidated"] == flow.invalidated_stages(stage)
    names = [name for name, _, _ in fake.calls]
    assert "SCREENPLAY_01" in names and "FINAL_CONTENT_01" in names and "FINAL_TIMING_01" in names
    assert ("EPISODE_SNAPSHOT_01" in names) == (stage in ("materials", "framework", "snapshot"))
    assert ("SNAPSHOT_LOCAL_01_CH001" in names) == (stage in ("materials", "framework", "snapshot"))
    assert ("VISUAL_DESIGN_01" in names) == (stage in ("materials", "framework", "snapshot", "design"))
    assert ("FACTS_01" in names) == (stage != "screenplay")
    assert bool(repairs) == (stage == "materials")


@pytest.mark.parametrize("stage", ["MATERIAL_REVIEW", "EPISODE_SNAPSHOT", "SNAPSHOT_LOCAL", "FACTS", "SCREENPLAY", "FINAL_CONTENT"])
def test_completed_protocol_failure_has_one_full_repair(stage):
    source, analyses, pack, snapshot = fixture()
    fake = Fake(source, analyses, pack, snapshot, broken_stage=stage)
    result, _ = run(fake, source, analyses, pack)
    assert result["draft"] == DRAFT
    assert len([name for name, _, _ in fake.calls if name.endswith("PROTOCOL_REPAIR")]) == 1


@pytest.mark.parametrize("stage", ["MATERIAL_REVIEW", "EPISODE_SNAPSHOT", "SNAPSHOT_LOCAL", "SCREENPLAY", "FINAL_CONTENT"])
def test_unknown_call_outcome_never_retried(stage):
    source, analyses, pack, snapshot = fixture()
    fake = Fake(source, analyses, pack, snapshot, unknown_stage=stage)
    with pytest.raises(RuntimeError, match="outcome_unknown"):
        run(fake, source, analyses, pack)
    assert len([name for name, _, _ in fake.calls if name.startswith(stage)]) == 1


@pytest.mark.parametrize("mutation,reason", [
    (lambda text: text.replace("scene_id: scene_1", "scene_id: unknown"), "scene_plan_coverage"),
    (lambda text: text.replace("state_ids:", "missing_ids:"), "marker_missing"),
    (lambda text: text.replace(",key_child", ""), "state_plan_binding"),
    (lambda text: text.replace(",key_child", ",key_child,key_child"), "state_plan_binding"),
])
def test_script_scene_and_state_reference_mismatches_are_program_failures(mutation, reason):
    source, analyses, pack, snapshot = fixture()
    with pytest.raises(ValueError, match=reason):
        flow.validate_scene_state_refs(mutation(DRAFT), {"snapshot": snapshot})


def test_compact_framework_facts_keep_states_and_originals_without_repeated_catalogs():
    source, analyses, pack, _ = fixture()
    payload = flow.framework_source_payload(source, pack)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert [row["text"] for row in payload["source_contexts"]] == [row["text"] for row in source["chapters"]]
    assert "passage_catalog" not in encoded and "source_evidence" not in encoded and "exact_quote" not in encoded
    fact = payload["chapter_fact_candidates"][0]["facts"][2]
    assert fact["state_changes"][0]["before_value"] == "小明"
    assert fact["state_changes"][0]["after_value"] == "林青"
    assert fact["event_time"] == "chapter_present"


def test_candidate_tampering_and_insufficient_admission_stop_before_models():
    source, analyses, pack, snapshot = fixture()
    fake = Fake(source, analyses, pack, snapshot)
    changed = deepcopy(analyses)
    changed[0]["facts"][0]["state_changes"] = []
    with pytest.raises(ValueError):
        run(fake, source, changed, pack)
    assert fake.calls == []
    with pytest.raises(ValueError, match="insufficient_capacity"):
        flow.run_production(fake, source, pack, {}, stats=lambda _: {}, record=lambda *_: None,
                            remaining_calls=lambda: 1, chapter_materials=analyses)
    assert fake.calls == []


def test_material_review_requires_entity_types_and_missing_typed_state_semantics():
    source, analyses, pack, snapshot = fixture()
    fake = Fake(source, analyses, pack, snapshot)
    run(fake, source, analyses, pack)
    prompt = next(prompt for name, prompt in fake.prompts if name.startswith("MATERIAL_REVIEW"))
    assert "typed state_changes" in prompt and "地名被当人物" in prompt
    assert "coverage 非空" in prompt


@pytest.mark.parametrize("repeated_rejection", [False, True])
def test_semantically_wrong_entity_and_missing_states_require_repair_and_new_review(repeated_rejection):
    # Regression for real local symptoms: a place was typed as a person and
    # states written in statements were absent from typed state_changes.
    # This synthesizes those defects; no real provider report is fabricated.
    source, good, _, snapshot = fixture()
    bad = deepcopy(good)
    raw = material.raw_candidate(bad[0])
    raw["entities"][3]["kind"] = "person"
    raw["facts"][0]["state_changes"] = []
    bad[0] = material.validate(raw, source["chapters"], bad[0]["chapter_plan"])
    pack = material.cloud_input(material.facts_catalog(bad, source["chapters"], book_name=source["book_name"]))
    class RejectBad(Fake):
        def __call__(self, name, role, prompt, payload, json_output=True):
            result = super().__call__(name, role, prompt, payload, json_output)
            if name.startswith("MATERIAL_REVIEW_00_CH001") and (name.endswith("A0") or repeated_rejection):
                result["decision"] = "revise"
                for row in result["checks"]:
                    if row["dimension"] in ("entity_mentions", "state_changes"):
                        row["decision"] = "revise"
                result["issues"] = [{"category": category, "location": "候选第1事实",
                                      "fact_ids": ["CH1-F001"], "paragraph_ids": ["CH1-P001"],
                                      "reason": reason, "source_refs": [{"paragraph_id": "CH1-P001",
                                      "exact_quote": "林青和小明在客厅，门外是走廊。钥匙原来由小明拿着。"}]}
                                     for category, reason in [("entity_mentions", "客厅是地点而非人物"),
                                                               ("state_changes", "句子记录了位置与持物但类型状态遗漏")]]
            return result
    fake = RejectBad(source, bad, pack, snapshot)
    repair_calls = []
    def repair(index, issues, attempt):
        repair_calls.append((index, attempt, issues))
        updated = material.cloud_input(material.facts_catalog(good, source["chapters"], book_name=source["book_name"]))
        fake.pack = updated
        return {"pack": updated, "chapter_materials": good}
    if repeated_rejection:
        with pytest.raises(flow.ProductionRejected, match="material_semantic_revision_limit"):
            run(fake, source, bad, pack, repair_materials=repair)
        assert not any(name.startswith("FRAMEWORK_") for name, _, _ in fake.calls)
    else:
        result, records = run(fake, source, bad, pack, repair_materials=repair)
        assert result["draft"] == DRAFT
        assert records["MATERIAL_BOUND_00_CH001_A0"]["downstream_ready"] is False
        assert records["MATERIAL_BOUND_00_CH001_A1"]["downstream_ready"] is True
    assert [(row[0], row[1]) for row in repair_calls] == [(1, 1)]
    assert len([name for name, _, _ in fake.calls if name.startswith("MATERIAL_REVIEW_00_CH001")]) == 2


def test_persistent_script_state_marker_failure_stops_before_final_reviews():
    source, analyses, pack, snapshot = fixture()
    class BadScript(Fake):
        def __call__(self, name, role, prompt, payload, json_output=True):
            result = super().__call__(name, role, prompt, payload, json_output)
            return result.replace("state_ids:", "wrong_ids:") if name.startswith("SCREENPLAY") else result
    fake = BadScript(source, analyses, pack, snapshot)
    with pytest.raises(ValueError, match="state_marker_missing"):
        run(fake, source, analyses, pack)
    assert len([name for name, _, _ in fake.calls if name.startswith("SCREENPLAY")]) == 2
    assert not any(name.startswith("FINAL_") for name, _, _ in fake.calls)


def test_snapshot_semantic_failure_is_diagnosed_and_reaudited_before_any_design():
    source, analyses, pack, snapshot = fixture()
    class RejectSnapshot(Fake):
        def __call__(self, name, role, prompt, payload, json_output=True):
            result = super().__call__(name, role, prompt, payload, json_output)
            if name == "SNAPSHOT_LOCAL_00_CH001":
                result.update(decision="revise", issues=[{"check": "identity_and_relationships", "layer": "character",
                              "location": "snapshot.states", "reason": "隔离责任路由断言", "required_change": "核对关系状态",
                              "source_evidence": [{"chapter_index": 1, "quote": "林青是小明的继母。"}]}])
                result["checks"]["identity_and_relationships"] = "fail"
            return result
    fake = RejectSnapshot(source, analyses, pack, snapshot, root_stage="snapshot")
    result, records = run(fake, source, analyses, pack)
    names = [name for name, _, _ in fake.calls]
    assert result["binding"]["root_repairs"] == 1
    assert "VISUAL_DESIGN_00" not in names and "SCREENPLAY_00" not in names
    assert names.index("SNAPSHOT_LOCAL_01_CH001") < names.index("VISUAL_DESIGN_01")
    assert records["INVALIDATION_00"]["responsible_stage"] == "snapshot"


@pytest.mark.parametrize("recover", [False, True])
def test_whole_script_over_target_is_repaired_once_or_rejected_before_final_reviews(recover):
    source, analyses, pack, snapshot = fixture()
    class OverTarget(Fake):
        def __call__(self, name, role, prompt, payload, json_output=True):
            result = super().__call__(name, role, prompt, payload, json_output)
            if name.startswith("SCREENPLAY") and not (recover and name.endswith("PROTOCOL_REPAIR")):
                return result.replace("0—10秒", "0—20秒")
            return result
    fake = OverTarget(source, analyses, pack, snapshot)
    if recover:
        result, records = run(fake, source, analyses, pack)
        assert result["draft"] == DRAFT
        assert records["SCRIPT_TIMING_BINDING_00"]["duration_seconds"] == 10
    else:
        with pytest.raises(ValueError, match="total_duration_exceeds_target"):
            run(fake, source, analyses, pack)
        assert not any(name.startswith("FINAL_") for name, _, _ in fake.calls)
    assert len([name for name, _, _ in fake.calls if name.startswith("SCREENPLAY")]) == 2


def test_scene_duration_cannot_borrow_another_scenes_budget():
    _, _, _, snapshot = fixture()
    snapshot["target_seconds"] = 20
    snapshot["beats"][0]["duration_seconds"] = 10
    with pytest.raises(ValueError, match="scene_duration_exceeds_plan"):
        flow.validate_script_timing(DRAFT.replace("0—10秒", "0—15秒"), {"snapshot": snapshot}, 20)


def test_time_segments_before_first_scene_are_rejected():
    _, _, _, snapshot = fixture()
    text = "### 【0—2秒】\n开场。\n" + DRAFT.replace("0—10秒", "2—10秒")
    with pytest.raises(ValueError, match="time_segment_outside_scene"):
        flow.validate_script_timing(text, {"snapshot": snapshot}, 10)


def test_arc_sources_outside_selected_chapters_are_refused_not_silently_dropped():
    source, _, pack, _ = fixture()
    bad = framework(pack)
    bad["episode_arc"]["source_passage_ids"] = ["CH3-P001"]
    with pytest.raises(ValueError, match="episode_arc_source_outside_selection"):
        flow.validate_framework(bad, pack, source["chapters"])
    with pytest.raises(ValueError, match="episode_arc_source_outside_selection"):
        flow.episode_selection_brief(bad, pack, source)


def test_future_framework_repair_evidence_does_not_leak_into_episode_creative_inputs():
    source, analyses, pack, snapshot = fixture()
    future = "第三天，林青带小明去了学校。"
    class RepairFutureFramework(Fake):
        def __call__(self, name, role, prompt, payload, json_output=True):
            result = super().__call__(name, role, prompt, payload, json_output)
            if name == "FRAMEWORK_LOCAL_00_CH003":
                result.update(decision="revise", issues=[{"check": "temporal_scope", "layer": "event",
                              "location": "mainline.2", "reason": future, "required_change": future,
                              "source_evidence": [{"chapter_index": 3, "quote": future}]}])
                result["checks"]["temporal_scope"] = "fail"
            return result
    fake = RepairFutureFramework(source, analyses, pack, snapshot)
    result, records = run(fake, source, analyses, pack)
    assert result["binding"]["root_repairs"] == 1
    assert future in json.dumps(records["INVALIDATION_00"], ensure_ascii=False)
    framework_retry = next(payload for name, _, payload in fake.calls if name == "FRAMEWORK_01")
    assert framework_retry["required_source_corrections"][0]["reason"] == future
    assert framework_retry["required_source_corrections"][0]["responsible_stage"] == "framework"
    for name, _, payload in fake.calls:
        if name.startswith(("EPISODE_SNAPSHOT", "SNAPSHOT_LOCAL", "VISUAL_DESIGN", "DESIGN_LOCAL", "FACTS", "SCREENPLAY", "FINAL_")):
            assert future not in json.dumps(payload, ensure_ascii=False)
            assert "episode_selection_brief" in payload
            assert payload["episode_selection_brief"]["episode_arc"] == framework(pack)["episode_arc"]


def test_episode_correction_with_future_source_is_rejected():
    with pytest.raises(ValueError, match="correction_future_source"):
        flow._stage_corrections([{"responsible_stage": "snapshot", "source_evidence": [{"chapter_index": 3}]}], "snapshot", [1])

