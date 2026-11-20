from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "data/fanqie_promotion/scene_plans/reference_404263_full_workflows_v2.json"
VOICE_PATH = ROOT / "data/qa/reference_404263_full_workflows_20260825/cosyvoice_narration_spec.json"
RUNNER_PATH = ROOT / "scripts/run_reference_404263_multiflow.py"
COMPOSER_PATH = ROOT / "scripts/compose_reference_404263_full_candidate.py"
EDIT_RECIPE_PATH = ROOT / "data/qa/reference_404263_full_workflows_20260825/full_candidate_edit_recipes_v1.json"
CONTINUITY_RECIPE_PATH = ROOT / "data/qa/reference_404263_full_workflows_20260825/full_candidate_edit_recipes_v2_continuity.json"
CONTINUITY_COMPOSER_PATH = ROOT / "scripts/compose_reference_404263_continuity_candidate.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plan() -> dict:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def test_full_plan_contract_is_exact_and_non_publishable() -> None:
    plan = _plan()
    assert plan["schema_version"] == "reference_404263_full_workflows/v2"
    assert plan["delivery"]["publish_allowed"] is False
    assert plan["delivery"]["douyin_upload_allowed"] is False
    assert plan["delivery"]["fanqie_backfill_allowed"] is False
    assert len(plan["beats"]) == 24
    assert round(sum(float(beat["duration"]) for beat in plan["beats"]), 2) == 103.63
    assert sum(int(beat["cut_count"]) for beat in plan["beats"]) == 72
    assert sum(beat["kind"] == "generated" for beat in plan["beats"]) == 20
    assert sum(beat["kind"] == "derived_generated" for beat in plan["beats"]) == 2


def test_controlled_workflow_uses_pose_only_move_and_splits_fragile_actions() -> None:
    plan = _plan()
    assert "controlled_wan22_animate_move_full" in plan["workflow_candidates"]
    policy = plan["motion_control_policy"]
    assert policy["engine"] == "wan2.2_animate_14b_move"
    assert policy["reference_signal"] == "pose_face_timing_only"
    assert policy["reference_pixels_allowed_in_delivery"] is False
    assert "p11_batch_money_celebration" in policy["move_scene_ranges"]
    assert set(policy["move_scene_driver_sources"]) == set(policy["move_scene_ranges"])
    for scene_id, driver in policy["move_scene_driver_sources"].items():
        driver_path = Path(driver["path"])
        if not driver_path.is_absolute():
            driver_path = ROOT / driver_path
        assert driver_path.is_file(), scene_id
        start, end = driver["range"]
        assert float(end) > float(start) >= 0.0, scene_id
    assert policy["move_scene_driver_sources"]["p04_enter_phone_room"]["path"].endswith(
        "p16_female_spending_montage.mp4"
    )
    assert "p07_learn_pipeline" in policy["deterministic_prop_scenes"]
    assert "p20_police_entry" in policy["layered_multi_person_scenes"]


def test_every_beat_has_auditable_performance_fields_and_existing_anchor() -> None:
    required = {"action", "expression", "gaze", "end_pose", "camera", "hard_reject"}
    for beat in _plan()["beats"]:
        assert required <= set(beat), beat["id"]
        assert beat["action"].strip()
        assert beat["hard_reject"]
        anchor = Path(beat["anchor"])
        if not anchor.is_absolute():
            anchor = ROOT / anchor
        assert anchor.is_file(), beat["id"]
        if beat.get("generation_anchor"):
            generation_anchor = Path(beat["generation_anchor"])
            if not generation_anchor.is_absolute():
                generation_anchor = ROOT / generation_anchor
            assert generation_anchor.is_file(), beat["id"]


def test_voice_spec_matches_all_beats_exactly_once() -> None:
    plan_ids = [beat["id"] for beat in _plan()["beats"]]
    voice = json.loads(VOICE_PATH.read_text(encoding="utf-8"))
    voice_ids = [line["scene_id"] for line in voice["lines"]]
    assert len(voice_ids) == 24
    assert len(set(voice_ids)) == 24
    assert voice_ids == plan_ids


def test_generation_prompt_does_not_execute_postproduction_cut_list() -> None:
    runner = _load_module("reference_404263_runner", RUNNER_PATH)
    beat = next(item for item in _plan()["beats"] if item["id"] == "p01_nightlife_hook")
    prompt = runner.scene_positive(beat)
    assert "no zoom" in prompt
    assert "no internal cuts" in prompt
    assert "post-production" in prompt
    assert beat["camera"] not in prompt


