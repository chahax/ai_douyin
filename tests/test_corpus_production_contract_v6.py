"""Offline routing and evidence contracts, not model content acceptance."""
from copy import deepcopy
import json

import pytest

from src.content_factory import corpus_chapter_materials_v6 as material
from src.content_factory import corpus_production_contract_v6 as flow
from src.content_factory.screenplay_review_cycle_v2 import CHECKS
from tests.test_corpus_chapter_materials_v6 import pass_review
from tests.test_corpus_episode_state_v6 import episode_fixture
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


def test_compact_framework_keeps_classified_materials_and_complete_originals():
    source, analyses, pack, _ = fixture()
    payload = flow.framework_source_payload(source, pack)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert [row["text"] for row in payload["source_contexts"]] == [row["text"] for row in source["chapters"]]
    assert "passage_catalog" not in encoded and "source_evidence" not in encoded and "exact_quote" not in encoded
    fact = payload["chapter_material_candidates"][0]["facts"][2]
    assert "state_changes" not in fact and "entity_ids" not in fact
    assert "entities" not in payload["chapter_material_candidates"][0]
    assert fact["event_time"] == "chapter_present"


def test_candidate_tampering_and_insufficient_admission_stop_before_models():
    source, analyses, pack, snapshot = fixture()
    fake = Fake(source, analyses, pack, snapshot)
    changed = deepcopy(analyses)
    changed[0]["facts"][0]["statement"] = "伪造已绑定材料"
    with pytest.raises(ValueError):
        run(fake, source, changed, pack)
    assert fake.calls == []
    with pytest.raises(ValueError, match="insufficient_capacity"):
        flow.run_production(fake, source, pack, {}, stats=lambda _: {}, record=lambda *_: None,
                            remaining_calls=lambda: 1, chapter_materials=analyses)
    assert fake.calls == []


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


def test_material_classification_accepts_natural_facts_without_any_state_table():
    source, analyses, pack, snapshot = fixture()
    assert all("entities" not in row for row in analyses)
    assert all("state_changes" not in fact and "entity_ids" not in fact
               for row in analyses for fact in row["facts"])
    fake = Fake(source, analyses, pack, snapshot)
    result, records = run(fake, source, analyses, pack)
    assert result["draft"] == DRAFT
    for name, _, payload in fake.calls:
        if name.startswith("MATERIAL_REVIEW"):
            assert "state_changes" not in payload["candidate"]["facts"][0]
            assert "entities" not in payload["candidate"]
            checks = payload["output_schema"]["properties"]["checks"]["items"]["properties"]["dimension"]["enum"]
            assert "state_changes" not in checks and "entity_mentions" not in checks
    snap_call = next(payload for name, _, payload in fake.calls if name == "SNAPSHOT_LOCAL_00_CH001")
    assert snap_call["episode_material_candidates"][0]["facts"] == analyses[0]["facts"]
    assert "state_completeness" in snap_call["output_schema"]["properties"]["checks"]["properties"]
    assert "chapter_material_reviews_sha256" in result["binding"]


@pytest.mark.parametrize("repeated", [False, True])
def test_missing_episode_detail_fails_snapshot_stage_and_never_reclassifies_chapters(repeated):
    source, analyses, pack, snapshot = fixture()
    class MissingDetail(Fake):
        def __call__(self, name, role, prompt, payload, json_output=True):
            result = super().__call__(name, role, prompt, payload, json_output)
            if name.startswith("SNAPSHOT_LOCAL") and (name.startswith("SNAPSHOT_LOCAL_00") or repeated):
                result["decision"] = "revise"
                result["checks"]["state_completeness"] = "fail"
                result["issues"] = [{"check": "state_completeness", "layer": "event", "location": "snapshot.states",
                                     "reason": "材料已记录交接，本集仍缺必要状态细节。",
                                     "required_change": "在本集快照补充状态及动作链并复审。",
                                     "source_evidence": [{"chapter_index": 1, "quote": "林青是小明的继母。"}]}]
            # Root diagnosis is an explicit snapshot omission, not a fabricated
            # claim that initial classification should contain detailed states.
            if name.startswith("ROOT_CAUSE"):
                row = result["diagnoses"][0]
                row["artifact_evidence"][0].update(field_path="snapshot.states", evidence_kind="omission", quote="")
            return result
    fake = MissingDetail(source, analyses, pack, snapshot, root_stage="snapshot")
    # We simulate the semantic reviewer, not model quality: the contract must
    # route and block completed review failures regardless of provider.
    if repeated:
        with pytest.raises(flow.ProductionRejected, match="snapshot_semantic_revision_limit_reached"):
            run(fake, source, analyses, pack)
    else:
        result, records = run(fake, source, analyses, pack)
        assert result["binding"]["root_repairs"] == 1
        assert records["INVALIDATION_00"]["responsible_stage"] == "snapshot"
    names = [name for name, _, _ in fake.calls]
    assert "SCREENPLAY_00" not in names and "VISUAL_DESIGN_00" not in names
    assert len([name for name in names if name.startswith("MATERIAL_REVIEW")]) == len(analyses)
    assert "FRAMEWORK_01" not in names
    if repeated:
        assert not any(name.startswith(("SCREENPLAY", "VISUAL_DESIGN", "FINAL_")) for name in names)


