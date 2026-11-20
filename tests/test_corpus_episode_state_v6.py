"""Offline v6 state contracts. No provider calls or production acceptance."""
from copy import deepcopy
import hashlib

import pytest

from src.content_factory import corpus_chapter_materials_v6 as facts
from src.content_factory import corpus_episode_state_v6 as episode
from tests.test_corpus_episode_state_v5 import episode_fixture as legacy_fixture


def _fid(number, chapter=1):
    return f"CH{chapter}-F{number:03d}"


def _catalog(source, raws):
    plans = facts.plan_chapters(source)
    accepted = [facts.validate(raw, source, plan) for raw, plan in zip(raws, plans)]
    return facts.facts_catalog(accepted, source, plans, "隔离状态样本")


def _raws(library):
    return [facts.raw_candidate(row) for row in library["analyses"]]


def episode_fixture():
    """Keep the legacy synthetic story and IDs, with genuinely light v6 facts."""
    source, old_library, raw = legacy_fixture()
    raw["prop_introductions"] = []
    raws = []
    for old in old_library["analyses"]:
        raws.append({"chapter_id": old["chapter_id"], "chapter_index": old["chapter_index"],
                     "facts": [{key: deepcopy(f[key]) for key in facts.FACT_KEYS}
                               for f in old["facts"]], "coverage": deepcopy(old["coverage"])})
    library = _catalog(source, raws)
    by_fact = {f["id"]: f for f in library["facts"]}
    for row in raw["entities"]:
        row.pop("source_entity_ids")
        row["identity_source_refs"] = [{"fact_id": fid,
            "paragraph_id": by_fact[fid]["source_evidence"][0]["paragraph_id"],
            "exact_quote": by_fact[fid]["source_evidence"][0]["exact_quote"]}
            for fid in row["identity_fact_ids"]]
    for row in raw["states"]:
        row["source_fact_refs"] = [{"fact_id": ref["fact_id"],
            "paragraph_id": by_fact[ref["fact_id"]]["source_evidence"][0]["paragraph_id"],
            "exact_quote": by_fact[ref["fact_id"]]["source_evidence"][0]["exact_quote"]}
            for ref in row.pop("source_state_refs")]
    return source, library, raw


def valid_fixture():
    source, library, raw = episode_fixture()
    return source, library, episode.validate_episode(raw, library, source, [1], 10)


def _check(source, library, raw):
    return episode.validate_episode(raw, library, source, raw["selected_chapter_indices"], raw["target_seconds"])


def _ref(library, number, chapter=1):
    fact = next(f for f in library["facts"] if f["id"] == _fid(number, chapter))
    evidence = fact["source_evidence"][0]
    return {"fact_id": fact["id"], "paragraph_id": evidence["paragraph_id"],
            "exact_quote": evidence["exact_quote"]}


def test_fact_only_materials_feed_source_bound_episode_and_writer_context():
    source, library, accepted = valid_fixture()
    assert library["entities"] == []
    assert all("entity_ids" not in f and "state_changes" not in f for f in library["facts"])
    context = episode.build_episode_context(accepted, library, source)
    assert context["selected_original_chapters"] == library["chapters"][:1]
    assert context["required_evidence_chapters"] == []
    assert context["episode_source_entities"] == accepted["snapshot"]["entities"]
    assert "global_bible" not in context
    assert accepted["binding"]["identity_evidence"]["adult"][0]["paragraph_sha256"]
    assert accepted["binding"]["state_evidence"]["key_adult"][0]["chapter_sha256"]
    assert accepted["validation"]["state_completeness_semantically_verified"] is False
    assert accepted["validation"]["knowledge_completeness_semantically_verified"] is False


def test_future_full_chapters_and_candidate_facts_are_excluded():
    source, library, _ = episode_fixture()
    payload = episode.episode_payload(library, source, [1], 10)
    assert all(f["chapter_index"] == 1 for f in payload["candidate_facts"])
    assert [c["index"] for c in payload["selected_original_chapters"]] == [1]
    assert "candidate_entities" not in payload


@pytest.mark.parametrize("modality,time", [(m, "chapter_present") for m in
    ("memory", "plan", "belief", "hypothetical", "quoted_story", "uncertain")]
    + [("actual", t) for t in ("earlier", "later", "unspecified")])
