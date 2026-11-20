from copy import deepcopy
import hashlib
import json

import pytest

from src.content_factory import corpus_chapters_v4 as material
from src.content_factory import corpus_production_contract_v4 as flow
from src.content_factory.screenplay_review_cycle_v2 import CHECKS


def fixture(count=2):
    chapters = []
    for i in range(1, count + 1):
        text = f"第{i}天，林青是小明的继母。\n林青把面包递给小明。\n小明点头接过面包。\n"
        chapters.append({"index": i, "title": f"第{i}章", "text": text,
                         "sha256": hashlib.sha256(text.encode()).hexdigest()})
    source = {"book_name": "测试书", "chapters": chapters}
    plans = material.plan_chapters(chapters)
    analyses = []
    for plan in plans:
        payload = material.chapter_payload(chapters, plan)
        raw = {"chapter_id": plan["id"], "chapter_index": plan["chapter_index"],
               "assignments": [{"passage_id": row["id"], "categories": ["event"], "importance": "supporting"}
                               for row in payload["paragraph_index"]]}
        analyses.append(material.validate(raw, chapters, plan))
    pack = material.cloud_input(material.materials_index(analyses, chapters, book_name="测试书"))
    return source, analyses, pack


def framework(pack):
    by_chapter = {}
    for row in pack["selected_core_passages"]:
        by_chapter.setdefault(row["chapter_index"], row["id"])
    first = by_chapter[1]
    return {"world": [], "characters": [{"id": "lin", "name": "林青", "aliases": [],
             "relationships": [{"text": "林青是小明的继母", "source_passage_ids": [first]}],
             "source_passage_ids": [first]}], "locations": [],
            "mainline": [{"chapter_indices": [idx], "text": "林青把面包递给小明", "source_passage_ids": [pid]}
                         for idx, pid in by_chapter.items()],
            "selected_chapter_indices": [1], "selection_reason": "完整的递面包事件",
            "episode_arc": {"opening": "林青拿着面包", "development": "递出面包", "turning_point": "小明接住", "ending": "小明点头",
                            "source_passage_ids": [first]}, "limitations": ["全量原文，分类不保证语义正确"]}


DRAFT = '世界背景：普通家庭。\n人物：林青、小明。\n### 【0—10秒】\n林青递出面包，小明接住并点头。\n林青：“先吃点面包。”\n'
DESIGN = "普通家庭设计稿；林青和小明在屋里递接面包，日间自然光。服装和家具属于创作补足。"


def generic_pass(payload):
    properties = payload["output_schema"]["properties"]
    return {"reviewed_artifact_sha256": properties["reviewed_artifact_sha256"]["const"],
            "checked_chapter_indices": properties["checked_chapter_indices"]["items"]["enum"],
            "checked_ids": properties["checked_ids"]["items"]["enum"],
            "decision": "pass", "checks": {key: "pass" for key in properties["checks"]["properties"]},
            "issues": [], "summary": "fixture semantic pass"}


class Fake:
    def __init__(self, source, analyses, pack, root_stage=None, broken_stage=None, unknown_stage=None):
        self.source, self.analyses, self.pack = source, analyses, pack
        self.calls = []
        self.root_stage, self.broken_stage, self.unknown_stage = root_stage, broken_stage, unknown_stage
        self.broken_once = False

    def __call__(self, name, role, prompt, payload, json_output=True):
        self.calls.append((name, role, deepcopy(payload)))
        if self.unknown_stage and name.startswith(self.unknown_stage):
            raise RuntimeError("transport_outcome_unknown")
        if self.broken_stage and name.startswith(self.broken_stage) and not self.broken_once:
            self.broken_once = True
            return "unformatted script" if name.startswith("SCREENPLAY") else {}
        if name.startswith(("MATERIAL_REVIEW", "FRAMEWORK_LOCAL", "DESIGN_LOCAL")):
            return generic_pass(payload)
        if name.startswith("FRAMEWORK_CONSISTENCY"):
            return {"reviewed_artifact_sha256": payload["reviewed_artifact_sha256"], "decision": "pass", "issues": [], "summary": "consistent"}
        if name.startswith("FRAMEWORK_"):
            return framework(self.pack)
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
                                              "serial_actions": [], "parallel_actions": ["递面包"], "reason": "fixture"}],
                      "summary": "fixture"}
            if fail:
                result["checks"]["character_relationships"] = "fail"
                result["blocking_issues"] = [{"check": "character_relationships", "location": "首段",
                    "draft_quote": "林青递出面包，小明接住并点头。", "reason": "fixture responsibility issue",
                    "required_change": "修责任层后重新生成", "source_evidence": [{"chapter_index": 1, "quote": "林青是小明的继母。"}]}]
            if name.startswith("FINAL_TIMING"):
                result["segment_timing"] = [{"range": row["range"], "serial_actions": [],
                                             "parallel_actions": [{"evidence_id": row["evidence"][0]["id"], "seconds": 2}],
                                             "reason": "动作与对白同时"} for row in payload["measured_segments"]]
            return result
        if name.startswith("ROOT_CAUSE"):
            stage = self.root_stage
            paths = {"framework": ("characters.0.relationships.0.text", "林青是小明的继母"),
                     "design": ("", "普通家庭设计稿"), "facts": ("facts.0.statement", "林青是小明的继母"),
                     "screenplay": ("", "林青递出面包"), "materials": ("CH001.assignments.0.categories", "event")}
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


