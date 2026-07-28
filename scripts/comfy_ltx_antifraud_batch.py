from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path


MOTIONS = {
    "01_unknown_call": (
        "Start: she looks down at the laptop with both hands near the keyboard. "
        "Action: the phone vibrates once; she slowly turns her eyes toward it, reaches with her right hand, "
        "lifts it to her right ear, and slightly furrows her eyebrows. "
        "End: she holds the phone naturally at her ear and listens. Motion is slow and subtle."
    ),
    "02_accusation": (
        "Start: she listens with a puzzled expression, phone against her right ear. "
        "Action: her eyes gradually tighten, her lower lip presses inward, and her fingers grip the phone a little more firmly. "
        "End: she remains still, visibly tense but restrained. Motion is very slow and small."
    ),
    "03_foreign_number": (
        "Start: the thumb rests away from the bottom of the phone screen. "
        "Action: the thumb moves slowly toward the lower screen, pauses several millimeters above it, trembles once, "
        "then pulls back without touching. End: the natural five-finger grip remains unchanged. "
        "Motion is slow, precise, and minimal."
    ),
    "04_pacing": (
        "Start: she stands beside the desk with the phone at her left ear and her right hand lowered. "
        "Action: she takes exactly two short natural steps toward the window while raising her right hand to rub one temple. "
        "End: she stops near the window, weight balanced on both feet, breathing slightly faster. "
        "Motion is moderate and controlled; no kneeling, no running."
    ),
    "05_transfer": (
        "Start: her right index finger is above the phone while the other fingers support it naturally. "
        "Action: the index finger descends slowly toward the confirmation area, stops just before contact, and trembles slightly. "
        "End: it remains hovering without pressing. Motion is extremely small and precise."
    ),
    "06_police_call": (
        "Start: she stares down at the phone with her index finger near the screen. "
        "Action: a second incoming call makes her freeze; her index finger pulls away, her eyes widen slightly, "
        "and she turns the phone upright toward herself. End: she prepares to answer the new call. "
        "Motion is slow and restrained."
    ),
    "07_real_officer": (
        "Start: the woman holds her phone near her face while the police officer faces camera. "
        "Action: the officer raises one open palm in a firm stop gesture and speaks calmly; "
        "the woman relaxes her shoulders and slowly lowers the phone to chest level. "
        "End: both hold steady, the woman visibly relieved. Motion is controlled and professional."
    ),
    "08_relief_warning": (
        "Start: the phone lies inactive on the desk and both of her hands cover her face. "
        "Action: she exhales once, slowly lowers both hands to the desk, straightens her back, and lifts her gaze. "
        "End: she looks calmly into the camera with a relieved expression. Motion is slow and gentle."
    ),
}

NEW_SAFE_MOTIONS = {
    "04_pacing": (
        "Start: she stands fully balanced beside the desk with the phone already held at her left ear. "
        "Action: she slowly shifts her weight, takes exactly one short forward step, then raises her right hand "
        "to press two fingers gently against her right temple. End: she stops with both feet planted and holds "
        "the stable anxious pose. Motion is slow and small; no turn, no crossing legs, no kneeling."
    ),
    "07_real_officer": (
        "Start: both people are already separated in their own halves of the video-call frame. "
        "Action: only the officer slowly raises one open palm to chest height; the woman lowers her phone by "
        "a few centimeters and relaxes her shoulders. End: both remain still in their original halves. "
        "Motion is minimal; nobody enters, exits, crosses the split, or duplicates."
    ),
    "06_police_call": (
        "Start: she holds one upright phone steadily at chest height with its blue screen facing her, while her "
        "free hand rests on the desk. Action: the phone stays in exactly the same position; only her eyes widen "
        "slightly, her chin lifts a little, and her free hand pulls back by two centimeters. End: she freezes in "
        "that surprised pose, still holding the same phone at chest height. Motion is extremely small and slow."
    ),
}

NEGATIVE = (
    "identity change, different face, hairstyle change, clothing change, missing silver necklace, "
    "extra person, duplicate person, cloned face, extra limb, missing limb, extra fingers, fused fingers, "
    "broken hand, warped phone, melting object, body deformation, child proportions, dancing, running, kneeling, "
    "large motion, fast motion, camera shake, pan, tilt, zoom, scene cut, flicker, exposure pumping, "
    "generated text, letters, numbers, logo, watermark"
)


def request_json(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def wait_history(base_url: str, prompt_id: str, timeout_seconds: int) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        history = request_json(f"{base_url}/history/{prompt_id}")
        if prompt_id in history:
            result = history[prompt_id]
            status = result.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False))
            return result
        time.sleep(3)
    raise TimeoutError(f"ComfyUI prompt timed out: {prompt_id}")