def test_ltx_graph_has_no_legacy_campus_prefix_and_locks_strength() -> None:
    runner = _load_module("reference_404263_runner_ltx", RUNNER_PATH)
    graph = runner.ltx_graph(
        image_name="approved.png",
        positive="original anti-fraud action",
        negative="no drift",
        seed=1,
        length=65,
        prefix="qa/test",
    )
    positive = graph["5"]["inputs"]["text"]
    assert "campus romance" not in positive.lower()
    assert "校园恋爱" not in positive
    assert graph["9"]["inputs"]["strength"] == 0.85
    assert graph["10"]["inputs"]["steps"] == 8


def test_wan_graph_uses_reviewed_stable_sampling_profile() -> None:
    runner = _load_module("reference_404263_runner_wan", RUNNER_PATH)
    graph = runner.wan_graph(
        image_name="approved.png",
        positive="constant action",
        negative="no drift",
        seed=1,
        length=49,
        prefix="qa/test",
    )
    sampler = graph["10"]["inputs"]
    assert sampler["steps"] == 20
    assert sampler["cfg"] == 4.0
    assert sampler["denoise"] == 1.0


def test_wan_animate_move_graph_uses_pose_only_and_reviewed_profile() -> None:
    runner = _load_module("reference_404263_runner_move", RUNNER_PATH)
    graph = runner.wan_animate_graph(
        image_name="original_anchor.png",
        driver_name="internal_pose_driver.mp4",
        positive="one clean step",
        negative="no extra limbs",
        seed=1,
        length=49,
        prefix="qa/test_move",
    )
    animate = graph["15"]["inputs"]
    assert animate["pose_video"] == ["14", 0]
    assert "face_video" not in animate
    assert "background_video" not in animate
    assert "character_mask" not in animate
    assert graph["16"]["inputs"]["steps"] == 6
    assert graph["16"]["inputs"]["cfg"] == 1.0


def test_incremental_render_manifest_preserves_unselected_shots() -> None:
    runner = _load_module("reference_404263_runner_manifest", RUNNER_PATH)
    report = {"shots": []}
    prior = {
        "p04_enter_phone_room": {"scene_id": "p04_enter_phone_room", "status": "rendered"},
        "p11_batch_money_celebration": {"scene_id": "p11_batch_money_celebration", "status": "rendered"},
    }
    runner.preserve_unselected_shots(report, prior, {"p11_batch_money_celebration"})
    assert report["shots"] == [prior["p04_enter_phone_room"]]


def test_controlled_candidate_uses_both_workflow_families() -> None:
    composer = _load_module("reference_404263_composer", COMPOSER_PATH)
    selected = {
        composer.selected_family(beat["id"], "controlled")
        for beat in _plan()["beats"]
        if beat["kind"] == "generated"
    }
    assert selected == {"ltx", "wan", "wan_animate"}
    assert composer.selected_family("p12_fake_illness_setup", "controlled") == "ltx"


def test_caption_wrapping_is_balanced_and_never_orphans_punctuation() -> None:
    composer = _load_module("reference_404263_composer_caption", COMPOSER_PATH)
    examples = (
        "他舍不得热一碗饭，他们只盯着到账。",
        "连生病，也只是他们安排的一场表演。",
        "直到所有人都以为，好日子不会结束。",
    )
    forbidden_line_starts = set("，。！？；：、,.!?;:")
    for example in examples:
        lines = composer.wrap_caption(example).splitlines()
        assert max(len(line) for line in lines) <= 17
        assert min(len(line) for line in lines) >= 6
        assert all(line[0] not in forbidden_line_starts for line in lines)

    plan = _plan()
    manual = {beat["id"]: beat["caption"] for beat in plan["beats"] if beat.get("caption")}
    assert "袋子，\n和镜子" in manual["p16_female_spending_montage"]
    assert "房间" in manual["p20_police_entry"].splitlines()[1]
    assert "屏幕那头" in manual["p22_victim_meets_truth"].splitlines()[1]


