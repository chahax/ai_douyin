from dataclasses import dataclass, field


DEFAULT_SONIC_FOX_CHARACTER = "data/ip_characters/_incoming/sonic_test/fox_planner_576_mouthboost_upscale1080_sharp.mp4"
INPUT_MODE_KEYWORDS = "keywords"
INPUT_MODE_ARTICLE_DIRECT = "article_direct"
INPUT_MODE_ARTICLE_EXTRACT = "article_extract"
INPUT_MODES = (
    INPUT_MODE_KEYWORDS,
    INPUT_MODE_ARTICLE_DIRECT,
    INPUT_MODE_ARTICLE_EXTRACT,
)


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
    text_file: str = ""
    input_mode: str = INPUT_MODE_KEYWORDS
    title: str = ""
    voice: str = ""
    tts_provider: str = "edge"
    character: str = DEFAULT_SONIC_FOX_CHARACTER
    character_position: str = "right_bottom"
    character_size: str = "medium"
    background: str = ""
    background_style: str = "anime"
    bgm: str = ""
    output_dir: str = "data/videos"
    audio_path: str = ""
    max_segments: int = 16
    use_comfy_background: bool = True
    # I-2 ComfyUI 容错：True 时 ComfyUI 不可用直接中止 pipeline；False 时用 None 背景继续（默认）
    strict_background: bool = False


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
    # I-2 ComfyUI 容错：error_class 反映 pipeline 状态（"" / "OOM" / "WORKFLOW" / "TIMEOUT" / "UNAVAILABLE"）
    error_class: str = ""