def test_noncurrent_material_cannot_update_state(modality, time):
    source, library, raw = episode_fixture()
    raws = _raws(library)
    raws[0]["facts"][1].update(modality=modality, event_time=time)
    with pytest.raises(ValueError, match="noncurrent_fact_used_as_state"):
        _check(source, _catalog(source, raws), raw)


@pytest.mark.parametrize("field", ["identity_source_refs", "source_fact_refs"])
def test_original_quote_cannot_be_forged(field):
    source, library, raw = episode_fixture()
    target = raw["entities"][0] if field.startswith("identity") else raw["states"][0]
    target[field][0]["exact_quote"] = "原文不存在的角色与状态"
    with pytest.raises(ValueError, match="source_quote_not_in_original"):
        _check(source, library, raw)


def test_quote_in_original_but_not_bound_to_declared_fact_is_rejected():
    source, library, raw = episode_fixture()
    raw["states"][0]["source_fact_refs"][0] = _ref(library, 3)
    raw["states"][0]["source_fact_refs"][0]["fact_id"] = _fid(1)
    with pytest.raises(ValueError, match="reference_not_bound_to_fact"):
        _check(source, library, raw)


def test_identity_names_and_duplicate_source_identity_are_checked():
    source, library, raw = episode_fixture()
    wrong = deepcopy(raw); wrong["entities"][0]["name"] = "不存在的名字"
    with pytest.raises(ValueError, match="canonical_name_not_from_source"):
        _check(source, library, wrong)
    clone = deepcopy(raw["entities"][0]); clone["id"] = "duplicate_actor"
    raw["entities"].append(clone)
    with pytest.raises(ValueError, match="source_identity_bound_twice"):
        _check(source, library, raw)


def test_identity_fact_set_must_equal_actual_identity_reference_set():
    source, library, raw = episode_fixture()
    raw["entities"][0]["identity_fact_ids"].append(_fid(2))
    with pytest.raises(ValueError, match="identity_fact_reference_mismatch"):
        _check(source, library, raw)


def test_identity_cannot_be_established_only_from_plan_or_memory():
    source, library, raw = episode_fixture()
    raw["entities"][0].update(identity_fact_ids=[_fid(4)], identity_source_refs=[_ref(library, 4)])
    with pytest.raises(ValueError, match="identity_evidence_not_actual"):
        _check(source, library, raw)


def test_opening_cannot_claim_later_transfer():
    source, library, raw = episode_fixture()
    raw["snapshots"][0]["state_ids"][2] = "key_adult"
    with pytest.raises(ValueError, match="fact_occurs_after_snapshot"):
        _check(source, library, raw)


@pytest.mark.parametrize("mutation,reason", [
    (lambda r: r["beats"][0].update(actions=[]), "unexplained_state_change"),
    (lambda r: r["beats"][0]["actions"][0].update(kind="perform"), "action_kind_state_mismatch"),
    (lambda r: r["beats"][0]["actions"][0].update(actor_ids=["child"]), "transfer_holder_not_acting"),
    (lambda r: r["beats"][0]["actions"][0]["changes"][0].update(from_state_id=""), "cannot_overwrite"),
    (lambda r: r["states"][0].update(subject_id="key"), "entity_type_or_reference"),
    (lambda r: r["beats"][0].update(duration_seconds=11), "duration_exceeds_target"),
    (lambda r: r["states"][-1].update(source_fact_refs=[]), "state_unanchored"),
    (lambda r: r["beats"][0]["actions"][0].update(source_fact_ids=[]), "action_unanchored"),
    (lambda r: r["beats"][0]["actions"][0].update(source_fact_ids=[_fid(1)]), "transfer_or_learn_requires_bound_source_action"),
])
def test_explicit_chain_errors_are_blocked(mutation, reason):
    source, library, raw = episode_fixture(); mutation(raw)
    with pytest.raises(ValueError, match=reason):
        _check(source, library, raw)


