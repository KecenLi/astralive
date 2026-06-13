from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "MODVII"
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    web_origin: str = "http://localhost:5173"

    asr_provider: str = "mock"
    vision_provider: str = "mock"
    llm_provider: str = "mock"
    tts_provider: str = "mock"
    realtime_provider: str = "none"

    google_application_credentials: str = ""

    openai_compatible_base_url: str = ""
    openai_compatible_api_key: str = ""
    openai_compatible_llm_model: str = ""
    openai_compatible_vision_model: str = ""
    openai_compatible_asr_base_url: str = ""
    openai_compatible_asr_api_key: str = ""
    openai_compatible_asr_model: str = ""
    openai_compatible_asr_endpoint_path: str = "/audio/transcriptions"
    openai_compatible_tts_base_url: str = ""
    openai_compatible_tts_api_key: str = ""
    openai_compatible_tts_model: str = ""
    openai_compatible_tts_voice: str = "default"
    openai_compatible_tts_endpoint_path: str = "/audio/speech"
    openai_compatible_tts_response_format: str = "mp3"

    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_api_key: str = ""
    gemini_llm_model: str = "gemini-3.5-flash"
    gemini_vision_model: str = "gemini-3.5-flash"
    gemini_asr_model: str = "gemini-3.1-flash-live-preview"
    gemini_realtime_model: str = "gemini-3.1-flash-live-preview"
    gemini_tts_model: str = "gemini-3.1-flash-tts-preview"
    gemini_tts_voice: str = "Kore"

    vertex_ai_project: str = ""
    vertex_ai_location: str = "global"
    vertex_ai_api_endpoint: str = "https://aiplatform.googleapis.com"
    vertex_ai_llm_model: str = "gemini-2.5-flash"
    vertex_ai_vision_model: str = "gemini-2.5-flash"
    vertex_ai_asr_model: str = "gemini-live-2.5-flash-native-audio"
    vertex_ai_realtime_model: str = "gemini-live-2.5-flash-native-audio"
    vertex_ai_tts_model: str = "gemini-3.1-flash-tts-preview"
    vertex_ai_tts_voice: str = "Kore"
    vertex_ai_request_timeout_seconds: float = 15.0

    cosyvoice3_python: str = ""
    cosyvoice3_repo_dir: str = str(PROJECT_ROOT / "third_party" / "CosyVoice")
    cosyvoice3_model_dir: str = str(PROJECT_ROOT / "models" / "Fun-CosyVoice3-0.5B")
    cosyvoice3_script: str = str(PROJECT_ROOT / "scripts" / "cosyvoice3_synth.py")
    cosyvoice3_worker_enabled: bool = True
    cosyvoice3_worker_script: str = str(PROJECT_ROOT / "scripts" / "cosyvoice3_worker.py")
    cosyvoice3_prompt_audio: str = ""
    cosyvoice3_prompt_text: str = (
        "You are MODVII, a warm and lively bilingual desktop companion.<|endofprompt|>"
        "希望你以后能够做的比我还好呦。"
    )
    cosyvoice3_device: str = "cpu"
    cosyvoice3_timeout_seconds: float = 120.0

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_llm_model: str = "qwen2.5:0.5b"

    audio_input_sample_rate: int = 16000
    audio_output_sample_rate: int = 24000
    audio_channels: int = 1
    audio_chunk_max_bytes: int = 262144
    audio_turn_max_bytes: int = 2097152
    audio_transcription_language: str = "zh-CN"
    audio_route: str = "asr_first"
    realtime_input_idle_timeout_seconds: float = 8.0
    realtime_turn_timeout_seconds: float = 8.0
    realtime_recovery_asr_timeout_seconds: float = 6.0

    wake_word: str = "小七"
    persona_prompt: str = (
        "你是 MODVII，也叫小七，一个中文优先的女性 AI VTuber 桌面伴侣。"
        "你通过麦克风、摄像头和屏幕理解用户当前上下文。"
        "用户说出“小七”后，先确认自己在听，然后专注理解用户接下来的要求并直接回应。"
        "回答要适合语音朗读，保持简短、自然、具体，通常一到两句话。"
        "多用追问推动对话，但不要空泛寒暄。"
        "你可以使用表情意图：neutral、happy、curious、surprised、confused、concerned、thinking、sleepy。"
        "如果视觉信息不足，明确说明不确定，并请求更清晰的镜头或屏幕。"
    )
    frame_jpeg_quality: float = 0.72
    max_frame_width: int = 1280
    max_frame_height: int = 720
    vision_cache_ttl_seconds: int = 30
    vision_request_timeout_seconds: float = 5.0
    vision_max_concurrency: int = 1
    vision_pending_frame_limit: int = 2
    vision_result_max_age_seconds: float = 12.0
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
