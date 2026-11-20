from copy import deepcopy
import hashlib
import json

import pytest
from jsonschema import Draft202012Validator

from src.content_factory import corpus_chapter_facts_v5 as facts


def chapters():
    texts = [
        "苏墨是叶南的继父。\n叶南站在门口，钥匙原来在他手中，随后递给苏墨。\n"
        "叶南想起去年自己把钥匙交给老师。\n苏墨打算明天带叶南去学校。\n"
        "叶南以为苏墨已经知道此事。\n……\n",
        "苏墨坐在家中。\n叶南敲门进屋，说自己昨天捡到钥匙。\n",
        "第二天苏墨仍在家中。\n门口放着一只空书包。\n",
    ]
    return [{"index": index, "title": f"第{index}章", "text": text,
             "sha256": hashlib.sha256(text.encode()).hexdigest()}
            for index, text in enumerate(texts, 1)]


def raw_fixture(payload):
    """Explicit no-fact test fixture, never evidence of real material quality."""
    return {"chapter_id": payload["chapter_id"], "chapter_index": payload["chapter_index"],
            "entities": [], "facts": [],
            "coverage": [{"paragraph_id": part["id"], "fact_ids": [],
                          "no_fact_reason": "隔离结构测试占位；真实内容须独立复核。"}
                         for part in payload["paragraph_index"]]}


def raw_for(source, plan):
    return raw_fixture(facts.chapter_payload(source, plan))


def rich_fixture():
    source = chapters()
    plan = facts.plan_chapters(source)[0]
    payload = facts.chapter_payload(source, plan)
    raw = raw_fixture(payload)
    parts = facts.chapters_v4.chapter_passages(source[0])
    text = {part["id"]: part["text"].strip() for part in parts}
    def refs(number):
        pid = f"CH1-P{number:03d}"
        return [{"paragraph_id": pid, "exact_quote": text[pid]}]
    names = [("苏墨", "person", 1), ("叶南", "person", 1), ("钥匙", "object", 2),
             ("门口", "place", 2), ("老师", "person", 3), ("学校", "place", 4)]
    raw["entities"] = [{"id": f"CH1-E{index:03d}", "kind": kind, "name": name,
                        "source_refs": refs(paragraph)}
                       for index, (name, kind, paragraph) in enumerate(names, 1)]
    data = [
        (1, "character", "苏墨是叶南的继父。", "actual", "timeless", [1, 2],
         "relation", 1, 2, "父子关系", "", "继父", "assertion"),
        (2, "event", "叶南把原来自己持有的钥匙递给苏墨。", "actual", "chapter_present", [1, 2, 3],
         "possession", 1, 3, "钥匙持有者", "叶南", "苏墨", "transition"),
        (3, "event", "叶南回忆去年把钥匙交给老师。", "memory", "earlier", [2, 3, 5],
         "possession", 5, 3, "钥匙持有者", "叶南", "老师", "transition"),
        (4, "event", "苏墨计划明天带叶南去学校。", "plan", "later", [1, 2, 6],
         "location", 1, 6, "计划去处", "", "学校", "assertion"),
        (5, "character", "叶南认为苏墨已经知道此事。", "belief", "chapter_present", [1, 2],
         "knowledge", 1, 0, "知情", "", "已经知道此事", "assertion"),
    ]
    for number, category, statement, modality, time, entities, kind, subject, obj, predicate, before, after, change_type in data:
        raw["facts"].append({"id": f"CH1-F{number:03d}", "categories": [category], "statement": statement,
                             "entity_ids": [f"CH1-E{i:03d}" for i in entities], "modality": modality,
                             "event_time": time, "narrative_anchor_passage_id": f"CH1-P{number:03d}",
                             "source_refs": refs(number),
                             "state_changes": [{"kind": kind, "subject_id": f"CH1-E{subject:03d}",
                                                "object_id": f"CH1-E{obj:03d}" if obj else "",
                                                "predicate": predicate, "before_value": before,
                                                "after_value": after, "change_type": change_type,
                                                "source_refs": refs(number)}]})
        raw["coverage"][number - 1].update(fact_ids=[f"CH1-F{number:03d}"], no_fact_reason="")
    accepted = facts.validate(raw, source, plan)
    return source, plan, payload, raw, accepted