def test_all_cast_and_props_need_opening_state():
    source, library, raw = episode_fixture()
    for identifier, message in [("adult_room", "character_location_missing"), ("key_child", "prop_holder_missing")]:
        wrong = deepcopy(raw)
        wrong["snapshots"][0]["state_ids"].remove(identifier)
        with pytest.raises(ValueError, match=message):
            _check(source, library, wrong)


def _learning(raw, library):
    raw["target_seconds"] = 15
    raw["states"].append({"id": "child_knows", "kind": "knowledge", "subject_id": "child",
        "object_id": _fid(2), "value": "known", "source_fact_refs": [_ref(library, 5)], "creative_addition_id": ""})
    raw["snapshots"].append({"id": "known", "anchor": {"fact_id": _fid(5), "edge": "after"},
        "state_ids": raw["snapshots"][-1]["state_ids"] + ["child_knows"]})
    raw["beats"].append({"id": "scene_2", "location_id": "room", "before_snapshot_id": "ending",
        "after_snapshot_id": "known", "cast_ids": ["adult", "child"],
        "actions": [{"id": "learn_relation", "kind": "learn", "actor_ids": ["adult", "child"],
            "description": "林青告知小明。", "changes": [{"from_state_id": "", "to_state_id": "child_knows"}],
            "source_fact_ids": [_fid(5)], "creative_addition_id": ""}],
        "purpose": "明确获知", "dialogue_goal": "传递关系信息", "duration_seconds": 5})
    raw["ending_snapshot_id"] = "known"


def test_knowledge_is_extracted_in_episode_without_any_upstream_state():
    source, library, raw = episode_fixture(); _learning(raw, library)
    accepted = _check(source, library, raw)
    assert accepted["snapshot"]["states"][-1]["value"] == "known"
    assert "state_changes" not in library["facts"][-1]


def test_knowledge_cannot_use_unproven_action_or_creative_addition():
    source, library, raw = episode_fixture(); _learning(raw, library)
    wrong = deepcopy(raw); wrong["beats"][-1]["actions"][0]["source_fact_ids"] = [_fid(1)]
    with pytest.raises(ValueError, match="transfer_or_learn_requires_bound_source_action"):
        _check(source, library, wrong)
    raw["creative_additions"] = [{"id": "art", "kind": "performance", "description": "自创知情", "entity_ids": ["child"]}]
    raw["states"][-1].update(source_fact_refs=[], creative_addition_id="art")
    with pytest.raises(ValueError, match="creative_state_not_allowed"):
        _check(source, library, raw)


def test_opening_cannot_know_a_fact_that_occurs_after_its_anchor():
    source, library, raw = episode_fixture()
    raw["states"].append({"id": "knows_future", "kind": "knowledge", "subject_id": "child",
        "object_id": _fid(3), "value": "known", "source_fact_refs": [_ref(library, 1)], "creative_addition_id": ""})
    for frame in raw["snapshots"]: frame["state_ids"].append("knows_future")
    with pytest.raises(ValueError, match="fact_occurs_after_snapshot"):
        _check(source, library, raw)


def test_state_omission_is_explicitly_left_for_snapshot_semantic_review():
    source, library, raw = episode_fixture()
    raw["snapshots"][-1]["anchor"] = {"fact_id": _fid(5), "edge": "after"}
    accepted = _check(source, library, raw)
    assert accepted["validation"]["semantic_review_required"]
    assert accepted["validation"]["knowledge_completeness_semantically_verified"] is False
    assert "知情" in episode.EPISODE_REVIEW_PROMPT


def test_creative_prop_ownership_is_forbidden_but_declared_blocking_allowed():
    source, library, raw = episode_fixture()
    raw["creative_additions"] = [{"id": "block", "kind": "blocking", "description": "补足站位", "entity_ids": ["adult", "key"]}]
    bad = deepcopy(raw); bad["states"][2].update(source_fact_refs=[], creative_addition_id="block")
    with pytest.raises(ValueError, match="creative_state_not_allowed"):
        _check(source, library, bad)
    raw["states"][0].update(source_fact_refs=[], creative_addition_id="block")
    assert _check(source, library, raw)["validation"]["script_actions_semantically_verified"] is False


