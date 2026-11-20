"""Select the nearest single character reference for a planned shot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SPECIAL_ACTIONS = {
    "looking_down": "front_down_020",
    "phone_reading": "front_down_020",
    "over_shoulder": "over_shoulder_right",
}


def load_library(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data.get("references"), list):
        raise ValueError("library.json must contain a references list")
    return data


def select_reference(
    library: dict[str, Any],
    *,
    yaw_deg: float = 0.0,
    pitch_deg: float = 0.0,
    shot_size: str = "medium",
    action: str = "neutral",
) -> dict[str, Any]:
    references = library["references"]
    by_id = {item["id"]: item for item in references}

    if shot_size == "full" and "full_body_front" in by_id:
        return by_id["full_body_front"]
    if action in SPECIAL_ACTIONS and SPECIAL_ACTIONS[action] in by_id:
        return by_id[SPECIAL_ACTIONS[action]]

    angle_refs = [item for item in references if item.get("role") == "head_angle"]
    return min(
        angle_refs,
        key=lambda item: abs(float(item["yaw_deg"]) - yaw_deg)
        + 0.35 * abs(float(item.get("pitch_deg", 0.0)) - pitch_deg),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Choose one identity reference image for a shot."
    )
    parser.add_argument("library", type=Path, help="Path to library.json")
    parser.add_argument("--yaw", type=float, default=0.0)
    parser.add_argument("--pitch", type=float, default=0.0)
    parser.add_argument(
        "--shot-size", choices=("close", "medium", "full"), default="medium"
    )
    parser.add_argument(
        "--action",
        choices=("neutral", "looking_down", "phone_reading", "over_shoulder"),
        default="neutral",
    )
    parser.add_argument("--json", action="store_true", help="Print structured output")
    args = parser.parse_args()

    library_path = args.library.resolve()
    library = load_library(library_path)
    selected = select_reference(
        library,
        yaw_deg=args.yaw,
        pitch_deg=args.pitch,
        shot_size=args.shot_size,
        action=args.action,
    )
    output = {
        "character_id": library["character_id"],
        "reference_id": selected["id"],
        "reference_path": str((library_path.parent / selected["file"]).resolve()),
        "yaw_deg": selected["yaw_deg"],
        "pitch_deg": selected["pitch_deg"],
        "role": selected["role"],
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(output["reference_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