def find_saved_video(history: dict, output_root: Path) -> Path:
    for output in history.get("outputs", {}).values():
        for image in output.get("images", []):
            if image.get("type") == "output" and image.get("filename", "").lower().endswith(".mp4"):
                return output_root / image.get("subfolder", "") / image["filename"]
        for video in output.get("videos", []):
            if video.get("type") == "output":
                return output_root / video.get("subfolder", "") / video["filename"]
        for file_info in output.get("files", []):
            if file_info.get("type") == "output" and file_info.get("filename", "").lower().endswith(".mp4"):
                return output_root / file_info.get("subfolder", "") / file_info["filename"]
    raise RuntimeError("ComfyUI history did not contain a saved video")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the anti-fraud baseline LTX video clips.")
    parser.add_argument("project")
    parser.add_argument("--template", default=r"data\qa\hospital_video\ltx23_shot01_i2v_workflow.json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-output", default=r"D:\IT\AI_vido\ComfyUI\output")
    parser.add_argument("--input-prefix", default="anti_fraud_police_chibi_v1/old")
    parser.add_argument("--variant", default="old", choices=("old", "new"))
    parser.add_argument("--seed-offset", type=int, default=1000)
    parser.add_argument("--only", action="append", help="Generate only a selected shot id; repeat as needed.")
    parser.add_argument("--overrides", help="Optional JSON mapping shot ids to prompt and motion overrides.")
    parser.add_argument("--filename-prefix", help="ComfyUI SaveVideo filename prefix.")
    parser.add_argument("--first-prompt-id", help="Resume an already queued first shot instead of submitting it again.")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    args = parser.parse_args()

    project = json.loads(Path(args.project).read_text(encoding="utf-8"))
    template = json.loads(Path(args.template).read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir).resolve()
    workflow_dir = output_dir / "workflows"
    clip_dir = output_dir / "clips"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    clip_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else []
    overrides = (
        json.loads(Path(args.overrides).read_text(encoding="utf-8"))
        if args.overrides else {}
    )
    done_ids = {item["id"] for item in report if item.get("status") in {"generated", "skipped"}}
    client_id = str(uuid.uuid4())

    for shot in project["shots"]:
        shot_id = shot["id"]
        if args.only and shot_id not in args.only:
            continue
        destination = clip_dir / f"{shot_id}.mp4"
        if args.skip_existing and (destination.is_file() or shot_id in done_ids):
            print(f"skipped {shot_id}", flush=True)
            continue

        workflow = json.loads(json.dumps(template))
        override = overrides.get(shot_id, {})
        motion = override.get("motion")
        if not motion:
            motion = NEW_SAFE_MOTIONS.get(shot_id, MOTIONS[shot_id]) if args.variant == "new" else MOTIONS[shot_id]
        shot_prompt = override.get("prompt", shot["prompt"])
        workflow["5"]["inputs"]["text"] = (
            shot_prompt + " Animate only the following controlled action. " + motion +
            " Preserve the exact first-frame composition, character identity, outfit, props, and room. "
            "The camera stays locked and stable. No dialogue or lip movement."
        )
        workflow["6"]["inputs"]["text"] = NEGATIVE
        workflow["8"]["inputs"]["image"] = f"{args.input_prefix}/{shot_id}.png"
        workflow["9"]["inputs"]["width"] = project["canvas"]["width"]
        workflow["9"]["inputs"]["height"] = project["canvas"]["height"]
        workflow["9"]["inputs"]["length"] = 97 if shot["duration"] >= 4 else 65
        workflow["9"]["inputs"]["strength"] = 0.94
        workflow["10"]["inputs"]["seed"] = shot["seed"] + args.seed_offset
        save_prefix = args.filename_prefix or f"anti_fraud_police_chibi/{args.variant}_video"
        workflow["13"]["inputs"]["filename_prefix"] = f"{save_prefix}/{shot_id}"

        workflow_path = workflow_dir / f"{shot_id}.api.json"
        workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.first_prompt_id and shot_id == project["shots"][0]["id"]:
            prompt_id = args.first_prompt_id
            print(f"resuming {shot_id}: {prompt_id}", flush=True)
        else:
            response = request_json(f"{args.base_url}/prompt", {"prompt": workflow, "client_id": client_id})
            prompt_id = response["prompt_id"]
            print(f"queued {shot_id}: {prompt_id}", flush=True)
        history = wait_history(args.base_url, prompt_id, args.timeout_seconds)
        source = find_saved_video(history, Path(args.comfy_output))
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, destination)
        report.append({
            "id": shot_id,
            "status": "generated",
            "prompt_id": prompt_id,
            "source": str(source),
            "output": str(destination),
            "seed": workflow["10"]["inputs"]["seed"],
            "frames": workflow["9"]["inputs"]["length"],
        })
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"generated {shot_id}: {destination}", flush=True)


if __name__ == "__main__":
    main()