@pytest.mark.parametrize("entry", [False, True])
def test_newly_visible_character_needs_entry_or_reveal_action(entry):
    source, library, raw = episode_fixture(); raw["target_seconds"] = 12
    establishing = deepcopy(raw["beats"][0])
    establishing.update(id="establish", after_snapshot_id="opening", cast_ids=["adult"], actions=[], duration_seconds=2)
    raw["beats"].insert(0, establishing)
    if entry:
        raw["beats"][1]["actions"].insert(0, {"id": "child_entry", "kind": "entry", "actor_ids": ["child"],
            "description": "显露原已在场的小明", "changes": [], "source_fact_ids": [_fid(1)], "creative_addition_id": ""})
        assert _check(source, library, raw)["validation"]["explicit_state_chain_checked"]
    else:
        with pytest.raises(ValueError, match="new_character_requires_entry"):
            _check(source, library, raw)


def test_nonactual_intermediate_state_cannot_be_hidden_by_later_replacement():
    source, library, raw = episode_fixture(); raws = _raws(library)
    planned = deepcopy(raws[0]["facts"][2]); planned.update(id=_fid(6), modality="plan")
    raws[0]["facts"].append(planned); raws[0]["coverage"][2]["fact_ids"].append(_fid(6))
    library = _catalog(source, raws)
    intermediate = deepcopy(raw["states"][-1]); intermediate.update(id="temporary", source_fact_refs=[_ref(library, 6)])
    raw["states"].append(intermediate)
    raw["beats"][0]["actions"][0]["changes"] = [{"from_state_id": "key_child", "to_state_id": "temporary"},
        {"from_state_id": "temporary", "to_state_id": "key_adult"}]
    with pytest.raises(ValueError, match="noncurrent_fact_used_as_state"):
        _check(source, library, raw)


def test_unchanged_state_is_not_a_transfer():
    source, library, raw = episode_fixture(); raw["states"][-1]["value"] = "child"
    with pytest.raises(ValueError, match="state_value_unchanged"):
        _check(source, library, raw)


def test_later_episode_receives_complete_used_earlier_chapters_only():
    source, library, raw = episode_fixture(); raw["selected_chapter_indices"] = [2]
    raw["states"] = [s for s in raw["states"] if s["id"] != "key_child"]
    raw["snapshots"] = [{"id": "opening", "anchor": {"fact_id": _fid(1, 2), "edge": "after"}, "state_ids": [s["id"] for s in raw["states"]]}]
    raw["ending_snapshot_id"] = "opening"; raw["beats"][0].update(after_snapshot_id="opening", actions=[])
    accepted = _check(source, library, raw)
    context = episode.build_episode_context(accepted, library, source)
    assert context["selected_original_chapters"] == library["chapters"][1:2]
    assert context["required_evidence_chapters"] == library["chapters"][:1]
    assert accepted["validation"]["past_state_persistence_semantically_verified"] is False


def test_binding_original_source_and_requested_range_cannot_change():
    source, library, accepted = valid_fixture(); altered = deepcopy(accepted)
    altered["snapshot"]["beats"][0]["purpose"] = "changed"
    with pytest.raises(ValueError, match="binding_changed"):
        episode.build_episode_context(altered, library, source)
    with pytest.raises(ValueError, match="schema_invalid"):
        episode.validate_episode(accepted["snapshot"], library, source, [1], 11)
    with pytest.raises(ValueError, match="selection_invalid"):
        episode.episode_payload(library, source, [1, 3], 10)
    source[0]["text"] += "新增"
    with pytest.raises(ValueError): episode.build_episode_context(accepted, library, source)


