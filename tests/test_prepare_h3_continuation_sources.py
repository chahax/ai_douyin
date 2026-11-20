"""CPU source-plan tests. Fixture colour images never certify media quality."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("continuation_sources", ROOT / "scripts/prepare_h3_continuation_sources.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
core = builder.core


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return core.binding(path)


@pytest.fixture
def prepared(tmp_path):
    selection = json.loads((ROOT / "data/video_generation/h3_library_bound_next_minute_20261113_v1/script_selection.json").read_text(encoding="utf-8"))
    run = tmp_path / "source_plan"
    write_json(run / "script_selection.json", selection)
    names = dict(su_mo="苏墨", ye_nan="叶南", ye_dong="叶东", ye_yaner="叶嫣儿", ye_xijue="叶西决")
    index = dict(characters={}, places={})
    for i, (cid, name) in enumerate(names.items()):
        path = tmp_path / "fixture_assets" / (cid + ".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (24, 32), (i * 20, 100, 100)).save(path)
        front = dict(entity_id=cid, view="front", image=core.binding(path))
        card = dict(entity_id=cid, name=name, description="source-bound test fixture plain clothing", images=dict(front=front))
        cb = write_json(tmp_path / "fixture_assets" / (cid + ".json"), card)
        index["characters"][cid] = dict(feature_card=cb, images=dict(front=front))
    for pid in ("su_mo_room", "children_room"):
        image = tmp_path / "fixture_assets" / (pid + ".png")
        Image.new("RGB", (24, 32), (80, 80, 80)).save(image)
        index["places"][pid] = dict(images=dict(front=dict(entity_id=pid, image=core.binding(image))))
    path = tmp_path / "fixture_assets" / "BINDING_INDEX.json"
    write_json(path, index)
    return run, path, selection


def entries(prepared):
    run, binding, _ = prepared
    return {sid: builder.build_one(run, sid, binding) for sid in builder.IDS}


def read_entry(value):
    return core.read(value["source_case"])["shots"][0]


def test_all_four_have_exact_full_cast_and_source_only_role(prepared):
    result = entries(prepared)
    for sid, value in result.items():
        entry = read_entry(value)
        req = core.validate_entry(entry)
        assert req["source_coverage_complete"]
        assert not req["classification_issues"]
        assert entry["source_entry_role"] == builder.ROLE
        assert entry["actual_first_image"] == entry["planning_preview_image"]
        assert set(req["visible_actors"]) == ({"su_mo"} if sid == "S01" else {"ye_dong", "ye_nan", "ye_yaner", "ye_xijue"})
        assert "narrator" in entry["character_names"]
        assert "narrator" not in entry["canonical_characters"]
        assert core.compile_prompt(entry)["dispatchable"] is False


def test_audio_words_order_speakers_and_counts_not_rewritten(prepared):
    result = entries(prepared)
    selected = {s["shot_id"]: s for s in prepared[2]["segments"]}
    count = 0
    for sid, value in result.items():
        entry = read_entry(value)
        expected = [s for s in selected[sid]["ordered_source_items"] if s["kind"] == "audio"]
        quote_words = [q.group()[1:-1] for q in core.QUOTE.finditer(core.check(entry["source"]).read_text(encoding="utf-8"))]
        assert quote_words == [s["text"] for s in expected]
        assert [a["speaker"] for a in entry["audio"]] == [s["speaker"] for s in expected]
        assert [a["mode"] for a in entry["audio"]] == ["voiceover" if s["speaker"] == "narrator" else "onscreen" for s in expected]
        assert value["readable_characters"] == selected[sid]["target_readable_characters"]
        count += len(expected)
    assert count == 9
    assert sum(v["readable_characters"] for v in result.values()) == 176


def test_each_original_action_once_only_strip_markdown(prepared):
    result = entries(prepared)
    for original in prepared[2]["segments"]:
        entry = read_entry(result[original["shot_id"]])
        actions = [s["text"] for s in entry["source_spans"] if s["kind"] == "action"]
        assert actions == [s["text"].replace("**", "") for s in original["ordered_source_items"] if s["kind"] == "action"]
        action_ids = [s["id"] for s in entry["source_spans"] if s["kind"] == "action"]
        assert [v for b in entry["camera_beats"] for v in b["source_span_ids"]] == action_ids
        assert len(entry["camera_beats"]) == 4


def test_planning_coverage_cannot_pass_as_real_future_first(prepared):
    for value in entries(prepared).values():
        entry = read_entry(value)
        review = core.read(entry["coverage_review"])
        assert set(review["checks"]["faces"].values()) == {False}
        assert set(review["checks"]["identities"].values()) == {False}
        assert review["checks"]["room_identity"] is False
        assert core.evaluate(entry)["status"] != "ready"


def test_quote_indices_recomputed_for_each_generated_prompt(prepared):
    result = entries(prepared)
    for value in result.values():
        entry = read_entry(value)
        req = core.validate_entry(entry)
        assert [a["quote_index"] for a in entry["audio"]] == list(range(len(entry["audio"])))
        for a in entry["audio"]:
            q = req["quotes"][a["quote_index"]]
            assert core.sha(q.group()) == a["quote_sha256"]


def test_authoritative_source_tamper_rejected_before_source_case(prepared, tmp_path):
    run, binding, selection = prepared
    copied = tmp_path / "authoritative.md"
    copied.write_bytes(Path(selection["source"]["path"]).read_bytes())
    selection["source"].update(core.binding(copied))
    write_json(run / "script_selection.json", selection)
    copied.write_bytes(copied.read_bytes() + b"\nchanged")
    with pytest.raises(core.ContinuityError, match="bound_input_changed"):
        builder.build_one(run, "S01", binding)
    assert not (run / "segments/S01/SOURCE_CASE.json").exists()


def test_changed_selected_word_rejected(prepared):
    run, binding, selection = prepared
    item = selection["segments"][0]["ordered_source_items"][1]
    item["text"] = item["text"].replace("邋遢", "整洁")
    write_json(run / "script_selection.json", selection)
    with pytest.raises(ValueError, match="selected_original_substring_changed"):
        builder.build_one(run, "S01", binding)


def test_unknown_character_and_changed_card_pixels_fail(prepared):
    run, binding, _ = prepared
    index = json.loads(binding.read_text(encoding="utf-8"))
    cardpath = Path(index["characters"]["su_mo"]["feature_card"]["path"])
    card = json.loads(cardpath.read_text(encoding="utf-8"))
    card["images"]["front"]["image"] = index["characters"]["ye_nan"]["images"]["front"]["image"]
    index["characters"]["su_mo"]["feature_card"] = write_json(cardpath, card)
    write_json(binding, index)
    with pytest.raises(ValueError, match="canonical_card_and_image_version_mismatch"):
        builder.build_one(run, "S01", binding)


def test_idempotent_build_preserves_frozen_outputs(prepared):
    run, binding, _ = prepared
    a = builder.build_one(run, "S01", binding)
    before = core.check(a["source_case"]).read_bytes()
    assert builder.build_one(run, "S01", binding) == a
    assert core.check(a["source_case"]).read_bytes() == before


def test_supplied_visual_approval_rejected(prepared):
    run, binding, _ = prepared
    good = builder.build_one(run, "S01", binding)
    entry = read_entry(good)
    review = core.read(entry["coverage_review"])
    review["checks"]["faces"]["su_mo"] = True
    path = run / "false_approval.json"
    write_json(path, review)
    with pytest.raises(ValueError, match="source_only_builder_accepts_no_visual_coverage_claim"):
        builder.build_one(run, "S01", binding, coverage_review=path)
