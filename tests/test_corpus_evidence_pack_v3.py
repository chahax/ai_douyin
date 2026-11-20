from copy import deepcopy
import json

import pytest

from src.content_factory import corpus_materials_v3 as material
from src.content_factory import corpus_evidence_pack_v3 as evidence


def fixture_index(count=3, all_core=False):
    source = [{"index": index, "title": f"第{index}章", "text": f"第{index}章家庭。\n孩子在屋里。\n父亲在窗边。\n"}
              for index in range(1, count + 1)]
    groups = material.plan_groups(source, max_chars=50, passage_chars=8, context_chars=5)
    results = []
    for group in groups:
        payload = material.group_payload(source, group)
        passages = [row for row in payload["source_passages"] if row["scope"] == "core"]
        priorities, seen, assignments = [], set(), []
        for passage in passages:
            first = passage["chapter_index"] not in seen
            if first:
                priorities.append(passage["id"])
                seen.add(passage["chapter_index"])
            assignments.append({"passage_id": passage["id"], "categories": ["character", "location"],
                                "importance": "core" if first or all_core or passage["id"].endswith("002") else "supporting"})
        results.append(material.validate({"group_id": group["id"], "assignments": assignments,
                                          "selected_core_passage_ids": priorities}, source, group))
    index = material.materials_index(results, source, groups, "测试小说")
    return index, material.cloud_input(index)


def test_expansion_preserves_all_classified_core_and_original_priorities():
    index, base = fixture_index()
    original_index, original_base = deepcopy(index), deepcopy(base)
    package, metadata = evidence.expand_core(index, base)
    core_ids = {row["passage_id"] for row in index["classification_index"] if row["importance"] == "core"}
    assert {row["id"] for row in package["selected_core_passages"]} == core_ids
    assert package["priority_passage_ids"] == index["selected_core_passage_ids"]
    assert package["classification_index"] == base["classification_index"]
    assert package["chapter_coverage"] == base["chapter_coverage"]
    assert package["source_digest"] == base["source_digest"]
    assert package["unselected_passage_ids"] == [row["id"] for row in index["passage_catalog"] if row["id"] not in core_ids]
    assert index == original_index and base == original_base
    assert metadata["semantic_review"] == "not_performed"


def test_no_compression_is_reported_when_every_passage_is_core():
    index, base = fixture_index(all_core=True)
    package, metadata = evidence.expand_core(index, base)
    assert package["selected_core_passages"] == index["passage_catalog"]
    assert package["limits"]["all_original_text_included"]
    assert package["limits"]["compression_performed"] is False
    assert metadata["statistics"]["compression_performed"] is False
    assert metadata["statistics"]["omitted_source_chars"] == 0
    assert package["unselected_passage_ids"] == []
    assert metadata["statistics"]["added_original_chars"] > 0


def test_partial_core_omits_only_supporting_text_and_retains_its_index():
    index, base = fixture_index()
    package, metadata = evidence.expand_core(index, base)
    assert metadata["statistics"]["compression_performed"]
    assert metadata["statistics"]["omitted_source_chars"] > 0
    assert len(package["classification_index"]) == len(index["passage_catalog"])
    support = [row["passage_id"] for row in index["classification_index"] if row["importance"] == "supporting"]
    assert package["unselected_passage_ids"] == support
    assert {row["id"] for row in material.lookup_passages(index, support)} == set(support)


def test_original_characters_and_offsets_are_preserved_once():
    index, base = fixture_index(all_core=True)
    package, _ = evidence.expand_core(index, base)
    assert len(package["selected_core_passages"]) == len(set(package["included_core_passage_ids"]))
    assert package["selected_core_passages"] == material.lookup_passages(index, package["included_core_passage_ids"])
    assert sum(len(row["text"]) for row in package["selected_core_passages"]) == index["source_chars"]


def test_every_chapter_remains_in_expanded_evidence_for_69_chapters():
    index, base = fixture_index(count=69)
    package, metadata = evidence.expand_core(index, base)
    assert {row["chapter_index"] for row in package["selected_core_passages"]} == set(range(1, 70))
    assert all(row["included_core_passage_ids"] and row["original_priority_passage_ids"]
               for row in package["core_input_chapter_coverage"])
    assert metadata["statistics"]["source_chapters"] == 69