def letter_fixture():
    """A new story isolates first discovery; material stage contains no state fields."""
    text = "阿禾在厨房，信放在厨房的柜子里。\n阿禾不知道柜子里有信。\n阿禾打开柜子，第一次发现了信。\n"
    source = [{"index": 1, "title": "第一次发现信", "text": text,
               "sha256": hashlib.sha256(text.encode()).hexdigest()}]
    plan = facts.plan_chapters(source)[0]
    parts = facts.chapters_v4.chapter_passages(source[0])
    entries = [(1, "阿禾在厨房"), (1, "信放在厨房的柜子里。"),
               (2, "阿禾不知道柜子里有信。"), (3, "阿禾打开柜子，第一次发现了信。")]
    model_raw = {"chapter_id": plan["id"], "chapter_index": 1, "facts": [], "coverage": []}
    for number, (paragraph, quote) in enumerate(entries, 1):
        pid = parts[paragraph - 1]["id"]
        model_raw["facts"].append({"id": _fid(number), "categories": ["event"],
            "statement": quote, "modality": "actual", "event_time": "chapter_present",
            "narrative_anchor_passage_id": pid,
            "source_refs": [{"paragraph_id": pid, "exact_quote": quote}]})
    for paragraph, part in enumerate(parts, 1):
        model_raw["coverage"].append({"paragraph_id": part["id"],
            "fact_ids": [_fid(i) for i, (p, _) in enumerate(entries, 1) if p == paragraph],
            "no_fact_reason": ""})
    library = _catalog(source, [model_raw])
    def state(identifier, kind, subject, value, number, obj=""):
        return {"id": identifier, "kind": kind, "subject_id": subject, "object_id": obj,
            "value": value, "source_fact_refs": [_ref(library, number)], "creative_addition_id": ""}
    states = [state("child_room", "location", "child", "room", 1),
              state("letter_room", "possession", "letter", "room", 2),
              state("letter_unknown", "knowledge", "child", "unknown", 3, _fid(2)),
              state("letter_known", "knowledge", "child", "known", 4, _fid(2))]
    entities = [{"id": eid, "kind": kind, "name": name, "identity_fact_ids": [_fid(number)],
                 "identity_source_refs": [_ref(library, number)]}
                for eid, kind, name, number in [("child", "person", "阿禾", 1),
                    ("letter", "object", "信", 2), ("room", "place", "厨房", 1)]]
    raw = {"selected_chapter_indices": [1], "target_seconds": 10,
        "entities": entities, "creative_additions": [], "prop_introductions": [],
        "world_fact_ids": [], "background_fact_ids": [],
        "states": states,
        "snapshots": [
            {"id": "opening", "anchor": {"fact_id": _fid(3), "edge": "after"},
             "state_ids": ["child_room", "letter_room", "letter_unknown"]},
            {"id": "ending", "anchor": {"fact_id": _fid(4), "edge": "after"},
             "state_ids": ["child_room", "letter_room", "letter_known"]}],
        "opening_snapshot_id": "opening", "ending_snapshot_id": "ending",
        "beats": [{"id": "scene_1", "location_id": "room", "before_snapshot_id": "opening",
            "after_snapshot_id": "ending", "cast_ids": ["child"],
            "actions": [{"id": "discover_letter", "kind": "learn", "actor_ids": ["child"],
                "description": "阿禾打开柜子，第一次发现了信。",
                "changes": [{"from_state_id": "letter_unknown", "to_state_id": "letter_known"}],
                "source_fact_ids": [_fid(4)], "creative_addition_id": ""}],
            "purpose": "发现此前未知的信件", "dialogue_goal": "明确由未知到获知", "duration_seconds": 10}],
        "limitations": ["柜内位置属于厨房内，细部摆位及首次发现的知情含义需独立语义核对。"]}
    return source, library, raw


def test_first_letter_discovery_is_refined_here_into_unknown_to_known():
    source, library, raw = letter_fixture()
    assert all("state_changes" not in f for f in library["facts"])
    accepted = _check(source, library, raw)
    assert accepted["snapshot"]["states"][-1]["value"] == "known"
    context = episode.build_episode_context(accepted, library, source)
    assert context["selected_original_chapters"] == library["chapters"]


def test_first_letter_discovery_without_learn_is_rejected():
    source, library, raw = letter_fixture()
    raw["beats"][0]["actions"] = []
    with pytest.raises(ValueError, match="unexplained_state_change"):
        _check(source, library, raw)


def test_first_letter_discovery_cannot_move_to_opening_or_use_future_plan():
    source, library, raw = letter_fixture()
    early = deepcopy(raw); early["snapshots"][0]["state_ids"][-1] = "letter_known"
    with pytest.raises(ValueError, match="fact_occurs_after_snapshot"):
        _check(source, library, early)
    originals = _raws(library)
    originals[0]["facts"][-1].update(modality="plan", event_time="later")
    with pytest.raises(ValueError, match="anchor_not_current_selected_event"):
        _check(source, _catalog(source, originals), raw)