def test_reviewed_edit_recipes_match_beat_durations_and_cut_counts() -> None:
    plan_by_id = {beat["id"]: beat for beat in _plan()["beats"]}
    payload = json.loads(EDIT_RECIPE_PATH.read_text(encoding="utf-8"))
    assert payload["schema"] == "reference_404263_full_candidate_edit_recipes/v1"
    assert payload["publish_allowed"] is False
    for mode, recipes in payload["modes"].items():
        assert mode in {"ltx", "wan", "controlled"}
        for beat_id, recipe in recipes.items():
            beat = plan_by_id[beat_id]
            cuts = recipe["cuts"]
            assert len(cuts) == int(beat["cut_count"]), (mode, beat_id)
            assert abs(sum(float(cut["seconds"]) for cut in cuts) - float(beat["duration"])) < 0.002
            for cut in cuts:
                assert cut["type"] in {"video", "anchor"}
                if cut["type"] == "video":
                    assert cut["family"] in {"ltx", "wan", "wan_animate"}


def _continuity_recipe() -> dict:
    return json.loads(CONTINUITY_RECIPE_PATH.read_text(encoding="utf-8"))


def test_continuity_recipe_covers_every_beat_without_legacy_cut_quota() -> None:
    composer = _load_module("reference_404263_continuity_composer", CONTINUITY_COMPOSER_PATH)
    plan = _plan()
    recipe = _continuity_recipe()
    beats = composer.validate_recipe(plan, recipe, "controlled")
    mode = recipe["modes"]["controlled"]
    assert len(beats) == 24
    assert set(mode) == {beat["id"] for beat in beats}
    assert sum(len(value["cuts"]) for value in mode.values()) < 72


def test_continuity_recipe_has_no_automatic_or_long_anchor_tails() -> None:
    mode = _continuity_recipe()["modes"]["controlled"]
    all_cuts = [cut for value in mode.values() for cut in value["cuts"]]
    assert all(cut["type"] != "anchor" for cut in all_cuts)
    holds = [cut for cut in all_cuts if cut["type"] == "end_hold"]
    assert holds
    assert all(float(cut["seconds"]) <= 0.8 for cut in holds)


def test_continuity_recipe_does_not_cross_engines_inside_one_action() -> None:
    mode = _continuity_recipe()["modes"]["controlled"]
    for beat_id, value in mode.items():
        families = {cut["family"] for cut in value["cuts"] if cut["type"] == "video"}
        assert len(families) <= 1, beat_id
    assert {cut["family"] for cut in mode["p04_enter_phone_room"]["cuts"] if cut["type"] == "video"} == {"ltx"}
    assert {cut["family"] for cut in mode["p15_male_luxury"]["cuts"] if cut["type"] == "video"} == {"ltx"}
    assert {cut["family"] for cut in mode["p23_denial"]["cuts"] if cut["type"] == "video"} == {"ltx"}


def test_p07_p08_p14_use_dedicated_non_reused_sources() -> None:
    mode = _continuity_recipe()["modes"]["controlled"]
    scene_ids = []
    for beat_id in ("p07_learn_pipeline", "p08_become_proficient", "p14_batch_script_pipeline"):
        videos = [cut for cut in mode[beat_id]["cuts"] if cut["type"] == "video"]
        assert videos
        assert {cut["scene_id"] for cut in videos} == {beat_id}
        scene_ids.append(videos[0]["scene_id"])
        ranges = {
            (float(cut["start"]), float(cut["start"]) + float(cut["source_seconds"]))
            for cut in videos
        }
        assert len(ranges) == len(videos)
    assert scene_ids == ["p07_learn_pipeline", "p08_become_proficient", "p14_batch_script_pipeline"]
    assert len(set(scene_ids)) == 3


def test_p19_p20_are_adjacent_windows_with_a_continuous_source_contract() -> None:
    mode = _continuity_recipe()["modes"]["controlled"]
    p19 = mode["p19_pre_raid_pause"]["cuts"][0]
    p20 = mode["p20_police_entry"]["cuts"][0]
    assert (p19["family"], p19["scene_id"]) == (p20["family"], p20["scene_id"])
    assert abs(float(p19["start"]) + float(p19["source_seconds"]) - float(p20["start"])) < 0.0001
    assert p19["transition_out"] == "continuous_source"


def test_only_motivated_ui_inserts_interrupt_action() -> None:
    plan_by_id = {beat["id"]: beat for beat in _plan()["beats"]}
    mode = _continuity_recipe()["modes"]["controlled"]
    for beat_id, value in mode.items():
        for cut in value["cuts"]:
            if cut["type"] != "ui_insert":
                continue
            if plan_by_id[beat_id]["kind"] != "deterministic_ui":
                assert cut.get("reason")
                assert float(cut["seconds"]) <= 1.2
