from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Smart Desktop AI Terminal"
    protocol: str = "smart-desktop-realtime-v1"

    device_id: str = "desktop-agent-001"
    edge_id: str = "esp32s3-sense-001"

    ai_provider: str = Field(default="mock")
    ai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ai_model: str = "qwen-plus"
    dashscope_api_key: str | None = None
    control_token: str | None = None
    device_token: str | None = None

    asr_provider: str = "dashscope_paraformer"
    asr_ws_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    asr_model: str = "paraformer-realtime-v2"
    asr_language_hint: str = "zh"
    asr_local_model: str = "paraformer-zh"
    asr_local_vad_model: str = "fsmn-vad"
    asr_local_punc_model: str = "ct-punc"
    asr_local_device: str = "cpu"
    asr_hotword: str = ""
    asr_vad_max_segment_ms: int = 60000
    asr_batch_size_s: int = 300
    asr_merge_vad: bool = True
    asr_merge_length_s: int = 15
    rfid_registry_path: Path = Path(__file__).resolve().parents[1] / "data" / "rfid_users.json"
    context_db_path: Path = Path(__file__).resolve().parents[1] / "data" / "context.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