def _same_paragraph_fixture(broad_quotes=False):
    source, library, raw = episode_fixture(); raws = _raws(library)
    lines = source[0]["text"].splitlines()
    source[0]["text"] = "".join(lines[:3]) + "\n" + "\n".join(lines[3:]) + "\n"
    source[0]["sha256"] = hashlib.sha256(source[0]["text"].encode()).hexdigest()
    mapping = {"CH1-P001": "CH1-P001", "CH1-P002": "CH1-P001", "CH1-P003": "CH1-P001",
               "CH1-P004": "CH1-P002", "CH1-P005": "CH1-P003"}
    for f in raws[0]["facts"]:
        f["narrative_anchor_passage_id"] = mapping[f["narrative_anchor_passage_id"]]
        for ref in f["source_refs"]: ref["paragraph_id"] = mapping[ref["paragraph_id"]]
    if broad_quotes:
        for index in (0, 2): raws[0]["facts"][index]["source_refs"][0]["exact_quote"] = "".join(lines[:3])
    raws[0]["coverage"] = [{"paragraph_id": pid,
        "fact_ids": [f["id"] for f in raws[0]["facts"] if f["narrative_anchor_passage_id"] == pid],
        "no_fact_reason": ""} for pid in ("CH1-P001", "CH1-P002", "CH1-P003")]
    for row in raw["states"]:
        for ref in row["source_fact_refs"]: ref["paragraph_id"] = mapping[ref["paragraph_id"]]
    library = _catalog(source, raws)
    return source, library, raw


def test_exact_evidence_orders_multiple_events_in_one_natural_paragraph():
    source, library, raw = _same_paragraph_fixture()
    assert _check(source, library, raw)["validation"]["event_time_bound_to_exact_anchor_quotes"]
    raw["snapshots"][0]["state_ids"][2] = "key_adult"
    raw["states"] = [s for s in raw["states"] if s["id"] != "key_child"]
    raw["beats"][0]["actions"] = []
    with pytest.raises(ValueError, match="fact_occurs_after_snapshot"):
        _check(source, library, raw)


def test_same_broad_quote_cannot_be_claimed_as_semantically_resolved_event_order():
    source, library, raw = _same_paragraph_fixture(broad_quotes=True)
    raw["snapshots"][0]["state_ids"][2] = "key_adult"
    raw["states"] = [s for s in raw["states"] if s["id"] != "key_child"]
    raw["beats"][0]["actions"] = []
    accepted = _check(source, library, raw)
    assert accepted["validation"]["semantic_review_required"]
    assert accepted["validation"]["shared_quote_event_order_semantically_verified"] is False


def test_nonfinite_beat_duration_cannot_bypass_total_seconds_check():
    source, library, raw = episode_fixture(); raw["beats"][0]["duration_seconds"] = float("nan")
    with pytest.raises(ValueError, match="duration_not_finite"):
        _check(source, library, raw)


def test_overlapping_quote_occurrences_are_ambiguous():
    source, library, raw = episode_fixture(); raws = _raws(library)
    source[0]["text"] += "aaaa\n"
    source[0]["sha256"] = hashlib.sha256(source[0]["text"].encode()).hexdigest()
    raws[0]["facts"].append({"id": _fid(6), "categories": ["world"], "statement": "aaaa",
        "modality": "actual", "event_time": "timeless", "narrative_anchor_passage_id": "CH1-P006",
        "source_refs": [{"paragraph_id": "CH1-P006", "exact_quote": "aaaa"}]})
    raws[0]["coverage"].append({"paragraph_id": "CH1-P006", "fact_ids": [_fid(6)], "no_fact_reason": ""})
    library = _catalog(source, raws)
    raw["entities"].append({"id": "overlap", "kind": "place", "name": "aaa",
        "identity_fact_ids": [_fid(6)], "identity_source_refs": [
            {"fact_id": _fid(6), "paragraph_id": "CH1-P006", "exact_quote": "aaa"}]})
    with pytest.raises(ValueError, match="source_quote_ambiguous"):
        _check(source, library, raw)


