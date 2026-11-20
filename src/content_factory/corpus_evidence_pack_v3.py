"""Deterministic expansion of classified core evidence for global understanding.

This adapter preserves the frozen local classification and its original priority
selection.  It adds original evidence; it never invents or rewrites novel facts.
"""
from copy import deepcopy
import re

from . import corpus_materials_v3 as materials


VERSION = "corpus_evidence_pack/v3.0-experimental"
RECIPE = "all_classified_core_original_passages_with_original_priority"
CLASSIFICATION_POLICY_VERSION = "corpus_core_classification/v3.1-experimental"


def validate_core_classification(raw, chapters, original_group):
    """Derive all-core selection from a *known complete* native classification.

    The caller owns the evidence that the response completed and is not unknown.
    This pure function neither changes nor settles the original task.  Only the
    old per-chapter priority-coverage failure is downgraded; all original schema,
    assignment, source and importance requirements continue to apply.

    Return ``(validated, derived_group, audit)``.  ``validated`` is compatible with
    ``materials.materials_index`` under its separate ``derived_group``.
    """
    original_failure = None
    try:
        materials.validate(raw, chapters, original_group)
    except ValueError as error:
        if str(error) != "selected_core_chapter_coverage_incomplete":
            raise
        original_failure = str(error)
    payload = materials.group_payload(chapters, original_group)
    passages = [row for row in payload["source_passages"] if row["scope"] == "core"]
    assignments = {row["passage_id"]: row for row in raw["assignments"]}
    core_ids = [row["id"] for row in passages
                if assignments[row["id"]]["importance"] == "core"]
    by_id = {row["id"]: row for row in passages}
    all_chapters = set(original_group["chapter_indices"])
    actual_core_chapters = {by_id[pid]["chapter_index"] for pid in core_ids}
    if actual_core_chapters != all_chapters:
        raise ValueError("classification_core_chapter_coverage_incomplete")
    priority = deepcopy(raw["selected_core_passage_ids"])
    priority_chapters = {by_id[pid]["chapter_index"] for pid in priority}
    missing_priority = sorted(all_chapters - priority_chapters)
    derived_group = deepcopy(original_group)
    derived_group["max_selected"] = max(original_group.get("max_selected", 8), len(core_ids))
    derived_raw = deepcopy(raw)
    derived_raw["selected_core_passage_ids"] = core_ids
    validated = materials.validate(derived_raw, chapters, derived_group)
    audit = {
        "version": CLASSIFICATION_POLICY_VERSION,
        "output_source": "deterministic_all_core",
        "original_group_sha256": materials.digest(original_group),
        "original_raw_sha256": materials.digest(raw),
        "original_priority_passage_ids": priority,
        "original_contract_result": "failed" if original_failure else "passed",
        "original_contract_failure": original_failure,
        "original_task_and_failure_unchanged": True,
        "native_classifications_unchanged": True,
        "native_importance_unchanged": True,
        "source_digest": validated["source_digest"],
        "effective_core_passage_ids": core_ids,
        "effective_core_chapters": sorted(actual_core_chapters),
        "derived_group_sha256": materials.digest(derived_group),
        "derived_raw_sha256": materials.digest(derived_raw),
        "validated_sha256": materials.digest(validated),
        "warnings": ([{"code": "priority_chapter_coverage_incomplete",
                       "missing_chapter_indices": missing_priority}]
                     if missing_priority else []),
        "semantic_review": "not_performed",
    }
    return validated, derived_group, audit


