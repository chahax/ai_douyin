from dataclasses import dataclass, field


@dataclass
class PresenterSegment:
    index: int
    text: str
    style: str = "caption"
    keywords: list[str] = field(default_factory=list)
    audio_path: str = ""
    duration: float = 0.0
    background_path: str = ""
    background_group: int = 0
    background_prompt: str = ""
    background_action: str = ""
    background_subject: str = ""
    background_include_ip: bool = False
    background_plan: dict = field(default_factory=dict)
    text_layer_path: str = ""
    clip_path: str = ""


@dataclass
class PresenterRequest:
    keywords: str = ""
    text: str = ""
    title: str = ""
    voice: str = ""
    tts_provider: str = "edge"
    character: str = "na1"
    character_position: str = "right_bottom"
    character_size: str = "medium"
    background: str = ""
    background_style: str = "anime"
    bgm: str = ""
    output_dir: str = "data/videos"
    audio_path: str = ""
    max_segments: int = 16


@dataclass
class CharacterAsset:
    path: str
    kind: str = "static"  # static / sequence / video / video_chroma


@dataclass
class PresenterResult:
    success: bool
    message: str
    video_path: str = ""
    work_dir: str = ""
    segments: list[PresenterSegment] = field(default_factory=list)
