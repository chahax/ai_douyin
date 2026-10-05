"""Compile a reconstructed-video analysis document into model-ready prompts.

The compiler is deliberately deterministic.  It turns the project's Markdown
analysis format into a prompt contract without requiring another LLM call.  A
later adapter can translate or reshape the prompts for a specific provider.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "analysis_video_prompt_pack/v1"
DEFAULT_STYLE = "现实主义电影质感的竖屏剧情短片，克制表演，自然光，真实皮肤和材质"
DEFAULT_NEGATIVE_PROMPT = (
    "不要可读文字、字幕、水印、平台标志或伪造手机界面；不要内部切镜、推拉变焦、"
    "甩镜或无意图的运镜；不要多人脸融合、身份漂移、服装变化、多余肢体、手指畸形、"
    "道具穿模、动作循环、瞬移、表情突变、口型乱动、背景闪烁或画面抖动。"
)
NATIVE_FULL_VIDEO_NEGATIVE_PROMPT = (
    "除提示词明确指定的中文字幕和手机界面文字外，不要生成任何额外文字、水印或平台标志；"
    "指定文字必须使用简体中文、字形清晰、内容准确、位置稳定。不要口型与声音不同步、"
    "多人脸融合、身份漂移、服装变化、多余肢体、手指畸形、道具穿模、动作循环、瞬移、"
    "表情突变、背景闪烁、画面抖动、音频爆音、重复对白或环境声突变。"
)
PRODUCTION_MODES = {"postproduction", "native_full_video"}

_TIME_RANGE_RE = re.compile(
    r"(?P<start>\d+(?:\.\d+)?)\s*[–—-]\s*(?P<end>\d+(?:\.\d+)?)\s*(?:s|秒)?",
    re.IGNORECASE,
)
_UI_TERMS = (
    "手机界面",
    "手机屏幕",
    "屏幕",
    "聊天界面",
    "转账",
    "收款",
    "金额",
    "余额",
    "账单",
    "流水",
    "新闻标题",
    "字幕",
    "文字",
)
_MULTI_PERSON_TERMS = (
    "两名",
    "二人",
    "三人",
    "多人",
    "一行人",
    "警察",
    "警方",
    "围住",
    "抓捕",
    "押走",
)


class AnalysisPromptPackError(ValueError):
    """Raised when the source document does not satisfy the input contract."""


def compile_analysis_prompt_pack(
    document_path: str | Path,
    *,
    output_path: str | Path | None = None,
    markdown_path: str | Path | None = None,
    style: str = DEFAULT_STYLE,
    model_profile: str = "generic-image-to-video",
    production_mode: str = "postproduction",
    generation_min_seconds: float = 2.0,
    generation_max_seconds: float = 5.0,
) -> dict[str, Any]:
    """Compile an analysis Markdown file into a structured prompt pack.

    The expected source contains ``角色``, ``表情、动作与表演节拍`` and
    ``逐镜头复刻表`` sections.  The first two are optional; the shot table is
    required because it is the segment boundary contract.
    """

    if generation_min_seconds <= 0:
        raise AnalysisPromptPackError("generation_min_seconds must be greater than zero")
    if generation_max_seconds < generation_min_seconds:
        raise AnalysisPromptPackError(
            "generation_max_seconds must be greater than or equal to generation_min_seconds"
        )
    if production_mode not in PRODUCTION_MODES:
        raise AnalysisPromptPackError(
            f"unsupported production_mode {production_mode!r}; expected one of {sorted(PRODUCTION_MODES)}"
        )

    source_path = Path(document_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    text = source_path.read_text(encoding="utf-8-sig")

    title = _extract_title(text) or source_path.stem
    summary = _parse_summary(_extract_section(text, "视频内容总结"))
    roles = _normalise_roles(_parse_markdown_table(_extract_section(text, "角色")))
    performances = _normalise_performances(
        _parse_markdown_table(_extract_section(text, "表情、动作与表演节拍"))
    )
    locations_and_props = _parse_bullets(_extract_section(text, "场景和关键道具"))
    shot_rows = _parse_markdown_table(_extract_section(text, "逐镜头复刻表"))
    shots = _normalise_shots(shot_rows)
    if not shots:
        raise AnalysisPromptPackError(
            "missing or empty '逐镜头复刻表'; expected columns 镜头、时间、画面与机位、台词/字幕、叙事作用"
        )

    segment_prompts = [
        _build_segment(
            shot,
            roles=roles,
            performances=performances,
            style=style,
            production_mode=production_mode,
            generation_min_seconds=generation_min_seconds,
            generation_max_seconds=generation_max_seconds,
        )
        for shot in shots
    ]

    pack: dict[str, Any] = {
        "schema": SCHEMA,
        "source_document": str(source_path),
        "title": title,
        "model_profile": model_profile,
        "production_mode": production_mode,
        "global": {
            "format": "vertical 9:16 narrative short video",
            "style_zh": style,
            "summary": summary,
            "character_bible": roles,
            "locations_and_props": locations_and_props,
            "continuity_rules_zh": [
                "所有分段锁定同一角色身份、发型、年龄、服装、配饰和体型。",
                "同一场景锁定空间方向、光线方向、时间和关键道具位置。",
                "每个生成片段只完成一个连续微动作，动作结束后稳定停住。",
                "切镜、景别变化、手机界面、字幕和可读文字全部在后期完成。",
                "后一个片段的起始姿态必须能承接前一个片段的结束姿态。",
            ],
            "negative_prompt_zh": _negative_prompt_for_mode(production_mode),
        },
        "segment_count": len(segment_prompts),
        "source_duration_seconds": round(max(shot["end_seconds"] for shot in shots), 3),
        "segments": segment_prompts,
    }

    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(pack, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if markdown_path is not None:
        destination = Path(markdown_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render_prompt_pack_markdown(pack), encoding="utf-8")
    return pack


def render_prompt_pack_markdown(pack: dict[str, Any]) -> str:
    """Render a prompt pack as a review-friendly Markdown document."""

    lines = [
        f"# {pack['title']}：视频大模型分段提示词包",
        "",
        f"- 协议：`{pack['schema']}`",
        f"- 模型配置：`{pack['model_profile']}`",
        f"- 分段数：{pack['segment_count']}",
        f"- 源片时长：{pack['source_duration_seconds']:.2f} 秒",
        "",
        "## 使用原则",
        "",
        (
            "每段提示词对应一个源镜头。模型在本段内直接生成画面、对白、口型、字幕和"
            "可见界面；分段完成后只需依次组装。"
            if pack.get("production_mode") == "native_full_video"
            else "每段提示词对应一个源镜头，但生成视频内部不得切镜。先生成角色和动作，"
            "再在剪辑阶段恢复源片的镜头顺序、时长、字幕、对白和手机界面。"
        ),
        "",
        "## 全局负面提示词",
        "",
        pack["global"]["negative_prompt_zh"],
        "",
        "## 分段索引",
        "",
        "| 段落 | 源时间 | 生成时长 | 路线 | 叙事作用 |",
        "|---|---:|---:|---|---|",
    ]
    for segment in pack["segments"]:
        source_time = f"{segment['source']['start_seconds']:.2f}–{segment['source']['end_seconds']:.2f}s"
        purpose = str(segment["source"]["narrative_purpose"]).replace("|", "\\|")
        lines.append(
            f"| {segment['id']} | {source_time} | {segment['generation']['duration_seconds']:.2f}s "
            f"| {segment['generation']['route']} | {purpose} |"
        )

    for segment in pack["segments"]:
        lines.extend(
            [
                "",
                f"## {segment['id']}｜源镜头 {segment['source']['shot_number']}",
                "",
                f"- 源时间：{segment['source']['start_seconds']:.2f}–{segment['source']['end_seconds']:.2f} 秒",
                f"- 生成路线：`{segment['generation']['route']}`",
                f"- 建议生成时长：{segment['generation']['duration_seconds']:.2f} 秒",
                f"- 台词/字幕（{'模型原生' if pack.get('production_mode') == 'native_full_video' else '后期'}）："
                f"{segment['postproduction']['dialogue_or_caption'] or '无'}",
                "",
                "### 首帧提示词",
                "",
                segment["prompts"]["keyframe_prompt_zh"],
                "",
                "### 动作提示词",
                "",
                segment["prompts"]["motion_prompt_zh"],
                "",
                "### 可直接提交的视频提示词",
                "",
                segment["prompts"]["video_prompt_zh"],
                "",
            ]
        )
        if segment["warnings"]:
            lines.extend(["### 制作提醒", ""])
            lines.extend(f"- {warning}" for warning in segment["warnings"])

    return "\n".join(lines).rstrip() + "\n"


def _extract_title(text: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


def _extract_section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^##\s+{re.escape(name)}\s*$", text)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"(?m)^##\s+", text[start:])
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def _parse_markdown_table(section: str) -> list[dict[str, str]]:
    table_lines: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines.append(stripped)
        elif table_lines:
            break
    if len(table_lines) < 2:
        return []

    rows = [_split_table_row(line) for line in table_lines]
    headers = rows[0]
    data_start = 2 if len(rows) > 1 and _is_separator_row(rows[1]) else 1
    result: list[dict[str, str]] = []
    for values in rows[data_start:]:
        if len(values) < len(headers):
            values += [""] * (len(headers) - len(values))
        result.append(dict(zip(headers, values[: len(headers)])))
    return result


def _split_table_row(line: str) -> list[str]:
    # The project's tables do not use escaped pipes as semantic cell content.
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_row(values: Iterable[str]) -> bool:
    return all(bool(re.fullmatch(r":?-{3,}:?", value.strip())) for value in values)


def _parse_time_range(value: str) -> tuple[float, float]:
    match = _TIME_RANGE_RE.search(value)
    if not match:
        raise AnalysisPromptPackError(f"invalid time range: {value!r}")
    start = float(match.group("start"))
    end = float(match.group("end"))
    if end <= start:
        raise AnalysisPromptPackError(f"time range end must be after start: {value!r}")
    return start, end


def _parse_summary(section: str) -> dict[str, str]:
    if not section:
        return {}
    matches = list(re.finditer(r"(?m)^###\s+(.+?)\s*$", section))
    summary: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        body = _clean_markdown_text(section[start:end])
        if body:
            summary[match.group(1).strip()] = body
    if not summary:
        body = _clean_markdown_text(section)
        if body:
            summary["概述"] = body
    return summary


def _parse_bullets(section: str) -> list[str]:
    bullets: list[str] = []
    for line in section.splitlines():
        match = re.match(r"\s*[-*]\s+(.+)", line)
        if match:
            bullets.append(_clean_markdown_text(match.group(1)))
    return bullets


def _clean_markdown_text(value: str) -> str:
    value = re.sub(r"[`*_]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _normalise_roles(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        name = _first_value(row, "角色", "人物", "姓名")
        if not name:
            continue
        result.append(
            {
                "name": _clean_markdown_text(name),
                "story_function": _clean_markdown_text(_first_value(row, "功能", "人物功能")),
                "performance_keywords": _clean_markdown_text(
                    _first_value(row, "表演关键词", "表演", "关键词")
                ),
            }
        )
    return result


def _normalise_performances(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        time_value = _first_value(row, "时间", "时间段")
        if not time_value:
            continue
        start, end = _parse_time_range(time_value)
        result.append(
            {
                "start_seconds": start,
                "end_seconds": end,
                "character": _clean_markdown_text(_first_value(row, "角色", "人物")),
                "expression": _clean_markdown_text(_first_value(row, "表情")),
                "action_and_gaze": _clean_markdown_text(
                    _first_value(row, "动作与视线", "动作", "动作/视线")
                ),
                "performance_purpose": _clean_markdown_text(
                    _first_value(row, "表演目的", "目的")
                ),
            }
        )
    return result


def _normalise_shots(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        time_value = _first_value(row, "时间", "时间段")
        visual = _first_value(row, "画面与机位", "画面", "镜头画面")
        if not time_value or not visual:
            continue
        start, end = _parse_time_range(time_value)
        shot_number = _clean_markdown_text(_first_value(row, "镜头", "编号") or str(index))
        result.append(
            {
                "shot_number": shot_number,
                "start_seconds": start,
                "end_seconds": end,
                "visual_and_camera": _clean_markdown_text(visual),
                "dialogue_or_caption": _clean_markdown_text(
                    _first_value(row, "台词/字幕", "台词", "对白/字幕")
                ),
                "narrative_purpose": _clean_markdown_text(
                    _first_value(row, "叙事作用", "作用", "功能")
                ),
            }
        )
    result.sort(key=lambda shot: (shot["start_seconds"], shot["end_seconds"]))
    return result


def _first_value(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key, "")
        if value:
            return value
    return ""


def _build_segment(
    shot: dict[str, Any],
    *,
    roles: list[dict[str, str]],
    performances: list[dict[str, Any]],
    style: str,
    production_mode: str,
    generation_min_seconds: float,
    generation_max_seconds: float,
) -> dict[str, Any]:
    source_duration = shot["end_seconds"] - shot["start_seconds"]
    spoken_lines = _extract_spoken_lines(shot["dialogue_or_caption"])
    required_duration = source_duration
    if production_mode == "native_full_video" and spoken_lines:
        required_duration = max(required_duration, _estimate_dialogue_duration(spoken_lines))
    generation_duration = min(max(required_duration, generation_min_seconds), generation_max_seconds)
    haystack = " ".join(
        [
            shot["visual_and_camera"],
            shot["dialogue_or_caption"],
            shot["narrative_purpose"],
        ]
    )
    participants = _infer_participants(haystack, roles)
    performance = _match_performance(shot, performances)
    # Generation routing must be based on what is visibly present.  Dialogue
    # such as "转了一万二" or a narrative-purpose note mentioning an amount
    # does not mean that this shot actually contains a readable UI insert.
    route, warnings = _classify_generation_route(shot["visual_and_camera"])

    role_lock = "；".join(
        f"{role['name']}（{role['performance_keywords'] or role['story_function']}）"
        for role in roles
        if role["name"] in participants
    )
    if not role_lock:
        role_lock = "延续角色设定表中的外形、服装与身份"

    expression = performance.get("expression") or "自然、克制并符合当前剧情"
    action_and_gaze = performance.get("action_and_gaze") or shot["visual_and_camera"]
    performance_purpose = performance.get("performance_purpose") or shot["narrative_purpose"]

    native_full_video = production_mode == "native_full_video"
    if native_full_video and route == "deterministic_ui_composite":
        warnings = [
            "该镜头要求模型原生生成可读界面；目标模型必须支持稳定的简体中文和数字渲染。"
        ]
    elif native_full_video and route == "layered_multi_person_composite":
        warnings = [
            "该镜头要求模型原生完成多人互动；目标模型必须支持稳定的多人身份和遮挡关系。"
        ]
    generation_route = route
    if native_full_video:
        generation_route = {
            "deterministic_ui_composite": "native_full_video_ui",
            "layered_multi_person_composite": "native_full_video_multi_person",
            "single_shot_image_to_video": "native_full_video_single_shot",
        }[route]
    ui_instruction = ""
    if route == "deterministic_ui_composite":
        if native_full_video:
            ui_instruction = (
                "手机或屏幕中的剧情界面、金额和消息由模型直接生成，使用清晰稳定的简体中文和"
                "阿拉伯数字，内容必须符合本镜头描述，不使用空白屏幕或后期占位。"
            )
        else:
            ui_instruction = (
                "手机或屏幕只保留稳定的空白显示区域，不生成任何可读文字或数字，"
                "真实界面、金额和字幕在后期合成。"
            )
    multi_instruction = ""
    if route == "layered_multi_person_composite":
        if native_full_video:
            multi_instruction = (
                "模型在一次生成中完成多人互动，始终保持每个人的脸、服装、站位和遮挡关系稳定，"
                "人物之间不融合、不交换身份。"
            )
        else:
            multi_instruction = (
                "多人互动优先拆为稳定背景和单人动作层生成，再按遮挡关系合成，保持每张脸独立。"
            )

    keyframe_text_rule = (
        "除剧情指定的界面文字外，不出现额外文字、水印或平台标志。"
        if native_full_video
        else "画面中不要出现字幕、水印、平台标志或可读文字。"
    )
    native_requirements = _native_generation_requirements(
        dialogue_or_caption=shot["dialogue_or_caption"],
        spoken_lines=spoken_lines,
        route=route,
    )

    keyframe_prompt = (
        f"{style}。竖屏9:16。{shot['visual_and_camera']}。"
        f"人物锁定：{role_lock}。起始表情：{expression}。"
        "这是动作即将发生的首帧，人物重心和手部姿态必须能自然启动下一步动作。"
        f"{ui_instruction}{multi_instruction}{keyframe_text_rule}"
    )
    motion_prompt = (
        f"从首帧开始，角色只完成一次连续、自然、可收束的微动作：{action_and_gaze}。"
        f"表情保持{expression}，表演意图是{performance_purpose}。"
        "动作路径清楚，速度符合真人，结束后稳定停住，给下一镜头留下可衔接的结束姿态。"
        "固定当前机位和景别，单一连续镜头，不在生成视频内部切镜，不推拉变焦，不甩镜。"
        f"{native_requirements if native_full_video else ''}"
    )
    postproduction_items = ["镜头切换和速度调整"]
    if shot["dialogue_or_caption"] and shot["dialogue_or_caption"] not in {
        "无",
        "无明确台词",
    }:
        postproduction_items.insert(0, "对白和字幕")
    if route == "deterministic_ui_composite":
        postproduction_items.insert(0, "可读手机界面")
    postproduction_summary = "、".join(postproduction_items)

    native_components = ["画面", "动作", "镜头速度"]
    if spoken_lines:
        native_components.extend(["普通话对白", "同步口型", "中文字幕"])
    elif shot["dialogue_or_caption"] and shot["dialogue_or_caption"] not in {
        "无",
        "无明确台词",
    }:
        native_components.append("指定画面文字")
    if route == "deterministic_ui_composite":
        native_components.append("可读手机界面")
    native_component_summary = "、".join(native_components)

    completion_instruction = (
        f"{native_requirements}本段{native_component_summary}全部由视频模型一次生成，"
        "不保留后期配音、字幕或界面占位。"
        if native_full_video
        else f"{postproduction_summary}由后期完成。"
    )

    video_prompt = (
        f"{style}，竖屏9:16剧情短片，时长约{generation_duration:.2f}秒。"
        f"画面：{shot['visual_and_camera']}。"
        f"人物连续性：{role_lock}。动作：{action_and_gaze}。表情：{expression}。"
        f"叙事目标：{performance_purpose}。{ui_instruction}{multi_instruction}"
        "只生成一个连贯动作，结束后稳定停住；固定机位，禁止在生成视频内部切镜、"
        f"变焦或改变景别。{completion_instruction}"
    )

    return {
        "id": f"segment-{int(shot['shot_number']):03d}"
        if shot["shot_number"].isdigit()
        else f"segment-{shot['shot_number']}",
        "source": {
            **shot,
            "duration_seconds": round(source_duration, 3),
        },
        "participants": participants,
        "performance_reference": performance or None,
        "generation": {
            "route": generation_route,
            "production_mode": production_mode,
            "duration_seconds": round(generation_duration, 3),
            "aspect_ratio": "9:16",
            "internal_cuts_allowed": False,
            "render_readable_text": native_full_video
            and bool(spoken_lines or route == "deterministic_ui_composite"),
            "render_audio": native_full_video and bool(spoken_lines),
        },
        "prompts": {
            "keyframe_prompt_zh": keyframe_prompt,
            "motion_prompt_zh": motion_prompt,
            "video_prompt_zh": video_prompt,
            "negative_prompt_zh": _negative_prompt_for_mode(production_mode),
        },
        "postproduction": {
            "camera_and_cut_reference": shot["visual_and_camera"],
            "dialogue_or_caption": shot["dialogue_or_caption"],
            "required": not native_full_video,
            "instruction_zh": (
                f"本段要求视频模型原生完成{native_component_summary}；"
                "分段生成后仅按顺序组装。"
                if native_full_video
                else f"按源时间恢复切镜；{postproduction_summary}以及音效在后期完成。"
            ),
        },
        "warnings": warnings,
    }


def _infer_participants(haystack: str, roles: list[dict[str, str]]) -> list[str]:
    participants: list[str] = []
    for role in roles:
        name = role["name"]
        aliases = {name}
        aliases.update(part for part in re.split(r"[/、（(]", name) if len(part) >= 2)
        if any(alias in haystack for alias in aliases):
            participants.append(name)

    alias_hints = {
        "女子": ("粉衣女子", "女子"),
        "男子": ("金发男子", "男子"),
        "闺蜜": ("闺蜜",),
        "老人": ("老人", "受害者"),
        "警察": ("警察", "警方"),
        "骗子": ("粉衣女子", "金发男子", "骗子"),
    }
    for clue, candidates in alias_hints.items():
        if clue not in haystack:
            continue
        for role in roles:
            if any(candidate in role["name"] for candidate in candidates):
                participants.append(role["name"])

    return list(dict.fromkeys(participants))


def _match_performance(
    shot: dict[str, Any], performances: list[dict[str, Any]]
) -> dict[str, Any]:
    midpoint = (shot["start_seconds"] + shot["end_seconds"]) / 2
    containing = [
        item
        for item in performances
        if item["start_seconds"] <= midpoint <= item["end_seconds"]
    ]
    if containing:
        return max(
            containing,
            key=lambda item: min(shot["end_seconds"], item["end_seconds"])
            - max(shot["start_seconds"], item["start_seconds"]),
        )
    overlapping = [
        item
        for item in performances
        if min(shot["end_seconds"], item["end_seconds"])
        > max(shot["start_seconds"], item["start_seconds"])
    ]
    if overlapping:
        return max(
            overlapping,
            key=lambda item: min(shot["end_seconds"], item["end_seconds"])
            - max(shot["start_seconds"], item["start_seconds"]),
        )
    return {}


def _classify_generation_route(haystack: str) -> tuple[str, list[str]]:
    if any(term in haystack for term in _UI_TERMS):
        return (
            "deterministic_ui_composite",
            [
                "该镜头包含界面、金额或可读文字；视频模型仅生成设备外壳、手部和环境，界面内容后期合成。"
            ],
        )
    if any(term in haystack for term in _MULTI_PERSON_TERMS):
        return (
            "layered_multi_person_composite",
            ["该镜头包含多人复杂互动；建议分层生成并合成，降低身份融合和肢体穿模风险。"],
        )
    return "single_shot_image_to_video", []


def _negative_prompt_for_mode(production_mode: str) -> str:
    if production_mode == "native_full_video":
        return NATIVE_FULL_VIDEO_NEGATIVE_PROMPT
    return DEFAULT_NEGATIVE_PROMPT


def _extract_spoken_lines(dialogue_or_caption: str) -> list[str]:
    if not dialogue_or_caption or dialogue_or_caption in {"无", "无明确台词"}:
        return []
    if dialogue_or_caption.startswith("硬字幕"):
        return []
    quoted = re.findall(r"[“\"]([^”\"]+)[”\"]", dialogue_or_caption)
    if quoted:
        return [_clean_markdown_text(line) for line in quoted if line.strip()]
    if "：" in dialogue_or_caption:
        candidate = dialogue_or_caption.split("：", 1)[1].strip()
        if candidate:
            return [_clean_markdown_text(candidate)]
    return []


def _estimate_dialogue_duration(spoken_lines: list[str]) -> float:
    character_count = sum(
        len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", line)) for line in spoken_lines
    )
    # About four Chinese characters per second plus a short lead/tail pause.
    return round(character_count / 4.0 + 0.6, 3)


def _native_generation_requirements(
    *,
    dialogue_or_caption: str,
    spoken_lines: list[str],
    route: str,
) -> str:
    requirements: list[str] = []
    if spoken_lines:
        dialogue = "；".join(spoken_lines)
        requirements.append(
            f"角色用清晰自然的普通话完整说出：“{dialogue}”，模型同步生成对应人声和准确口型"
        )
        requirements.append(
            f"画面下方同步显示内容完全一致、清晰稳定的简体中文字幕：“{dialogue}”"
        )
    elif dialogue_or_caption and dialogue_or_caption not in {"无", "无明确台词"}:
        requirements.append(f"模型在画面中准确呈现指定文字：“{dialogue_or_caption}”")
    if route == "deterministic_ui_composite":
        requirements.append("模型直接生成镜头描述要求的手机界面、消息和金额，确保清晰可读且稳定")
    if not requirements:
        requirements.append("模型同步生成与场景匹配的自然环境声")
    return "；".join(requirements) + "。"
