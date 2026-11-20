"""Evidence-bound episode state plans; no model, filesystem or provider calls.

The checks below validate declared identities, source boundaries and explicit
state transitions. They do not establish that a quotation entails a fact or
that two chapter-local names denote the same person; independent review remains
mandatory. Narrative position and the source's event-time label stay separate.
"""
from copy import deepcopy
import math

from jsonschema import Draft202012Validator

from . import corpus_chapter_materials_v6 as facts_api
from . import corpus_chapters_v4 as chapters_api


VERSION = "corpus_episode_state/v6"
KINDS = ("location", "possession", "knowledge", "relation", "condition")
ACTION_KINDS = ("entry", "exit", "move", "transfer", "learn", "perform")
ART_KINDS = ("appearance", "lighting", "set_dressing", "blocking", "performance")

EPISODE_PROMPT = """你是 MiniMax 本集状态与场景设计师。完整阅读选定原章和材料事实，只细化本集实际需要的人物、地点、道具和状态，不能把后续章剧情提前。材料阶段只有原文事实，没有预制实体或状态；请在本阶段按原文整理，不能把材料数量或字段合法当成语义已审核。
entities 为本集规范实体，逐项列 identity_fact_ids 和 identity_source_refs；身份引用每条是 fact_id、paragraph_id、exact_quote，必须来自该事实已经绑定的原文，规范名称至少在身份原文中出现。跨章身份合并、实体类型与人物关系仍需独立内容审核。不要把同一源身份分成多个演员。
states 每条列 source_fact_refs（同样的 fact_id、paragraph_id、exact_quote），直接引用事实原文，不使用前置 state_changes 或 change_index。location 的 subject_id 是人物，value 是地点实体ID；possession 的 subject_id 是物品，value 是持有人或存放地点ID；knowledge 的 subject_id 是人物、object_id 是所知事实ID、value 为 known/unknown；relation 的 subject/object 为实体，value 为原文关系；condition 为来源状态或明确的表演补足。location/possession/condition 的 object_id 为空。每人开场有位置，已在开场的道具有归属。原文稍后才出现、开场无合法归属证据的道具，用 prop_introductions 列 object_id、beat_id、action_id，不捏造开场状态；其首次归属必须在所列真实来源 transfer 动作中以空 from_state_id 引入，来源事件位于本场前后锚点之间，之前快照不可出现该道具状态。通常 prop_introductions 为空数组，不能用于删除已在开场的道具状态。明确检查原文的首次发现、获知、隐瞒和未知等信息在本集知情状态中是否完整，不假设材料已替你提取。
所有状态必须有真实原文来源，或仅对位置/表演状态明确列 creative_additions 的 blocking/performance。不得凭美术补足编造身份、关系、知情或物品归属。其余美术补足用 appearance/lighting/set_dressing 单列。
snapshot.anchor 是本集 actual/chapter_present 事实的 before/after。现在状态仅接受 actual 且 chapter_present/timeless 的来源；历史章当时状态是否延续须审核。earlier、memory、plan、belief、hypothetical、quoted_story、uncertain 只作背景，不能直接更新现在。开场不得引用之后才发生的转移、获知或进场。状态引用原句必须属于它声明的事实证据，原段逐字连续引用；不能改字或借同段其他句伪装该事实证据。
每个状态槽由 kind+subject_id+object_id 唯一标识；snapshots.state_ids 同槽只一个值。beats 前后快照接续，动作 changes 依次替换状态，最终与下一快照完全一致。进场 entry、离场 exit、位移 move、道具转交 transfer、获知 learn；perform 不暗改这些状态。动作 source_fact_ids 包含目标状态全部原文事实，创作状态与动作使用同一 creative_addition_id；道具转交/获知必须来自真实原文。当前没有变化的“仍在”是状态，不虚构成转移。各场 cast_ids 为本场实际在场人，新人物出场须有进场或显露动作。
每个 beat 写信息目的、对白目标、时长，不写最终对白；合计不超 target_seconds。返回完整JSON。所有身份归并、状态完整性、知情漏提、原文是否支持断言、历史状态是否持续与动作可行性仍须独立语义审查。"""

