"""Build the reviewed editorial revision for the current novel-script trial.

This keeps the strongest cached candidate, removes the answer from its opening
preview, restores the omitted possessive warning in speakable fragments, and
adds the peak reaction and aftershock that the model draft cut off.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from src.content_factory.novel_schemas import NovelSplit
from src.content_factory.novel_splitter import (
    _find_dialogue_emotion_errors,
    _find_dialogue_timing_errors,
    _find_unanchored_dialogue,
)


def scene(narration, dialogue, first, last, duration=4.0):
    return {
        "scene_id": 0,
        "narration": narration,
        "dialogue": dialogue,
        "first_frame_prompt": first,
        "last_frame_prompt": last,
        "duration_seconds": duration,
        "background_style": "dream_shaper_xl",
    }


def line(speaker, text, emotion):
    return {"speaker": speaker, "text": text, "emotion": emotion}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8").strip()
    analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
    selected = analysis["selected_highlight"]
    start, end = int(selected["source_start_char"]), int(selected["source_end_char"])
    excerpt = source[start:end]
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    base = NovelSplit.model_validate(candidate).model_dump(mode="json")
    scenes = base["scenes"]

    # Opening preview: keep the emotional reversal, withhold Lin Xia's answer.
    scenes[1] = scene(
        "洛雪微抬起头，眼中含着泪光，妩媚的声音再次传来。",
        [line("洛雪微", "难道你有了我还不够吗~~~", "tender")],
        "Close-up of Luo Xuewei lifting her head with tears glistening in her eyes, tender pleading expression",
        "Reaction close-up of Lin Xia caught off guard, eyes widening as he looks at her, answer withheld",
        4.0,
    )
    scenes[4]["first_frame_prompt"] = (
        "Medium shot of Luo Xuewei turning back with a displeased expression, keeping her attention on Lin Xia"
    )
    scenes[7]["first_frame_prompt"] = (
        "Medium shot of Lin Xia looking confused as he answers Luo Xuewei's question"
    )
    scenes[10]["first_frame_prompt"] = (
        "Medium shot of Lin Xia looking skeptical at Luo Xuewei, unconvinced by her claim"
    )

    warning = [
        scene(
            "洛雪微瞪大着眼睛，漂亮的脸蛋此刻无比严肃。",
            [line("洛雪微", "你是有老婆的男人，", "determined")],
            "Close-up of Luo Xuewei staring at Lin Xia with a stern, unwavering expression",
            "Reaction close-up of Lin Xia listening at extremely close distance, tension held",
            4.0,
        ),
        scene(
            "两个人的脸几乎贴在一起，双方都能感受到彼此呼出的热气。",
            [line("洛雪微", "要和别的女人保持距离，", "determined")],
            "Tight two-shot of their faces almost touching while Luo Xuewei continues her warning",
            "Close-up of Luo Xuewei holding the intense eye line as Lin Xia remains silent",
            4.0,
        ),
        scene(
            "洛雪微没有松开林夏，继续说出自己的要求。",
            [line("洛雪微", "就算要和别的女人说话", "tense")],
            "Medium close-up of Luo Xuewei still holding Lin Xia's arm as she continues speaking",
            "Reaction close-up of Lin Xia hesitating, unable to give an immediate answer",
            4.0,
        ),
        scene(
            "林夏没有开口答应，不愿承诺自己做不到的事情。",
            [line("洛雪微", "也得有我在场知道不？", "tense")],
            "Close-up of Luo Xuewei finishing the demand with a fixed, serious gaze",
            "Close-up of Lin Xia staying silent, visibly conflicted and unwilling to promise",
            4.0,
        ),
    ]
    # Replace the old summary-only warning with four speakable, source-exact shots.
    scenes = scenes[:12] + warning + scenes[13:]

    # Use the two existing touch/blow shots for the apology line.
    scenes[-2]["dialogue"] = [
        line("洛雪微", "刚刚是我太用力了，我的不好，", "tender")
    ]
    scenes[-2]["first_frame_prompt"] = (
        "Close-up of Luo Xuewei releasing his arm and gently holding his palm, expression softened"
    )
    scenes[-2]["last_frame_prompt"] = (
        "Close-up of Luo Xuewei softly stroking Lin Xia's palm while she apologizes"
    )
    scenes[-1]["dialogue"] = [line("洛雪微", "我帮你轻轻吹一吹。", "tender")]

    ending = [
        scene(
            "洛雪微抬起头，眼中含着泪光，像一只刚挠完人又开始卖乖的小猫。",
            [line("洛雪微", "老公~你答应人家好不好嘛~", "tender")],
            "Close-up of Luo Xuewei lifting her head, tears glistening, pleading softly like a contrite cat",
            "Reaction close-up of Lin Xia blushing and losing his resolve while she waits for his answer",
            4.5,
        ),
        scene(
            "妩媚的声音再次传来，她的粉唇微微张开，不断靠近林夏已经泛红的手指。",
            [line("洛雪微", "难道你有了我还不够吗~~~", "tender")],
            "Extreme close-up of Luo Xuewei's lips near Lin Xia's reddened fingers as she asks again",
            "Close-up of Lin Xia's stunned face, his resistance visibly collapsing before he answers",
            4.0,
        ),
        scene(
            "林夏赤红着脸连连点头，趁洛雪微愣神时连忙收回自己的手。",
            [line("林夏", "好……好！！！", "stunned")],
            "Close-up of Lin Xia answering with a fully flushed face, nodding repeatedly in surrender",
            "Medium shot of Lin Xia quickly pulling back his hand while Luo Xuewei pauses in surprise",
            4.5,
        ),
        scene(
            "洛雪微嘴角翘起，杏眼弯弯，满含笑意地看着面红耳赤的林夏。",
            [line("洛雪微", "那我可是记好了～", "happy")],
            "Close-up of Luo Xuewei's triumphant smile and crescent-shaped eyes after his answer",
            "Final two-shot: Luo Xuewei watches the blushing Lin Xia with a knowing, teasing smile",
            4.5,
        ),
    ]
    scenes.extend(ending)
    for index, item in enumerate(scenes):
        item["scene_id"] = index
    revised = NovelSplit.model_validate(
        {
            "novel_title": base["novel_title"],
            "characters": base["characters"],
            "scenes": scenes,
        }
    )
    errors = {
        "dialogue": _find_unanchored_dialogue(revised, excerpt),
        "timing": _find_dialogue_timing_errors(revised),
        "emotion": _find_dialogue_emotion_errors(revised),
    }
    if any(errors.values()):
        raise RuntimeError(json.dumps(errors, ensure_ascii=False))

    payload = {
        "schema": "novel_highlight_storyboard/v3",
        "driver_mode": analysis["driver_mode"],
        "driver_decision": analysis["driver_decision"],
        "highlight_id": selected["highlight_id"],
        "source_sha256": analysis["source_sha256"],
        "source_excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest().upper(),
        "narration_usage": "visual_direction_only_not_spoken",
        "editorial_revision": {
            "base_candidate": str(args.candidate),
            "opening_answer_withheld": True,
            "omitted_warning_restored_as_source_exact_fragments": True,
            "peak_before_during_after_restored": True,
            "deterministic_gates": {
                "dialogue_source_exact": "passed",
                "dialogue_timing": "passed",
                "emotion_labels": "passed",
            },
        },
        "storyboard": revised.model_dump(mode="json"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "scene_count": len(revised.scenes),
                "duration_seconds": revised.total_duration_seconds,
                "dialogue_count": sum(len(item.dialogue) for item in revised.scenes),
                "non_neutral": sum(
                    line.emotion != "neutral"
                    for item in revised.scenes
                    for line in item.dialogue
                ),
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
