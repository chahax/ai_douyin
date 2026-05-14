from dataclasses import dataclass, field


@dataclass
class PresenterSegment:
    index: int
    text: str
    style: str = "caption"
    keywords: list[str] = field(default_factory=list)
    audio_path: str = ""
    duration: float = 0.0
    text_layer_path: str = ""
    clip_path: str = ""


@dataclass
class PresenterRequest:
    keywords: str = ""
    text: str = ""
    title: str = ""
    voice: str = ""
    tts_provider: str = "gpt_sovits"
    character: str = "na1"
    background: str = ""
    bgm: str = ""
    output_dir: str = "data/videos"
    audio_path: str = ""
    max_segments: int = 8


@dataclass
class CharacterAsset:
    path: str
    kind: str = "static"  # static / sequence


@dataclass
class PresenterResult:
    success: bool
    message: str
    video_path: str = ""
    work_dir: str = ""
    segments: list[PresenterSegment] = field(default_factory=list)
