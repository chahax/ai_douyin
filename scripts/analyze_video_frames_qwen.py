"""Analyze uniformly sampled local video frames with Qwen3-VL."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = PROJECT_ROOT / ".local_models" / "video_analysis" / "Qwen3-VL-4B-Instruct"


DEFAULT_PROMPT = """你正在按时间顺序查看同一条短视频的关键帧。请只依据画面证据进行分析，不要虚构画面外事实。
输出严格 JSON，不要 Markdown，字段如下：
{
  "summary": "视频画面讲了什么",
  "content_category": "内容类别",
  "topic_labels": ["只根据画面可确认的主题标签"],
  "user_intents": ["画面可能服务的用户意图，无法判断则留空"],
  "characters_and_setting": ["人物和场景"],
  "visual_timeline": [{"time": "约多少秒", "event": "画面事件"}],
  "content_structure": [{"start": 0, "end": 5, "role": "hook/body/proof/cta", "summary": "该段作用"}],
  "visible_text": ["可辨认的关键字幕或界面文字"],
  "presentation_type": "talking_head/story_drama/screen_recording/text_cards/interview/mixed/unknown",
  "pacing": "fast/balanced/slow/unknown",
  "editing_style": ["构图、切镜、字幕、色调和节奏"],
  "hook_and_retention": ["开头钩子和视觉留存机制"],
  "uncertainties": ["无法仅凭画面确定的内容"]
}
不得根据人物外貌识别或猜测真实身份。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames", type=Path, help="Directory containing ordered JPG/PNG frames.")
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--interval-seconds", type=float, default=8.0)
    parser.add_argument("--max-images", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=900)
    parser.add_argument("--prompt-file", type=Path)
    return parser.parse_args()


def sample_frames(frame_dir: Path, limit: int) -> list[Path]:
    frames = sorted(
        path for path in frame_dir.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not frames:
        raise RuntimeError(f"No frames found in {frame_dir}")
    if len(frames) <= limit:
        return frames
    indices = [round(index * (len(frames) - 1) / (limit - 1)) for index in range(limit)]
    return [frames[index] for index in indices]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    frame_dir = args.frames.resolve()
    output = args.output.resolve()
    model_path = args.model.resolve()
    frames = sample_frames(frame_dir, args.max_images)
    prompt = (
        args.prompt_file.resolve().read_text(encoding="utf-8")
        if args.prompt_file
        else DEFAULT_PROMPT
    )

    content: list[dict[str, str]] = []
    all_frames = sorted(
        path for path in frame_dir.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    for frame in frames:
        frame_index = all_frames.index(frame)
        content.append(
            {
                "type": "text",
                "text": f"关键帧 {frame.name}，时间约 {frame_index * args.interval_seconds:.1f} 秒：",
            }
        )
        content.append({"type": "image", "image": str(frame)})
    content.append({"type": "text", "text": prompt})
    messages = [{"role": "user", "content": content}]

    print(f"Loading {model_path} on CUDA for {len(frames)} frames...", flush=True)
    processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        model_path,
        dtype=torch.bfloat16,
        device_map="cuda:0",
        local_files_only=True,
        low_cpu_mem_usage=True,
        attn_implementation="sdpa",
    ).eval()
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)
    with torch.inference_mode():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
            use_cache=True,
        )
    trimmed = [
        output_ids[len(input_ids) :]
        for input_ids, output_ids in zip(inputs.input_ids, generated_ids)
    ]
    answer = processor.batch_decode(
        trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]
    payload = {
        "schema": "local_qwen_frame_analysis/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": str(model_path),
        "frames": [str(frame) for frame in frames],
        "frame_interval_seconds": args.interval_seconds,
        "prompt": prompt,
        "answer": answer,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(answer)
    print(f"Wrote Qwen analysis: {output}")


if __name__ == "__main__":
    main()