def pass_review(payload):
    return {"candidate_sha256": payload["candidate_sha256"], "decision": "pass",
            "checked_fact_ids": deepcopy(payload["required_fact_ids"]),
            "checked_coverage_ids": deepcopy(payload["required_coverage_ids"]),
            "checks": [{"dimension": dimension, "decision": "pass", "reason": "隔离测试通过"}
                       for dimension in facts.REVIEW_CHECKS], "issues": []}


def catalog_fixture():
    source, plan, _, _, accepted = rich_fixture()
    plans = facts.plan_chapters(source)
    analyses = [accepted] + [facts.validate(raw_for(source, item), source, item) for item in plans[1:]]
    return source, plans, analyses, facts.facts_catalog(analyses, source, plans, "隔离样本")


def test_payload_is_complete_chapter_plus_whole_context_and_no_duplicate_paragraph_body():
    source = chapters()
    plan = facts.plan_chapters(source)[1]
    payload = facts.chapter_payload(source, plan)
    assert payload["core_chapter"]["text"] == source[1]["text"]
    assert [row["text"] for row in payload["context_chapters"]] == [source[0]["text"], source[2]["text"]]
    assert all("text" not in row for row in payload["paragraph_index"] + payload["context_reference_index"])
    assert payload["reading_policy"] == facts.policy()
    assert "classification_scope" not in payload["reading_policy"]
    assert "本章" in facts.EXTRACT_PROMPT


def test_schema_allows_explicit_no_fact_chapter_but_does_not_mark_semantic_pass():
    source = chapters()
    plan = facts.plan_chapters(source)[2]
    payload = facts.chapter_payload(source, plan)
    raw = raw_fixture(payload)
    Draft202012Validator(facts.chapter_schema(plan, payload)).validate(raw)
    accepted = facts.validate(raw, source, plan)
    assert accepted["facts"] == []
    assert accepted["validation"]["semantic_review"] == "not_performed"
    assert accepted["validation"]["current_state_verified"] is False


def test_source_evidence_offsets_and_hashes_are_computed_from_original():
    source, _, _, _, accepted = rich_fixture()
    for fact in accepted["facts"]:
        for evidence in fact["source_evidence"]:
            original = source[evidence["chapter_index"] - 1]["text"]
            assert original[evidence["start_offset"]:evidence["end_offset"]] == evidence["exact_quote"]
            assert evidence["sha256"] == hashlib.sha256(evidence["exact_quote"].encode()).hexdigest()
            assert evidence["chapter_sha256"] == source[evidence["chapter_index"] - 1]["sha256"]
            assert evidence["scope"] == "core"


def test_event_time_differs_from_narrative_position_and_noncurrent_state_is_blocked():
    _, _, _, _, accepted = rich_fixture()
    by_id = {fact["id"]: fact for fact in accepted["facts"]}
    assert by_id["CH1-F001"]["state_application"] == "background_candidate_requires_review"
    assert by_id["CH1-F002"]["state_application"] == "candidate_requires_review"
    for identifier in ("CH1-F003", "CH1-F004", "CH1-F005"):
        fact = by_id[identifier]
        assert fact["narrative_position"]["chapter_index"] == 1
        assert fact["state_application"] == "blocked_noncurrent_modality_or_time"
        assert fact["state_changes"][0]["state_application"] == "blocked_noncurrent_modality_or_time"
    assert by_id["CH1-F003"]["event_time"] == "earlier"
    assert by_id["CH1-F004"]["event_time"] == "later"


