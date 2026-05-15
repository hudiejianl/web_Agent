import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
logging.getLogger("chromadb.telemetry.product.posthog").disabled = True


class Settings(BaseSettings):
    app_name: str = "Admission Research Agent"
    app_env: str = "development"
    database_path: str = "data/runtime/admission_agent.sqlite3"
    chroma_path: str = "data/runtime/chroma"
    chroma_collection: str = "tutors"
    log_level: str = "INFO"
    embedding_model: str = "hashing"
    llm_provider: str = "none"
    llm_model: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: int = 45
    request_timeout_seconds: int = 15
    max_context_messages: int = 8
    summary_trigger_messages: int = 10

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def database_file(self) -> Path:
        return Path(self.database_path)

    @property
    def chroma_dir(self) -> Path:
        return Path(self.chroma_path)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.database_file.parent.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    return settings
