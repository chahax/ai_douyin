"""Version 2 evidence acceptance: preserved theme is independent of issue count."""
from copy import deepcopy
from .creative_story_emotion import digest, validate_emotion_review


def normalize_review_evidence(review, script):
    """Return an evidence-indexed validation copy, preserving the raw model value."""
    result = deepcopy(review)
    audit = []
    refs = [ref for issue in result["full_text_review"]["issues"] for ref in issue["evidence_refs"]]
    refs += [ref for c in result["emotion_review"]["criteria"] for ref in c["evidence_refs"]]
    ids = [b["id"] for b in script["beats"]]
    if len(set(ids)) != len(ids):
        raise ValueError("ambiguous source beat identity")
    for ref in refs:
        original = ref["path"]
        parts = original.split(".")
        if (len(parts) != 6 or parts[:2] != ["script", "beats"]
                or parts[3] != "steps" or parts[5] != "text" or not parts[4].isdigit()):
            raise ValueError("review reference must point to played source text")
        if parts[2].isdigit():
            index = int(parts[2])
        elif parts[2] in ids:
            index = ids.index(parts[2])
        else:
            raise ValueError("unknown review beat reference")
        try:
            value = script["beats"][index]["steps"][int(parts[4])]["text"]
        except IndexError:
            raise ValueError("review reference index missing") from None
        if ref["quote"] != value:
            raise ValueError("review quote differs from the actual source")
        parts[2] = str(index)
        ref["path"] = ".".join(parts)
        audit.append({"original_path": original, "canonical_path": ref["path"],
                      "quote_unchanged": True})
    return result, audit


def validate_complete_review_v2(value, script, brief):
    from scripts.run_creative_emotion_revision_v1 import review_schema
    from jsonschema import Draft202012Validator
    Draft202012Validator(review_schema(script, brief)).validate(value)
    normalized, audit = normalize_review_evidence(value, script)
    full = value["full_text_review"]
    if len({i["id"] for i in full["issues"]}) != len(full["issues"]):
        raise ValueError("duplicate full-review issue")
    checkpoint = validate_emotion_review(normalized["emotion_review"], script, brief)
    if checkpoint == "needs_complete_revision" and not full["issues"]:
        raise ValueError("emotion must-fix omitted from full review")
    return {"schema": "full_emotion_review_acceptance/v2",
            "raw_review_sha256": digest(value), "script_sha256": digest(script),
            "full_review_complete": True,
            "needs_revision": bool(full["issues"]) or full["story_preserved"] is not True,
            "emotion_checkpoint": checkpoint, "reference_resolution": audit,
            "raw_review_modified": False, "creative_quality_passed": False}

