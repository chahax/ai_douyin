"""Build source-only H3 scene plans from an exact, already selected screenplay.

This command performs no model calls.  Its legacy ``actual_first_image`` field
is explicitly a planning preview; production must bind its real start image in
LIBRARY_INPUT from a saved native result or a real scene-stage receipt.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_continuity_input_v33 as core

IDS = ("S01", "S02", "S03", "S04")
ROLE = "script_plan_only_actual_start_bound_in_LIBRARY_INPUT"
DEFAULT_RUN = Path(__file__).resolve().parents[1] / "data/video_generation/h3_library_bound_next_minute_20261113_v1"


def _read(path_or_binding):
    value = path_or_binding if isinstance(path_or_binding, dict) else core.binding(path_or_binding)
    return json.loads(core.check(value).read_text(encoding="utf-8")), value


def _plain(text):
    # These selected source paragraphs only use bold delimiters.  Parentheses,
    # punctuation, pronouns and every narrative word remain exactly as written.
    return text.replace("**", "")


def _freeze_text(path, text):
    path = Path(path)
    data = text.encode("utf-8")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("existing_source_plan_is_immutable:" + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return core.binding(path)


def _freeze_json(path, value):
    return _freeze_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _verify_original(selection):
    original = core.check({k: selection["source"][k] for k in ("path", "sha256")})
    decoded = original.read_text(encoding="utf-8")
    raw = original.read_bytes()
    entries = selection["segments"]
    if [item["shot_id"] for item in entries] != list(IDS):
        raise ValueError("four_ordered_source_segments_required")
    last_end = -1
    for item in entries:
        source_items = list(item["ordered_source_items"])
        if "entry_context" in item:
            source_items.append(item["entry_context"])
        for span in source_items:
            a, b = span["source_start"], span["source_end"]
            if decoded[a:b] != span["text"] or core.sha(span["text"]) != span["sha256"]:
                raise ValueError("selected_original_substring_changed")
            if "source_raw_utf8_byte_start" in span:
                x, y = span["source_raw_utf8_byte_start"], span["source_raw_utf8_byte_end"]
                if raw[x:y].decode("utf-8") != span["text"]:
                    raise ValueError("selected_raw_byte_substring_changed")
        for span in item["ordered_source_items"]:
            if span["source_start"] < last_end:
                raise ValueError("selected_source_order_or_coverage_overlaps")
            last_end = span["source_end"]
        chars = sum(len(re.findall(r"[\u3400-\u9fffA-Za-z0-9]", s["text"]))
                    for s in item["ordered_source_items"] if s["kind"] == "audio")
        if chars != item["target_readable_characters"]:
            raise ValueError("selected_audio_character_count_changed")
    return original


def _assets(binding_index, seg):
    index, index_binding = _read(binding_index)
    names = {"narrator": "中性旁白"}
    canon = {}
    descriptions = {}
    cards = {}
    actors = seg["entire_segment_actor_ids"]
    if not actors or len(set(actors)) != len(actors) or "narrator" in actors:
        raise ValueError("explicit_non_narrator_full_clip_cast_required")
    for cid in actors:
        record = index["characters"][cid]
        card, cb = _read(record["feature_card"])
        front = record["images"]["front"]
        if card["entity_id"] != cid or front["entity_id"] != cid:
            raise ValueError("canonical_library_character_identity_changed")
        image = {k: front["image"][k] for k in ("path", "sha256")}
        core.image(image)
        if card["images"]["front"]["image"] != image:
            raise ValueError("canonical_card_and_image_version_mismatch")
        name, description = card["name"], card["description"]
        if not isinstance(description, str) or not description.strip():
            raise ValueError("version_bound_character_description_required")
        if core.QUOTE.search(description) or re.search("镜头|特写|中近景|面部近景|平顺切|结束在", description):
            raise ValueError("library_description_is_not_source_audio_or_camera")
        names[cid], canon[cid] = name, image
        descriptions[cid], cards[cid] = description, cb
    place = index["places"][seg["place_id"]]
    room = {k: place["images"]["front"]["image"][k] for k in ("path", "sha256")}
    core.image(room)
    return index_binding, names, canon, room, descriptions, cards


def _actor(pose, *parts):
    return {"pose": pose, "visible_parts": list(parts)}


def _camera(sid, action_ids):
    """A small explicit schedule, with every pose copied from selected text.

    Whole-clip cast is the union of these shots.  A close shot does not remove
    the other actors from required library assets.
    """
    def beat(start, end, framing, actors, acts=()):
        return dict(start=start, end=end, cut=bool(start), framing=framing,
                    actors=actors, source_span_ids=[action_ids[i] for i in acts])
    father = lambda pose: {"su_mo": _actor(pose, "face", "torso", "hands")}
    yan = _actor("跪坐在床沿", "face", "torso", "hands")
    small = _actor("牙关咬紧", "face", "torso", "hands")
    standing = "在屋里，站着或蹲着"
    all_kids = dict(ye_yaner=yan, ye_xijue=small,
                    ye_dong=_actor(standing, "face", "torso"),
                    ye_nan=_actor(standing, "face", "torso"))
    if sid == "S01":
        return [beat(0, 5, "medium", father("苏墨走回床边"), (0,)),
                beat(5, 9, "face_close", father("苏墨站在床边，皱眉苦思"), (1,)),
                beat(9, 12, "face_close", father("苏墨站在床边，皱眉苦思")),
                beat(12, 15, "hands_close", father("把面包放到旧木桌上"), (2,))]
    if sid == "S02":
        return [beat(0, 3, "medium", {"ye_yaner": yan, "ye_xijue": small}, (0,)),
                beat(3, 6, "face_close", {"ye_xijue": small}, (1,)),
                beat(6, 10, "hands_close", {"ye_yaner": yan, "ye_xijue": small}),
                beat(10, 15, "medium", all_kids)]
    if sid == "S03":
        ending = deepcopy(all_kids)
        ending["ye_dong"] = _actor("叶东双眸冒火，紧握双拳，转身就要往外走", "face", "torso", "hands", "legs")
        return [beat(0, 4, "medium", all_kids),
                beat(4, 8, "face_close", {"ye_xijue": small}),
                beat(8, 11, "hands_close", {"ye_yaner": yan, "ye_xijue": small}),
                beat(11, 15, "medium", ending, (0,))]
    ending = deepcopy(all_kids)
    ending["ye_dong"] = _actor("他垂下眼，冷静下来", "face", "torso", "hands")
    ending["ye_nan"] = _actor("叶南一把拦在他身前", "face", "torso", "hands")
    ending["ye_yaner"] = _actor("叶嫣儿也抬起头附和", "face", "torso", "hands")
    return [beat(0, 5, "medium", {
                "ye_nan": _actor("叶南一把拦在他身前", "face", "torso", "hands"),
                "ye_dong": _actor("紧握双拳，转身就要往外走", "face", "torso", "hands")}, (0,)),
            beat(5, 9, "face_close", {"ye_yaner": ending["ye_yaner"]}, (1,)),
            beat(9, 12, "face_close", {"ye_dong": ending["ye_dong"]}, (2,)),
            beat(12, 15, "medium", ending)]


AUDIO_WINDOWS = {"S01": ((.5, 3.3), (5, 13.5)),
                 "S02": ((1, 1.8), (3, 5), (6, 13)),
                 "S03": ((0, 13.5),),
                 "S04": ((.3, 3.7), (5, 8.4), (8.5, 15))}


def build_one(run, shot_id, binding_index, *, selection_path=None,
              first_image=None, coverage_review=None):
    """Freeze one textual plan; no actual generation start or quality approval.

    ``first_image`` is optional only as a *planning preview*.  Neither this
    function nor its output authenticates a native start/previous tail.
    """
    run = Path(run).resolve()
    if shot_id not in IDS:
        raise ValueError("four_explicit_shot_ids_required")
    selection, selection_binding = _read(selection_path or run / "script_selection.json")
    original = _verify_original(selection)
    segments = {item["shot_id"]: item for item in selection["segments"]}
    seg = segments[shot_id]
    index_binding, names, canon, room, descriptions, cards = _assets(binding_index, seg)
    preview = core.binding(first_image) if first_image is not None and not isinstance(first_image, dict) else first_image
    preview = preview or room
    core.image(preview)
    spans, chunks, provenance = [], [], []
    def add(kind, text, origin):
        start = sum(len(chunk) for chunk in chunks)
        span = dict(id="s%03d" % len(spans), kind=kind, start=start,
                    end=start + len(text), text=text, sha256=core.sha(text))
        spans.append(span)
        chunks.extend((text, "\n"))
        provenance.append(dict(span_id=span["id"], **origin))
        return span["id"]
    add("context", "真人写实中国家庭短剧。竖屏9:16，普通话与原生同步声音。", {"kind": "production_format"})
    audio_context = add("context", "旁白为中性画外声；明确角色对白由署名角色开口。声音按原句呈现。", {"kind": "audio_format"})
    description_ids = {}
    for cid in seg["entire_segment_actor_ids"]:
        description_ids[cid] = [add("context", names[cid] + "：" + descriptions[cid],
                                    {"kind": "bound_library_feature", "actor_id": cid, "feature_card": cards[cid]})]
    context_seg = seg if "entry_context" in seg else segments["S02"]
    state = [add("context", _plain(context_seg["entry_context"]["text"]),
                 {"kind": "original_scene_entry_context", "selection_shot_id": context_seg["shot_id"],
                  "original": context_seg["entry_context"], "render_transform": "strip_bold_markers_only"})]
    if shot_id in ("S02", "S03", "S04"):
        # Source-anchored pose vocabulary for passive/reaction shots.  It is
        # textual planning context, not a claim about a future real tail.
        for index, item in enumerate(segments["S02"]["ordered_source_items"]):
            if item["kind"] == "action":
                state.append(add("context", _plain(item["text"]),
                    {"kind": "selected_pose_context_not_actual_tail", "selection_shot_id": "S02",
                     "item_index": index, "original": item, "render_transform": "strip_bold_markers_only"}))
    if shot_id == "S04":
        item = next(i for i in segments["S03"]["ordered_source_items"] if i["kind"] == "action")
        state.append(add("context", _plain(item["text"]),
                         {"kind": "selected_pose_context_not_actual_tail", "selection_shot_id": "S03",
                          "original": item, "render_transform": "strip_bold_markers_only"}))
    action_ids, audio = [], []
    windows = iter(AUDIO_WINDOWS[shot_id])
    for index, item in enumerate(seg["ordered_source_items"]):
        origin = {"kind": "selected_body_item", "selection_shot_id": shot_id,
                  "item_index": index, "original": item}
        if item["kind"] == "audio":
            text = "“" + item["text"] + "”"
            add("audio", text, dict(origin, render_transform="add_quote_delimiters_only"))
            start, end = next(windows)
            audio.append(dict(quote_index=len(audio), quote_sha256=core.sha(text),
                              speaker=item["speaker"], mode="voiceover" if item["speaker"] == "narrator" else "onscreen",
                              start=start, end=end))
        elif item["kind"] == "action":
            sid = add("action", _plain(item["text"]), dict(origin, render_transform="strip_bold_markers_only"))
            action_ids.append(sid)
            state.append(sid)
        else:
            add("context", _plain(item["text"]), dict(origin, render_transform="strip_bold_markers_only"))
    prompt = "".join(chunks)
    prompt_binding = _freeze_text(run / "source_prompts" / (shot_id + ".txt"), prompt)
    quotes = list(core.QUOTE.finditer(prompt))
    if len(quotes) != len(audio):
        raise ValueError("non_audio_context_contains_quote_occurrence")
    for a, quote in zip(audio, quotes):
        a["quote_index"] = quotes.index(quote)
        if a["quote_sha256"] != core.sha(quote.group()):
            raise ValueError("actual_prompt_quote_index_changed")
    review_value = dict(schema=core.REVIEW, reviewed_by="source_plan_builder_not_visual_review",
        target_image=preview, canonical_characters=canon, canonical_room=room,
        checks=dict(topology_coherent=False, room_identity=False,
                    faces={cid: False for cid in canon}, identities={cid: False for cid in canon}),
        completion_known=False, outcome_unknown=False,
        evidence=["Planning preview only; no native start-frame receipt and no visual coverage approval."])
    review_binding = _freeze_json(run / "segments" / shot_id / "PLANNING_COVERAGE_REVIEW.json", review_value)
    if coverage_review is not None:
        supplied, supplied_binding = _read(coverage_review)
        if supplied != review_value:
            raise ValueError("source_only_builder_accepts_no_visual_coverage_claim")
        review_binding = supplied_binding
    entry = dict(shot_id=shot_id, source=prompt_binding,
        source_scope=dict(start=0, end=len(prompt)), source_spans=spans,
        duration=15, audio=audio, camera_beats=_camera(shot_id, action_ids),
        character_names=names, canonical_characters=canon, canonical_room=room,
        character_description_span_ids=description_ids, audio_context_span_ids=[audio_context],
        source_state_span_ids=state, actual_first_image=preview, planning_preview_image=preview,
        coverage_review=review_binding, audio_format="plain_zh", postproduction_subtitles=False,
        first_frame_policy="first_camera_beat/v1", source_entry_role=ROLE,
        actual_first_image_role="legacy_compatibility_planning_preview_not_dispatch_input",
        authoritative_script={"path": str(original), "sha256": core.binding(original)["sha256"]},
        script_selection=selection_binding, library_binding=index_binding,
        full_clip_actor_ids=list(seg["entire_segment_actor_ids"]),
        place_id=seg["place_id"], story_time=seg["scene_time"], source_item_provenance=provenance,
        real_start_frame_required_from="LIBRARY_INPUT.native_result_or_scene_stage_receipt")
    checked = core.validate_entry(entry)
    if not checked["source_coverage_complete"] or set(checked["visible_actors"]) != set(seg["entire_segment_actor_ids"]):
        raise ValueError("complete_text_and_full_clip_cast_coverage_required")
    compiled = core.compile_prompt(entry)
    if compiled["dispatchable"] is not False:
        raise ValueError("source_plan_must_not_approve_dispatch")
    case = _freeze_json(run / "segments" / shot_id / "SOURCE_CASE.json", dict(schema=core.SCHEMA, shots=[entry]))
    return dict(status="source_plan_only_no_post", shot_id=shot_id, source_case=case,
                prompt=prompt_binding, actual_start_verified=False, model_posts=0,
                full_clip_actor_ids=checked["visible_actors"], source_coverage_complete=True,
                expected_quotes=[q.group()[1:-1] for q in quotes],
                readable_characters=seg["target_readable_characters"], production_approved=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--binding-index", type=Path, required=True)
    parser.add_argument("--shot", choices=IDS)
    args = parser.parse_args()
    result = [build_one(args.run, sid, args.binding_index) for sid in ((args.shot,) if args.shot else IDS)]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