def test_state_detail_review_cannot_send_initial_materials_back_for_missing_state_fields():
    source, analyses, pack, snapshot = fixture()
    artifacts = {"materials": flow._material_artifacts(analyses), "snapshot": {"snapshot": snapshot}}
    issues = [{"check": "state_completeness", "reason": "本集漏状态"}]
    raw = {"reviewed_issues_sha256": flow.digest(issues), "decision": "diagnosed", "reason": "misrouted",
           "diagnoses": [{"final_issue_index": 0, "layer": "event", "responsible_stage": "materials",
                          "chapter_index": 1, "cause": "不应要求第一阶段提供状态表", "required_change": "错误返修",
                          "source_evidence": [{"chapter_index": 1, "quote": "林青是小明的继母。"}],
                          "artifact_evidence": [{"artifact_name": "materials", "artifact_sha256": flow.digest(artifacts["materials"]),
                                                 "field_path": "CH001.facts", "evidence_kind": "omission", "quote": ""}]}]}
    with pytest.raises(ValueError, match="state_detail_omission_belongs_to_snapshot"):
        flow.validate_diagnosis(raw, issues, artifacts, source["chapters"])


def test_letter_fact_is_accepted_as_material_but_omitted_knowledge_fails_episode_review():
    from src.content_factory import corpus_episode_state_v6 as episode
    from tests.test_corpus_episode_state_v6 import letter_fixture
    chapters, library, raw = letter_fixture()
    source = {"chapters": chapters, "book_name": library["book_name"]}
    materials_result = flow.review_materials(lambda name, role, prompt, payload: pass_review(payload),
                                            source, library["analyses"])
    assert materials_result["decision"] == "pass"
    assert "第一次发现了信" in library["facts"][-1]["statement"]
    assert "state_changes" not in library["facts"][-1]
    # Deliberately retain the discovery action but omit all knowledge detail.
    # A self-consistent empty transition is not a semantic acceptance.
    raw["states"] = [s for s in raw["states"] if s["kind"] != "knowledge"]
    for frame in raw["snapshots"]:
        frame["state_ids"] = [sid for sid in frame["state_ids"] if sid not in ("letter_unknown", "letter_known")]
    raw["beats"][0]["actions"][0].update(kind="perform", changes=[])
    accepted = episode.validate_episode(raw, library, chapters, [1], 10)
    assert not accepted["validation"]["knowledge_completeness_semantically_verified"]
    context = episode.build_episode_context(accepted, library, chapters)
    context["episode_material_candidates"] = library["analyses"]
    def reviewer(name, role, prompt, payload):
        assert payload["episode_material_candidates"][0]["facts"][-1]["id"] == "CH1-F004"
        result = generic_pass(payload)
        result.update(decision="revise", issues=[{
            "check": "state_completeness", "layer": "event", "location": "snapshot.states",
            "reason": "本集演出首次发现，但未表达此前未知到获知的状态变化。",
            "required_change": "仅返修本集知情状态和learn动作。",
            "source_evidence": [{"chapter_index": 1, "quote": "阿禾打开柜子，第一次发现了信。"}]}])
        result["checks"]["state_completeness"] = "fail"
        return result
    reviewed = flow.review_snapshot(reviewer, context, accepted, record=lambda *_: None, attempt=0)
    assert reviewed["downstream_ready"] is False
    assert reviewed["issues"][0]["check"] == "state_completeness"

