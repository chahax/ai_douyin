from copy import deepcopy
import hashlib
import json

import pytest
from jsonschema import Draft202012Validator

from src.content_factory import corpus_chapter_materials_v6 as materials


def chapters():
    texts = [
        "林岚是阿禾的继母。\n黄铜钥匙挂在林岚腰间，她打算明早再交给阿禾。\n"
        "阿禾想起去年把另一把木钥匙交给父亲周远。\n……\n",
        "林岚将黄铜钥匙递给阿禾，阿禾接住后装进右口袋。\n周远还在院外，并不知道这次交接。\n",
        "次日阿禾打开柜子发现一封信。\n周远这才知道林岚昨天已经交出了黄铜钥匙。\n",
    ]
    return [{"index": i, "title": f"第{i}章", "text": text,
             "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
            for i, text in enumerate(texts, 1)]


def raw_for(source, plan):
    raw = {"chapter_id": plan["id"], "chapter_index": plan["chapter_index"],
           "facts": [], "coverage": []}
    chapter = next(row for row in source if row["index"] == plan["chapter_index"])
    for part in materials.chapters_v4.chapter_passages(chapter):
        if part["text"].strip() == "……":
            raw["coverage"].append({"paragraph_id": part["id"], "fact_ids": [],
                                    "no_fact_reason": "省略号单独构成停顿，没有独立材料。"})
            continue
        identifier = f'CH{plan["chapter_index"]}-F{len(raw["facts"]) + 1:03d}'
        raw["facts"].append({
            "id": identifier, "categories": ["event"], "statement": part["text"].strip(),
            "modality": "actual", "event_time": "chapter_present",
            "narrative_anchor_passage_id": part["id"],
            "source_refs": [{"paragraph_id": part["id"], "exact_quote": part["text"].strip()}],
        })
        raw["coverage"].append({"paragraph_id": part["id"], "fact_ids": [identifier], "no_fact_reason": ""})
    if plan["chapter_index"] == 1 and len(raw["facts"]) == 3:
        raw["facts"][0].update(categories=["character"], event_time="timeless")
        raw["facts"][1].update(statement="林岚计划明早把黄铜钥匙交给阿禾。", modality="plan", event_time="later")
        raw["facts"][2].update(modality="memory", event_time="earlier")
    return raw


def fixture():
    source = chapters()
    plans = materials.plan_chapters(source)
    raw = raw_for(source, plans[0])
    accepted = materials.validate(raw, source, plans[0])
    return source, plans, raw, accepted


def catalog_fixture():
    source, plans, _, _ = fixture()
    accepted = [materials.validate(raw_for(source, plan), source, plan) for plan in plans]
    return source, plans, accepted, materials.facts_catalog(accepted, source, plans, "两把钥匙")


def pass_review(payload):
    return {"candidate_sha256": payload["candidate_sha256"], "decision": "pass",
            "checked_fact_ids": deepcopy(payload["required_fact_ids"]),
            "checked_coverage_ids": deepcopy(payload["required_coverage_ids"]),
            "checks": [{"dimension": dimension, "decision": "pass", "reason": "隔离协议测试结果"}
                       for dimension in materials.REVIEW_CHECKS], "issues": []}


def test_complete_author_chapter_and_neighbors_are_kept_without_body_duplication():
    source, plans, _, _ = fixture()
    payload = materials.chapter_payload(source, plans[1], "两把钥匙")
    assert payload["core_chapter"]["text"] == source[1]["text"]
    assert [c["text"] for c in payload["context_chapters"]] == [source[0]["text"], source[2]["text"]]
    assert all("text" not in p for p in payload["paragraph_index"] + payload["context_reference_index"])
    assert payload["reading_policy"]["state_detail"] == "deferred_until_episode_detail"


def test_initial_schema_has_no_entity_or_state_arrays_and_accepts_natural_materials():
    source, plans, raw, accepted = fixture()
    schema = materials.chapter_schema(plans[0], materials.chapter_payload(source, plans[0]))
    Draft202012Validator(schema).validate(raw)
    assert "entities" not in schema["properties"]
    assert not {"entity_ids", "state_changes"} & schema["properties"]["facts"]["items"]["properties"].keys()
    assert "entities" not in accepted
    assert all("state_changes" not in fact and "entity_ids" not in fact for fact in accepted["facts"])
    assert accepted["validation"]["semantic_review"] == "not_performed"
    assert accepted["validation"]["episode_detail_performed"] is False
    assert accepted["validation"]["current_state_verified"] is False
    assert materials.raw_candidate(accepted) == raw


def test_simpler_contract_does_not_require_detailed_states_from_initial_model():
    from src.content_factory import corpus_chapter_facts_v5 as old
    source, plans, _, _ = fixture()
    v6 = materials.chapter_schema(plans[0], materials.chapter_payload(source, plans[0]))
    v5 = old.chapter_schema(plans[0], old.chapter_payload(source, plans[0]))
    assert len(json.dumps(v6)) < len(json.dumps(v5))
    assert materials.REVIEW_CHECKS == ("source_fidelity", "classification", "modality_and_event_time", "paragraph_coverage")


def test_source_offsets_hashes_and_narrative_positions_remain_bound():
    source, _, _, accepted = fixture()
    for fact in accepted["facts"]:
        anchor = fact["narrative_position"]
        assert anchor["chapter_index"] == 1
        assert anchor["paragraph_id"] == fact["narrative_anchor_passage_id"]
        for evidence in fact["source_evidence"]:
            assert source[0]["text"][evidence["start_offset"]:evidence["end_offset"]] == evidence["exact_quote"]
            assert evidence["sha256"] == hashlib.sha256(evidence["exact_quote"].encode("utf-8")).hexdigest()
            assert evidence["chapter_sha256"] == source[0]["sha256"]


def test_plans_memories_and_narrative_position_are_not_current_state():
    _, _, _, accepted = fixture()
    assert accepted["facts"][0]["state_application"] == "background_candidate_requires_review"
    for fact in accepted["facts"][1:]:
        assert fact["state_application"] == "blocked_noncurrent_modality_or_time"
        assert fact["narrative_position"]["chapter_index"] == 1
    assert accepted["facts"][1]["event_time"] == "later"
    assert accepted["facts"][2]["event_time"] == "earlier"


@pytest.mark.parametrize("mutation,reason", [
    (lambda raw: raw.update(entities=[]), "schema_invalid"),
    (lambda raw: raw["facts"][0].update(state_changes=[]), "schema_invalid"),
    (lambda raw: raw["facts"][0].update(entity_ids=[]), "schema_invalid"),
    (lambda raw: raw["facts"].append(deepcopy(raw["facts"][0])), "fact_id_duplicate"),
    (lambda raw: raw["facts"][0].update(id="CH2-F001"), "schema_invalid"),
    (lambda raw: raw["facts"][0].update(categories=["knowledge"]), "schema_invalid"),
    (lambda raw: raw["facts"][0]["source_refs"][0].update(exact_quote="林岚是阿禾的生母。"), "quote_not_in_original"),
    (lambda raw: raw["facts"][0]["source_refs"][0].update(paragraph_id="CH1-P999"), "paragraph_unknown"),
    (lambda raw: raw["facts"][0].update(narrative_anchor_passage_id="CH1-P002"), "anchor_not_in_evidence"),
    (lambda raw: raw["coverage"].pop(), "schema_invalid"),
    (lambda raw: raw["coverage"][0].update(fact_ids=[], no_fact_reason=""), "fact_ids_or_explicit_no_fact"),
    (lambda raw: raw["coverage"][0].update(no_fact_reason="有事实也写理由"), "fact_ids_or_explicit_no_fact"),
    (lambda raw: raw["coverage"][0].update(fact_ids=["CH1-F002"]), "coverage_fact_evidence_mismatch"),
])
def test_material_provenance_and_coverage_remain_strict(mutation, reason):
    source, plans, raw, _ = fixture()
    mutation(raw)
    with pytest.raises(ValueError, match=reason):
        materials.validate(raw, source, plans[0])


def test_neighbor_only_evidence_cannot_become_this_chapters_material():
    source, plans, raw, _ = fixture()
    raw["facts"][0]["source_refs"] = [{"paragraph_id": "CH2-P002", "exact_quote": "周远还在院外，并不知道这次交接。"}]
    with pytest.raises(ValueError, match="requires_current_chapter_evidence"):
        materials.validate(raw, source, plans[0])


def test_valid_neighbor_citation_remains_context_and_does_not_inflate_core_coverage():
    source, plans, raw, _ = fixture()
    raw["facts"][0]["source_refs"].append({"paragraph_id": "CH2-P002", "exact_quote": "周远还在院外，并不知道这次交接。"})
    accepted = materials.validate(raw, source, plans[0])
    assert accepted["facts"][0]["source_evidence"][-1]["scope"] == "context"
    assert all(p["paragraph_id"].startswith("CH1-") for p in accepted["coverage"])


def test_repeated_quote_is_rejected_instead_of_guessing_offsets():
    source = [{"index": 1, "title": "重复", "text": "林岚看着林岚的照片。"}]
    plan = materials.plan_chapters(source)[0]
    raw = raw_for(source, plan)
    raw["facts"][0]["source_refs"][0]["exact_quote"] = "林岚"
    with pytest.raises(ValueError, match="quote_ambiguous"):
        materials.validate(raw, source, plan)


def test_catalog_keeps_full_chapters_and_does_not_claim_identity_or_state_detail():
    source, _, _, catalog = catalog_fixture()
    assert catalog["chapters"] == source
    assert catalog["entities"] == []
    assert catalog["policy"]["identity_resolution"] == "deferred_until_episode_detail"
    assert catalog["policy"]["episode_detail_performed"] is False
    pack = materials.cloud_input(catalog)
    assert len(pack["chapter_materials"]) == 3
    assert "chapter_facts" not in pack
    assert pack["limits"]["omitted_chars"] == 0
    assert pack["limits"]["full_source"] is True
    assert pack["limits"]["compression_performed"] is False
    assert pack["limits"]["material_candidates_semantically_reviewed"] is False
    assert pack["limits"]["episode_detail_performed"] is False
    assert pack["source_chars"] == sum(len(c["text"]) for c in source)
    for chapter in source:
        assert "".join(p["text"] for p in pack["selected_core_passages"] if p["chapter_index"] == chapter["index"]) == chapter["text"]


@pytest.mark.parametrize("mutation", [
    lambda c: c["facts"][0].update(statement="篡改"),
    lambda c: c["analyses"][0]["facts"][0]["source_evidence"][0].update(start_offset=999),
    lambda c: c["chapters"][0].update(text="替换"),
    lambda c: c.update(source_digest="wrong"),
    lambda c: c["entities"].append({"id": "fake"}),
    lambda c: c["policy"].update(episode_detail_performed=True),
])
def test_catalog_tampering_is_rejected(mutation):
    _, _, _, catalog = catalog_fixture()
    mutation(catalog)
    with pytest.raises(ValueError):
        materials.cloud_input(catalog)


def test_all_author_chapters_required_for_complete_catalog():
    source, plans, accepted, _ = catalog_fixture()
    with pytest.raises(ValueError, match="chapter_set_mismatch"):
        materials.facts_catalog(accepted[:-1], source, plans)
    with pytest.raises(ValueError, match="all_chapter_coverage_incomplete"):
        materials.facts_catalog(accepted[:-1], source, plans[:-1])


def test_material_review_pass_does_not_claim_episode_state_pass():
    source, plans, _, accepted = fixture()
    payload = materials.review_payload(accepted, source, plans[0])
    review = materials.validate_review(pass_review(payload), payload)
    assert review["decision"] == "pass"
    assert review["validation"]["review_is_model_opinion"] is True
    assert review["validation"]["current_state_verified"] is False


def test_missing_material_review_requires_bound_original_evidence():
    source, plans, _, accepted = fixture()
    payload = materials.review_payload(accepted, source, plans[0])
    raw = pass_review(payload)
    raw["decision"] = "revise"
    next(c for c in raw["checks"] if c["dimension"] == "paragraph_coverage")["decision"] = "revise"
    raw["issues"] = [{"category": "paragraph_coverage", "location": "facts", "fact_ids": [],
                      "paragraph_ids": ["CH1-P002"], "reason": "遗漏钥匙仍在林岚腰间的明确当前背景。",
                      "source_refs": [{"paragraph_id": "CH1-P002", "exact_quote": "黄铜钥匙挂在林岚腰间"}]}]
    checked = materials.validate_review(raw, payload)
    assert checked["issues"][0]["source_evidence"][0]["scope"] == "core"
    raw["issues"][0]["source_refs"][0]["exact_quote"] = "钥匙在阿禾口袋"
    with pytest.raises(ValueError, match="quote_not_in_original"):
        materials.validate_review(raw, payload)


def test_review_cannot_reintroduce_state_array_requirement_or_skip_classification():
    source, plans, _, accepted = fixture()
    payload = materials.review_payload(accepted, source, plans[0])
    raw = pass_review(payload)
    next(c for c in raw["checks"] if c["dimension"] == "classification")["dimension"] = "state_changes"
    with pytest.raises(ValueError, match="schema_invalid"):
        materials.validate_review(raw, payload)


def test_no_fact_chapter_is_structurally_valid_but_still_needs_semantic_review():
    source = [{"index": 1, "title": "停顿", "text": "……\n"}]
    plan = materials.plan_chapters(source)[0]
    accepted = materials.validate(raw_for(source, plan), source, plan)
    assert accepted["facts"] == []
    payload = materials.review_payload(accepted, source, plan)
    checked = materials.validate_review(pass_review(payload), payload)
    assert checked["checked_fact_ids"] == []
    assert accepted["validation"]["semantic_review"] == "not_performed"
