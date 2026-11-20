"""Offline contracts. Synthetic quotations are not real novel acceptance."""
from copy import deepcopy
import hashlib

import pytest

from src.content_factory import corpus_chapter_facts_v5 as facts
from src.content_factory import corpus_episode_state_v5 as episode


def _eid(number, chapter=1):
    return f"CH{chapter}-E{number:03d}"


def _fid(number, chapter=1):
    return f"CH{chapter}-F{number:03d}"


def _catalog(source, raws):
    plans = facts.plan_chapters(source)
    accepted = [facts.validate(raw, source, plan) for raw, plan in zip(raws, plans)]
    return facts.facts_catalog(accepted, source, plans, "隔离状态样本")


def _raws(library):
    return [facts.raw_candidate(row) for row in library["analyses"]]


def episode_fixture():
    """Return (complete chapters, verified candidate library, raw valid plan)."""
    texts = [
        "林青和小明在客厅，门外是走廊。钥匙原来由小明拿着。\n"
        "林青是小明的继母。\n小明把钥匙交给林青。\n"
        "小明想起去年把钥匙交给老师。\n林青告诉小明自己是他的继母。\n",
        "第二天，林青和小明在客厅。\n",
        "第三天，林青带小明去了学校。\n",
    ]
    source = [{"index": i, "title": f"第{i}章", "text": text,
               "sha256": hashlib.sha256(text.encode()).hexdigest()}
              for i, text in enumerate(texts, 1)]
    raws = []
    for plan in facts.plan_chapters(source):
        payload = facts.chapter_payload(source, plan)
        raws.append({"chapter_id": plan["id"], "chapter_index": plan["chapter_index"],
                     "entities": [], "facts": [],
                     "coverage": [{"paragraph_id": p["id"], "fact_ids": [],
                                   "no_fact_reason": "隔离无事实占位，不是质量验收。"}
                                  for p in payload["paragraph_index"]]})
    parts = facts.chapters_v4.chapter_passages(source[0])
    def refs(number):
        return [{"paragraph_id": parts[number - 1]["id"],
                 "exact_quote": parts[number - 1]["text"].strip()}]
    names = [("林青", "person", 1), ("小明", "person", 1), ("钥匙", "object", 1),
             ("客厅", "place", 1), ("走廊", "place", 1), ("老师", "person", 4)]
    raws[0]["entities"] = [{"id": _eid(i), "name": name, "kind": kind,
                            "source_refs": refs(paragraph)}
                           for i, (name, kind, paragraph) in enumerate(names, 1)]
    def change(kind, subject, obj, after, paragraph, before=""):
        return {"kind": kind, "subject_id": _eid(subject), "object_id": _eid(obj) if obj else "",
                "predicate": kind, "before_value": before, "after_value": after,
                "change_type": "transition" if before else "assertion", "source_refs": refs(paragraph)}
    changes = [
        [change("location", 1, 4, "客厅", 1), change("location", 2, 4, "客厅", 1),
         change("possession", 2, 3, "小明", 1)],
        [change("relation", 1, 2, "继母", 2)],
        [change("possession", 1, 3, "林青", 3, "小明")],
        [change("possession", 6, 3, "老师", 4, "小明")],
        [change("knowledge", 2, 1, "知道林青是继母", 5, "不知道林青是继母")],
    ]
    for i, (entity_numbers, modality, time) in enumerate([
        ([1, 2, 3, 4, 5], "actual", "chapter_present"),
        ([1, 2], "actual", "timeless"), ([1, 2, 3], "actual", "chapter_present"),
        ([2, 3, 6], "memory", "earlier"), ([1, 2], "actual", "chapter_present")], 1):
        raws[0]["facts"].append({"id": _fid(i), "categories": ["event" if i != 2 else "character"],
                                  "statement": parts[i - 1]["text"].strip(),
                                  "entity_ids": [_eid(n) for n in entity_numbers], "modality": modality,
                                  "event_time": time, "narrative_anchor_passage_id": parts[i - 1]["id"],
                                  "source_refs": refs(i), "state_changes": changes[i - 1]})
        raws[0]["coverage"][i - 1].update(fact_ids=[_fid(i)], no_fact_reason="")
    # One actual anchor in each later chapter makes temporal exclusion testable.
    for chapter in (2, 3):
        part = facts.chapters_v4.chapter_passages(source[chapter - 1])[0]
        ref = [{"paragraph_id": part["id"], "exact_quote": part["text"].strip()}]
        raws[chapter - 1]["entities"] = [{"id": _eid(1, chapter), "kind": "person",
                                         "name": "林青", "source_refs": ref}]
        raws[chapter - 1]["facts"] = [{"id": _fid(1, chapter), "categories": ["event"],
                                      "statement": part["text"].strip(), "entity_ids": [_eid(1, chapter)],
                                      "modality": "actual", "event_time": "chapter_present",
                                      "narrative_anchor_passage_id": part["id"],
                                      "source_refs": ref, "state_changes": []}]
        raws[chapter - 1]["coverage"][0].update(fact_ids=[_fid(1, chapter)], no_fact_reason="")
    library = _catalog(source, raws)
    def state(identifier, kind, subject, value, fact_number, change_index=0, obj=""):
        return {"id": identifier, "kind": kind, "subject_id": subject, "object_id": obj,
                "value": value, "source_state_refs": [{"fact_id": _fid(fact_number),
                                                          "change_index": change_index}],
                "creative_addition_id": ""}
    canonical = ["adult", "child", "key", "room", "hall"]
    initial = ["adult_room", "child_room", "key_child", "relation"]
    final = ["adult_room", "child_room", "key_adult", "relation"]
    raw = {"selected_chapter_indices": [1], "target_seconds": 10,
           "entities": [{"id": cid, "name": names[i - 1][0], "kind": names[i - 1][1],
                         "source_entity_ids": [_eid(i)], "identity_fact_ids": [_fid(1)]}
                        for i, cid in enumerate(canonical, 1)],
           "creative_additions": [], "world_fact_ids": [], "background_fact_ids": [_fid(4)],
           "states": [state("adult_room", "location", "adult", "room", 1),
                      state("child_room", "location", "child", "room", 1, 1),
                      state("key_child", "possession", "key", "child", 1, 2),
                      state("relation", "relation", "adult", "继母", 2, obj="child"),
                      state("key_adult", "possession", "key", "adult", 3)],
           "snapshots": [{"id": "opening", "anchor": {"fact_id": _fid(1), "edge": "after"}, "state_ids": initial},
                         {"id": "ending", "anchor": {"fact_id": _fid(3), "edge": "after"}, "state_ids": final}],
           "opening_snapshot_id": "opening", "ending_snapshot_id": "ending",
           "beats": [{"id": "scene_1", "location_id": "room", "before_snapshot_id": "opening",
                      "after_snapshot_id": "ending", "cast_ids": ["adult", "child"],
                      "actions": [{"id": "handover", "kind": "transfer", "actor_ids": ["child", "adult"],
                                   "description": "小明把钥匙交给林青。",
                                   "changes": [{"from_state_id": "key_child", "to_state_id": "key_adult"}],
                                   "source_fact_ids": [_fid(3)], "creative_addition_id": ""}],
                      "purpose": "交代道具转移", "dialogue_goal": "确认交接", "duration_seconds": 10}],
           "limitations": ["结构和证据绑定不证明语义，需独立审查。"]}
    return source, library, raw


