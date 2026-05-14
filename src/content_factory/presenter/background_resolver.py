from pathlib import Path

from PIL import Image, ImageDraw

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

    def resolve_background(self, requested: str, work_dir: Path) -> str:
        if requested:
            candidate = project_path(requested)
            if candidate.exists():
                return str(candidate)

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