EPISODE_REVIEW_PROMPT = """你是独立本集状态审核员。对照完整原文、材料事实与 episode_state_plan，审核本集需要的人物身份、角色位置、道具归属、关系和知情状态；材料阶段没有提取状态，不能以其未列状态为由跳过检查。尤其检查首次发现或获知的知情状态有没有遗漏、谁尚不知道、何时得知，以及场景进出/交接依赖、开场与结束状态。程序仅证明引用和显式状态链一致，不证明语义充分；不能用关键词、字段非空或规则数量假装内容审查。此前章实际状态是否仍延续、非当前或未来信息是否串入现在须逐项判断。身份合并、实体类型、同名异人、表演补足与来源事实分开审核。问题定位 state/beat/entity ID 和真实原文，不改写候选或伪造通过。"""

def digest(value):
    return chapters_api.digest(value)


def _obj(**properties):
    return {"type": "object", "properties": deepcopy(properties),
            "required": list(properties), "additionalProperties": False}


TEXT = {"type": "string", "minLength": 1}
STRING = {"type": "string"}


def _array(items, minimum=0, unique=False):
    return {"type": "array", "items": deepcopy(items), "minItems": minimum,
            "uniqueItems": unique}


def _ids(values, minimum=0):
    return _array({"enum": list(values)} if values else False, minimum, True)


def _check(raw, schema):
    error = next(Draft202012Validator(schema).iter_errors(raw), None)
    if error is not None:
        raise ValueError("episode_schema_invalid:" + ".".join(map(str, error.path)))


def _library(library, chapters=None):
    verified = facts_api._verify_catalog(library)
    if chapters is not None and chapters_api._chapters(chapters) != verified["chapters"]:
        raise ValueError("episode_original_chapters_changed")
    return verified


def _selection(library, selected):
    if (not isinstance(selected, list) or not selected
            or any(type(i) is not int for i in selected)
            or selected != list(range(min(selected), max(selected) + 1))
            or len(selected) > 6
            or not set(selected) <= {c["index"] for c in library["chapters"]}):
        raise ValueError("episode_selection_invalid")
    return selected


def _available(library, last_chapter):
    return [f for f in library["facts"] if f["chapter_index"] <= last_chapter
            and all(ref["chapter_index"] <= last_chapter for ref in f["source_evidence"])]


def episode_schema(library, selected_chapter_indices, target_seconds=None):
    library = _library(library)
    selected = _selection(library, selected_chapter_indices)
    if target_seconds is not None and (type(target_seconds) not in (int, float)
            or not math.isfinite(target_seconds) or not 0 < target_seconds <= 600):
        raise ValueError("episode_target_seconds_invalid")
    source_facts = _available(library, max(selected))
    fact_ids = [f["id"] for f in source_facts]
    strings = lambda minimum=0: _array(TEXT, minimum, True)
    anchor = _obj(fact_id={"enum": fact_ids}, edge={"enum": ["before", "after"]})
    evidence_ref = _obj(fact_id={"enum": fact_ids}, paragraph_id=TEXT, exact_quote=TEXT)
    entity = _obj(id=TEXT, kind={"enum": ["person", "object", "place", "group"]}, name=TEXT,
                  identity_fact_ids=_ids(fact_ids, 1),
                  identity_source_refs=_array(evidence_ref, 1, True))
    addition = _obj(id=TEXT, kind={"enum": list(ART_KINDS)}, description=TEXT, entity_ids=strings())
    state = _obj(id=TEXT, kind={"enum": list(KINDS)}, subject_id=TEXT, object_id=STRING,
                 value=STRING, source_fact_refs=_array(evidence_ref, unique=True),
                 creative_addition_id=STRING)
    snapshot = _obj(id=TEXT, anchor=anchor, state_ids=strings())
    action = _obj(id=TEXT, kind={"enum": list(ACTION_KINDS)}, actor_ids=strings(1),
                  description=TEXT, changes=_array(_obj(from_state_id=STRING, to_state_id=STRING)),
                  source_fact_ids=_ids(fact_ids), creative_addition_id=STRING)
    beat = _obj(id=TEXT, location_id=TEXT, before_snapshot_id=TEXT, after_snapshot_id=TEXT,
                cast_ids=strings(1), actions=_array(action), purpose=TEXT, dialogue_goal=TEXT,
                duration_seconds={"type": "number", "exclusiveMinimum": 0, "maximum": 600})
    duration = ({"const": target_seconds} if target_seconds is not None else
                {"type": "number", "exclusiveMinimum": 0, "maximum": 600})
    return _obj(selected_chapter_indices={"const": selected}, target_seconds=duration,
                entities=_array(entity, 1), creative_additions=_array(addition),
                prop_introductions=_array(_obj(object_id=TEXT, beat_id=TEXT, action_id=TEXT), unique=True),
                world_fact_ids=_ids(fact_ids), background_fact_ids=_ids(fact_ids),
                states=_array(state, 1), snapshots=_array(snapshot, 1),
                opening_snapshot_id=TEXT, ending_snapshot_id=TEXT,
                beats=_array(beat, 1), limitations=_array(TEXT, 1))