def test_clean_route_roles_and_full_source_bindings():
    source, analyses, pack = fixture()
    fake = Fake(source, analyses, pack)
    result, records = run(fake, source, analyses, pack)
    assert result["draft"] == DRAFT
    assert result["binding"]["source_pack_sha256"] == flow.digest(pack)
    assert result["binding"]["media_acceptance"] is False
    assert {name for name, role, _ in fake.calls if role == "director"} == {"FINAL_CONTENT_00", "FINAL_TIMING_00"}
    assert all(role == "writer" for name, role, _ in fake.calls if name.startswith(("MATERIAL", "FRAMEWORK_00", "VISUAL", "FACTS", "SCREENPLAY")))
    assert len([name for name, _, _ in fake.calls if name.startswith("DESIGN_LOCAL")]) == 2
    assert len(fake.calls) == flow.minimum_calls(2)["total"]
    assert "MATERIALS_ACCEPTED" in records


@pytest.mark.parametrize("stage", ["framework", "design", "facts", "screenplay", "materials"])
def test_root_repair_invalidates_and_recreates_all_downstream(stage):
    source, analyses, pack = fixture()
    fake = Fake(source, analyses, pack, root_stage=stage)
    repairs = []
    def repair(index, issues, attempt):
        repairs.append((index, attempt))
        changed = deepcopy(analyses)
        changed[0]["assignments"][0]["categories"] = ["character", "event"]
        raw = {key: changed[0][key] for key in ("chapter_id", "chapter_index", "assignments")}
        changed[0] = material.validate(raw, source["chapters"], changed[0]["chapter_plan"])
        updated = material.cloud_input(material.materials_index(changed, source["chapters"], book_name="测试书"))
        fake.pack = updated
        return {"pack": updated, "chapter_materials": changed}
    result, records = run(fake, source, analyses, pack, repair_materials=repair)
    assert result["binding"]["root_repairs"] == 1
    assert records["INVALIDATION_00"]["invalidated"] == flow.invalidated_stages(stage)
    names = [name for name, _, _ in fake.calls]
    assert "SCREENPLAY_01" in names and "FINAL_CONTENT_01" in names and "FINAL_TIMING_01" in names
    assert ("FRAMEWORK_01" in names) == (stage in ("framework", "materials"))
    assert ("VISUAL_DESIGN_01" in names) == (stage in ("framework", "materials", "design"))
    assert ("FACTS_01" in names) == (stage != "screenplay")
    assert bool(repairs) == (stage == "materials")


@pytest.mark.parametrize("stage", ["FACTS", "SCREENPLAY", "FRAMEWORK_LOCAL", "FINAL_CONTENT"])
def test_known_protocol_failure_gets_one_bounded_repair(stage):
    source, analyses, pack = fixture()
    fake = Fake(source, analyses, pack, broken_stage=stage)
    result, _ = run(fake, source, analyses, pack)
    assert result["draft"] == DRAFT
    assert len([name for name, _, _ in fake.calls if name.endswith("PROTOCOL_REPAIR")]) == 1


@pytest.mark.parametrize("stage", ["MATERIAL_REVIEW", "FRAMEWORK_LOCAL", "FACTS", "SCREENPLAY", "FINAL_CONTENT"])
def test_unknown_transport_never_retried(stage):
    source, analyses, pack = fixture()
    fake = Fake(source, analyses, pack, unknown_stage=stage)
    with pytest.raises(RuntimeError, match="outcome_unknown"):
        run(fake, source, analyses, pack)
    assert len([name for name, _, _ in fake.calls if name.startswith(stage)]) == 1
    assert not any(name.endswith("PROTOCOL_REPAIR") for name, _, _ in fake.calls)


