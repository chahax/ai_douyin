from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from src.content_factory.presenter.models import CharacterAsset


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def project_path(path: str | Path) -> Path:
    value = Path(path)
    if value.is_absolute():
        return value
    return PROJECT_ROOT / value


class BackgroundResolver:
    DEFAULT_BACKGROUNDS = (
        "data/videos/bg_comfy_green_loop_motion.mp4",
        "data/videos/bg_loop.mp4",
        "data/videos/bg_healing.jpg",
        "data/bg_t0.png",
    )

    CHARACTER_CANDIDATES = {
        "na1": (
            ("data/framepack/frames_looped/na1_idle_v1/%06d.png", "sequence"),
            ("data/png/composite_na1.png", "static"),
            ("data/png/na1_nobg.png", "static"),
        ),
        "n3": (
            ("data/framepack/frames_looped/n3_idle_v1/%06d.png", "sequence"),
            ("data/png/composite_n3.png", "static"),
            ("data/png/n3_nobg.png", "static"),
        ),
    }

    def resolve_background(self, requested: str, work_dir: Path, style: str = "anime") -> str:
        if requested:
            candidate = project_path(requested)
            if candidate.exists():
                return str(candidate)

        normalized_style = (style or "anime").strip().lower()
        if normalized_style == "anime":
            fallback = work_dir / "background_anime.png"
            self._create_anime_background(fallback)
            return str(fallback)

        for path in self.DEFAULT_BACKGROUNDS:
            candidate = project_path(path)
            if candidate.exists():
                return str(candidate)

        fallback = work_dir / "background_gradient.png"
        self._create_gradient(fallback)
        return str(fallback)

    def resolve_character(self, character: str) -> CharacterAsset:
        raw = (character or "na1").strip()
        explicit = project_path(raw)
        if explicit.exists():
            return CharacterAsset(path=str(explicit), kind="static")

        for path, kind in self.CHARACTER_CANDIDATES.get(raw, self.CHARACTER_CANDIDATES["na1"]):
            if kind == "sequence":
                first_frame = project_path(path.replace("%06d", "000001"))
                if first_frame.exists():
                    return CharacterAsset(path=str(project_path(path)), kind=kind)
            else:
                candidate = project_path(path)
                if candidate.exists():
                    return CharacterAsset(path=str(candidate), kind=kind)

        raise FileNotFoundError(f"未找到数字人素材: {character}")

    def _create_gradient(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = 1080, 1920
        image = Image.new("RGB", (width, height), "#18304f")
        draw = ImageDraw.Draw(image)
        for y in range(height):
            ratio = y / height
            r = int(24 + 30 * ratio)
            g = int(48 + 65 * ratio)
            b = int(79 + 45 * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))
        image.save(output_path)

    def _create_anime_background(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = 1080, 1920
        image = Image.new("RGB", (width, height), "#bfe6ff")
        draw = ImageDraw.Draw(image)

        # Soft anime sky gradient.
        for y in range(height):
            ratio = y / height
            if ratio < 0.58:
                t = ratio / 0.58
                r = int(176 + 58 * t)
                g = int(224 + 16 * t)
                b = int(255 - 24 * t)
            else:
                t = (ratio - 0.58) / 0.42
                r = int(234 + 11 * t)
                g = int(240 - 10 * t)
                b = int(231 - 26 * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # Distant city silhouettes in a clean anime palette.
        horizon = 1180
        city_colors = ["#9fc5dd", "#8ab4d4", "#78a6c9"]
        buildings = [
            (40, 980, 180, horizon), (210, 900, 330, horizon), (380, 1020, 500, horizon),
            (550, 930, 690, horizon), (730, 1010, 840, horizon), (880, 880, 1020, horizon),
        ]
        for idx, rect in enumerate(buildings):
            draw.rectangle(rect, fill=city_colors[idx % len(city_colors)])
            x0, y0, x1, y1 = rect
            for wx in range(x0 + 22, x1 - 20, 36):
                for wy in range(y0 + 34, min(y1 - 40, y0 + 220), 52):
                    draw.rounded_rectangle((wx, wy, wx + 14, wy + 22), radius=3, fill="#eaf7ff")

        # Foreground floor with a slight perspective feel.
        draw.polygon([(0, 1320), (1080, 1230), (1080, 1920), (0, 1920)], fill="#f4e7ca")
        for i in range(9):
            y = 1320 + i * 78
            draw.line([(0, y), (1080, y - 90)], fill="#dfcda9", width=3)
        for x in range(-280, 1300, 210):
            draw.line([(x, 1920), (x + 410, 1230)], fill="#e6d5b5", width=3)

        # Soft light blobs, blurred so they read like painted highlights instead of UI decoration.
        glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.ellipse((710, 120, 1240, 650), fill=(255, 247, 184, 76))
        glow_draw.ellipse((-180, 1020, 260, 1500), fill=(255, 255, 255, 58))
        glow = glow.filter(ImageFilter.GaussianBlur(42))
        image = Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")

        image.save(output_path)
