"""Render a reviewed novel storyboard as a human-readable Markdown script."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def fmt_time(seconds: float) -> str:
    minutes = int(seconds // 60)
    remaining = seconds - minutes * 60
    return f"{minutes:02d}:{remaining:04.1f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--storyboard", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
    wrapper = json.loads(args.storyboard.read_text(encoding="utf-8"))
    review = json.loads(args.review.read_text(encoding="utf-8"))
    selected = analysis["selected_highlight"]
    storyboard = wrapper["storyboard"]
    lines = [
        f"# 《{storyboard['novel_title']}》小说高光试产剧本",
        "",
        f"- 最终审核：**{review['decision']}**",
        f"- 高光：**{selected['title']}**",
        f"- 成片规划：{len(storyboard['scenes'])} 镜 / {storyboard['total_duration_seconds']:g} 秒",
        "- 声音设计：本表的“画面与动作”是导演指令，不作为旁白朗读；只有对白栏进入角色声音与口型流程。",
        f"- 核心冲突：{selected['conflict']}",
        f"- 情绪转折：{selected['turning_point']}",
        f"- 峰值余波：{selected['aftershock']}",
        "",
        "## 分镜剧本",
        "",
        "| 镜 | 时间 | 画面与动作 | 对白与表演 |",
        "|---:|:---:|---|---|",
    ]
    elapsed = 0.0
    for item in storyboard["scenes"]:
        start = elapsed
        elapsed += float(item["duration_seconds"])
        dialogue = "<br>".join(
            f"**{line['speaker']}**（{line['emotion']}）：{line['text']}"
            for line in item.get("dialogue", [])
        ) or "无对白，保留反应与停顿"
        action = str(item["narration"]).replace("|", "\\|").replace("\n", "<br>")
        dialogue = dialogue.replace("|", "\\|")
        lines.append(
            f"| {int(item['scene_id']) + 1} | {fmt_time(start)}–{fmt_time(elapsed)} | {action} | {dialogue} |"
        )
    lines.extend(
        [
            "",
            "## 审核结论",
            "",
            "- 开头两镜先展示温柔反转和关键追问，隐藏林夏的回答；第三镜回到停车场开端。",
            "- 占有欲警告被拆为四个可说完的连续镜头，保留听者沉默和犹豫，不再把长句塞进 5 秒。",
            "- 峰值按“语气突变 → 牵手安抚 → 吹手 → 追问 → 林夏回答 → 洛雪微得意余波”完整展开。",
            "- 对白全部是选中原文的逐字连续子串；只修复过唯一对应原文的标点变体。",
            "- 本轮只完成小说内容恢复、高光分析和剧本/分镜审核，尚未启动视频生成。",
            "",
            f"审核记录：`{args.review.name}`；剧本 JSON：`{args.storyboard.name}`。",
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(args.output.resolve()))


if __name__ == "__main__":
    main()