def episode_payload(library, chapters, selected_chapter_indices, target_seconds=90):
    library = _library(library, chapters)
    selected = _selection(library, selected_chapter_indices)
    if type(target_seconds) not in (int, float) or not 0 < target_seconds <= 600:
        raise ValueError("episode_target_seconds_invalid")
    facts = _available(library, max(selected))
    return {"version": VERSION, "book_name": library["book_name"],
            "source_digest": library["source_digest"], "facts_catalog_sha256": digest(library),
            "selected_chapter_indices": selected, "target_seconds": target_seconds,
            "selected_original_chapters": [deepcopy(c) for c in library["chapters"] if c["index"] in selected],
            "candidate_facts": deepcopy(facts),
            "material_contract": "Facts and citations only; identities, presence, possession and knowledge must be extracted for this episode.",
            "scope": "Full selected chapters; earlier candidate evidence remains quoted. Future chapters are excluded. Required complete evidence chapters are added after selection."}


def _by_id(rows, label):
    result = {row["id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("episode_duplicate_" + label)
    return result


def _key(state):
    return state["kind"], state["subject_id"], state["object_id"]


def _event_span(value):
    """Use the fact's exact anchor quotations, not its entire source paragraph.

    Two facts citing the same broad quotation remain temporally indistinguishable;
    resolving their event order is an explicit semantic-review responsibility.
    """
    position = value["narrative_position"]
    evidence = [ref for ref in value["source_evidence"]
                if ref["paragraph_id"] == position["paragraph_id"]]
    if not evidence:
        raise ValueError("episode_anchor_evidence_missing")
    return (position["chapter_index"], min(ref["start_offset"] for ref in evidence),
            max(ref["end_offset"] for ref in evidence))


def validate_episode(raw, library, chapters, selected_chapter_indices, target_seconds=None):
    library = _library(library, chapters)
    selected = _selection(library, selected_chapter_indices)
    _check(raw, episode_schema(library, selected, target_seconds))
    if (type(raw["target_seconds"]) not in (int, float)
            or not math.isfinite(raw["target_seconds"]) or not 0 < raw["target_seconds"] <= 600
            or any(type(beat["duration_seconds"]) not in (int, float)
                   or not math.isfinite(beat["duration_seconds"]) for beat in raw["beats"])):
        raise ValueError("episode_duration_not_finite")
    facts = _by_id(library["facts"], "facts")
    passages = {p["id"]: p for c in library["chapters"]
                for p in chapters_api.chapter_passages(c)}
    entities = _by_id(raw["entities"], "entities")
    states, snapshots = _by_id(raw["states"], "states"), _by_id(raw["snapshots"], "snapshots")
    additions = _by_id(raw["creative_additions"], "creative_additions")
    _by_id(raw["beats"], "beats")
    used_facts, identity_bindings, state_bindings, source_mentions = set(), {}, {}, {}

    def fact(fid):
        if fid not in facts:
            raise ValueError("episode_unknown_fact")
        value = facts[fid]
        if value["chapter_index"] > max(selected) or any(e["chapter_index"] > max(selected) for e in value["source_evidence"]):
            raise ValueError("episode_future_source_fact")
        used_facts.add(fid)
        return value

    def entity(eid, kinds=None):
        if eid not in entities or (kinds and entities[eid]["kind"] not in kinds):
            raise ValueError("episode_entity_type_or_reference_invalid")
        return entities[eid]

    def bind_ref(ref):
        value = fact(ref["fact_id"])
        paragraph = passages.get(ref["paragraph_id"])
        if paragraph is None or paragraph["chapter_index"] > max(selected):
            raise ValueError("episode_source_paragraph_invalid")
        quote = ref["exact_quote"]
        if not quote.strip() or paragraph["text"].find(quote) < 0:
            raise ValueError("episode_source_quote_not_in_original")
        if paragraph["text"].find(quote, paragraph["text"].index(quote) + 1) >= 0:
            raise ValueError("episode_source_quote_ambiguous")
        if not any(e["paragraph_id"] == ref["paragraph_id"] and quote in e["exact_quote"]
                   for e in value["source_evidence"]):
            raise ValueError("episode_reference_not_bound_to_fact")
        offset = paragraph["text"].index(quote)
        return {**deepcopy(ref), "chapter_index": paragraph["chapter_index"],
                "start_offset": paragraph["start_offset"] + offset,
                "end_offset": paragraph["start_offset"] + offset + len(quote),
                "paragraph_sha256": paragraph["sha256"],
                "chapter_sha256": paragraph["chapter_sha256"]}

    for row in entities.values():
        support = [fact(fid) for fid in row["identity_fact_ids"]]
        refs = row["identity_source_refs"]
        if {ref["fact_id"] for ref in refs} != set(row["identity_fact_ids"]):
            raise ValueError("episode_identity_fact_reference_mismatch")
        if any(f["modality"] != "actual" or f["event_time"] not in {"chapter_present", "timeless"}
               for f in support):
            raise ValueError("episode_identity_evidence_not_actual")
        bound = [bind_ref(ref) for ref in refs]
        if not any(row["name"] in ref["exact_quote"] for ref in bound):
            raise ValueError("episode_canonical_name_not_from_source")
        for ref in bound:
            offset = ref["exact_quote"].find(row["name"])
            while offset >= 0:
                start = ref["start_offset"] + offset
                mention = (ref["paragraph_id"], start, start + len(row["name"]))
                if mention in source_mentions and source_mentions[mention] != row["id"]:
                    raise ValueError("episode_source_identity_bound_twice")
                source_mentions[mention] = row["id"]
                offset = ref["exact_quote"].find(row["name"], offset + 1)
        identity_bindings[row["id"]] = bound
    for row in additions.values():
        for eid in row["entity_ids"]:
            entity(eid)

    def anchor(value):
        f = fact(value["fact_id"])
        if f["chapter_index"] not in selected or f["modality"] != "actual" or f["event_time"] != "chapter_present":
            raise ValueError("episode_anchor_not_current_selected_event")
        chapter_index, start, end = _event_span(f)
        return chapter_index, start if value["edge"] == "before" else end

    def current(fid, cutoff):
        f = fact(fid)
        if f["modality"] != "actual" or f["event_time"] not in {"timeless", "chapter_present"}:
            raise ValueError("episode_noncurrent_fact_used_as_state")
        chapter_index, _, end = _event_span(f)
        if f["event_time"] == "chapter_present" and (chapter_index, end) > cutoff:
            raise ValueError("episode_fact_occurs_after_snapshot")
        return f

    if raw["opening_snapshot_id"] not in snapshots or raw["ending_snapshot_id"] not in snapshots:
        raise ValueError("episode_snapshot_reference_invalid")
    points = {sid: anchor(s["anchor"]) for sid, s in snapshots.items()}
    opening, ending = raw["opening_snapshot_id"], raw["ending_snapshot_id"]
    if points[opening] > points[ending]:
        raise ValueError("episode_snapshot_time_reversed")
    for fid in raw["world_fact_ids"]:
        current(fid, points[opening])
    for fid in raw["background_fact_ids"]:
        fact(fid)

    def state_shape(s):
        kind, subject, obj, value = s["kind"], s["subject_id"], s["object_id"], s["value"]
        entity(subject)
        if kind in {"location", "possession", "condition"} and obj:
            raise ValueError("episode_state_object_not_applicable")
        if kind == "location":
            entity(subject, {"person"})
            if value:
                entity(value, {"place"})
        elif kind == "possession":
            entity(subject, {"object"})
            if value:
                entity(value, {"person", "place"})
        elif kind == "knowledge":
            entity(subject, {"person"}); fact(obj)
            if value not in {"known", "unknown"}:
                raise ValueError("episode_knowledge_value_invalid")
        elif kind == "relation":
            entity(obj)
            if not value:
                raise ValueError("episode_relation_empty")
        elif not value:
            raise ValueError("episode_condition_empty")
        if s["creative_addition_id"]:
            addition = additions.get(s["creative_addition_id"])
            allowed = {"location": "blocking", "condition": "performance"}
            if not addition or allowed.get(kind) != addition["kind"] or subject not in addition["entity_ids"]:
                raise ValueError("episode_creative_state_not_allowed")
        if s["source_fact_refs"] and s["creative_addition_id"]:
            raise ValueError("episode_source_and_creative_basis_mixed")
        if not s["source_fact_refs"] and not s["creative_addition_id"]:
            raise ValueError("episode_state_unanchored")
        state_bindings[s["id"]] = [bind_ref(ref) for ref in s["source_fact_refs"]]

    for s in states.values():
        state_shape(s)

    def frame(sid):
        if sid not in snapshots:
            raise ValueError("episode_snapshot_reference_invalid")
        result = {}
        for state_id in snapshots[sid]["state_ids"]:
            if state_id not in states or _key(states[state_id]) in result:
                raise ValueError("episode_snapshot_slot_duplicate_or_unknown")
            s = states[state_id]
            for ref in s["source_fact_refs"]:
                current(ref["fact_id"], points[sid])
            if s["kind"] == "knowledge" and s["value"] == "known":
                current(s["object_id"], points[sid])
            result[_key(s)] = state_id
        return result

    frames = {sid: frame(sid) for sid in snapshots}
    people = {eid for eid, e in entities.items() if e["kind"] == "person"}
    props = {eid for eid, e in entities.items() if e["kind"] == "object"}
    introductions = {}
    for introduction in raw["prop_introductions"]:
        prop = introduction["object_id"]
        entity(prop, {"object"})
        if prop in introductions:
            raise ValueError("episode_prop_introduction_duplicate")
        if ("possession", prop, "") in frames[opening]:
            raise ValueError("episode_prop_introduction_already_at_opening")
        introductions[prop] = introduction

    def props_referenced(s):
        return {s["subject_id"], s["object_id"]} & props

    introduced = {eid for eid in props if ("possession", eid, "") in frames[opening]}
    for state_id in frames[opening].values():
        if not props_referenced(states[state_id]) <= introduced:
            raise ValueError("episode_prop_state_before_introduction")
    for eid in people:
        if ("location", eid, "") not in frames[opening]:
            raise ValueError("episode_opening_character_location_missing")
    for eid in props:
        if ("possession", eid, "") not in frames[opening] and eid not in introductions:
            raise ValueError("episode_opening_prop_holder_missing")
    for state_id in frames[opening].values():
        s = states[state_id]
        if not s["source_fact_refs"] and not s["creative_addition_id"]:
            raise ValueError("episode_opening_state_unanchored")

    previous, last_cast, seen_actions, used_snapshots = opening, set(), set(), {opening}
    used_states = set(frames[opening].values())
    for number, beat in enumerate(raw["beats"]):
        before, after = beat["before_snapshot_id"], beat["after_snapshot_id"]
        if before != previous or before not in frames or after not in frames or points[after] < points[before]:
            raise ValueError("episode_beat_state_link_or_time_invalid")
        entity(beat["location_id"], {"place"})
        cast = set(beat["cast_ids"])
        for eid in cast:
            entity(eid, {"person"})
        active = dict(frames[before]); entered, exited = set(), set()
        for action in beat["actions"]:
            if action["id"] in seen_actions:
                raise ValueError("episode_duplicate_action")
            seen_actions.add(action["id"])
            for eid in action["actor_ids"]:
                entity(eid, {"person"})
            if not set(action["actor_ids"]) <= cast:
                raise ValueError("episode_action_actor_not_in_cast")
            for fid in action["source_fact_ids"]:
                current(fid, points[after])
            if not action["source_fact_ids"] and not action["creative_addition_id"]:
                raise ValueError("episode_action_unanchored")
            if action["creative_addition_id"] and action["creative_addition_id"] not in additions:
                raise ValueError("episode_action_creative_reference_invalid")
            if action["kind"] == "entry":
                entered.update(action["actor_ids"])
            if action["kind"] == "exit":
                exited.update(action["actor_ids"])
            for change in action["changes"]:
                old, new = change["from_state_id"], change["to_state_id"]
                if not new or new not in states or (old and old not in states):
                    raise ValueError("episode_action_state_reference_invalid")
                target = states[new]; key = _key(target)
                pending_props = props_referenced(target) - introduced
                if pending_props:
                    prop = target["subject_id"]
                    declared = introductions.get(prop)
                    if (pending_props != {prop} or target["kind"] != "possession" or old
                            or action["kind"] != "transfer" or not declared
                            or declared["beat_id"] != beat["id"] or declared["action_id"] != action["id"]):
                        raise ValueError("episode_prop_state_before_introduction")
                    if target["creative_addition_id"] or action["creative_addition_id"]:
                        raise ValueError("episode_prop_introduction_requires_original_source")
                    refs = target["source_fact_refs"]
                    if not refs:
                        raise ValueError("episode_prop_introduction_requires_original_source")
                    for ref in refs:
                        source = current(ref["fact_id"], points[after])
                        chapter_index, _, end = _event_span(source)
                        if (source["chapter_index"] not in selected or source["event_time"] != "chapter_present"
                                or (chapter_index, end) <= points[before]):
                            raise ValueError("episode_prop_introduction_source_outside_beat")
                    introduced.add(prop)
                for ref in target["source_fact_refs"]:
                    current(ref["fact_id"], points[after])
                if target["kind"] == "knowledge" and target["value"] == "known":
                    current(target["object_id"], points[after])
                if old:
                    if states[old]["value"] == target["value"]:
                        raise ValueError("episode_action_state_value_unchanged")
                    if _key(states[old]) != key or active.get(key) != old:
                        raise ValueError("episode_action_before_state_mismatch")
                elif key in active:
                    raise ValueError("episode_action_cannot_overwrite_existing_slot")
                allowed = {"location": {"entry", "exit", "move"}, "possession": {"transfer"},
                           "knowledge": {"learn"}, "relation": {"perform"}, "condition": {"perform"}}
                if action["kind"] not in allowed[target["kind"]]:
                    raise ValueError("episode_action_kind_state_mismatch")
                if target["kind"] in {"location", "knowledge", "condition"} and target["subject_id"] not in action["actor_ids"]:
                    raise ValueError("episode_changed_actor_missing")
                if target["kind"] == "possession":
                    holders = {target["value"], states[old]["value"] if old else ""} & people
                    if not holders <= set(action["actor_ids"]):
                        raise ValueError("episode_transfer_holder_not_acting")
                if target["kind"] == "relation" and not target["source_fact_refs"]:
                    raise ValueError("episode_relation_change_requires_source")
                if target["kind"] == "knowledge" and target["value"] != "known":
                    raise ValueError("episode_learn_requires_known_target")
                if target["kind"] in {"possession", "knowledge"}:
                    source_ids = {ref["fact_id"] for ref in target["source_fact_refs"]}
                    if not source_ids or not source_ids <= set(action["source_fact_ids"]):
                        raise ValueError("episode_transfer_or_learn_requires_bound_source_action")
                source_ids = {ref["fact_id"] for ref in target["source_fact_refs"]}
                if source_ids and not source_ids <= set(action["source_fact_ids"]):
                    raise ValueError("episode_changed_state_action_source_mismatch")
                if target["creative_addition_id"] and action["creative_addition_id"] != target["creative_addition_id"]:
                    raise ValueError("episode_changed_state_creative_action_mismatch")
                active[key] = new
                used_states.add(new)
        if active != frames[after]:
            raise ValueError("episode_unexplained_state_change")
        def at_location(values):
            return {eid for eid in people if ("location", eid, "") in values
                    and states[values[("location", eid, "")]]["value"] == beat["location_id"]}
        start_present, end_present = at_location(frames[before]), at_location(frames[after])
        if not cast <= start_present | end_present:
            raise ValueError("episode_cast_location_mismatch")
        if not end_present - start_present <= entered or not start_present - end_present <= exited:
            raise ValueError("episode_entry_or_exit_action_missing")
        if number and not cast - last_cast <= entered:
            raise ValueError("episode_new_character_requires_entry")
        if not entered <= end_present or not exited <= start_present:
            raise ValueError("episode_entry_or_exit_state_mismatch")
        previous, last_cast = after, cast
        used_snapshots.update((before, after)); used_states.update(frames[after].values())
    if previous != ending or used_snapshots != set(snapshots) or used_states != set(states):
        raise ValueError("episode_unused_or_unlinked_state")
    if introduced != props:
        raise ValueError("episode_prop_introduction_not_executed")
    if sum(b["duration_seconds"] for b in raw["beats"]) > raw["target_seconds"]:
        raise ValueError("episode_beat_duration_exceeds_target")
    required_chapters = set(selected)
    for fid in used_facts:
        required_chapters.update(e["chapter_index"] for e in facts[fid]["source_evidence"])
    for refs in [*identity_bindings.values(), *state_bindings.values()]:
        required_chapters.update(ref["chapter_index"] for ref in refs)
    if any(i > max(selected) for i in required_chapters):
        raise ValueError("episode_future_evidence_chapter")
    return {"version": VERSION, "snapshot": deepcopy(raw),
            "binding": {"facts_catalog_sha256": digest(library), "source_digest": library["source_digest"],
                        "snapshot_sha256": digest(raw), "selected_chapter_indices": selected,
                        "used_fact_ids": sorted(used_facts),
                        "identity_evidence": identity_bindings, "state_evidence": state_bindings,
                        "required_source_chapter_indices": sorted(required_chapters)},
            "validation": {"source_bound": True, "explicit_state_chain_checked": True,
                           "future_source_excluded": True, "semantic_review_required": True,
                           "identity_merges_semantically_verified": False,
                           "state_completeness_semantically_verified": False,
                           "knowledge_completeness_semantically_verified": False,
                           "source_assertion_entailment_semantically_verified": False,
                           "event_time_bound_to_exact_anchor_quotes": True,
                           "shared_quote_event_order_semantically_verified": False,
                           "past_state_persistence_semantically_verified": False,
                           "script_actions_semantically_verified": False}}


def build_episode_context(validated, library, chapters):
    """Return the actual writer input; never include the whole-book framework."""
    if not isinstance(validated, dict) or validated.get("version") != VERSION:
        raise ValueError("episode_validated_version_invalid")
    rebound = validate_episode(validated["snapshot"], library, chapters,
                               validated["binding"]["selected_chapter_indices"])
    if rebound != validated:
        raise ValueError("episode_validated_binding_changed")
    binding, raw = validated["binding"], validated["snapshot"]
    selected = binding["selected_chapter_indices"]
    required = set(binding["required_source_chapter_indices"])
    facts = [deepcopy(f) for f in library["facts"] if f["id"] in binding["used_fact_ids"]]
    entities = deepcopy(raw["entities"])
    return {"book_name": library["book_name"], "target_seconds": raw["target_seconds"],
            "selected_chapter_indices": selected,
            "episode_brief": {"chapter_indices": selected,
                              "opening_snapshot_id": raw["opening_snapshot_id"],
                              "ending_snapshot_id": raw["ending_snapshot_id"],
                              "temporal_rule": "Only explicitly evidenced current state or declared scene actions; historical/nonactual background cannot update current state."},
            "selected_original_chapters": [deepcopy(c) for c in library["chapters"] if c["index"] in selected],
            "required_evidence_chapters": [deepcopy(c) for c in library["chapters"] if c["index"] in required - set(selected)],
            "episode_source_facts": facts, "episode_source_entities": entities,
            "episode_state_plan": deepcopy(raw), "episode_state_binding": deepcopy(binding),
            "source_scope": "Complete selected chapters and complete specifically referenced earlier evidence chapters. No future chapters or whole-book framework.",
            "state_validation": deepcopy(validated["validation"])}