def test_deterministic_rebuild_and_json_round_trip_match():
    index, base = fixture_index()
    package, metadata = evidence.expand_core(index, base)
    assert (package, metadata) == evidence.expand_core(index, base)
    restored_package = json.loads(json.dumps(package, ensure_ascii=False))
    restored_metadata = json.loads(json.dumps(metadata, ensure_ascii=False))
    assert evidence.verify_expansion(index, base, restored_package, restored_metadata)
    assert metadata["materials_index_sha256"] == material.digest(index)
    assert metadata["base_pack_sha256"] == material.digest(base)
    assert metadata["expanded_pack_sha256"] == material.digest(package)


@pytest.mark.parametrize("field", ["text", "sha256", "start_offset", "chapter_sha256"])
def test_source_evidence_tampering_is_rejected(field):
    index, base = fixture_index()
    row = index["passage_catalog"][-1]
    row[field] = row[field] + (1 if isinstance(row[field], int) else "被改")
    with pytest.raises(ValueError, match="materials_catalog_text_mismatch"):
        evidence.expand_core(index, base)


def test_modified_or_incomplete_base_pack_is_rejected():
    index, base = fixture_index()
    base["selected_core_passages"].pop()
    with pytest.raises(ValueError, match="evidence_base_pack_binding_mismatch"):
        evidence.expand_core(index, base)


def test_duplicate_catalog_or_priority_is_rejected():
    index, base = fixture_index()
    index["passage_catalog"].append(deepcopy(index["passage_catalog"][0]))
    with pytest.raises(ValueError, match="duplicate_catalog_passage"):
        evidence.expand_core(index, base)
    index, base = fixture_index()
    index["selected_core_passage_ids"].append(index["selected_core_passage_ids"][0])
    with pytest.raises(ValueError, match="materials_index_selection_mismatch"):
        evidence.expand_core(index, base)


def test_supporting_priority_is_rejected():
    index, base = fixture_index()
    index["classification_index"][0]["importance"] = "supporting"
    with pytest.raises(ValueError, match="materials_index_classification_mismatch"):
        evidence.expand_core(index, base)


def test_modified_expansion_or_metadata_cannot_be_verified():
    index, base = fixture_index()
    package, metadata = evidence.expand_core(index, base)
    package["selected_core_passages"][0]["text"] += "新编剧情"
    with pytest.raises(ValueError, match="evidence_expanded_pack_binding_mismatch"):
        evidence.verify_expansion(index, base, package, metadata)
    package, metadata = evidence.expand_core(index, base)
    metadata["statistics"]["source_chars"] += 1
    with pytest.raises(ValueError, match="evidence_expansion_metadata_mismatch"):
        evidence.verify_expansion(index, base, package, metadata)


def test_expansion_does_not_depend_on_story_name_or_special_passage_terms():
    index, _ = fixture_index()
    index["book_name"] = "完全不同的故事"
    base = material.cloud_input(index)
    package, metadata = evidence.expand_core(index, base)
    assert package["book_name"] == "完全不同的故事"
    assert metadata["recipe"] == evidence.RECIPE
    assert set(package["priority_passage_ids"]) <= set(package["included_core_passage_ids"])


def classification_fixture(count=2, max_chars=10000):
    source = [{"index": index, "title": f"第{index}章", "text": "一段原文。\n另一段话。\n第三段话。\n"}
              for index in range(1, count + 1)]
    groups = material.plan_groups(source, max_chars=max_chars, passage_chars=6, context_chars=5)
    records = []
    for group in groups:
        payload = material.group_payload(source, group)
        passages = [row for row in payload["source_passages"] if row["scope"] == "core"]
        selected, seen = [], set()
        for passage in passages:
            if passage["chapter_index"] not in seen:
                selected.append(passage["id"])
                seen.add(passage["chapter_index"])
        raw = {"group_id": group["id"],
               "assignments": [{"passage_id": row["id"], "categories": ["character", "event"],
                                "importance": "core"} for row in passages],
               "selected_core_passage_ids": selected}
        records.append({"group_id": group["id"], "completion_state": "known_complete",
                        "raw": raw, "raw_sha256": material.digest(raw)})
    return source, groups, records


