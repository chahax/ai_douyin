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
    SCRIPT_LLM_TIMEOUT_SECONDS: int = 600
    SCRIPT_LLM_MAX_TOKENS: int = 32768
    SCRIPT_LLM_MODEL: str = ""
    SCRIPT_LLM_THINKING: str = ""
    SCRIPT_REVIEW_LLM_MODEL: str = ""
    SOURCE_ANALYSIS_LOW_MEMORY: bool = False
    SOURCE_EXPRESSION_SYNTHESIS_PROVIDER: str = "local_qwen"
    SOURCE_EXPRESSION_LLM_MODEL: str = ""
    VIDEO_SCRIPT_MODEL: str = "Minimax-M2.7"
    VIDEO_SCRIPT_TEMPERATURE: float = 0.2
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
    DOUYIN_OAUTH_REDIRECT_URI: str = ""
    DOUYIN_HOME_URL: str = "https://www.douyin.com/"
    DOUYIN_CREATOR_BASE_URL: str = "https://creator.douyin.com"
    DOUYIN_UPLOAD_URL: str = "https://creator.douyin.com/creator-micro/content/upload"
    DOUYIN_STORAGE_STATE_PATH: str = "./data/browser/douyin/storage_state.json"
    DOUYIN_USER_DATA_DIR: str = "./data/browser/douyin/user_data"
    TREND_BROWSER_STORAGE_STATE_PATH: str = "./data/browser/douyin_trend/storage_state.json"
    TREND_BROWSER_USER_DATA_DIR: str = "./data/browser/douyin_trend/user_data"
    TREND_DB_PATH: str = "./data/trend_intelligence.db"
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

    # Session cookie (跨刷新保持登录)
    SESSION_SECRET: str = ""  # HMAC 签名密钥；为空时由程序启动时生成并写入 data/.session_secret
    SESSION_COOKIE_NAME: str = "ai_douyin_session"
    SESSION_COOKIE_DAYS: int = 30  # 30 天内刷新免登录

    # GPT-SoVITS
    GPT_SOVITS_API_URL: str = "http://127.0.0.1:9880"
    GPT_SOVITS_SDK_ROOT: str = "./GPT_SoVITS"
    GPT_SOVITS_USE_SDK: bool = True
    GPT_SOVITS_ENABLE_HTTP_FALLBACK: bool = False
    GPT_SOVITS_DEFAULT_REF_AUDIO: str = "./data/ref_audio/mature_male_ref.wav"
    GPT_SOVITS_DEFAULT_REF_TEXT: str = "是的，爱和混乱有时候会同时到来，但人最终要学会让自己重新稳定下来。"
    # 必须使用 conda Python 3.9 执行 SDK（系统 Python 3.14 无法加载 SDK 的 C 扩展）
    GPT_SOVITS_CONDA_PYTHON: str = ""  # 由用户在 .env 里填绝对路径，例如 Windows: "C:/Users/<you>/.conda/envs/GPTSoVits/python.exe"

    # ComfyUI background generation
    COMFYUI_HOST: str = "127.0.0.1"
    COMFYUI_PORT: int = 8190
    COMFYUI_MAIN_PATH: str = ""  # ComfyUI 的 main.py 绝对路径，由用户在 .env 里填；留空则 BackgroundResolver 跳过按需启动
    COMFYUI_CHECKPOINT: str = "flux1-schnell-fp8.safetensors"
    COMFYUI_STEPS: int = 8
    COMFYUI_CFG: float = 1.0
    ENABLE_BACKGROUND_SCENE_PLANNER: bool = False
    BACKGROUND_SCENE_LIBRARY_DIR: str = "data/background_scene_library"
    BACKGROUND_SCENE_PLANNER_USE_LLM: bool = False
    BACKGROUND_SCENE_ANALYSIS_MODEL: str = ""

    # Independently authenticated Seedance video providers.
    SEEDANCE_PROVIDER: str = "ark_api"
    ARK_API_KEY: str = ""
    ARK_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    ARK_SEEDANCE_MODEL: str = "doubao-seedance-2-0-mini-260615"
    SEEDANCE_API_KEY: str = ""
    SEEDANCE_BASE_URL: str = "https://operator.las.ap-southeast-1.bytepluses.com/api/v1"
    SEEDANCE_MODEL: str = "dreamina-seedance-2-5-260628"
    SEEDANCE_TIMEOUT_SECONDS: int = 120
    SEEDANCE_POLL_INTERVAL_SECONDS: float = 5.0
    SEEDANCE_DEFAULT_RATIO: str = "9:16"
    SEEDANCE_DEFAULT_RESOLUTION: str = "480p"
    DREAMINA_CLI_PATH: str = "data/tools/dreamina/dreamina.exe"
    DREAMINA_MODEL_VERSION: str = "seedance2.5"
    DREAMINA_CLI_TIMEOUT_SECONDS: int = 120
    DREAMINA_CLI_POLL_INTERVAL_SECONDS: float = 3.0
    # Local accounting only. Zero means that no local budget/quota is configured.
    SEEDANCE_MONTHLY_BUDGET_USD: float = 0.0
    SEEDANCE_MONTHLY_QUOTA_SECONDS: float = 0.0
    # Seedance 2.5 estimated output-only rates from the current BytePlus LAS pricing.
    SEEDANCE_ESTIMATED_USD_PER_SECOND_480P: float = 0.2056
    SEEDANCE_ESTIMATED_USD_PER_SECOND_720P: float = 0.4621
    SEEDANCE_USAGE_REPORT_DIR: str = "data/video_generation/seedance"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator(
        "LLM_PROVIDER",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "VIDEO_SCRIPT_MODEL",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "COMFYUI_HOST",
        "COMFYUI_MAIN_PATH",
        "COMFYUI_CHECKPOINT",
        "BACKGROUND_SCENE_LIBRARY_DIR",
        "BACKGROUND_SCENE_ANALYSIS_MODEL",
        "SEEDANCE_PROVIDER",
        "ARK_API_KEY",
        "ARK_BASE_URL",
        "ARK_SEEDANCE_MODEL",
        "SEEDANCE_API_KEY",
        "SEEDANCE_BASE_URL",
        "SEEDANCE_MODEL",
        "SEEDANCE_DEFAULT_RATIO",
        "SEEDANCE_DEFAULT_RESOLUTION",
        "SEEDANCE_USAGE_REPORT_DIR",
        "DREAMINA_CLI_PATH",
        "DREAMINA_MODEL_VERSION",
        "TREND_BROWSER_STORAGE_STATE_PATH",
        "TREND_BROWSER_USER_DATA_DIR",
        "TREND_DB_PATH",
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

    @field_validator("SEEDANCE_PROVIDER")
    @classmethod
    def validate_seedance_provider(cls, value: str) -> str:
        if value not in {"dreamina_cli", "byteplus_api", "ark_api"}:
            raise ValueError("SEEDANCE_PROVIDER must be dreamina_cli, byteplus_api or ark_api")
        return value

    @field_validator("SEEDANCE_DEFAULT_RATIO")
    @classmethod
    def validate_seedance_ratio(cls, value: str) -> str:
        allowed = {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"}
        if value not in allowed:
            raise ValueError(f"SEEDANCE_DEFAULT_RATIO must be one of {sorted(allowed)}")
        return value

    @field_validator("SEEDANCE_DEFAULT_RESOLUTION")
    @classmethod
    def validate_seedance_resolution(cls, value: str) -> str:
        if value not in {"480p", "720p", "1080p", "4k"}:
            raise ValueError(
                "SEEDANCE_DEFAULT_RESOLUTION must be 480p, 720p, 1080p or 4k; individual model limits still apply"
            )
        return value

    @field_validator(
        "SEEDANCE_MONTHLY_BUDGET_USD",
        "SEEDANCE_MONTHLY_QUOTA_SECONDS",
        "SEEDANCE_ESTIMATED_USD_PER_SECOND_480P",
        "SEEDANCE_ESTIMATED_USD_PER_SECOND_720P",
    )
    @classmethod
    def validate_seedance_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Seedance budget, quota, and rates must not be negative")
        return value


settings = Settings()
