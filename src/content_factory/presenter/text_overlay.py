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

    def render(self, segment: PresenterSegment, title: str, output_path: Path) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        self._draw_title(draw, title)
        if segment.style == "title":
            self._draw_focus(draw, segment.text, font_size=64)
        elif segment.style == "highlight":
            self._draw_focus(draw, segment.text, font_size=58)
        else:
            self._draw_keywords(draw, segment.keywords)
            self._draw_caption(draw, segment.text)

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
        font = self._font(44)
        lines = self._wrap_text(draw, title, font, max_width=900, max_lines=2)
        y = 84
        for line in lines:
            self._draw_text_with_shadow(draw, (72, y), line, font, fill=(255, 255, 255, 245))
            y += 58

    def _draw_keywords(self, draw: ImageDraw.ImageDraw, keywords: list[str]) -> None:
        if not keywords:
            return
        font = self._font(40)
        text = "  /  ".join(keywords[:3])
        bbox = draw.textbbox((0, 0), text, font=font)
        pad_x, pad_y = 28, 18
        x, y = 72, 260
        rect = (x - pad_x, y - pad_y, x + (bbox[2] - bbox[0]) + pad_x, y + (bbox[3] - bbox[1]) + pad_y)
        draw.rounded_rectangle(rect, radius=20, fill=(0, 0, 0, 95))
        self._draw_text_with_shadow(draw, (x, y), text, font, fill=(255, 238, 185, 245))

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

    def _draw_caption(self, draw: ImageDraw.ImageDraw, text: str) -> None:
        font_size = 46
        font = self._font(font_size)
        lines = self._wrap_text(draw, text, font, max_width=880, max_lines=2)
        line_height = int(font_size * 1.45)
        box_height = max(150, line_height * len(lines) + 48)
        x0, y0 = 70, self.height - box_height - 116
        x1, y1 = self.width - 70, y0 + box_height
        draw.rounded_rectangle((x0, y0, x1, y1), radius=26, fill=(0, 0, 0, 150))
        y = y0 + 26
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            x = (self.width - (bbox[2] - bbox[0])) // 2
            self._draw_text_with_shadow(draw, (x, y), line, font, fill=(255, 255, 255, 245))
            y += line_height

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

        if len(lines) == max_lines and len("".join(lines)) < len(text):
            lines[-1] = lines[-1].rstrip("，。！？,.!?") + "..."
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