def incomplete_priority_fixture():
    source, groups, records = classification_fixture()
    raw = records[0]["raw"]
    raw["selected_core_passage_ids"] = ["CH1-P001", "CH1-P002"]
    records[0]["raw_sha256"] = material.digest(raw)
    return source, groups, records


def test_known_complete_priority_failure_derives_all_core_without_changing_native():
    source, groups, records = incomplete_priority_fixture()
    raw, original = records[0]["raw"], deepcopy(records[0]["raw"])
    original_group = deepcopy(groups[0])
    with pytest.raises(ValueError, match="selected_core_chapter_coverage_incomplete"):
        material.validate(raw, source, groups[0])
    validated, derived_group, audit = evidence.validate_core_classification(raw, source, groups[0])
    assert raw == original and groups[0] == original_group
    assert audit["version"] == evidence.CLASSIFICATION_POLICY_VERSION
    assert audit["output_source"] == "deterministic_all_core"
    assert audit["original_contract_failure"] == "selected_core_chapter_coverage_incomplete"
    assert audit["original_contract_result"] == "failed"
    assert audit["original_priority_passage_ids"] == ["CH1-P001", "CH1-P002"]
    assert audit["warnings"][0]["missing_chapter_indices"] == [2]
    assert validated["assignments"] == raw["assignments"]
    assert len(validated["selected_core_passage_ids"]) == len(raw["assignments"])
    assert derived_group["max_selected"] >= len(raw["assignments"])
    index = material.materials_index([validated], source, [derived_group])
    assert index["validation"]["all_acquired_chapters_in_core_input"]
    with pytest.raises(ValueError, match="selected_core_chapter_coverage_incomplete"):
        material.validate(raw, source, groups[0])


def test_valid_priority_uses_same_deterministic_core_derivation():
    source, groups, records = classification_fixture()
    validated, _, audit = evidence.validate_core_classification(records[0]["raw"], source, groups[0])
    assert audit["original_contract_result"] == "passed"
    assert audit["warnings"] == []
    assert len(validated["selected_core_passage_ids"]) > len(audit["original_priority_passage_ids"])
    assert audit["native_importance_unchanged"]


@pytest.mark.parametrize("mutation,match", [
    (lambda raw: raw["assignments"].pop(), "materials_schema_invalid"),
    (lambda raw: raw["assignments"].append(deepcopy(raw["assignments"][0])), "duplicate_passage_assignment"),
    (lambda raw: raw["assignments"][0].update(passage_id="CH999-P001"), "unknown_passage_id"),
    (lambda raw: raw["assignments"][0].update(categories=["unknown"]), "materials_schema_invalid"),
    (lambda raw: raw["assignments"][0].update(importance="supporting"), "selected_passage_not_core"),
    (lambda raw: raw.update(summary="自由改写"), "materials_schema_invalid"),
    (lambda raw: raw["selected_core_passage_ids"].append(raw["selected_core_passage_ids"][0]), "materials_schema_invalid"),
])
def test_derivation_does_not_relax_other_native_validation(mutation, match):
    source, groups, records = incomplete_priority_fixture()
    raw = records[0]["raw"]
    mutation(raw)
    with pytest.raises(ValueError, match=match):
        evidence.validate_core_classification(raw, source, groups[0])


def test_derivation_requires_actual_core_evidence_in_every_chapter():
    source, groups, records = incomplete_priority_fixture()
    raw = records[0]["raw"]
    for row in raw["assignments"]:
        if row["passage_id"].startswith("CH2-"):
            row["importance"] = "supporting"
    with pytest.raises(ValueError, match="classification_core_chapter_coverage_incomplete"):
        evidence.validate_core_classification(raw, source, groups[0])


def test_derivation_does_not_promote_supporting_passages():
    source, groups, records = incomplete_priority_fixture()
    raw = records[0]["raw"]
    raw["assignments"][-1]["importance"] = "supporting"
    validated, _, audit = evidence.validate_core_classification(raw, source, groups[0])
    assert raw["assignments"][-1]["passage_id"] not in audit["effective_core_passage_ids"]
    assert validated["assignments"][-1]["importance"] == "supporting"


