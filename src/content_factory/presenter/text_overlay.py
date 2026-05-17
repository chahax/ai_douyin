from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.content_factory.presenter.models import PresenterSegment


FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)


class TextOverlayRenderer:
    def __init__(self, width: int = 1080, height: int = 1920):
        self.width = width
        self.height = height

    def render(
        self,
        segment: PresenterSegment,
        title: str,
        output_path: Path,
        character_position: str = "right_bottom",
        character_size: str = "medium",
    ) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        self._draw_title(draw, title)
        self._draw_caption(draw, segment.text, character_position, character_size)

        image.save(output_path)
        return str(output_path)

    def _font(self, size: int):
        for path in FONT_CANDIDATES:
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
        return ImageFont.load_default()

    def _draw_title(self, draw: ImageDraw.ImageDraw, title: str) -> None:
        title = (title or "数字人主讲").strip()
        font = self._font(46)
        lines = self._wrap_text(draw, title, font, max_width=900, max_lines=2)
        y = 78
        for line in lines:
            draw.text((72, y), line, font=font, fill=(0, 0, 0, 255))
            y += 58

    def _draw_keywords(self, draw: ImageDraw.ImageDraw, keywords: list[str]) -> None:
        if not keywords:
            return
        font = self._font(32)
        x, y = 72, 220
        for keyword in keywords[:2]:
            text = keyword[:8]
            bbox = draw.textbbox((0, 0), text, font=font)
            width = bbox[2] - bbox[0]
            rect = (x, y, x + width + 44, y + 58)
            draw.rounded_rectangle(rect, radius=18, fill=(18, 43, 72, 104), outline=(255, 255, 255, 68), width=1)
            self._draw_text_with_shadow(draw, (x + 22, y + 11), text, font, fill=(255, 238, 185, 238))
            x = rect[2] + 16

    def _draw_focus(self, draw: ImageDraw.ImageDraw, text: str, font_size: int) -> None:
        font = self._font(font_size)
        lines = self._wrap_text(draw, text, font, max_width=860, max_lines=3)
        line_height = int(font_size * 1.35)
        block_height = line_height * len(lines)
        y = 520 - block_height // 2
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            x = (self.width - (bbox[2] - bbox[0])) // 2
            self._draw_text_with_shadow(draw, (x, y), line, font, fill=(255, 255, 255, 250), stroke=3)
            y += line_height

    def _draw_caption(self, draw: ImageDraw.ImageDraw, text: str, character_position: str, character_size: str) -> None:
        font_size = 42
        font = self._font(font_size)
        x0, y0, x1 = self._caption_box_bounds(character_position, character_size)
        max_width = x1 - x0
        lines = self._wrap_text(draw, text, font, max_width=max_width, max_lines=2)
        line_height = int(font_size * 1.35)
        block_height = line_height * len(lines)
        y = y0 - block_height // 2
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_width = bbox[2] - bbox[0]
            x = x0 + max(0, (max_width - line_width) // 2)
            draw.text((x, y), line, font=font, fill=(0, 0, 0, 255))
            y += line_height

    def _caption_box_bounds(self, character_position: str, character_size: str) -> tuple[int, int, int]:
        position = (character_position or "right_bottom").strip().lower()
        size = (character_size or "medium").strip().lower()
        if position == "right_bottom":
            right_edge = {"small": 680, "medium": 580, "large": 480}.get(size, 580)
            return 72, 1710, right_edge
        if position == "left_bottom":
            left_edge = {"small": 400, "medium": 500, "large": 600}.get(size, 500)
            return left_edge, 1710, self.width - 72
        return 80, 1660, self.width - 80

    def _wrap_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font,
        max_width: int,
        max_lines: int,
    ) -> list[str]:
        text = (text or "").strip()
        if not text:
            return []

        lines = []
        current = ""
        for char in text:
            candidate = current + char
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if bbox[2] - bbox[0] <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = char
                if len(lines) >= max_lines:
                    break
        if current and len(lines) < max_lines:
            lines.append(current)

        return lines

    def _draw_text_with_shadow(
        self,
        draw: ImageDraw.ImageDraw,
        pos: tuple[int, int],
        text: str,
        font,
        fill,
        stroke: int = 1,
    ) -> None:
        x, y = pos
        if stroke:
            draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 180))
        else:
            draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 110))
            draw.text((x, y), text, font=font, fill=fill)
