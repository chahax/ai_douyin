from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "WisdomAI"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # LLM Settings
    LLM_PROVIDER: str = ""
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-chat"
    LLM_TIMEOUT_SECONDS: int = 120
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
    ENABLE_HF_EMBEDDING_FALLBACK: bool = False

    # Database
    DATABASE_URL: str = "sqlite:///./data/wisdom_ai.db"

    # Redis (Optional)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Platform APIs (Douyin)
    DOUYIN_CLIENT_KEY: str = ""
    DOUYIN_CLIENT_SECRET: str = ""
    DOUYIN_HOME_URL: str = "https://www.douyin.com/"
    DOUYIN_CREATOR_BASE_URL: str = "https://creator.douyin.com"
    DOUYIN_UPLOAD_URL: str = "https://creator.douyin.com/creator-micro/content/upload"
    DOUYIN_STORAGE_STATE_PATH: str = "./data/browser/douyin/storage_state.json"
    DOUYIN_USER_DATA_DIR: str = "./data/browser/douyin/user_data"
    BROWSER_CHANNEL: str = ""
    BROWSER_HEADLESS: bool = False
    BROWSER_SLOW_MO_MS: int = 0
    BROWSER_TIMEOUT_MS: int = 30000

    # Account login email verification
    SMTP_HOST: str = "smtp.163.com"
    SMTP_PORT: int = 25
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_SSL: bool = False
    LOGIN_CODE_TTL_MINUTES: int = 10
    LOGIN_CODE_COOLDOWN_SECONDS: int = 60

    # Storage
    STORAGE_ROOT: str = "./data"
    BOOKS_DIR: str = "./data/books"
    SYNC_BOOKS_SOURCE_DIR: str = "C:/data/books"
    EXTRACTED_DIR: str = "./data/extracted"
    VIDEOS_DIR: str = "./data/videos"
    REF_AUDIO_DIR: str = "./data/ref_audio"
    CHROMA_PERSIST_DIR: str = "./data/chroma_db"
    DEFAULT_BGM_PATH: str = "./data/ref_audio/Morning-Routine-Lofi-Study-Music(chosic.com).mp3"
    TTS_PROVIDER: str = "edge"

    # GPT-SoVITS
    GPT_SOVITS_API_URL: str = "http://127.0.0.1:9880"
    GPT_SOVITS_SDK_ROOT: str = "./GPT_SoVITS"
    GPT_SOVITS_USE_SDK: bool = True
    GPT_SOVITS_ENABLE_HTTP_FALLBACK: bool = False
    GPT_SOVITS_DEFAULT_REF_AUDIO: str = "./data/ref_audio/mature_male_ref.wav"
    GPT_SOVITS_DEFAULT_REF_TEXT: str = "是的，爱和混乱有时候会同时到来，但人最终要学会让自己重新稳定下来。"
    # 必须使用 conda Python 3.9 执行 SDK（系统 Python 3.14 无法加载 SDK 的 C 扩展）
    GPT_SOVITS_CONDA_PYTHON: str = "C:/Users/c/.conda/envs/GPTSoVits/python.exe"

    # ComfyUI background generation
    COMFYUI_HOST: str = "127.0.0.1"
    COMFYUI_PORT: int = 8190
    COMFYUI_MAIN_PATH: str = "D:/IT/AI_vido/ComfyUI/main.py"
    COMFYUI_CHECKPOINT: str = "flux1-schnell-fp8.safetensors"
    COMFYUI_STEPS: int = 8
    COMFYUI_CFG: float = 1.0
    ENABLE_BACKGROUND_SCENE_PLANNER: bool = False
    BACKGROUND_SCENE_LIBRARY_DIR: str = "data/background_scene_library"
    BACKGROUND_SCENE_PLANNER_USE_LLM: bool = False
    BACKGROUND_SCENE_ANALYSIS_MODEL: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator(
        "LLM_PROVIDER",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "COMFYUI_HOST",
        "COMFYUI_MAIN_PATH",
        "COMFYUI_CHECKPOINT",
        "BACKGROUND_SCENE_LIBRARY_DIR",
        "BACKGROUND_SCENE_ANALYSIS_MODEL",
        mode="before",
    )
    @classmethod
    def normalize_string_value(cls, value):
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if " #" in normalized:
            normalized = normalized.split(" #", 1)[0].rstrip()
        return normalized

    @field_validator("DEBUG", mode="before")
    @classmethod
    def normalize_debug_value(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "dev", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return value


settings = Settings()