def build_core_index_from_completed_groups(completed_groups, chapters, original_groups, book_name=""):
    """Build a separate all-core index from bound, known-complete responses.

    Each record is ``{group_id, completion_state: 'known_complete', raw,
    raw_sha256}``.  The parent must establish completion from original native
    receipts; declaring a state here is not a substitute for that evidence.
    No file is changed and no model request is made.
    """
    if not isinstance(completed_groups, list) or not completed_groups:
        raise ValueError("completed_classifications_empty")
    if not isinstance(original_groups, list) or not original_groups:
        raise ValueError("completed_classification_groups_empty")
    originals = {group["id"]: group for group in original_groups}
    if len(originals) != len(original_groups):
        raise ValueError("completed_classification_duplicate_group")
    seen, accepted, derived_groups, audits = set(), [], [], []
    for record in completed_groups:
        if not isinstance(record, dict) or record.get("completion_state") != "known_complete":
            raise ValueError("classification_response_not_known_complete")
        gid = record.get("group_id")
        if gid not in originals or gid in seen:
            raise ValueError("completed_classification_group_set_mismatch")
        raw = record.get("raw")
        if (not isinstance(raw, dict) or raw.get("group_id") != gid
                or record.get("raw_sha256") != materials.digest(raw)):
            raise ValueError("completed_classification_raw_binding_mismatch")
        validated, group, audit = validate_core_classification(raw, chapters, originals[gid])
        seen.add(gid)
        accepted.append(validated)
        derived_groups.append(group)
        audits.append({"group_id": gid, **audit})
    if seen != set(originals):
        raise ValueError("completed_classification_group_set_mismatch")
    derived_groups.sort(key=lambda group: group["chapter_indices"][0])
    index = materials.materials_index(accepted, chapters, derived_groups, book_name)
    ordered_audits = sorted(audits, key=lambda audit: originals[audit["group_id"]]["chapter_indices"][0])
    return {"index": index, "derived_groups": derived_groups, "group_audits": ordered_audits,
            "audit": {"version": CLASSIFICATION_POLICY_VERSION,
                      "output_source": "deterministic_all_core",
                      "source_digest": index["source_digest"],
                      "original_groups_sha256": materials.digest(original_groups),
                      "derived_groups_sha256": materials.digest(derived_groups),
                      "materials_index_sha256": materials.digest(index),
                      "group_audits_sha256": materials.digest(ordered_audits),
                      "groups_with_original_priority_warning": [audit["group_id"] for audit in ordered_audits
                                                                if audit["warnings"]],
                      "original_task_and_failure_unchanged": True,
                      "semantic_review": "not_performed"}}