def test_derivation_checks_original_source_hash_and_context_scope():
    source, groups, records = classification_fixture(count=3, max_chars=25)
    raw = records[0]["raw"]
    payload = material.group_payload(source, groups[0])
    raw["assignments"][0]["passage_id"] = next(row["id"] for row in payload["source_passages"]
                                                if row["scope"] == "context")
    with pytest.raises(ValueError, match="context_passage_cannot_be_assigned"):
        evidence.validate_core_classification(raw, source, groups[0])
    source[0]["sha256"] = "modified"
    with pytest.raises(ValueError, match="source_chapter_sha256_mismatch"):
        evidence.validate_core_classification(raw, source, groups[0])


def test_completed_builder_rejects_unknown_and_mismatched_native():
    source, groups, records = classification_fixture()
    records[0]["completion_state"] = "outcome_unknown"
    with pytest.raises(ValueError, match="classification_response_not_known_complete"):
        evidence.build_core_index_from_completed_groups(records, source, groups)
    records[0]["completion_state"] = "known_complete"
    records[0]["raw_sha256"] = "wrong"
    with pytest.raises(ValueError, match="completed_classification_raw_binding_mismatch"):
        evidence.build_core_index_from_completed_groups(records, source, groups)


def test_completed_builder_requires_exact_original_group_set():
    source, groups, records = classification_fixture(count=3, max_chars=25)
    with pytest.raises(ValueError, match="completed_classification_group_set_mismatch"):
        evidence.build_core_index_from_completed_groups(records[:-1], source, groups)
    with pytest.raises(ValueError, match="completed_classification_group_set_mismatch"):
        evidence.build_core_index_from_completed_groups(records + [records[0]], source, groups)


def test_completed_builder_69_chapter_coverage_and_bound_reconstruction():
    source, groups, records = classification_fixture(count=69, max_chars=70)
    result = evidence.build_core_index_from_completed_groups(records, source, groups, "不同故事")
    index = result["index"]
    assert index["source_chapter_count"] == 69
    assert index["validation"]["all_acquired_chapters_in_core_input"]
    package = material.cloud_input(index)
    assert {row["chapter_index"] for row in package["selected_core_passages"]} == set(range(1, 70))
    assert result["audit"]["materials_index_sha256"] == material.digest(index)
    assert result == evidence.build_core_index_from_completed_groups(list(reversed(records)), source, groups, "不同故事")


def test_completed_builder_separates_original_failure_and_new_derivation():
    source, groups, records = incomplete_priority_fixture()
    result = evidence.build_core_index_from_completed_groups(records, source, groups)
    assert result["audit"]["groups_with_original_priority_warning"] == ["G001"]
    assert result["group_audits"][0]["original_raw_sha256"] == records[0]["raw_sha256"]
    assert result["group_audits"][0]["original_task_and_failure_unchanged"]
    assert result["group_audits"][0]["original_priority_passage_ids"] == records[0]["raw"]["selected_core_passage_ids"]


def adoption_priority_fixture():
    source, groups, records = incomplete_priority_fixture()
    result = evidence.build_core_index_from_completed_groups(records, source, groups)
    index = result["index"]
    priority = result["group_audits"][0]["original_priority_passage_ids"]
    provenance = {"adoption_sha256": material.digest(result["audit"]),
                  "policy_version": evidence.CLASSIFICATION_POLICY_VERSION,
                  "source_sha256": material.digest(source)}
    return index, material.cloud_input(index), priority, provenance


def test_priority_override_retains_true_original_order_and_partial_chapter_coverage():
    index, base, priority, provenance = adoption_priority_fixture()
    native_index, native_base, native_provenance = deepcopy(index), deepcopy(base), deepcopy(provenance)
    priority.reverse()
    package, metadata = evidence.expand_core(index, base, original_priority_ids=priority,
                                             priority_provenance=provenance)
    assert package["priority_passage_ids"] == priority
    assert metadata["original_priority_passage_ids"] == priority
    assert package["core_input_chapter_coverage"][0]["original_priority_passage_ids"] == priority
    assert package["core_input_chapter_coverage"][1]["original_priority_passage_ids"] == []
    assert package["core_input_chapter_coverage"][1]["included_core_passage_ids"]
    assert package["classification_index"] == base["classification_index"]
    assert package["chapter_coverage"] == base["chapter_coverage"]
    assert package["limits"]["classification_selected_for_core_means_original_priority"] is False
    assert package["limits"]["chapter_coverage_selection_means_original_priority"] is False
    assert package["limits"]["classification_selected_for_core_means_effective_index_selection"]
    assert metadata["statistics"]["priority_passages"] == len(priority)
    actual_priority_chars = sum(len(row["text"]) for row in material.lookup_passages(index, priority))
    assert metadata["statistics"]["priority_chars"] == actual_priority_chars
    assert package["limits"]["original_priority_chars"] == actual_priority_chars
    assert metadata["statistics"]["added_original_chars"] == index["source_chars"] - actual_priority_chars
    assert metadata["priority_source"] == "frozen_core_adoption"
    assert metadata["original_priority_provenance"] == provenance
    assert metadata["original_priority_provenance_sha256"] == material.digest(provenance)
    assert index == native_index and base == native_base and provenance == native_provenance
    assert evidence.verify_expansion(index, base, package, metadata,
                                     original_priority_ids=priority, priority_provenance=provenance)


