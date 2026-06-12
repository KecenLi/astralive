from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "AstraLive"
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    web_origin: str = "http://localhost:5173"

    asr_provider: str = "mock"
    vision_provider: str = "mock"
    llm_provider: str = "mock"
    tts_provider: str = "mock"
    realtime_provider: str = "none"

    openai_compatible_base_url: str = ""
    openai_compatible_api_key: str = ""
    openai_compatible_llm_model: str = ""
    openai_compatible_vision_model: str = ""
    openai_compatible_tts_model: str = ""

    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_api_key: str = ""
    gemini_llm_model: str = "gemini-3.5-flash"
    gemini_vision_model: str = "gemini-3.5-flash"
    gemini_realtime_model: str = ""

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_llm_model: str = "qwen2.5:0.5b"

    wake_word: str = "阿斯塔"
    frame_jpeg_quality: float = 0.72
    max_frame_width: int = 1280
    max_frame_height: int = 720
    vision_cache_ttl_seconds: int = 30
    scene_change_threshold: float = 0.12

    data_dir: Path = Field(default=Path("data"))

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def sqlite_dir(self) -> Path:
        return self.data_dir / "sqlite"


@lru_cache
def get_settings() -> Settings:
    return Settings()