def valid_fixture():
    source, library, raw = episode_fixture()
    return source, library, episode.validate_episode(raw, library, source, [1], 10)


def _check(source, library, raw):
    return episode.validate_episode(raw, library, source, raw["selected_chapter_indices"], raw["target_seconds"])


def test_complete_episode_and_writer_context_keep_only_required_original_chapters():
    source, library, validated = valid_fixture()
    context = episode.build_episode_context(validated, library, source)
    assert context["selected_original_chapters"] == library["chapters"][:1]
    assert context["required_evidence_chapters"] == []
    assert context["episode_brief"]["chapter_indices"] == [1]
    assert context["episode_state_plan"] == validated["snapshot"]
    assert _eid(6) in {e["id"] for e in context["episode_source_entities"]}  # Historical teacher is defined.
    assert "global_bible" not in context and "mainline" not in context
    assert all(f["chapter_index"] == 1 for f in context["episode_source_facts"])
    assert context["state_validation"]["semantic_review_required"] is True


def test_future_chapter_candidates_and_complete_text_are_excluded():
    source, library, _ = episode_fixture()
    payload = episode.episode_payload(library, source, [1], 10)
    assert all(f["chapter_index"] == 1 for f in payload["candidate_facts"])
    assert all(e["chapter_index"] == 1 for e in payload["candidate_entities"])
    assert [c["index"] for c in payload["selected_original_chapters"]] == [1]


def test_entity_derived_only_from_future_neighbor_is_not_available():
    source, library, raw = episode_fixture()
    raws = _raws(library)
    raws[0]["entities"][3]["source_refs"] = [{"paragraph_id": "CH2-P001", "exact_quote": "客厅"}]
    library = _catalog(source, raws)
    payload = episode.episode_payload(library, source, [1], 10)
    assert _eid(4) not in {e["id"] for e in payload["candidate_entities"]}
    assert _fid(1) not in {f["id"] for f in payload["candidate_facts"]}
    with pytest.raises(ValueError, match="schema_invalid"):
        _check(source, library, raw)