def expand_core(index, base_pack, *, original_priority_ids=None, priority_provenance=None):
    """Return ``(expanded_pack, expansion_metadata)`` without mutating inputs.

    ``base_pack`` must equal the validated original ``materials.cloud_input``.
    Existing classification/coverage fields describe the index selection;
    ``core_input_chapter_coverage`` describes the expanded evidence actually sent.
    If the index already contains deterministic all-core selection, its separately
    frozen original model priorities can be supplied with adoption provenance.
    """
    canonical_base = materials.cloud_input(index)
    if base_pack != canonical_base:
        raise ValueError("evidence_base_pack_binding_mismatch")
    classifications = {row["passage_id"]: row for row in index["classification_index"]}
    override_priority = original_priority_ids is not None
    if not override_priority and priority_provenance is not None:
        raise ValueError("evidence_priority_provenance_without_override")
    if override_priority:
        if (not isinstance(original_priority_ids, list)
                or any(not isinstance(pid, str) for pid in original_priority_ids)
                or len(original_priority_ids) != len(set(original_priority_ids))):
            raise ValueError("evidence_original_priority_invalid")
        if (not isinstance(priority_provenance, dict)
                or not isinstance(priority_provenance.get("policy_version"), str)
                or not priority_provenance["policy_version"].strip()
                or any(not isinstance(priority_provenance.get(field), str)
                       or not re.fullmatch(r"[0-9a-f]{64}", priority_provenance[field])
                       for field in ("adoption_sha256", "source_sha256"))):
            raise ValueError("evidence_priority_provenance_invalid")
        try:
            materials.digest(priority_provenance)
        except (TypeError, ValueError) as error:
            raise ValueError("evidence_priority_provenance_invalid") from error
        priority = deepcopy(original_priority_ids)
    else:
        priority = deepcopy(index["selected_core_passage_ids"])
    core_ids = [row["id"] for row in index["passage_catalog"]
                if classifications[row["id"]]["importance"] == "core"]
    core_set = set(core_ids)
    if not core_ids or len(core_set) != len(core_ids):
        raise ValueError("evidence_core_catalog_invalid")
    if not set(priority) <= core_set:
        raise ValueError("evidence_priority_not_core")
    core_passages = materials.lookup_passages(index, core_ids)
    source_chapters = {row["chapter_index"] for row in index["chapter_coverage"]}
    if {row["chapter_index"] for row in core_passages} != source_chapters:
        raise ValueError("evidence_core_chapter_coverage_incomplete")
    core_chars = sum(len(row["text"]) for row in core_passages)
    original_chars = index["source_chars"]
    core_catalog = {row["id"]: row for row in core_passages}
    priority_chars = sum(len(core_catalog[pid]["text"]) for pid in priority)
    all_source_included = len(core_passages) == len(index["passage_catalog"])
    recipe_binding = {"version": VERSION, "recipe": RECIPE,
                      "materials_version": index["version"],
                      "materials_index_sha256": materials.digest(index),
                      "base_pack_sha256": materials.digest(base_pack),
                      "source_digest": index["source_digest"],
                      "classification_and_priority_unchanged": True,
                      "selection_does_not_imply_semantic_approval": True}
    if override_priority:
        recipe_binding.update({"priority_source": "frozen_core_adoption",
                               "original_priority_provenance": deepcopy(priority_provenance),
                               "original_priority_provenance_sha256": materials.digest(priority_provenance)})
    package = deepcopy(base_pack)
    package["priority_passage_ids"] = priority
    package["selected_core_passages"] = core_passages
    package["included_core_passage_ids"] = core_ids
    package["unselected_passage_ids"] = [row["id"] for row in index["passage_catalog"]
                                          if row["id"] not in core_set]
    package["evidence_expansion"] = recipe_binding
    package["core_input_chapter_coverage"] = [
        {"chapter_index": chapter["chapter_index"],
         "original_priority_passage_ids": ([pid for pid in priority
                                             if core_catalog[pid]["chapter_index"] == chapter["chapter_index"]]
                                            if override_priority else deepcopy(chapter["selected_core_passage_ids"])),
         "included_core_passage_ids": [row["id"] for row in core_passages
                                       if row["chapter_index"] == chapter["chapter_index"]]}
        for chapter in index["chapter_coverage"]]
    package["limits"].update({
        "selected_core_chars": core_chars,
        "original_priority_chars": priority_chars,
        "original_priority_passage_count": len(priority),
        "included_core_passage_count": len(core_passages),
        "all_original_text_included": all_source_included,
        "source_characters_omitted": original_chars - core_chars,
        "compression_performed": core_chars < original_chars,
        "classification_selected_for_core_means_original_priority": True,
        "chapter_coverage_selection_means_original_priority": True,
    })
    if override_priority:
        package["limits"].update({
            "classification_selected_for_core_means_original_priority": False,
            "chapter_coverage_selection_means_original_priority": False,
            "classification_selected_for_core_means_effective_index_selection": True,
            "chapter_coverage_selection_means_effective_index_selection": True,
            "original_priority_coverage_required": False,
        })
    metadata = {**deepcopy(recipe_binding),
                "expanded_pack_sha256": materials.digest(package),
                "original_priority_passage_ids": priority,
                "included_core_passage_ids": core_ids,
                "statistics": {"source_chapters": len(source_chapters),
                               "source_passages": len(index["passage_catalog"]),
                               "source_chars": original_chars,
                               "priority_passages": len(priority),
                               "priority_chars": priority_chars,
                               "included_core_passages": len(core_passages),
                               "included_core_chars": core_chars,
                               "added_passages": len(core_passages) - len(priority),
                               "added_original_chars": core_chars - priority_chars,
                               "omitted_source_chars": original_chars - core_chars,
                               "compression_performed": core_chars < original_chars,
                               "all_original_text_included": all_source_included},
                "semantic_review": "not_performed"}
    return package, metadata


def verify_expansion(index, base_pack, expanded_pack, metadata, *,
                     original_priority_ids=None, priority_provenance=None):
    """Reconstruct the exact deterministic product before using frozen evidence."""
    expected_pack, expected_metadata = expand_core(index, base_pack,
                                                  original_priority_ids=original_priority_ids,
                                                  priority_provenance=priority_provenance)
    if expanded_pack != expected_pack:
        raise ValueError("evidence_expanded_pack_binding_mismatch")
    if metadata != expected_metadata:
        raise ValueError("evidence_expansion_metadata_mismatch")
    return True
