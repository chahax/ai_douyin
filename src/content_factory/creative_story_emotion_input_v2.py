"""Full source brief is mandatory; emotion notes extend it, never replace it."""
from copy import deepcopy
import json
from .creative_story_emotion import build_emotion_revision_input, digest


def validate_original_brief(value):
    if not isinstance(value, dict):
        raise ValueError("original creative brief is required")
    for k in ("theme", "relationships", "audience_emotion", "visual_style", "turn", "ending"):
        if not isinstance(value.get(k), str) or not value[k].strip():
            raise ValueError("original brief missing " + k)
    for k in ("constraints", "avoid"):
        if (not isinstance(value.get(k), list) or not value[k]
                or any(not isinstance(x, str) or not x.strip() for x in value[k])):
            raise ValueError("original brief missing complete " + k)


def build_complete_revision_input(previous_script, emotional_brief, reference_pack,
                                  feedback, *, creative_brief):
    validate_original_brief(creative_brief)
    value = build_emotion_revision_input(previous_script, emotional_brief, reference_pack, feedback)
    context = json.loads(value["messages"][1]["content"])
    context["creative_brief"] = deepcopy(creative_brief)
    value["messages"][1]["content"] = json.dumps(context, ensure_ascii=False)
    value["messages"][0]["content"] += (
        "creative_brief是完整原始要求，emotional_brief只是补充；"
        "不能用补充简报覆盖或删去原constraints、avoid、关系风险、转折和结尾。"
        "必须在正文兑现过去反复帮忙的证据；不能用摸包或捏票代替这一历史。")
    value["bindings"]["creative_brief_sha256"] = digest(creative_brief)
    value["schema"] = "complete_emotion_revision_input/v2"
    value["original_brief_preserved"] = True
    return value


def build_complete_review_context(script, emotional_brief, reference_pack,
                                  feedback, *, creative_brief):
    validate_original_brief(creative_brief)
    return {"script": deepcopy(script), "creative_brief": deepcopy(creative_brief),
            "emotional_brief": deepcopy(emotional_brief), "reference_pack": deepcopy(reference_pack),
            "feedback": deepcopy(feedback),
            "source_text_paths": [f"script.beats.{i}.steps.{j}.text"
                for i, b in enumerate(script["beats"]) for j, _ in enumerate(b["steps"])]}

