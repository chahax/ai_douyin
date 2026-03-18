import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "WisdomAI"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # LLM Settings
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-chat"

    # Database
    DATABASE_URL: str = "sqlite:///./data/wisdom_ai.db"
    
    # Redis (Optional)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Platform APIs (Douyin)
    DOUYIN_CLIENT_KEY: str = ""
    DOUYIN_CLIENT_SECRET: str = ""
    
    # Storage
    STORAGE_ROOT: str = "./data"
    BOOKS_DIR: str = "./data/books"
    EXTRACTED_DIR: str = "./data/extracted"
    VIDEOS_DIR: str = "./data/videos"

    class Config:
        env_file = ".env"

settings = Settings()
