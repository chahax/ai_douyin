"""Deterministic cleanup for AI-generated subject masks."""

from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw, ImageFilter


def refine_subject_mask(
    mask: Image.Image,
    *,
    threshold: int = 128,
    grow: int = 0,
    feather: float = 0.0,
) -> Image.Image:
    if not 0 <= threshold <= 255:
        raise ValueError("threshold must be between 0 and 255")
    if grow < 0:
        raise ValueError("grow cannot be negative")
    if feather < 0:
        raise ValueError("feather cannot be negative")

    grayscale = mask.convert("L")
    binary = grayscale.point(lambda value: 255 if value >= threshold else 0)
    filled = _fill_holes(binary)
    if grow:
        filled = filled.filter(ImageFilter.MaxFilter(grow * 2 + 1))
    if feather:
        filled = filled.filter(ImageFilter.GaussianBlur(feather))
    return filled


def _fill_holes(binary: Image.Image) -> Image.Image:
    width, height = binary.size
    padded = Image.new("L", (width + 2, height + 2), 0)
    padded.paste(binary, (1, 1))
    inverse = ImageChops.invert(padded)
    ImageDraw.floodfill(inverse, (0, 0), 0)
    holes = inverse.crop((1, 1, width + 1, height + 1))
    return ImageChops.lighter(binary, holes)
