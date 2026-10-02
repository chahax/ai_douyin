"""Build the two full, review-only 404263 detailed-script projects.

The source of truth is the 64-unit markdown production contract. Unit 064 is
expanded into six generation segments, producing 69 executable segments in
each visual style. No reference-video pixels or audio are used.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCRIPT = (
    ROOT
    / "docs/archive/2026-09-video-pipeline-reset"
    / "REFERENCE_404263_DETAILED_ADAPTATION_SCRIPT_V1.md"
)
DEFAULT_OUTPUT = ROOT / "data/qa/reference_404263_detailed_two_style_full_20260826"


STYLES = {
    "semireal": (
        "Vertical 9:16 warm cinematic semi-realistic Chinese adult crime drama. "
        "Natural mature facial anatomy and realistic adult body proportions, subtly stylized but never glossy AI fashion photography. "
        "Detailed skin, hair and cloth, controlled film contrast, shallow depth of field, character-first framing and restrained acting. "
    ),
    "bighead3d": (
        "Vertical 9:16 premium cinematic stylized 3D adult animation in the established Perfect Lover direction. "
        "Every person is an unmistakably Chinese adult with a moderately oversized but individually shaped head, expressive mature eyes, "
        "an anatomically adult compact body, softly modeled skin, detailed hair and cloth, feature-film lighting and shallow depth of field. "
        "Different characters keep visibly different facial structures; this is not a child, mascot, doll or shared beauty-template cast. "
    ),
}


CHARACTERS = {
    "lead_female": {
        "name": "女主",
        "prompt": (
            "adult Chinese woman age 23, slim build and narrow shoulders, distinctive heart-shaped face, wide-set round dark eyes, "
            "black hair in two compact high buns with two thin braids, one small star hair clip, dusty-pink knit top and dark grey shorts"
        ),
        "invariants": "heart-shaped face, wide-set eyes, twin high buns, two thin braids and star hair clip",
        "seed": 826701,
    },
    "friend_blonde": {
        "name": "朋友A",
        "prompt": (
            "adult Chinese woman age 25, tall lean build, distinctive long narrow face, sharp cat-shaped dark eyes, "
            "short chin-length honey-blonde bob, black sleeveless top with one leopard-print panel"
        ),
        "invariants": "long narrow face, cat-shaped eyes, honey-blonde chin-length bob and tall lean build",
        "seed": 826702,
    },
    "friend_black": {
        "name": "朋友B",
        "prompt": (
            "adult Chinese woman age 24, athletic build and broad shoulders, distinctive square jaw, straight brows and narrow eyes, "
            "black high ponytail and plain black sleeveless athletic top"
        ),
        "invariants": "square jaw, narrow eyes, high black ponytail, broad shoulders and athletic build",
        "seed": 826703,
    },
    "male_operator": {
        "name": "男操盘手",
        "prompt": (
            "adult Chinese man age 27, tall slim build, distinctive long narrow angular face, pronounced brow ridge, slightly hollow cheeks, "
            "messy short dyed-blond hair with dark roots, plain black T-shirt, dark jeans and one gold wristwatch"
        ),
        "invariants": "long narrow angular face, pronounced brow ridge, messy dyed-blond hair, black T-shirt and gold wristwatch",
        "seed": 826704,
    },
    "victim_chen": {
        "name": "陈叔",
        "prompt": (
            "adult Chinese man age 66, broad square weathered face, grey buzzcut, deep natural wrinkles, rough hands, "
            "slightly stooped average build and brown knitted cardigan over a muted beige shirt"
        ),
        "invariants": "broad square weathered face, grey buzzcut, rough hands, brown cardigan and age 66",
        "seed": 826705,
    },
    "victim_wu": {
        "name": "吴叔",
        "prompt": (
            "adult Chinese man age 61, slim build, distinctive long thin face, silver-rim glasses, short salt-and-pepper hair, "
            "deep-blue practical jacket and reserved posture"
        ),
        "invariants": "long thin face, silver-rim glasses, salt-and-pepper hair, deep-blue jacket and slim build",
        "seed": 826706,
    },
    "victim_liu": {
        "name": "刘老师",
        "prompt": (
            "adult Chinese man age 58, round mature face, salt-and-pepper short hair, thin reading glasses, "
            "plaid shirt and calm retired-teacher bearing"
        ),
        "invariants": "round mature face, reading glasses, salt-and-pepper hair, plaid shirt and age 58",
        "seed": 826707,
    },
    "officer_front": {
        "name": "前排警员",
        "prompt": (
            "adult Chinese male police officer age 36, broad athletic build, distinctive square face and black buzzcut, "
            "plain solid dark-navy duty uniform with no readable badges or letters"
        ),
        "invariants": "broad athletic build, square face, black buzzcut and plain dark-navy uniform",
        "seed": 826708,
    },
    "officer_rear": {
        "name": "后排警员",
        "prompt": (
            "adult Chinese male police officer age 31, lean build, distinctive narrow face and neat short black hair, "
            "plain solid dark-navy duty uniform and dark evidence gloves with no readable badges or letters"
        ),
        "invariants": "lean build, narrow face, neat short hair, dark evidence gloves and plain dark-navy uniform",
        "seed": 826709,
    },
}


COMMON_AVOID = (
    "child, minor, baby, toddler, mascot, plush toy, shared face, cloned face, same face on different people, duplicate person, "
    "identity change, age change, hairstyle change, clothing change, extra hand, extra arm, extra leg, missing limb, extra fingers, "
    "fused fingers, broken hand, body deformation, character merging, warped phone, duplicate phone, active phone turning black, "
    "screen flicker, generated text, fake letters, fake numbers, logo, watermark, crouching without instruction, kneeling without instruction, "
    "random hand waving, camera shake, uncontrolled zoom, scene cut, loop, repeated beginning, frozen interval, exposure pumping"
)


DETERMINISTIC_IDS = {
    "003", "005", "011", "019", "025", "028", "029", "035", "037", "042", "044", "046", "048",
    "052", "056", "057", "061", "063", "064c",
}


CHARACTER_BY_SHOT = {
    "001": ("lead_female", "friend_blonde", "friend_black"),
    "002": ("lead_female", "friend_blonde", "friend_black"),
    "003": ("lead_female",),
    "004": ("lead_female", "friend_blonde", "friend_black"),
    "005": (),
    "006": ("male_operator",), "007": ("male_operator",), "008": ("male_operator",),
    "009": ("lead_female",), "010": ("lead_female",), "011": ("male_operator",),
    "012": ("male_operator",), "013": ("lead_female",), "014": ("lead_female", "male_operator"),
    "015": ("male_operator",), "016": ("lead_female",), "017": ("lead_female", "male_operator"),
    "018": ("lead_female", "male_operator"), "019": ("lead_female",), "020": ("lead_female",),
    "021": ("lead_female",), "022": ("male_operator",), "023": (),
    "024": ("victim_chen",), "025": ("victim_chen",), "026": ("victim_chen",),
    "027": ("male_operator",), "028": ("victim_liu",), "029": (), "030": ("male_operator",),
    "031": ("lead_female",), "032": ("lead_female",), "033": ("male_operator", "lead_female"),
    "034": ("lead_female",), "035": ("lead_female",), "036": ("lead_female", "male_operator"),
    "037": (), "038": ("lead_female",), "039": ("male_operator", "lead_female"),
    "040": ("male_operator",), "041": ("male_operator",), "042": ("male_operator",),
    "043": ("lead_female",), "044": (), "045": ("lead_female",), "046": ("lead_female",),
    "047": ("lead_female", "male_operator"), "048": (), "049": ("male_operator",),
    "050": ("male_operator",), "051": ("lead_female",), "052": ("lead_female",),
    "053": ("lead_female", "male_operator"), "054": ("victim_wu",), "055": ("victim_wu",),
    "056": (), "057": ("victim_wu",), "058": ("officer_front", "officer_rear"),
    "059": ("male_operator", "lead_female", "officer_front", "officer_rear"),
    "060": ("male_operator", "officer_front"), "061": ("male_operator", "officer_front"),
    "062": ("lead_female",), "063": ("officer_rear",),
    "064a": ("victim_chen",), "064b": ("victim_chen",), "064c": ("victim_chen",),
    "064d": ("victim_chen",), "064e": ("victim_chen",), "064f": ("victim_chen",),
}


DIALOGUE = {
    "002": ("lead_female", "一说心情不好，红包马上到。", "年轻女性炫耀但自然，语速稍快。"),
    "004": ("friend_black", "今晚你请。", "年轻女性随口打趣，短促自然。"),
    "010": ("male_operator", "去哪儿了？", "年轻男性从画外冷淡催促。"),
    "012": ("male_operator", "十二部手机都在等回复。", "年轻男性低头说话，熟练而不耐烦。"),
    "014": ("lead_female", "为什么都用我的照片？", "年轻女性压住惊慌，清楚质问。"),
    "016": ("male_operator", "别问。", "年轻男性从画外冷硬打断。"),
    "017": ("male_operator", "先把这一轮回完。", "年轻男性命令式但不吼叫。"),
    "018": ("lead_female", "他们以为只跟我聊天。", "年轻女性迟疑、逐渐意识到问题。"),
    "020": ("male_operator", "下一部。", "年轻男性简短催促。"),
    "021": ("lead_female", "刚下班，今天有点难受，不想让你担心。", "年轻女性刻意温柔地录制语音。"),
    "024": ("lead_female", "今天有点难受。", "年轻女性语音消息，虚弱是表演出来的。"),
    "025": ("victim_chen", "别饿着。", "年长男性真诚关心，声音温和缓慢。"),
    "026": ("victim_chen", "去买点热的。", "年长男性善意叮嘱，不煽情。"),
    "028": ("victim_liu", "发烧别硬扛。", "退休教师式温和关心，吐字清楚。"),
    "030": ("male_operator", "陈叔五百，刘老师一千二，记上。", "年轻男性冷淡报数，节奏清楚。"),
    "032": ("male_operator", "手放额头，别笑。", "年轻男性从画外指导造假，平静冷漠。"),
    "033": ("lead_female", "这样够可怜吗？", "年轻女性试探询问，没有真的虚弱。"),
    "036": ("male_operator", "够了。", "年轻男性简短确认。"),
    "040": ("friend_blonde", "需要照镜子吗？", "成年女店员礼貌询问。"),
    "041": ("male_operator", "这一排都要。", "年轻男性炫耀、得意但不喊叫。"),
    "045": ("lead_female", "都包起来。", "年轻女性自信消费，语气利落。"),
    "050": ("male_operator", "羡慕吧？", "年轻男性外放炫耀，短句。"),
    "051": ("lead_female", "这才是我要的生活。", "年轻女性对自拍镜头满足地说。"),
    "053": ("male_operator", "别回。", "年轻男性从画外冷淡阻止。"),
    "058": ("officer_front", "警察！别动，双手离开手机！", "成年男警员有力度地下达命令，清楚而专业。"),
    "060": ("male_operator", "误会！", "年轻男性慌乱辩解，短促。"),
    "062": ("lead_female", "我们只是跟朋友聊天。", "年轻女性惊慌辩解，声音发紧。"),
    "063": ("officer_rear", "几十部手机、统一话术，这叫聊天？", "成年男警员冷静反问，强调证据。"),
    "064a": ("officer_rear", "警方破获特大电信诈骗案，现场查获大量涉案手机。", "男性电视新闻播报，正式克制。"),
    "064f": ("victim_chen", "老吴，你接电话啊……怎么不理我？", "年长男性困惑转为压抑难过，停顿自然，不嚎哭。"),
}


ENDING_SEGMENTS = [
    ("064a", 90.07, 91.10, "老人房间侧面中近景，电视冷光照在陈叔脸上", "陈叔抬眼听电视新闻，右手停在桌边", "电视新闻播报进入"),
    ("064b", 91.10, 93.13, "陈叔面部近景，桌上手机在画面下缘", "他皱眉确认联系人姓名，视线缓慢转向桌上手机", "房间低噪与呼吸"),
    ("064c", 93.13, 94.40, "破裂手机极近景，屏幕稳定亮起", "拨号界面出现失联联系人，裂纹和手机位置不变", "一次按键音"),
    ("064d", 94.40, 97.33, "陈叔桌边中景，手机位于右手前方", "他沿一条直线路径拿起手机到胸口，左手扶桌", "拨号等待音开始"),
    ("064e", 97.33, 99.50, "陈叔侧面近景", "他把手机从胸口抬到右耳，身体微微前倾后等待", "等待音继续"),
    ("064f", 99.50, 104.30, "陈叔贴耳面部特写", "他轻声询问，停住后缓慢呼气，肩膀逐渐塌下，手机始终贴耳", "最后只留呼吸"),
]


def rounded_frames(duration_seconds: float, fps: int = 25) -> int:
    """Return the smallest 8n+1 LTX length that covers the target duration."""
    return max(17, int(math.ceil(max(0.0, duration_seconds * fps - 1.0) / 8.0)) * 8 + 1)


def parse_rows(markdown: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    pattern = re.compile(r"^`(?P<id>\d{3})`\s+(?P<start>\d+(?:\.\d+)?)–(?P<end>\d+(?:\.\d+)?)$")
    for raw in markdown.splitlines():
        if not raw.startswith("| `"):
            continue
        parts = [part.strip() for part in raw.strip().strip("|").split("|")]
        if len(parts) != 5:
            continue
        match = pattern.match(parts[0])
        if not match:
            continue
        shot_id = match.group("id")
        if shot_id == "064":
            continue
        rows.append({
            "id": shot_id,
            "start": float(match.group("start")),
            "end": float(match.group("end")),
            "composition": parts[1],
            "action": parts[2],
            "audio_direction": parts[3],
            "edit_workflow": parts[4],
        })
    if [row["id"] for row in rows] != [f"{index:03d}" for index in range(1, 64)]:
        raise ValueError("detailed script table must contain ordered units 001..063 before ending expansion")
    for shot_id, start, end, composition, action, audio in ENDING_SEGMENTS:
        rows.append({
            "id": shot_id,
            "start": start,
            "end": end,
            "composition": composition,
            "action": action,
            "audio_direction": audio,
            "edit_workflow": "LTX+LP+UI",
        })
    return rows


def scene_context(shot_id: str) -> str:
    number = 64 if shot_id.startswith("064") else int(shot_id)
    if number <= 4:
        return "Night street with pink-purple neon, wet pavement reflections and warm skin tones; people dominate, signage is unreadable bokeh."
    if number <= 22:
        return "Cramped scam workroom with cold-cyan overhead light and steady blue-white phone glow; background stays dark and subordinate."
    if number == 23:
        return "High night-city transition with distant traffic and many warm apartment lights, no readable signs."
    if number <= 31:
        return "Distinct modest victim interior with warm lonely practical light; hands, eyes and ordinary domestic details dominate."
    if number <= 39:
        return "Messy bedroom fake-illness setup with cool window light and one phone fill light; actor performance dominates."
    if number <= 48:
        return "Bright consumption montage with warm jewelry, beauty-store or dining light; no brands or readable receipts."
    if number <= 53:
        return "Sunny saturated rooftop pool setting with cyan water; main characters dominate and background guests remain independently posed."
    if number <= 57:
        return "Cold-blue night lake, restrained and non-graphic; communicate consequence through silhouette, splash, ripples and wet phone only."
    if number <= 63:
        return "Cold-blue police raid in the workroom; officers have distinct faces, clear weight transfer and plain unreadable uniforms."
    return "Low-lit modest elderly apartment with cool television light and one cracked phone; intimate grief without melodrama."


def shot_prompt(style: str, row: dict[str, object], participants: tuple[str, ...]) -> str:
    cast_text = ". ".join(CHARACTERS[item]["prompt"] for item in participants)
    cast_rule = (
        "Every named person has a visibly different face, age, build, hairstyle and clothing silhouette; never copy one person's face onto another. "
        if len(participants) > 1 else "Preserve this character's unique face, age, hairstyle, build and clothes. "
    )
    phone_rule = ""
    joined = f"{row['composition']} {row['action']}"
    if "手机" in joined or "屏" in joined:
        phone_rule = (
            "Every active phone is a separate stable object with a blank steady blue-white illuminated screen at constant brightness; "
            "do not generate readable text or an extra phone. "
        )
    return (
        STYLES[style]
        + scene_context(str(row["id"])) + " "
        + ((cast_text + ". ") if cast_text else "No recurring cast identity is required in this insert. ")
        + cast_rule + phone_rule
        + f"Composition contract: {row['composition']}. "
        + f"Visible story action at the first frame: {row['action']}. "
        + "No background establishing shot, no readable text, no logo and no watermark."
    )


def motion_prompt(row: dict[str, object]) -> str:
    return (
        f"Perform exactly this single micro-action: {row['action']}. "
        "The action has one clear start pose, one natural path and one settled end pose. "
        "Keep feet, hands, gaze, props and body weight physically coherent. Do not add gestures, crouching, watch-checking or new objects. "
        "Preserve the first-frame identities, clothes, lighting and scene. Camera remains stable unless the composition explicitly requires tracking."
    )


def master_project(style: str) -> dict[str, object]:
    items = []
    for character_id, character in CHARACTERS.items():
        items.append({
            "id": character_id,
            "character_id": character_id,
            "seed": character["seed"] + (100 if style == "bighead3d" else 0),
            "prompt": (
                STYLES[style]
                + "Single-character waist-up identity master portrait against a simple neutral studio gradient. "
                + character["prompt"] + ". Calm mature expression, direct three-quarter gaze, hands low and mostly outside frame, "
                "exactly one adult, no phone, no props, no generated text."
            ),
        })
    return {
        "project_id": f"reference_404263_detailed_{style}_character_masters_20260826",
        "style": style,
        "canvas": {"width": 704, "height": 1248, "fps": 25},
        "keyframe_generation": {
            "checkpoint": "flux1-schnell-fp8.safetensors", "width": 704, "height": 1248,
            "steps": 4, "cfg": 1.0, "sampler": "euler", "scheduler": "simple",
        },
        "anchor": items[0],
        "shots": items[1:],
    }


def build_project(style: str, rows: list[dict[str, object]], source_script: Path) -> dict[str, object]:
    shots = []
    for index, row in enumerate(rows, start=1):
        shot_id = str(row["id"])
        participants = CHARACTER_BY_SHOT[shot_id]
        duration = round(float(row["end"]) - float(row["start"]), 3)
        dialogue = DIALOGUE.get(shot_id)
        shot: dict[str, object] = {
            "id": shot_id,
            "index": index,
            "timeline_start_seconds": float(row["start"]),
            "timeline_end_seconds": float(row["end"]),
            "duration": duration,
            "style": style,
            "participants": list(participants),
            "primary_character": participants[0] if participants else None,
            "identity_lock": CHARACTERS[participants[0]]["invariants"] if participants else None,
            "render_mode": "deterministic" if shot_id in DETERMINISTIC_IDS else "ltx_i2v",
            "recommended_workflow": row["edit_workflow"],
            "seed": 826800 + index + (1000 if style == "bighead3d" else 0),
            "frames": rounded_frames(duration),
            "i2v_strength": 0.94,
            "ip_scale": 0.48 if len(participants) > 1 else 0.62,
            "prompt": shot_prompt(style, row, participants),
            "motion": motion_prompt(row),
            "composition_contract": row["composition"],
            "source_action": row["action"],
            "audio_direction": row["audio_direction"],
            "caption": dialogue[1] if dialogue else "",
            "speaker": dialogue[0] if dialogue else None,
            "speech_direction": dialogue[2] if dialogue else "No dialogue; preserve natural breathing and the specified reaction only.",
        }
        if shot_id in {"064e", "064f"}:
            shot["continuity_from"] = "064d" if shot_id == "064e" else "064e"
        shots.append(shot)
    duration = round(sum(float(shot["duration"]) for shot in shots), 3)
    if len(shots) != 69 or abs(duration - 104.3) > 0.02:
        raise ValueError(f"expected 69 segments / 104.30 seconds, got {len(shots)} / {duration}")
    return {
        "schema": "reference_404263_detailed_two_style_project/v1",
        "project_id": f"reference_404263_detailed_{style}_full_20260826",
        "title": f"《批量关心》详细剧本完整版—{style}",
        "style": style,
        "status": "ready_for_generation_not_publishable",
        "source_script": str(source_script),
        "reference_video_pixels_used": False,
        "reference_video_audio_used": False,
        "canvas": {"width": 704, "height": 1248, "fps": 25},
        "keyframe_generation": {
            "checkpoint": "flux1-schnell-fp8.safetensors", "width": 704, "height": 1248,
            "steps": 4, "cfg": 1.0, "sampler": "euler", "scheduler": "simple",
        },
        "video_generation": {
            "model": "LTX2/ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors",
            "i2v_strength": 0.94, "negative_prompt": COMMON_AVOID,
        },
        "character_bible": CHARACTERS,
        "segment_count": len(shots),
        "duration_seconds": duration,
        "publish_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
        "shots": shots,
    }


def voice_spec(project: dict[str, object], output_dir: Path) -> dict[str, object]:
    female = ROOT / "data/audio/kokoro/auditions/female/zf_001.wav"
    female_alt = ROOT / "data/audio/kokoro/auditions/female/zf_048.wav"
    male = ROOT / "data/audio/kokoro/auditions/male/zm_052.wav"
    male_alt = ROOT / "data/audio/kokoro/auditions/male/zm_034.wav"
    cast = {
        "lead_female": {"prompt_wav": str(female)},
        "friend_black": {"prompt_wav": str(female_alt)},
        "friend_blonde": {"prompt_wav": str(female_alt)},
        "male_operator": {"prompt_wav": str(male)},
        "victim_chen": {"prompt_wav": str(male_alt)},
        "victim_liu": {"prompt_wav": str(male_alt)},
        "officer_front": {"prompt_wav": str(male)},
        "officer_rear": {"prompt_wav": str(male)},
    }
    lines = []
    for shot in project["shots"]:
        if not shot["caption"]:
            continue
        speaker = str(shot["speaker"])
        lines.append({
            "id": f"{shot['id']}_{speaker}", "scene_id": shot["id"], "speaker": speaker,
            "text": shot["caption"], "instruct": shot["speech_direction"], "speed": 1.08,
        })
    return {
        "schema": "reference_404263_detailed_dialogue_cosyvoice/v1",
        "output_dir": str(output_dir), "cast": cast, "lines": lines,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    script_path = args.script.resolve()
    output_root = args.output_dir.resolve()
    rows = parse_rows(script_path.read_text(encoding="utf-8"))
    outputs: dict[str, object] = {}
    for style in STYLES:
        style_root = output_root / style
        style_root.mkdir(parents=True, exist_ok=True)
        project_path = style_root / "story_project.json"
        master_path = style_root / "character_master_project.json"
        project = build_project(style, rows, script_path)
        project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        master_path.write_text(json.dumps(master_project(style), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        outputs[style] = {"project": str(project_path), "masters": str(master_path)}
    voice_path = output_root / "dialogue_cosyvoice_spec.json"
    semireal_project = json.loads((output_root / "semireal/story_project.json").read_text(encoding="utf-8"))
    voice_path.write_text(
        json.dumps(voice_spec(semireal_project, output_root / "audio_cosyvoice_raw"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    outputs["voice_spec"] = str(voice_path)
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