def test_insufficient_clean_budget_rejected_before_any_call():
    source, analyses, pack = fixture()
    fake = Fake(source, analyses, pack)
    with pytest.raises(ValueError, match="insufficient_capacity"):
        flow.run_production(fake, source, pack, {}, stats=lambda _: {}, record=lambda *_: None,
                            remaining_calls=lambda: 1, chapter_materials=analyses)
    assert fake.calls == []


def test_changed_pack_classification_rejected_before_calls():
    source, analyses, pack = fixture()
    altered = deepcopy(analyses)
    altered[0]["assignments"][0]["categories"] = ["character"]
    fake = Fake(source, analyses, pack)
    with pytest.raises(ValueError, match="binding_mismatch"):
        run(fake, source, altered, pack)
    assert not fake.calls


def test_framework_claim_identity_does_not_embed_other_chapter_relationships():
    source, analyses, pack = fixture(4)
    fw = framework(pack)
    remote = next(row["id"] for row in pack["selected_core_passages"] if row["chapter_index"] == 4)
    fw["characters"][0]["relationships"].append({"text": "后文关系", "source_passage_ids": [remote]})
    first = flow._framework_claims(fw, pack, 1)
    identity = next(row for row in first if row["id"].endswith("identity"))
    assert "relationships" not in identity["value"]
    assert not any(row["id"].endswith("relationships.1") for row in first)
    assert any(row["id"].endswith("relationships.1") for row in flow._framework_claims(fw, pack, 4))


def test_framework_requests_preserve_complete_chapters_without_duplicate_hash_catalog():
    source, analyses, pack = fixture(4)
    payload = flow.framework_source_payload(source, pack)
    assert [row["text"] for row in payload["source_contexts"]] == [row["text"] for row in source["chapters"]]
    assert len(payload["passage_directory"]["rows"]) == len(pack["selected_core_passages"])
    assert payload["passage_directory"]["columns"] == ["id", "chapter_index", "start_offset", "end_offset"]
    assert "chapter_sha256" not in json.dumps(payload)


def test_source_issue_requires_valid_exact_original_evidence():
    source, analyses, pack = fixture(1)
    artifact = "设计原文"
    schema = flow.review_schema(artifact, source["chapters"])
    raw = generic_pass({"output_schema": schema})
    raw.update(decision="revise", issues=[{"check": "identity_and_relationships", "layer": "character",
                "location": "关系", "reason": "错误", "required_change": "修正", "source_evidence": []}])
    raw["checks"]["identity_and_relationships"] = "fail"
    with pytest.raises(ValueError, match="source_evidence_required"):
        flow.validate_stage_review(raw, artifact, source["chapters"])
    raw["issues"][0]["source_evidence"] = [{"chapter_index": 1, "quote": "不存在的原句"}]
    with pytest.raises(ValueError, match="original_quote_mismatch"):
        flow.validate_stage_review(raw, artifact, source["chapters"])


def test_local_design_and_diagnosis_source_units_are_complete_single_chapters():
    source, analyses, pack = fixture(4)
    fake = Fake(source, analyses, pack, root_stage="screenplay")
    run(fake, source, analyses, pack)
    originals = {row["index"]: row["text"] for row in source["chapters"]}
    for name, _, payload in fake.calls:
        if name.startswith("DESIGN_LOCAL"):
            rows = payload["selected_original_chapters"]
        elif name.startswith("ROOT_CAUSE"):
            rows = payload["source_original_chapters"]
            assert "artifacts" not in payload
            assert "passage_catalog" not in json.dumps(payload, ensure_ascii=False)
        else:
            continue
        assert len(rows) == 1
        assert rows[0]["text"] == originals[rows[0]["index"]]