def later_prop_fixture():
    """The source first mentions the key at handover, with no opening owner evidence."""
    source, library, raw = episode_fixture(); originals = _raws(library)
    removed = "钥匙原来由小明拿着。"
    source[0]["text"] = source[0]["text"].replace(removed, "")
    source[0]["sha256"] = hashlib.sha256(source[0]["text"].encode()).hexdigest()
    for fact in originals[0]["facts"]:
        fact["statement"] = fact["statement"].replace(removed, "")
        for ref in fact["source_refs"]: ref["exact_quote"] = ref["exact_quote"].replace(removed, "")
    library = _catalog(source, originals)
    for entity in raw["entities"]:
        for ref in entity["identity_source_refs"]: ref["exact_quote"] = ref["exact_quote"].replace(removed, "")
        if entity["id"] == "key":
            entity.update(identity_fact_ids=[_fid(3)], identity_source_refs=[_ref(library, 3)])
    raw["states"] = [s for s in raw["states"] if s["id"] != "key_child"]
    for state in raw["states"]:
        for ref in state["source_fact_refs"]: ref["exact_quote"] = ref["exact_quote"].replace(removed, "")
    raw["snapshots"][0]["state_ids"].remove("key_child")
    raw["beats"][0]["actions"][0]["changes"][0]["from_state_id"] = ""
    raw["prop_introductions"] = [{"object_id": "key", "beat_id": "scene_1", "action_id": "handover"}]
    return source, library, raw


def test_later_prop_can_enter_from_a_real_transfer_without_fabricated_opening_owner():
    source, library, raw = later_prop_fixture()
    accepted = _check(source, library, raw)
    assert "key_child" not in accepted["snapshot"]["snapshots"][0]["state_ids"]
    assert accepted["snapshot"]["prop_introductions"][0]["object_id"] == "key"
    assert "key_adult" in accepted["snapshot"]["snapshots"][-1]["state_ids"]


@pytest.mark.parametrize("mutation,reason", [
    (lambda raw: raw.update(prop_introductions=[]), "opening_prop_holder_missing"),
    (lambda raw: raw["prop_introductions"][0].update(action_id="wrong"), "prop_state_before_introduction"),
    (lambda raw: raw["prop_introductions"][0].update(beat_id="wrong"), "prop_state_before_introduction"),
    (lambda raw: raw["beats"][0]["actions"][0].update(kind="perform"), "prop_state_before_introduction"),
    (lambda raw: raw["beats"][0].update(actions=[]), "unexplained_state_change"),
    (lambda raw: raw["states"][-1].update(source_fact_refs=[]), "state_unanchored"),
    (lambda raw: raw["snapshots"][0]["state_ids"].append("key_adult"), "fact_occurs_after_snapshot"),
])
def test_later_prop_requires_exact_declared_source_action_and_no_early_state(mutation, reason):
    source, library, raw = later_prop_fixture(); mutation(raw)
    with pytest.raises(ValueError, match=reason): _check(source, library, raw)


def test_existing_opening_prop_cannot_be_reclassified_as_later_introduction():
    source, library, raw = episode_fixture()
    raw["prop_introductions"] = [{"object_id": "key", "beat_id": "scene_1", "action_id": "handover"}]
    with pytest.raises(ValueError, match="prop_introduction_already_at_opening"):
        _check(source, library, raw)


def test_later_prop_introduction_is_unique_and_cannot_be_creatively_invented():
    source, library, raw = later_prop_fixture(); duplicate = deepcopy(raw)
    duplicate["prop_introductions"].append({"object_id": "key", "beat_id": "scene_1", "action_id": "other"})
    with pytest.raises(ValueError, match="prop_introduction_duplicate"):
        _check(source, library, duplicate)
    raw["creative_additions"] = [{"id": "art", "kind": "performance", "description": "变出钥匙", "entity_ids": ["child", "adult"]}]
    raw["beats"][0]["actions"][0]["creative_addition_id"] = "art"
    with pytest.raises(ValueError, match="prop_introduction_requires_original_source"):
        _check(source, library, raw)


