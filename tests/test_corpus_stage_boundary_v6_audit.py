"""Independent stage-boundary checks; synthetic, offline, no model calls."""
from copy import deepcopy
import hashlib

import pytest

from src.content_factory import corpus_chapter_materials_v6 as materials
from src.content_factory import corpus_episode_state_v6 as episode
from src.content_factory import corpus_production_contract_v6 as flow
from tests.test_corpus_episode_state_v6 import episode_fixture, _catalog, _raws
from tests.test_corpus_production_contract_v6 import Fake, fixture, run


def same_paragraph_fixture():
    """Author paragraph contains both initial possession and its later transfer."""
    source, library, raw = episode_fixture()
    raws = _raws(library)
    lines = source[0]["text"].splitlines(keepends=True)
    source[0]["text"] = "".join(line.rstrip("\n") for line in lines[:3]) + "\n" + "".join(lines[3:])
    source[0]["sha256"] = hashlib.sha256(source[0]["text"].encode()).hexdigest()
    for fact in raws[0]["facts"]:
        original = int(fact["narrative_anchor_passage_id"].split("-P")[1])
        paragraph = "CH1-P%03d" % (1 if original <= 3 else original - 2)
        fact["narrative_anchor_passage_id"] = paragraph
        for ref in fact["source_refs"]:
            ref["paragraph_id"] = paragraph
    raws[0]["coverage"] = [
        {"paragraph_id": "CH1-P001", "fact_ids": ["CH1-F001", "CH1-F002", "CH1-F003"], "no_fact_reason": ""},
        {"paragraph_id": "CH1-P002", "fact_ids": ["CH1-F004"], "no_fact_reason": ""},
        {"paragraph_id": "CH1-P003", "fact_ids": ["CH1-F005"], "no_fact_reason": ""},
    ]
    library = _catalog(source, raws)
    by_id = {fact["id"]: fact for fact in library["facts"]}
    for entity in raw["entities"]:
        for ref in entity["identity_source_refs"]:
            ref["paragraph_id"] = by_id[ref["fact_id"]]["source_evidence"][0]["paragraph_id"]
    for state in raw["states"]:
        for ref in state["source_fact_refs"]:
            ref["paragraph_id"] = by_id[ref["fact_id"]]["source_evidence"][0]["paragraph_id"]
    return source, library, raw


def test_same_paragraph_later_transfer_cannot_become_earlier_opening_state():
    source, library, raw = same_paragraph_fixture()
    raw["snapshots"][0]["state_ids"] = ["key_adult" if item == "key_child" else item
                                       for item in raw["snapshots"][0]["state_ids"]]
    raw["states"] = [state for state in raw["states"] if state["id"] != "key_child"]
    raw["beats"][0]["actions"] = []
    with pytest.raises(ValueError, match="fact_occurs_after_snapshot"):
        episode.validate_episode(raw, library, source, [1], 10)


def test_same_paragraph_correct_transfer_retains_author_paragraph_and_chain():
    source, library, raw = same_paragraph_fixture()
    accepted = episode.validate_episode(raw, library, source, [1], 10)
    assert len(library["analyses"][0]["passage_catalog"]) == 3
    assert accepted["validation"]["explicit_state_chain_checked"] is True
    assert all("state_changes" not in fact for fact in library["facts"])


def test_snapshot_review_sees_unreferenced_material_needed_to_detect_omission():
    source, analyses, pack, snapshot = fixture()
    fake = Fake(source, analyses, pack, snapshot)
    run(fake, source, analyses, pack)
    payload = next(p for name, _, p in fake.calls if name == "SNAPSHOT_LOCAL_00_CH001")
    candidate_ids = {f["id"] for a in payload["episode_material_candidates"] for f in a["facts"]}
    used_ids = set(payload["episode_snapshot"]["binding"]["used_fact_ids"])
    assert "CH1-F005" in candidate_ids - used_ids
    assert "state_completeness" in payload["output_schema"]["properties"]["checks"]["properties"]
    assert [c["index"] for c in payload["selected_original_chapters"]] == [1]


def test_state_completeness_failure_blocks_design_and_does_not_reclassify_materials():
    source, analyses, pack, snapshot = fixture()

    class Incomplete(Fake):
        def __call__(self, name, role, prompt, payload, json_output=True):
            result = super().__call__(name, role, prompt, payload, json_output)
            if name.startswith("SNAPSHOT_LOCAL"):
                result["decision"] = "revise"
                result["checks"]["state_completeness"] = "fail"
                result["issues"] = [{"check": "state_completeness", "layer": "character",
                    "location": "snapshot.states", "reason": "演出告知却缺少孩子获知状态。",
                    "required_change": "在本集补来源绑定的知情状态与learn动作。",
                    "source_evidence": [{"chapter_index": 1, "quote": "林青告诉小明自己是他的继母。"}]}]
            return result

    fake = Incomplete(source, analyses, pack, snapshot)
    with pytest.raises(flow.ProductionRejected) as caught:
        flow.run_production(fake, source, pack, {"target_seconds": 10, "root_repair_limit": 0},
                            stats=lambda _: {}, record=lambda *_: None,
                            remaining_calls=lambda: 1000, chapter_materials=analyses)
    assert caught.value.stage == "snapshot"
    assert sum(name.startswith("MATERIAL_REVIEW") for name, _, _ in fake.calls) == len(analyses)
    assert not any(name.startswith(("VISUAL_DESIGN", "SCREENPLAY", "FINAL_")) for name, _, _ in fake.calls)


def test_state_completeness_cannot_be_routed_back_to_initial_material_array_omission():
    source, analyses, _, snapshot = fixture()
    issue = {"check": "state_completeness", "layer": "character", "reason": "缺知情状态"}
    artifacts = {"materials": flow._material_artifacts(analyses), "snapshot": {"snapshot": snapshot}}
    diagnosis = {"reviewed_issues_sha256": flow.digest([issue]), "decision": "diagnosed", "reason": "fixture",
        "diagnoses": [{"final_issue_index": 0, "layer": "character", "responsible_stage": "materials",
            "chapter_index": 1, "cause": "错把无状态数组归材料", "required_change": "错误上游修改",
            "source_evidence": [{"chapter_index": 1, "quote": "林青告诉小明自己是他的继母。"}],
            "artifact_evidence": [{"artifact_name": "materials", "artifact_sha256": flow.digest(artifacts["materials"]),
                "field_path": "CH001.facts", "evidence_kind": "omission", "quote": ""}]}]}
    with pytest.raises(ValueError, match="state_detail_omission_belongs_to_snapshot"):
        flow.validate_diagnosis(diagnosis, [issue], artifacts, source["chapters"])
    diagnosis["diagnoses"][0].update(responsible_stage="snapshot", chapter_index=0)
    diagnosis["diagnoses"][0]["artifact_evidence"] = [{"artifact_name": "snapshot",
        "artifact_sha256": flow.digest(artifacts["snapshot"]), "field_path": "snapshot.states",
        "evidence_kind": "omission", "quote": ""}]
    assert flow.validate_diagnosis(diagnosis, [issue], artifacts, source["chapters"])["responsible_stage"] == "snapshot"


def test_new_material_schema_cannot_silently_accept_legacy_detailed_output():
    source, library, _ = episode_fixture()
    accepted = library["analyses"][0]
    native = materials.raw_candidate(accepted)
    native["entities"] = []
    with pytest.raises(ValueError, match="schema_invalid"):
        materials.validate(native, source, accepted["chapter_plan"])
