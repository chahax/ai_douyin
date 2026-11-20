"""Create numbered contact sheets from PySceneDetect representative frames."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenes", type=Path)
    parser.add_argument("csv", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--rows", type=int, default=4)
    parser.add_argument("--thumb-width", type=int, default=240)
    return parser.parse_args()


def load_scene_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        next(handle)
        return list(csv.DictReader(handle))


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
    ):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def main() -> None:
    args = parse_args()
    scene_dir = args.scenes.resolve()
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = sorted(scene_dir.glob("*-Scene-*-01.jpg"))
    rows = load_scene_rows(args.csv.resolve())
    if len(frames) != len(rows):
        raise RuntimeError(f"Scene frame/CSV mismatch: {len(frames)} != {len(rows)}")

    thumb_width = args.thumb_width
    thumb_height = round(thumb_width * 16 / 9)
    label_height = 34
    cell_height = thumb_height + label_height
    per_sheet = args.columns * args.rows
    font = load_font(18)

    for sheet_index in range(math.ceil(len(frames) / per_sheet)):
        start = sheet_index * per_sheet
        selected = frames[start : start + per_sheet]
        canvas = Image.new(
            "RGB",
            (args.columns * thumb_width, args.rows * cell_height),
            "white",
        )
        draw = ImageDraw.Draw(canvas)
        for local_index, frame_path in enumerate(selected):
            scene_index = start + local_index
            row = rows[scene_index]
            x = (local_index % args.columns) * thumb_width
            y = (local_index // args.columns) * cell_height
            with Image.open(frame_path) as image:
                thumb = ImageOps.fit(image.convert("RGB"), (thumb_width, thumb_height))
            canvas.paste(thumb, (x, y + label_height))
            label = (
                f"S{int(row['Scene Number']):02d} "
                f"{float(row['Start Time (seconds)']):05.1f}-"
                f"{float(row['End Time (seconds)']):05.1f}s"
            )
            draw.text((x + 5, y + 6), label, fill="black", font=font)
        output = output_dir / f"scene_contact_{sheet_index + 1:02d}.jpg"
        canvas.save(output, quality=92)
        print(output)


if __name__ == "__main__":
    main()