def test_later_prop_source_must_occur_within_introducing_beat():
    source, library, raw = later_prop_fixture()
    raw["states"][-1]["source_fact_refs"] = [_ref(library, 1)]
    raw["beats"][0]["actions"][0]["source_fact_ids"] = [_fid(1)]
    with pytest.raises(ValueError, match="prop_introduction_source_outside_beat"):
        _check(source, library, raw)


def test_later_prop_cannot_have_condition_state_before_its_introduction():
    source, library, raw = later_prop_fixture()
    raw["states"].append({"id": "key_condition", "kind": "condition", "subject_id": "key",
        "object_id": "", "value": "表面反光", "source_fact_refs": [], "creative_addition_id": "art"})
    raw["creative_additions"] = [{"id": "art", "kind": "performance", "description": "反光", "entity_ids": ["key"]}]
    raw["snapshots"][0]["state_ids"].append("key_condition")
    with pytest.raises(ValueError, match="prop_state_before_introduction"):
        _check(source, library, raw)


def _two_same_named_people_fixture():
    text = "东边的林青在客厅，西边的林青也在客厅。"
    source = [{"index": 1, "title": "同名不同人", "text": text,
               "sha256": hashlib.sha256(text.encode()).hexdigest()}]
    plan = facts.plan_chapters(source)[0]
    material = {"chapter_id": plan["id"], "chapter_index": 1, "facts": [],
                "coverage": [{"paragraph_id": "CH1-P001", "fact_ids": [_fid(1), _fid(2)], "no_fact_reason": ""}]}
    for number, quote in enumerate(["东边的林青在客厅", "西边的林青也在客厅"], 1):
        material["facts"].append({"id": _fid(number), "categories": ["character", "location"],
            "statement": quote, "modality": "actual", "event_time": "chapter_present",
            "narrative_anchor_passage_id": "CH1-P001",
            "source_refs": [{"paragraph_id": "CH1-P001", "exact_quote": quote}]})
    library = _catalog(source, [material])
    raw = {"selected_chapter_indices": [1], "target_seconds": 5,
        "entities": [{"id": eid, "kind": kind, "name": name, "identity_fact_ids": [_fid(number)],
            "identity_source_refs": [_ref(library, number)]} for eid, kind, name, number in
            [("east", "person", "林青", 1), ("west", "person", "林青", 2), ("room", "place", "客厅", 1)]],
        "creative_additions": [], "prop_introductions": [], "world_fact_ids": [], "background_fact_ids": [],
        "states": [{"id": eid + "_room", "kind": "location", "subject_id": eid, "object_id": "",
            "value": "room", "source_fact_refs": [_ref(library, number)], "creative_addition_id": ""}
            for eid, number in [("east", 1), ("west", 2)]],
        "snapshots": [{"id": "opening", "anchor": {"fact_id": _fid(2), "edge": "after"},
            "state_ids": ["east_room", "west_room"]}],
        "opening_snapshot_id": "opening", "ending_snapshot_id": "opening",
        "beats": [{"id": "scene_1", "location_id": "room", "before_snapshot_id": "opening",
            "after_snapshot_id": "opening", "cast_ids": ["east", "west"], "actions": [],
            "purpose": "交代两个同名人物", "dialogue_goal": "分别识别", "duration_seconds": 5}],
        "limitations": ["不同原文出现位置不自动证明身份相异，同名身份仍须语义审查。"]}
    return source, library, raw


def test_two_same_names_in_same_paragraph_can_bind_distinct_original_mentions():
    source, library, raw = _two_same_named_people_fixture()
    accepted = _check(source, library, raw)
    assert accepted["validation"]["identity_merges_semantically_verified"] is False
    assert accepted["binding"]["identity_evidence"]["east"][0]["start_offset"] != accepted["binding"]["identity_evidence"]["west"][0]["start_offset"]


def test_one_original_name_mention_cannot_be_assigned_to_two_actors():
    source, library, raw = _two_same_named_people_fixture()
    raw["entities"][1].update(identity_fact_ids=[_fid(1)], identity_source_refs=[_ref(library, 1)])
    with pytest.raises(ValueError, match="source_identity_bound_twice"):
        _check(source, library, raw)