@pytest.mark.parametrize("kind", ["sha", "path", "quote", "scope"])
def test_root_diagnosis_rejects_forged_artifact_or_source(kind):
    source, analyses, pack = fixture(1)
    artifacts = {"screenplay": DRAFT}
    issues = [{"reason": "test"}]
    raw = {"reviewed_issues_sha256": flow.digest(issues), "decision": "diagnosed", "reason": "known",
           "diagnoses": [{"final_issue_index": 0, "layer": "character", "responsible_stage": "screenplay", "chapter_index": 0,
                "cause": "错误", "required_change": "修正", "source_evidence": [{"chapter_index": 1, "quote": "林青是小明的继母。"}],
                "artifact_evidence": [{"artifact_name": "screenplay", "artifact_sha256": flow.digest(DRAFT),
                                       "field_path": "", "evidence_kind": "present", "quote": "林青递出面包"}]}]}
    anchor = raw["diagnoses"][0]["artifact_evidence"][0]
    if kind == "sha": anchor["artifact_sha256"] = "wrong"
    if kind == "path": anchor["field_path"] = "missing"
    if kind == "quote": anchor["quote"] = "不存在的台词"
    if kind == "scope": raw["diagnoses"][0]["source_evidence"][0]["chapter_index"] = 2
    with pytest.raises(ValueError):
        flow.validate_diagnosis(raw, issues, artifacts, source["chapters"])


def test_root_insufficient_evidence_does_not_guess_stage():
    source, analyses, pack = fixture(1)
    issues = [{"reason": "unknown"}]
    result = flow.validate_diagnosis({"reviewed_issues_sha256": flow.digest(issues), "decision": "insufficient_evidence",
                                     "reason": "跨章来源不足", "diagnoses": []},
                                    issues, {"screenplay": DRAFT}, source["chapters"])
    assert result["responsible_stage"] is None


def test_large_source_enum_is_transport_only_compacted():
    schema = {"items": {"enum": [f"id{i}" for i in range(5000)]}}
    compact = flow._request_schema(schema)
    assert compact["items"]["type"] == "string"
    assert len(schema["items"]["enum"]) == 5000


def test_material_rejection_repairs_only_that_chapter_then_minimax_rechecks():
    source, analyses, pack = fixture()
    class MaterialFailure(Fake):
        def __call__(self, name, role, prompt, payload, json_output=True):
            result = super().__call__(name, role, prompt, payload, json_output)
            if name == "MATERIAL_REVIEW_00_CH001_A0":
                result["checks"]["character"] = "fail"
                result.update(decision="revise", issues=[{"check": "character", "layer": "character", "location": "第一段",
                    "reason": "身份段漏分人物", "required_change": "给该段加人物类",
                    "source_evidence": [{"chapter_index": 1, "quote": "林青是小明的继母。"}]}])
            return result
    fake = MaterialFailure(source, analyses, pack)
    callbacks = []
    def repair(index, issues, attempt):
        callbacks.append((index, attempt, deepcopy(issues)))
        changed = deepcopy(analyses)
        changed[0]["assignments"][0]["categories"] = ["character", "event"]
        raw = {key: changed[0][key] for key in ("chapter_id", "chapter_index", "assignments")}
        changed[0] = material.validate(raw, source["chapters"], changed[0]["chapter_plan"])
        updated = material.cloud_input(material.materials_index(changed, source["chapters"], book_name="测试书"))
        fake.pack = updated
        return {"pack": updated, "chapter_materials": changed}
    result, records = run(fake, source, analyses, pack, repair_materials=repair)
    assert callbacks[0][:2] == (1, 1) and len(callbacks) == 1
    assert len([name for name, _, _ in fake.calls if name.startswith("MATERIAL_REVIEW_00_CH001")]) == 2
    assert analyses[0]["assignments"][0]["categories"] == ["event"]
    assert result["binding"]["source_pack_sha256"] != flow.digest(pack)


def root_fixture():
    source, analyses, pack = fixture()
    fw = framework(pack)
    context = flow._episode_context(source, pack, fw, DESIGN, 10, {})
    artifacts = {"materials": flow._material_artifacts(analyses), "framework": fw,
                 "design": DESIGN, "facts": {"facts": []}, "screenplay": DRAFT}
    return source, analyses, pack, context, artifacts


def test_multichapter_root_evidence_is_joint_and_original_chapter_not_split():
    source, analyses, pack, context, artifacts = root_fixture()
    issue = {"check": "character_relationships", "source_evidence": [
        {"chapter_index": 1, "quote": "林青是小明的继母。"}, {"chapter_index": 2, "quote": "林青是小明的继母。"}]}
    fake = Fake(source, analyses, pack, root_stage="materials")
    result = flow.diagnose_issues(fake, [issue], artifacts, pack, context, [], record=lambda *_: None, attempt=0)
    assert result["responsible_stage"] == "materials"
    assert len(fake.calls) == 1
    payload = fake.calls[0][2]
    assert [row["index"] for row in payload["source_original_chapters"]] == [1, 2]
    assert [row["text"] for row in payload["source_original_chapters"]] == [row["text"] for row in source["chapters"]]