@pytest.mark.parametrize("modality,time", [(m, "chapter_present") for m in
                         ("memory", "plan", "belief", "hypothetical", "quoted_story", "uncertain")]
                         + [("actual", t) for t in ("earlier", "later", "unspecified")])
def test_noncurrent_fact_cannot_update_current_state(modality, time):
    source, library, raw = episode_fixture()
    raws = _raws(library)
    raws[0]["facts"][1].update(modality=modality, event_time=time)
    with pytest.raises(ValueError, match="noncurrent_fact_used_as_state"):
        _check(source, _catalog(source, raws), raw)


def test_opening_cannot_use_end_of_same_chapter_transfer():
    source, library, raw = episode_fixture()
    raw["snapshots"][0]["state_ids"][2] = "key_adult"
    with pytest.raises(ValueError, match="fact_occurs_after_snapshot"):
        _check(source, library, raw)


@pytest.mark.parametrize("reverse", [False, True])
def test_possession_direction_is_resolved_by_explicit_entity_types(reverse):
    source, library, raw = episode_fixture()
    if reverse:
        raws = _raws(library)
        for f in raws[0]["facts"]:
            for change in f["state_changes"]:
                if change["kind"] == "possession":
                    change["subject_id"], change["object_id"] = change["object_id"], change["subject_id"]
        library = _catalog(source, raws)
    assert _check(source, library, raw)["validation"]["explicit_state_chain_checked"]


@pytest.mark.parametrize("mutation", [
    lambda raw: raw["states"][-1].update(source_state_refs=[]),
    lambda raw: raw["beats"][0]["actions"][0].update(source_fact_ids=[]),
    lambda raw: raw["beats"][0]["actions"][0].update(source_fact_ids=[_fid(1)]),
])
def test_transfer_requires_target_evidence_and_matching_action_fact(mutation):
    source, library, raw = episode_fixture()
    mutation(raw)
    with pytest.raises(ValueError, match="transfer_or_learn_requires_bound_source_action"):
        _check(source, library, raw)


def _learning(raw):
    raw["target_seconds"] = 15
    raw["states"].append({"id": "child_knows", "kind": "knowledge", "subject_id": "child",
                          "object_id": _fid(2), "value": "known",
                          "source_state_refs": [{"fact_id": _fid(5), "change_index": 0}],
                          "creative_addition_id": ""})
    raw["snapshots"].append({"id": "known", "anchor": {"fact_id": _fid(5), "edge": "after"},
                             "state_ids": raw["snapshots"][-1]["state_ids"] + ["child_knows"]})
    raw["beats"].append({"id": "scene_2", "location_id": "room", "before_snapshot_id": "ending",
                          "after_snapshot_id": "known", "cast_ids": ["adult", "child"],
                          "actions": [{"id": "learn_relation", "kind": "learn", "actor_ids": ["adult", "child"],
                                       "description": "林青告知小明。", "changes": [{"from_state_id": "", "to_state_id": "child_knows"}],
                                       "source_fact_ids": [_fid(5)], "creative_addition_id": ""}],
                          "purpose": "明确获知", "dialogue_goal": "传递关系信息", "duration_seconds": 5})
    raw["ending_snapshot_id"] = "known"


def test_learning_with_source_action_is_supported():
    source, library, raw = episode_fixture()
    _learning(raw)
    assert _check(source, library, raw)["snapshot"]["ending_snapshot_id"] == "known"


@pytest.mark.parametrize("missing", ["state", "action"])
def test_knowledge_cannot_be_created_by_an_unproven_action(missing):
    source, library, raw = episode_fixture()
    _learning(raw)
    if missing == "state":
        raw["states"][-1]["source_state_refs"] = []
    else:
        raw["beats"][-1]["actions"][0]["source_fact_ids"] = []
    with pytest.raises(ValueError, match="transfer_or_learn_requires_bound_source_action"):
        _check(source, library, raw)


@pytest.mark.parametrize("mutation,reason", [
    (lambda r: r["beats"][0].update(actions=[]), "unexplained_state_change"),
    (lambda r: r["beats"][0]["actions"][0].update(kind="perform"), "action_kind_state_mismatch"),
    (lambda r: r["beats"][0]["actions"][0].update(actor_ids=["child"]), "transfer_holder_not_acting"),
    (lambda r: r["beats"][0]["actions"][0]["changes"][0].update(from_state_id=""), "cannot_overwrite"),
    (lambda r: r["entities"][1].update(source_entity_ids=[_eid(1)]), "source_entity_bound_twice"),
    (lambda r: r["states"][0].update(subject_id="key"), "entity_type_or_reference"),
    (lambda r: r["beats"][0].update(duration_seconds=11), "duration_exceeds_target"),
])
def test_explicit_state_and_identity_errors_are_blocked(mutation, reason):
    source, library, raw = episode_fixture()
    mutation(raw)
    with pytest.raises(ValueError, match=reason):
        _check(source, library, raw)