@pytest.mark.parametrize("modality", ["memory", "plan", "belief", "hypothetical", "quoted_story", "uncertain"])
def test_nonactual_modality_never_becomes_current_state(modality):
    assert facts.state_application(modality, "chapter_present") == "blocked_noncurrent_modality_or_time"
    assert facts.state_application(modality, "timeless") == "blocked_noncurrent_modality_or_time"


@pytest.mark.parametrize("time", ["earlier", "later", "unspecified"])
def test_actual_but_noncurrent_time_cannot_silently_update_current_state(time):
    assert facts.state_application("actual", time) == "blocked_noncurrent_modality_or_time"


def test_narrative_anchor_is_bound_to_current_evidence_not_free_timestamp():
    source, plan, _, raw, _ = rich_fixture()
    raw["facts"][0]["narrative_anchor_passage_id"] = "CH1-P002"
    with pytest.raises(ValueError, match="narrative_anchor_not_in_evidence"):
        facts.validate(raw, source, plan)


@pytest.mark.parametrize("mutation,reason", [
    (lambda raw: raw["facts"].append(deepcopy(raw["facts"][0])), "fact_id_duplicate"),
    (lambda raw: raw["entities"].append(deepcopy(raw["entities"][0])), "entity_id_duplicate"),
    (lambda raw: raw["facts"][0].update(id="CH2-F001"), "schema_invalid"),
    (lambda raw: raw["facts"][0].update(entity_ids=["CH1-E999"]), "entity_reference_unknown"),
    (lambda raw: raw["entities"][0].update(name="原文没有的人"), "name_not_in_cited_source"),
    (lambda raw: raw["facts"][0]["source_refs"][0].update(exact_quote="苏墨是叶南的亲生父亲。"), "quote_not_in_original"),
    (lambda raw: raw["facts"][0]["source_refs"][0].update(paragraph_id="CH1-P999"), "paragraph_unknown"),
    (lambda raw: raw["facts"][0].update(modality="certain"), "schema_invalid"),
    (lambda raw: raw["coverage"].pop(), "schema_invalid"),
    (lambda raw: raw["coverage"][0].update(fact_ids=[], no_fact_reason=""), "fact_ids_or_explicit_no_fact"),
    (lambda raw: raw["coverage"][0].update(no_fact_reason="也有说明"), "fact_ids_or_explicit_no_fact"),
    (lambda raw: raw["coverage"][0].update(fact_ids=["CH1-F002"]), "coverage_fact_evidence_mismatch"),
])
def test_invalid_facts_and_coverage_are_rejected(mutation, reason):
    source, plan, _, raw, _ = rich_fixture()
    mutation(raw)
    with pytest.raises(ValueError, match=reason):
        facts.validate(raw, source, plan)


def test_context_only_claim_cannot_become_current_chapter_fact():
    source, plan, _, raw, _ = rich_fixture()
    raw["facts"][0]["source_refs"] = [{"paragraph_id": "CH2-P001", "exact_quote": "苏墨坐在家中。"}]
    with pytest.raises(ValueError, match="requires_current_chapter_evidence"):
        facts.validate(raw, source, plan)


def test_context_reference_is_bound_and_never_counts_as_core_coverage():
    source, plan, _, raw, _ = rich_fixture()
    raw["facts"][0]["source_refs"].append({"paragraph_id": "CH2-P001", "exact_quote": "苏墨坐在家中。"})
    accepted = facts.validate(raw, source, plan)
    evidence = accepted["facts"][0]["source_evidence"][-1]
    assert evidence["scope"] == "context" and evidence["chapter_index"] == 2
    assert all(row["paragraph_id"].startswith("CH1-") for row in accepted["coverage"])


def test_repeated_quote_requires_longer_unique_evidence():
    source = [{"index": 1, "title": "重复", "text": "苏墨看着苏墨的照片。"}]
    plan = facts.plan_chapters(source)[0]
    raw = raw_for(source, plan)
    raw["entities"] = [{"id": "CH1-E001", "name": "苏墨", "kind": "person",
                        "source_refs": [{"paragraph_id": "CH1-P001", "exact_quote": "苏墨"}]}]
    with pytest.raises(ValueError, match="quote_ambiguous"):
        facts.validate(raw, source, plan)


