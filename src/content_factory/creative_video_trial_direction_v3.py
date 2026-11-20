"""Whole-film direction by model-chosen cut endpoints, not copied source lists.

The frozen source supplies contiguous ranges. Native creative values and all
cut endpoints are preserved, never patched or supplemented by this compiler.
"""
from __future__ import annotations

from copy import deepcopy

from . import creative_video_trial_contract_v1 as base

VERSION = "creative_video_trial_direction/v3"
MAX_FILM_SECONDS = 180
RULE = base.WHOLE_DIRECTION_RULE + (
    "只提交opening的创作字段和remaining_segments逐段创作字段及end_source_ref，不抄全文source清单或段ID。"
    "opening固定使用first_refs；每个end_source_ref是下一段的最后一个完整来源，必须严格向后推进，最后到全文最后来源。"
    "程序按连续原文切片展开归属；它不会补缺段、增加尾声、移动模型切点或缩短原对白。"
    "段数由本次整片创作决定；每段4至15秒，整片总目标不超过180秒。")


def _source_ranges(script, first_refs):
    base.opening_source(script, first_refs)
    ordered = list(base.catalog(script))
    remaining = ordered[len(first_refs):]
    if not remaining:
        raise ValueError("whole direction endpoint wire requires remaining sources beyond opening")
    return ordered, remaining


def whole_direction_schema(script, first_refs):
    _, remaining = _source_ranges(script, first_refs)
    old = base.whole_direction_schema(script)
    creative = {key: deepcopy(value) for key, value in old["properties"]["segments"]["items"]["properties"].items()
                if key != "source_refs"}
    rest = {**deepcopy(creative), "end_source_ref": {"enum": remaining}}
    rest["end_source_ref"]["description"] = "本段最后一个完整来源；严格晚于上一段终点，最后一段必须到全文最后来源。"
    fields = {key: deepcopy(value) for key, value in old["properties"].items() if key != "segments"}
    fields["opening"] = base._obj(creative)
    fields["remaining_segments"] = {"type": "array", "minItems": 1, "maxItems": len(remaining),
        "items": base._obj(rest), "description": "模型决定切点与段数，不复写source列表；全部target_seconds连同opening合计最多180秒。"}
    return base._obj(fields)


def compile_direction(raw, script, first_refs):
    base._validate(whole_direction_schema(script, first_refs), raw)
    if raw["availability"] != "known": raise ValueError("whole direction availability unknown")
    ordered, _ = _source_ranges(script, first_refs)
    cursor = len(first_refs)
    segments = [{**deepcopy(raw["opening"]), "source_refs": deepcopy(first_refs)}]
    for segment in raw["remaining_segments"]:
        end = ordered.index(segment["end_source_ref"]) + 1
        if end <= cursor:
            raise ValueError("cut endpoint must strictly advance; no duplicate or reversed endpoint")
        segments.append({**{key: deepcopy(value) for key, value in segment.items() if key != "end_source_ref"},
            "source_refs": ordered[cursor:end]})
        cursor = end
    if cursor != len(ordered):
        raise ValueError("last cut endpoint must reach the final full source; no missing tail or automatic epilogue")
    expanded = {key: deepcopy(value) for key, value in raw.items() if key not in ("opening", "remaining_segments")}
    expanded["segments"] = segments
    compiled = base.compile_whole_direction(expanded, script)
    total = sum(segment["target_seconds"] for segment in segments)
    if total > MAX_FILM_SECONDS:
        raise ValueError("whole direction exceeds the 180 second film planning boundary")
    return {"schema": VERSION, "script_sha256": base.digest(script), "first_refs": deepcopy(first_refs),
        "native": deepcopy(raw), "native_sha256": base.digest(raw), "expanded_v1_native": expanded,
        "compiled_v1": compiled, "segments": deepcopy(compiled["segments"]),
        "total_target_seconds": total, "maximum_film_seconds": MAX_FILM_SECONDS,
        "native_cut_endpoints": [row["end_source_ref"] for row in raw["remaining_segments"]],
        "all_native_creative_values_preserved": True, "source_ownership_expansion_only": True,
        "whole_source_coverage_complete": True, "source_text_unchanged": True,
        "normal_spoken_characters_per_second": base.NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
        "timing_is_estimate": True, "measured_audio": False, "fit_scaled": False,
        "machine_script_quality": False, "actual_media_quality_passed": False}
