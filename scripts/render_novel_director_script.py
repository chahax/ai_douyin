"""Render the visual-directed novel package as a readable director script."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _time(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{seconds % 60:04.1f}"


def _safe(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    package = json.loads(args.package.read_text(encoding="utf-8"))
    review = json.loads(args.review.read_text(encoding="utf-8"))
    storyboard = package["storyboard"]
    direction = package["visual_direction"]
    bible = direction["visual_bible"]
    genre = bible["genre_analysis"]
    lines = [
        f"# 《{storyboard['novel_title']}》导演版小说视频剧本",
        "",
        f"- 视觉审核：**{review['decision']}**",
        f"- 题材判断：**{genre['primary_genre']}**",
        f"- 画风：**{genre['style_profile']['medium']}**",
        f"- 画风编号：`{genre['style_profile']['style_id']}`",
        f"- 规格：9:16 / {len(storyboard['scenes'])}镜 / {storyboard['total_duration_seconds']:g}秒",
        f"- 选择理由：{genre['selection_reason']}",
        "",
        "## 题材与美术圣经",
        "",
        f"- 平台分类：{' / '.join(genre['platform_categories'])}",
        f"- 简介标签：{' / '.join(genre['abstract_labels'])}",
        f"- 色彩：{bible['format']['palette']}",
        f"- 材质：{bible['format']['texture']}",
        f"- 林夏：{bible['production_design_choices']['林夏']}",
        f"- 洛雪微：{bible['production_design_choices']['洛雪微']}",
        f"- 事实边界：{bible['production_design_choices']['fact_boundary']}",
        f"- 空间：{bible['set_design']['layout']}",
        f"- 轴线：{bible['set_design']['axis']}",
        f"- 光源：{'；'.join(bible['set_design']['lighting_sources'])}",
        f"- 连续道具：{bible['continuity_lock']['hands_and_prop']}",
        "",
        "## 逐镜导演表",
        "",
        "| 镜/时间 | 对白 | 景别与机位 | 前中后景构图 | 表演细节 | 连续性与剪辑 |",
        "|---|---|---|---|---|---|",
    ]
    elapsed = 0.0
    shots = direction["shots"]
    for scene, shot in zip(storyboard["scenes"], shots):
        start = elapsed
        elapsed += float(scene["duration_seconds"])
        dialogue = "<br>".join(
            f"**{row['speaker']}**（{row['emotion']}）：{row['text']}"
            for row in scene.get("dialogue", [])
        ) or "无对白"
        camera = shot["camera"]
        composition = shot["composition"]
        continuity = shot["continuity"]
        lines.append(
            f"| {int(scene['scene_id']) + 1}<br>{_time(start)}–{_time(elapsed)} "
            f"| {_safe(dialogue)} "
            f"| **{_safe(shot['shot_size'])}**<br>{_safe(camera['lens_equivalent'])}；{_safe(camera['height_angle_movement'])} "
            f"| 前：{_safe(composition['foreground'])}<br>中：{_safe(composition['midground'])}<br>后：{_safe(composition['background'])}<br>焦点：{_safe(composition['focal_point'])} "
            f"| {_safe(shot['performance']['visible_action_and_micro_expression'])}<br>光线：{_safe(shot['lighting'])} "
            f"| 起：{_safe(continuity['start_state'])}<br>止：{_safe(continuity['end_state'])}<br>切：{_safe(shot['cut_reason'])} |"
        )
    lines.extend(
        [
            "",
            "## 生成锁定",
            "",
            "- 每镜已有完整中文生成提示词，存放在导演 JSON 的 `visual_direction.shots[].generation_prompt_zh`。",
            "- 画风、人物年龄感、发型、服装、画面左右关系、世界光源和军训服袋均为跨镜锁定项。",
            "- 前两镜是峰值预示；第3镜明确执行时间重置，之后只按连续时间推进。",
            "- 本文件是文字导演审片材料，尚未生成视频，不能据此标记视频画面通过。",
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(args.output.resolve()))


if __name__ == "__main__":
    main()