@pytest.mark.parametrize("mutation,reason", [
    (lambda change: change.update(before_value="他原先是亲父"), "assertion_cannot_claim_before"),
    (lambda change: change.update(subject_id="CH1-E999"), "state_entity_not_declared"),
    (lambda change: change.update(change_type="transition", before_value=""), "transition_requires_distinct"),
    (lambda change: change.update(change_type="transition", before_value=change["after_value"]), "transition_requires_distinct"),
    (lambda change: change.update(source_refs=[{"paragraph_id": "CH1-P003", "exact_quote": "叶南想起去年自己把钥匙交给老师。"}]), "state_evidence_outside_fact"),
])
def test_state_changes_require_explicit_bound_inputs(mutation, reason):
    source, plan, _, raw, _ = rich_fixture()
    mutation(raw["facts"][0]["state_changes"][0])
    with pytest.raises(ValueError, match=reason):
        facts.validate(raw, source, plan)


def test_catalog_revalidates_and_keeps_original_chapters_and_local_entity_ids():
    source, _, _, catalog = catalog_fixture()
    assert catalog["chapters"] == source
    assert len(catalog["analyses"]) == 3 and len(catalog["facts"]) == 5
    assert catalog["entities"][0]["identity_scope"] == "chapter_local_unresolved"
    assert catalog["entities"][0]["chapter_index"] == 1
    assert catalog["validation"]["semantic_review"] == "not_performed"


@pytest.mark.parametrize("mutation", [
    lambda catalog: catalog["facts"][0].update(statement="篡改事实"),
    lambda catalog: catalog["analyses"][0]["facts"][0]["source_evidence"][0].update(start_offset=999),
    lambda catalog: catalog["analyses"][0]["facts"][2].update(state_application="candidate_requires_review"),
    lambda catalog: catalog["entities"][0].update(identity_scope="confirmed_global_identity"),
    lambda catalog: catalog["chapters"][0].update(text="替换原文"),
    lambda catalog: catalog.update(source_digest="wrong"),
])
def test_catalog_tampering_blocked_before_cloud(mutation):
    _, _, _, catalog = catalog_fixture()
    mutation(catalog)
    with pytest.raises(ValueError):
        facts.cloud_input(catalog)


def test_catalog_missing_chapter_cannot_claim_complete_book():
    source, plans, analyses, _ = catalog_fixture()
    with pytest.raises(ValueError, match="analysis_chapter_set_mismatch"):
        facts.facts_catalog(analyses[:-1], source, plans)
    with pytest.raises(ValueError, match="all_chapter_coverage_incomplete"):
        facts.facts_catalog(analyses[:-1], source, plans[:-1])


def test_legacy_source_pack_preserves_every_character_without_fake_classification():
    from src.content_factory.corpus_production_contract_v3 import _source
    source, _, _, catalog = catalog_fixture()
    pack = facts.cloud_input(catalog)
    assert pack["classification_index"] == []
    assert pack["limits"]["legacy_classification_performed"] is False
    assert pack["limits"]["fact_candidates_semantically_reviewed"] is False
    assert pack["limits"]["omitted_chars"] == 0
    _source(pack, source)
    for chapter in source:
        assert "".join(row["text"] for row in pack["selected_core_passages"]
                       if row["chapter_index"] == chapter["index"]) == chapter["text"]


def test_review_covers_facts_and_no_fact_paragraphs_and_binds_candidate():
    source, plan, _, _, accepted = rich_fixture()
    payload = facts.review_payload(accepted, source, plan)
    review = facts.validate_review(pass_review(payload), payload)
    assert review["decision"] == "pass"
    assert len(review["checked_coverage_ids"]) == 6
    assert len(review["checked_fact_ids"]) == 5
    assert review["binding"]["candidate_sha256"] == facts.digest(accepted)
    assert review["validation"]["current_state_verified"] is False


