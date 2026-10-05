"""User intent for one production; defaults are proposals, never user approvals."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = "creative_brief/v1"
FIELDS = ("theme", "audience", "relationships", "audience_emotion", "visual_style", "turn", "ending")


def normalize_brief(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("创作简报需要 creative_brief/v1")
    if set(value) - {"schema", "title", "duration_seconds", "duration_policy", "constraints", "avoid", *FIELDS}:
        raise ValueError("创作简报包含未知字段")
    if not isinstance(value.get("theme"), str) or not value["theme"].strip():
        raise ValueError("创作简报至少需要主题 theme")
    duration = value.get("duration_seconds", [60, 100])
    if (not isinstance(duration, list) or len(duration) != 2
            or any(type(x) is not int for x in duration)
            or not 4 <= duration[0] <= duration[1] <= 600):
        raise ValueError("duration_seconds 必须是4–600秒内的闭区间")
    result = {"schema": SCHEMA, "theme": value["theme"].strip(),
              "duration_seconds": duration, "delegated_fields": []}
    if "duration_policy" in value:
        if value["duration_policy"] not in ("flexible", "strict_range"):
            raise ValueError("duration_policy 必须为 flexible 或 strict_range")
        result["duration_policy"] = value["duration_policy"]
    for key in FIELDS[1:]:
        text = value.get(key, "")
        if not isinstance(text, str):
            raise ValueError(key + " 必须是文本")
        result[key] = text.strip()
        if not result[key]:
            result["delegated_fields"].append(key)
    if "duration_seconds" not in value:
        result["delegated_fields"].append("duration_seconds")
    for key in ("constraints", "avoid"):
        rows = value.get(key, [])
        if not isinstance(rows, list) or any(not isinstance(x, str) or not x.strip() for x in rows):
            raise ValueError(key + " 必须为非空文本项的列表")
        result[key] = [x.strip() for x in rows]
    return result


def load_brief(path: Path) -> dict[str, Any]:
    return normalize_brief(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def brief_focus(brief: dict[str, Any]) -> str:
    lo, hi = brief["duration_seconds"]
    if brief.get("duration_policy") == "flexible":
        return (f"参考时长（可浮动）{lo}—{hi}秒。创作简报："
                + json.dumps(brief, ensure_ascii=False, sort_keys=True)
                + "。优先完整表达情绪、事件和画面；按实际对白、刺激与反应安排秒数，总长可随内容浮动，"
                "不为靠近参考范围删掉必要表演或增加填充动作。画风仍按简报；明确的局部时序要求仍生效。")
    return (f"目标时长{lo}—{hi}秒。创作简报："
            + json.dumps(brief, ensure_ascii=False, sort_keys=True)
            + "。空白字段由编剧导演提出方案，不冒充用户已确定；先明确镜头信息与人物反应，"
            "删除无叙事作用的操作；画风和时长已有值时不得擅自改动。")


def focus_duration_is_flexible(focus: str) -> bool:
    """Read the typed policy from generated brief focus, not incidental prose."""
    if not isinstance(focus,str):
        return False
    for line in focus.splitlines():
        if not line.startswith("参考时长（可浮动）") or "创作简报：" not in line:
            continue
        try:
            brief,_ = json.JSONDecoder().raw_decode(line.split("创作简报：",1)[1])
        except (ValueError,TypeError):
            continue
        if isinstance(brief,dict) and brief.get("schema")==SCHEMA:
            return brief.get("duration_policy")=="flexible"
    return False
