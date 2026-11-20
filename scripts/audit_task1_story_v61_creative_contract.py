from __future__ import annotations

"""Read-only creative-contract audit for the reviewed V6.1 story plan."""

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


SCHEMA = "fanqie_v61_creative_contract_audit/v1"
EXPECTED_SCHEMA = "fanqie_performance_story_plan/v1"
EXPECTED_BOOK_ID = "7656344274241326104"
EXPECTED_ALIAS = "我闭着眼睛玩"
EXPECTED_BEAT_IDS = (
    "b01_boast", "b02_grab_reaction", "b03_object_question",
    "b04_confused_answer", "b05_age_burst", "b06_pull_away",
    "b07_protest", "b08_offer_one", "b09_offer_two", "b10_offer_three",
    "b11_flip", "b12_car_reveal", "b13_registry_reveal", "b14_certificate",
    "b15_terms", "b16_escape", "b17a_kiss_reaction", "b17b_hunt_order",
    "b18_cta",
)
CTA_ID = "b18_cta"
FORBIDDEN_TEXT_TERMS = (
    "旁白", "本书讲述", "故事开始", "接下来", "接着看", "且听", "欲知后事",
)
FORBIDDEN_VISUAL_TERMS = (
    "anime", "cartoon", "chibi", "presenter", "digital human",
    "talking head", "anchor host", "mascot", "plush toy",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _count_text_weight(text: str) -> int:
    """Match production CJK/Latin dialogue-weight counting exactly."""
    count = 0
    index = 0
    while index < len(text):
        codepoint = ord(text[index])
        is_cjk = (
            0x4E00 <= codepoint <= 0x9FFF
            or 0x3400 <= codepoint <= 0x4DBF
            or 0xF900 <= codepoint <= 0xFAFF
            or 0x3040 <= codepoint <= 0x309F
            or 0x30A0 <= codepoint <= 0x30FF
            or 0xAC00 <= codepoint <= 0xD7AF
        )
        if is_cjk:
            count += 1
            index += 1
        elif text[index].isalpha() and codepoint < 128:
            count += 1
            while (
                index < len(text)
                and text[index].isalpha()
                and ord(text[index]) < 128
            ):
                index += 1
        else:
            index += 1
    return count


def audit(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("plan root must be a JSON object")
    beats = data.get("beats")
    cast = data.get("cast")
    creative = data.get("creative_contract")
    if not isinstance(beats, list) or not isinstance(cast, dict) or not isinstance(creative, dict):
        raise ValueError("plan must contain beats list, cast object and creative_contract")

    if data.get("schema_version") != EXPECTED_SCHEMA:
        errors.append("schema_version mismatch")
    if str(data.get("source_book_id")) != EXPECTED_BOOK_ID:
        errors.append("source_book_id mismatch")
    if data.get("promotion_alias") != EXPECTED_ALIAS:
        errors.append("promotion_alias mismatch")
    if data.get("publish_allowed") is not False:
        errors.append("plan publish_allowed must remain false")
    if creative.get("visual_style") != "photorealistic_live_action":
        errors.append("visual style must be photorealistic_live_action")
    if creative.get("explanatory_narration_allowed") is not False:
        errors.append("explanatory narration must be forbidden")
    if creative.get("voiceover_cta_only") is not True:
        errors.append("voiceover must be restricted to final CTA")
    if creative.get("voiceover_allowed") is not False:
        errors.append("off-camera voiceover must be forbidden")
    if creative.get("cta_delivery_mode") != "on_camera_character":
        errors.append("creative contract CTA delivery must be on_camera_character")

    ids = [str(beat.get("id") or "") for beat in beats if isinstance(beat, dict)]
    if ids != list(EXPECTED_BEAT_IDS):
        errors.append("beat IDs/order do not exactly match the reviewed 19-beat story")
    durations: list[float] = []
    spoken_count = 0
    silent_action_count = 0
    dialogue_weight = 0
    cta_weight = 0
    action_and_emotion_count = 0
    unique_voice_refs: set[str] = set()
    emotion_voice_count = 0
    material_evidence: dict[str, list[dict[str, Any]]] = {
        "anchors": [], "character_masters": [], "voice_references": [],
    }

    for character_id, cfg in cast.items():
        if not isinstance(cfg, dict):
            errors.append(f"cast {character_id}: config must be object")
            continue
        raw_age = cfg.get("age")
        age = raw_age if isinstance(raw_age, int) and not isinstance(raw_age, bool) else 0
        if cfg.get("adult") is not True or age < 18:
            errors.append(f"cast {character_id}: must be explicitly adult")
        voice_reference = str(cfg.get("voice_reference") or "")
        voice_engine = str(cfg.get("voice_engine") or "")
        instruct = str(cfg.get("instruct") or "")
        if not voice_reference or not Path(voice_reference).is_file():
            errors.append(f"cast {character_id}: fixed voice reference missing")
        else:
            unique_voice_refs.add(str(Path(voice_reference).resolve()).lower())
            expected_voice_sha = str(cfg.get("voice_reference_sha256") or "").upper()
            actual_voice_sha = _sha256(Path(voice_reference))
            voice_ok = bool(expected_voice_sha) and actual_voice_sha == expected_voice_sha
            material_evidence["voice_references"].append({
                "character_id": character_id, "path": str(Path(voice_reference).resolve()),
                "expected_sha256": expected_voice_sha, "actual_sha256": actual_voice_sha,
                "ok": voice_ok,
            })
            if not voice_ok:
                errors.append(f"cast {character_id}: voice reference SHA-256 mismatch")
        master_path = Path(str(cfg.get("master_image") or ""))
        expected_master_sha = str(cfg.get("master_sha256") or "").upper()
        actual_master_sha = _sha256(master_path) if master_path.is_file() else ""
        master_ok = bool(expected_master_sha) and actual_master_sha == expected_master_sha
        material_evidence["character_masters"].append({
            "character_id": character_id, "path": str(master_path),
            "expected_sha256": expected_master_sha, "actual_sha256": actual_master_sha,
            "ok": master_ok,
        })
        if not master_ok:
            errors.append(f"cast {character_id}: character master SHA-256 mismatch")
        if "CosyVoice3" not in voice_engine or "instruct2" not in voice_engine:
            errors.append(f"cast {character_id}: emotion-capable CosyVoice3 instruct2 required")
        if not instruct or "避免播音腔" not in instruct:
            errors.append(f"cast {character_id}: natural-speech anti-announcer instruction missing")
    if len(unique_voice_refs) != len(cast):
        errors.append("each cast member must have a unique fixed voice reference")

    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            errors.append(f"beat {index}: must be object")
            continue
        scene_id = str(beat.get("id") or f"index-{index}")
        try:
            duration = float(beat.get("duration_target_seconds"))
        except (TypeError, ValueError):
            errors.append(f"{scene_id}: invalid duration")
            continue
        durations.append(duration)
        if duration < 1.2 or duration > 4.0:
            errors.append(f"{scene_id}: duration outside 1.2-4.0 seconds")
        action = str(beat.get("visible_action") or "").strip()
        emotion = str(beat.get("emotion") or "").strip()
        camera = str(beat.get("camera") or "").strip()
        text = str(beat.get("text") or "").strip()
        speaker = str(beat.get("speaker") or "").strip()
        instruct = str(beat.get("instruct") or "").strip()
        prompt_surface = f"{action} {camera}".lower()
        if not action or not emotion or not camera:
            errors.append(f"{scene_id}: visible action, readable emotion and camera are required")
        else:
            action_and_emotion_count += 1
        forbidden_visual = [term for term in FORBIDDEN_VISUAL_TERMS if term in prompt_surface]
        for term in forbidden_visual:
            errors.append(f"{scene_id}: source action/camera contains forbidden visual term {term!r}")
        anchor_path = Path(str(beat.get("shot_anchor_image") or ""))
        expected_anchor_sha = str(beat.get("shot_anchor_sha256") or "").upper()
        actual_anchor_sha = _sha256(anchor_path) if anchor_path.is_file() else ""
        anchor_ok = bool(expected_anchor_sha) and actual_anchor_sha == expected_anchor_sha
        material_evidence["anchors"].append({
            "scene_id": scene_id, "path": str(anchor_path),
            "expected_sha256": expected_anchor_sha, "actual_sha256": actual_anchor_sha,
            "ok": anchor_ok,
        })
        if not anchor_ok:
            errors.append(f"{scene_id}: reviewed anchor SHA-256 mismatch")
        if text:
            spoken_count += 1
            if not speaker or speaker not in cast:
                errors.append(f"{scene_id}: every spoken beat must use a cast speaker")
            if not instruct or not emotion:
                errors.append(f"{scene_id}: spoken beat lacks emotion/instruct")
            raw_speed = beat.get("speed")
            speed = (
                float(raw_speed)
                if isinstance(raw_speed, (int, float)) and not isinstance(raw_speed, bool)
                else 0.0
            )
            if speed < 0.95 or speed > 1.20:
                errors.append(f"{scene_id}: performance speed outside 0.95-1.20")
            elif instruct and emotion:
                emotion_voice_count += 1
            forbidden_text = [term for term in FORBIDDEN_TEXT_TERMS if term in text]
            if forbidden_text:
                errors.append(f"{scene_id}: explanatory narration marker found")
            if scene_id == CTA_ID:
                if beat.get("beat_type") != "promotional_cta":
                    errors.append(f"{scene_id}: final CTA must be explicitly typed promotional_cta")
                if beat.get("delivery_mode") != "on_camera_character":
                    errors.append(f"{scene_id}: final CTA must be delivered on camera by a character")
                cta_weight += _count_text_weight(text)
            else:
                dialogue_weight += _count_text_weight(text)
        else:
            if speaker:
                errors.append(f"{scene_id}: speaker set on silent beat")
            if not action:
                errors.append(f"{scene_id}: silent beat must still be action-driven")
            silent_action_count += 1

    total_duration = round(sum(durations), 3)
    median_duration = statistics.median(durations) if durations else 0.0
    if abs(total_duration - float(data.get("estimated_total_seconds") or 0)) > 0.05:
        errors.append("estimated total does not match beat sum")
    if total_duration > 45.0:
        errors.append("story exceeds 45 seconds")
    if median_duration > 2.8:
        errors.append("median shot duration exceeds 2.8 seconds")
    if action_and_emotion_count != len(beats):
        errors.append("every beat must have action and emotion")
    if spoken_count < 17 or silent_action_count < 1:
        errors.append("story must be dialogue-led with at least one silent action beat")
    spoken_weight = dialogue_weight + cta_weight
    dialogue_ratio = dialogue_weight / spoken_weight if spoken_weight else 0.0
    if dialogue_ratio < 0.85:
        errors.append("character dialogue ratio excluding CTA is below 85%")

    return {
        "schema_version": SCHEMA,
        "plan_path": str(path.resolve()),
        "plan_sha256": _sha256(path),
        "passed": not errors,
        "errors": errors,
        "requirements": {
            "photorealistic_live_action": creative.get("visual_style") == "photorealistic_live_action",
            "no_explanatory_narration": creative.get("explanatory_narration_allowed") is False,
            "character_dialogue_driven": dialogue_ratio >= 0.85,
            "every_beat_action_and_emotion": action_and_emotion_count == len(beats),
            "emotion_voice_configuration_per_spoken_beat": emotion_voice_count == spoken_count,
            "fixed_distinct_character_voice_assets": len(unique_voice_refs) == len(cast),
            "tight_rhythm": median_duration <= 2.8 and total_duration <= 45.0,
            "publish_closed": data.get("publish_allowed") is False,
        },
        "human_quality_gates": {
            "natural_emotional_voice_proven": False,
            "natural_emotional_voice_requires_frontend_smoke_review": True,
            "whole_video_natural_voice_requires_frontend_final_review": True,
            "static_configuration_is_not_naturalness_proof": True,
        },
        "material_evidence": material_evidence,
        "metrics": {
            "beat_count": len(beats),
            "spoken_beat_count": spoken_count,
            "silent_action_beat_count": silent_action_count,
            "total_seconds": total_duration,
            "median_shot_seconds": median_duration,
            "maximum_shot_seconds": max(durations) if durations else 0.0,
            "dialogue_character_weight": dialogue_weight,
            "cta_weight": cta_weight,
            "dialogue_ratio_excluding_cta": round(dialogue_ratio, 6),
        },
        "side_effects": {
            "tts": 0, "gpu": 0, "database_writes": 0,
            "browser": 0, "upload": 0, "backfill": 0,
        },
    }


def _write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise ValueError(f"refusing to overwrite creative audit: {path}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit V6.1 creative contract read-only.")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.plan.resolve())
        _write_exclusive(args.output.resolve(), result)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