def test_review_of_no_fact_candidate_still_checks_every_paragraph():
    source = chapters()
    plan = facts.plan_chapters(source)[2]
    accepted = facts.validate(raw_for(source, plan), source, plan)
    payload = facts.review_payload(accepted, source, plan)
    result = facts.validate_review(pass_review(payload), payload)
    assert result["checked_fact_ids"] == []
    assert len(result["checked_coverage_ids"]) == 2


def revise_review(payload):
    raw = pass_review(payload)
    raw["decision"] = "revise"
    next(row for row in raw["checks"] if row["dimension"] == "source_fidelity")["decision"] = "revise"
    raw["issues"] = [{"category": "source_fidelity", "location": "facts.CH1-F001", "fact_ids": ["CH1-F001"],
                      "paragraph_ids": ["CH1-P001"], "reason": "隔离测试定位",
                      "source_refs": [{"paragraph_id": "CH1-P001", "exact_quote": "苏墨是叶南的继父。"}]}]
    return raw


def test_review_revision_binds_original_evidence_and_never_rewrites_candidate():
    source, plan, _, _, accepted = rich_fixture()
    original = deepcopy(accepted)
    payload = facts.review_payload(accepted, source, plan)
    review = facts.validate_review(revise_review(payload), payload)
    assert review["decision"] == "revise"
    assert review["issues"][0]["source_evidence"][0]["start_offset"] == 0
    assert accepted == original


@pytest.mark.parametrize("mutation,reason", [
    (lambda raw: raw.update(candidate_sha256="bad"), "schema_invalid"),
    (lambda raw: raw["checked_fact_ids"].pop(), "schema_invalid"),
    (lambda raw: raw["checked_coverage_ids"].pop(), "schema_invalid"),
    (lambda raw: raw["checks"][0].update(dimension=raw["checks"][1]["dimension"]), "check_set_mismatch"),
    (lambda raw: raw.update(decision="pass"), "decision_inconsistent"),
    (lambda raw: raw["issues"][0]["source_refs"][0].update(exact_quote="他是亲父"), "quote_not_in_original"),
    (lambda raw: raw["issues"][0].update(paragraph_ids=["CH1-P002"]), "evidence_location_mismatch"),
])
def test_invalid_review_cannot_release_candidate(mutation, reason):
    source, plan, _, _, accepted = rich_fixture()
    payload = facts.review_payload(accepted, source, plan)
    raw = revise_review(payload)
    mutation(raw)
    with pytest.raises(ValueError, match=reason):
        facts.validate_review(raw, payload)


def test_full_chapter_input_is_never_truncated_to_fit_context():
    source = [{"index": 1, "title": "长章", "text": "一个连续自然段" * 15000}]
    plan = facts.plan_chapters(source)[0]
    payload = facts.chapter_payload(source, plan)
    assert payload["core_chapter"]["text"] == source[0]["text"]
    assert len(payload["paragraph_index"]) == 1
    payload["output_schema"] = facts.chapter_schema(plan, payload)
    bound = len(facts.EXTRACT_PROMPT.encode()) + len(json.dumps(payload, ensure_ascii=False).encode()) + 8192 + 1024
    assert bound > 65536


@pytest.mark.parametrize("mutation", [
    lambda payload: payload["candidate"]["facts"][0].update(statement="换成另一个事实"),
    lambda payload: payload["core_chapter"].update(text="换成另一段正文"),
    lambda payload: payload["required_fact_ids"].pop(),
])
def test_review_input_mutation_cannot_reuse_original_candidate_hash(mutation):
    source, plan, _, _, accepted = rich_fixture()
    payload = facts.review_payload(accepted, source, plan)
    raw = pass_review(payload)
    mutation(payload)
    with pytest.raises(ValueError, match="review_payload_binding_mismatch"):
        facts.validate_review(raw, payload)