def test_complete_root_evidence_over_capacity_stops_before_model_dispatch():
    source, analyses, pack, context, artifacts = root_fixture()
    calls = []
    with pytest.raises(flow.ProductionRejected, match="complete_evidence_exceeds_capacity"):
        flow.diagnose_issues(lambda *args: calls.append(args),
                             [{"check": "character_relationships", "source_evidence": [{"chapter_index": 1, "quote": "林青是小明的继母。"}]}],
                             artifacts, pack, context, [], record=lambda *_: None, attempt=0,
                             local_route={"context": 1024, "max_tokens": 128})
    assert calls == []


def test_timing_root_without_source_cannot_invent_source_fact():
    source, analyses, pack, context, artifacts = root_fixture()
    calls = []
    def call(name, role, prompt, payload, json_output=True):
        calls.append(payload)
        return {"reviewed_issues_sha256": payload["reviewed_issues_sha256"], "decision": "diagnosed", "reason": "程序证明局部超时",
                "diagnoses": [{"final_issue_index": 0, "layer": "dialogue_timing", "responsible_stage": "screenplay",
                    "chapter_index": 0, "cause": "对白分配过多", "required_change": "改时长或压缩对白", "source_evidence": [],
                    "artifact_evidence": [{"artifact_name": "screenplay", "artifact_sha256": flow.digest(DRAFT), "field_path": "",
                                           "evidence_kind": "present", "quote": "林青递出面包"}]}]}
    result = flow.diagnose_issues(call, [{"check": "dialogue_timing", "source_evidence": [], "reason": "对白超时"}],
                                 artifacts, pack, context, [], record=lambda *_: None, attempt=0)
    assert calls[0]["source_original_chapters"] == []
    assert result["responsible_stage"] == "screenplay"
    malformed = {"reviewed_issues_sha256": flow.digest([{}]), "decision": "diagnosed", "reason": "bad", "diagnoses": [
        {"final_issue_index": 0, "layer": "character", "responsible_stage": "screenplay", "chapter_index": 0,
         "cause": "无来源猜关系", "required_change": "改", "source_evidence": [],
         "artifact_evidence": [{"artifact_name": "screenplay", "artifact_sha256": flow.digest(DRAFT), "field_path": "",
                                "evidence_kind": "present", "quote": "林青递出面包"}]}]}
    with pytest.raises(ValueError, match="source_evidence_required"):
        flow.validate_diagnosis(malformed, [{}], artifacts, [])


def test_root_unknown_never_repeated_for_multichapter_evidence():
    source, analyses, pack, context, artifacts = root_fixture()
    fake = Fake(source, analyses, pack, unknown_stage="ROOT_CAUSE")
    with pytest.raises(RuntimeError, match="outcome_unknown"):
        flow.diagnose_issues(fake, [{"check": "character_relationships", "source_evidence": [
            {"chapter_index": 1, "quote": "林青是小明的继母。"}, {"chapter_index": 2, "quote": "林青是小明的继母。"}]}],
            artifacts, pack, context, [], record=lambda *_: None, attempt=0)
    assert len(fake.calls) == 1


def test_material_root_chapter_must_match_original_artifact_field():
    source, analyses, pack, context, artifacts = root_fixture()
    issue = {"check": "character_relationships", "source_evidence": [
        {"chapter_index": 1, "quote": "林青是小明的继母。"}, {"chapter_index": 2, "quote": "林青是小明的继母。"}]}
    class WrongChapter(Fake):
        def __call__(self, name, role, prompt, payload, json_output=True):
            raw = super().__call__(name, role, prompt, payload, json_output)
            raw["diagnoses"][0]["artifact_evidence"][0]["field_path"] = "CH002.assignments.0.categories"
            return raw
    fake = WrongChapter(source, analyses, pack, root_stage="materials")
    with pytest.raises(ValueError, match="material_root_chapter_evidence_mismatch"):
        flow.diagnose_issues(fake, [issue], artifacts, pack, context, [], record=lambda *_: None, attempt=0)
    assert len(fake.calls) == 2