def test_priority_override_binding_cannot_be_verified_as_default_or_other_adoption():
    index, base, priority, provenance = adoption_priority_fixture()
    package, metadata = evidence.expand_core(index, base, original_priority_ids=priority,
                                             priority_provenance=provenance)
    with pytest.raises(ValueError, match="evidence_expanded_pack_binding_mismatch"):
        evidence.verify_expansion(index, base, package, metadata)
    other = deepcopy(provenance)
    other["adoption_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="evidence_expanded_pack_binding_mismatch"):
        evidence.verify_expansion(index, base, package, metadata,
                                  original_priority_ids=priority, priority_provenance=other)


@pytest.mark.parametrize("priority", [["CH999-P001"], ["CH1-P001", "CH1-P001"], "CH1-P001", [None]])
def test_priority_override_rejects_unknown_duplicate_and_malformed_ids(priority):
    index, base, _, provenance = adoption_priority_fixture()
    with pytest.raises(ValueError, match="evidence_(original_priority_invalid|priority_not_core)"):
        evidence.expand_core(index, base, original_priority_ids=priority, priority_provenance=provenance)


def test_priority_override_cannot_include_supporting_passage():
    index, base = fixture_index()
    supporting = next(row["passage_id"] for row in index["classification_index"]
                      if row["importance"] == "supporting")
    _, _, _, provenance = adoption_priority_fixture()
    with pytest.raises(ValueError, match="evidence_priority_not_core"):
        evidence.expand_core(index, base, original_priority_ids=[supporting], priority_provenance=provenance)


@pytest.mark.parametrize("provenance", [None, {},
    {"adoption_sha256": "bad", "source_sha256": "a" * 64, "policy_version": "policy"},
    {"adoption_sha256": "a" * 64, "source_sha256": "bad", "policy_version": "policy"},
    {"adoption_sha256": "a" * 64, "source_sha256": "b" * 64, "policy_version": ""}])
def test_priority_override_requires_frozen_adoption_and_source_provenance(provenance):
    index, base, priority, _ = adoption_priority_fixture()
    with pytest.raises(ValueError, match="evidence_priority_provenance_invalid"):
        evidence.expand_core(index, base, original_priority_ids=priority, priority_provenance=provenance)


def test_priority_provenance_without_override_is_rejected():
    index, base, _, provenance = adoption_priority_fixture()
    with pytest.raises(ValueError, match="evidence_priority_provenance_without_override"):
        evidence.expand_core(index, base, priority_provenance=provenance)


def test_empty_priority_hints_do_not_remove_required_all_core_chapter_evidence():
    index, base, _, provenance = adoption_priority_fixture()
    package, metadata = evidence.expand_core(index, base, original_priority_ids=[], priority_provenance=provenance)
    assert package["priority_passage_ids"] == []
    assert metadata["statistics"]["priority_chars"] == 0
    assert metadata["statistics"]["priority_passages"] == 0
    assert all(row["included_core_passage_ids"] for row in package["core_input_chapter_coverage"])
    assert package["limits"]["all_original_text_included"]


def test_default_expansion_does_not_add_override_fields():
    index, base = fixture_index()
    package, metadata = evidence.expand_core(index, base)
    assert package["priority_passage_ids"] == index["selected_core_passage_ids"]
    assert "priority_source" not in metadata
    assert "original_priority_provenance" not in metadata
    assert package["limits"]["chapter_coverage_selection_means_original_priority"]
