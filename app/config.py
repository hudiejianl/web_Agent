import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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
    enable_browser_research: bool = True
    enable_rag_eval: bool = True
    auto_seed_data: bool = True
    max_browser_search_pages: int = 2
    max_browser_candidates: int = 10
    max_browser_ingest: int = 3
    max_browser_navigation_pages: int = 8
    browser_fetch_retries: int = 2
    embedding_model: str = "hashing"
    embedding_provider: str = "local"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_timeout_seconds: int = 30
    rag_chunk_size: int = 600
    rag_chunk_overlap: int = 120
    reranker_provider: str = "local"
    reranker_model: str = ""
    reranker_api_key: str = ""
    reranker_base_url: str = ""
    reranker_timeout_seconds: int = 30
    llm_provider: str = "none"
    llm_model: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: int = 45
    request_timeout_seconds: int = 15
    max_context_messages: int = 8
    summary_trigger_messages: int = 10
    enable_opentelemetry: bool = False
    otel_service_name: str = "admission-research-agent"
    otel_exporter_otlp_endpoint: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("max_browser_search_pages")
    @classmethod
    def clamp_search_pages(cls, value: int) -> int:
        return max(1, min(value, 5))

    @field_validator("max_browser_candidates")
    @classmethod
    def clamp_browser_candidates(cls, value: int) -> int:
        return max(1, min(value, 50))

    @field_validator("max_browser_ingest")
    @classmethod
    def clamp_browser_ingest(cls, value: int) -> int:
        return max(1, min(value, 20))

    @field_validator("max_browser_navigation_pages")
    @classmethod
    def clamp_browser_navigation_pages(cls, value: int) -> int:
        return max(1, min(value, 50))

    @field_validator("browser_fetch_retries")
    @classmethod
    def clamp_fetch_retries(cls, value: int) -> int:
        return max(1, min(value, 5))

    @field_validator("rag_chunk_size")
    @classmethod
    def clamp_chunk_size(cls, value: int) -> int:
        return max(100, min(value, 4000))

    @field_validator("rag_chunk_overlap")
    @classmethod
    def clamp_chunk_overlap(cls, value: int) -> int:
        return max(0, min(value, 1000))

    @field_validator("max_context_messages")
    @classmethod
    def clamp_context_messages(cls, value: int) -> int:
        return max(2, min(value, 50))

    @field_validator("summary_trigger_messages")
    @classmethod
    def clamp_summary_trigger(cls, value: int) -> int:
        return max(2, min(value, 100))

    @field_validator("request_timeout_seconds", "llm_timeout_seconds", "embedding_timeout_seconds", "reranker_timeout_seconds")
    @classmethod
    def clamp_timeouts(cls, value: int) -> int:
        return max(1, min(value, 300))

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
