"""Full-source assignments for whole direction, independent of trial scope.

Native creative values remain untouched. Only source ownership is expanded
deterministically into the frozen v1 director contract. This is a text-only
planning contract, not script-quality approval or permission to make a film.
"""
from __future__ import annotations

from copy import deepcopy

from . import creative_video_trial_contract_v1 as base

VERSION = "creative_video_trial_direction/v2"
MAX_FILM_SECONDS = 180
RULE = base.WHOLE_DIRECTION_RULE + (
    "这是整片文本规划，不是本次只拍首段的媒体范围。source_assignments按全部来源原顺序每项归属一个segment_id。"
    "固定首段M001仅包含first_refs；其他来源继续规划M002起的全片，不遗漏。"
    "segments只写每段创作信息和时长，不复写source_refs或对白。每段4至15秒，整片目标总时长不超过180秒。"
    "本次媒体调用数、用户试拍采用和参考图片不限制整片规划覆盖。")


def _segment_ids(script):
    return [f"M{i:03d}" for i in range(1, len(base.catalog(script)) + 1)]


def whole_direction_schema(script, first_refs):
    base.opening_source(script, first_refs)
    sources = base.catalog(script)
    segment_ids = _segment_ids(script)
    assignments = []
    for ref in sources:
        assignment = base._obj({"source_ref": {"const": ref},
            "segment_id": {"const": "M001"} if ref in first_refs else {"enum": segment_ids[1:]}})
        assignments.append(assignment)
    v1_segment = base.whole_direction_schema(script)["properties"]["segments"]["items"]
    segments = []
    for segment_id in segment_ids:
        fields = {key: deepcopy(value) for key, value in v1_segment["properties"].items() if key != "source_refs"}
        fields["segment_id"] = {"const": segment_id}
        segments.append(base._obj(fields))
    fields = {key: deepcopy(value) for key, value in base.whole_direction_schema(script)["properties"].items()
              if key != "segments"}
    fields["source_assignments"] = {"type": "array", "prefixItems": assignments, "items": False,
        "minItems": len(sources), "maxItems": len(sources),
        "description": "全部来源逐项完整覆盖；首段M001只含first_refs，其余每项继续归属后续段，不能仅返回试拍两项。"}
    fields["segments"] = {"type": "array", "prefixItems": segments, "items": False,
        "minItems": 1, "maxItems": len(sources),
        "description": "M001起连续段ID，每段必须有来源归属，不能孤立创作元数据；target_seconds合计最多180秒。"}
    return base._obj(fields)


def compile_direction(raw, script, first_refs):
    """Retain all native fields; add no creative text or source rewrite."""
    base._validate(whole_direction_schema(script, first_refs), raw)
    if raw["availability"] != "known": raise ValueError("whole direction availability unknown")
    owners = {segment["segment_id"]: [] for segment in raw["segments"]}
    for row in raw["source_assignments"]:
        if row["segment_id"] not in owners:
            raise ValueError("source assignment refers to missing segment metadata")
        owners[row["segment_id"]].append(row["source_ref"])
    if any(not refs for refs in owners.values()):
        raise ValueError("orphan segment metadata has no source ownership")
    if owners["M001"] != first_refs:
        raise ValueError("M001 must own exactly the fixed first refs")
    expanded = {key: deepcopy(value) for key, value in raw.items() if key != "source_assignments"}
    expanded["segments"] = [{**{key: deepcopy(value) for key, value in segment.items() if key != "segment_id"},
        "source_refs": deepcopy(owners[segment["segment_id"]])} for segment in raw["segments"]]
    compiled_v1 = base.compile_whole_direction(expanded, script)
    total = sum(segment["target_seconds"] for segment in raw["segments"])
    if total > MAX_FILM_SECONDS:
        raise ValueError("whole direction exceeds the 180 second film planning boundary")
    return {"schema": VERSION, "script_sha256": base.digest(script), "first_refs": deepcopy(first_refs),
        "native_sha256": base.digest(raw), "native": deepcopy(raw), "expanded_v1_native": expanded,
        "compiled_v1": compiled_v1, "segments": deepcopy(compiled_v1["segments"]),
        "total_target_seconds": total, "maximum_film_seconds": MAX_FILM_SECONDS,
        "all_native_creative_values_preserved": True, "source_ownership_expansion_only": True,
        "whole_source_coverage_complete": True, "source_text_unchanged": True,
        "normal_spoken_characters_per_second": base.NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
        "timing_is_estimate": True, "measured_audio": False, "fit_scaled": False,
        "machine_script_quality": False, "actual_media_quality_passed": False}
