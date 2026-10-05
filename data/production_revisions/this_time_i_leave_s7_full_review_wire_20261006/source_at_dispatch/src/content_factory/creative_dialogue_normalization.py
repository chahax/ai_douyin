"""Lossless normalization of misplaced timing annotations in dialogue locks."""
from copy import deepcopy
import math


def normalize_dialogue_lock_timing(value, script):
    """Remove only valid start/end annotations when every locked dialogue is exact."""
    original = deepcopy(value)
    result = deepcopy(value)
    changes = []
    if not isinstance(result, dict) or not isinstance(script, dict):
        return original, []
    beats, shots = script.get("beats"), result.get("shots")
    if not isinstance(beats, list) or not isinstance(shots, list):
        return original, []
    try:
        expected = {b["id"]: b["dialogue"] for b in beats}
    except (KeyError, TypeError):
        return original, []
    if len(expected) != len(beats) or any(not isinstance(d, list) for d in expected.values()):
        return original, []
    actual = {key: [] for key in expected}
    for shot_index, shot in enumerate(shots):
        if not isinstance(shot, dict) or shot.get("beat_id") not in expected or not isinstance(shot.get("dialogue_lock"), list):
            return original, []
        for line_index, line in enumerate(shot["dialogue_lock"]):
            if not isinstance(line, dict) or not {"speaker", "text"} <= set(line):
                return original, []
            extras = set(line) - {"speaker", "text"}
            if extras:
                if extras != {"start", "end"}:
                    return original, []
                start, end = line["start"], line["end"]
                if any(type(t) not in (int, float) or not math.isfinite(t) for t in (start, end)):
                    return original, []
                if not 0 <= start < end:
                    return original, []
                duration = shot.get("duration_seconds")
                if type(duration) in (int, float) and end > duration:
                    return original, []
                changes.append({"path": f"shots.{shot_index}.dialogue_lock.{line_index}",
                                "removed_timing": {"start": start, "end": end}})
                del line["start"]
                del line["end"]
            actual[shot["beat_id"]].append(deepcopy(line))
    if actual != expected:
        return original, []
    return result, changes