def test_creative_prop_ownership_is_not_allowed():
    source, library, raw = episode_fixture()
    raw["creative_additions"].append({"id": "art", "kind": "blocking", "description": "自创交接", "entity_ids": ["key"]})
    raw["states"][2].update(source_state_refs=[], creative_addition_id="art")
    with pytest.raises(ValueError, match="creative_state_not_allowed"):
        _check(source, library, raw)


@pytest.mark.parametrize("entry", [False, True])
def test_new_on_screen_character_has_an_explicit_entry_action(entry):
    source, library, raw = episode_fixture()
    raw["target_seconds"] = 12
    establishing = deepcopy(raw["beats"][0])
    establishing.update(id="establish", after_snapshot_id="opening", cast_ids=["adult"],
                        actions=[], purpose="先呈现林青", duration_seconds=2)
    raw["beats"].insert(0, establishing)
    if entry:
        raw["beats"][1]["actions"].insert(0, {"id": "child_entry", "kind": "entry", "actor_ids": ["child"],
                                             "description": "镜头显出本来在客厅的小明。", "changes": [],
                                             "source_fact_ids": [_fid(1)], "creative_addition_id": ""})
        assert _check(source, library, raw)["validation"]["explicit_state_chain_checked"]
    else:
        with pytest.raises(ValueError, match="new_character_requires_entry"):
            _check(source, library, raw)


def test_declared_blocking_is_allowed_without_claiming_source_semantics():
    source, library, raw = episode_fixture()
    raw["creative_additions"].append({"id": "blocking", "kind": "blocking",
                                       "description": "客厅内补足林青的站位。", "entity_ids": ["adult"]})
    raw["states"][0].update(source_state_refs=[], creative_addition_id="blocking")
    accepted = _check(source, library, raw)
    assert accepted["validation"]["script_actions_semantically_verified"] is False


def test_nonactual_intermediate_state_is_blocked_even_when_replaced_before_scene_end():
    source, library, raw = episode_fixture()
    raws = _raws(library)
    planned = deepcopy(raws[0]["facts"][2])
    planned.update(id=_fid(6), modality="plan")
    raws[0]["facts"].append(planned)
    raws[0]["coverage"][2]["fact_ids"].append(_fid(6))
    intermediate = deepcopy(raw["states"][-1])
    intermediate.update(id="key_temporary", source_state_refs=[{"fact_id": _fid(6), "change_index": 0}])
    raw["states"].append(intermediate)
    action = raw["beats"][0]["actions"][0]
    action["changes"] = [{"from_state_id": "key_child", "to_state_id": "key_temporary"},
                         {"from_state_id": "key_temporary", "to_state_id": "key_adult"}]
    with pytest.raises(ValueError, match="noncurrent_fact_used_as_state"):
        _check(source, _catalog(source, raws), raw)


def test_later_selected_episode_retains_complete_earlier_evidence_without_future_text():
    source, library, raw = episode_fixture()
    raw["selected_chapter_indices"] = [2]
    raw["states"] = [s for s in raw["states"] if s["id"] != "key_child"]
    raw["snapshots"] = [{"id": "opening", "anchor": {"fact_id": _fid(1, 2), "edge": "after"},
                          "state_ids": [s["id"] for s in raw["states"]]}]
    raw["ending_snapshot_id"] = "opening"
    raw["beats"][0].update(after_snapshot_id="opening", actions=[])
    validated = _check(source, library, raw)
    context = episode.build_episode_context(validated, library, source)
    assert [c["index"] for c in context["selected_original_chapters"]] == [2]
    assert context["required_evidence_chapters"] == library["chapters"][:1]
    assert context["state_validation"]["past_state_persistence_semantically_verified"] is False


def test_validation_binding_is_frozen_and_original_text_cannot_change():
    source, library, validated = valid_fixture()
    changed = deepcopy(validated)
    changed["snapshot"]["beats"][0]["purpose"] = "篡改"
    with pytest.raises(ValueError, match="binding_changed"):
        episode.build_episode_context(changed, library, source)
    source[0]["text"] += "新增正文"
    with pytest.raises(ValueError):
        episode.build_episode_context(validated, library, source)


def test_fixed_target_and_selection_are_not_model_overrides():
    source, library, raw = episode_fixture()
    with pytest.raises(ValueError, match="schema_invalid"):
        episode.validate_episode(raw, library, source, [1], 11)
    with pytest.raises(ValueError, match="selection_invalid"):
        episode.episode_payload(library, source, [1, 3], 10)
