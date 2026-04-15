"""Application configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Runtime settings for the FastAPI backend."""

    app_name: str = "F1 Intelligence API"
    app_version: str = "2.0.0"
    environment: str = "development"
    default_data_source: str = str(BASE_DIR / "fia_2026_component_snapshot.csv")
    source_manifest_path: str = str(BASE_DIR / "fia_2026_document_sources.json")
    circuit_rankings_path: str = str(BASE_DIR / "strategic_circuit_rankings_2026.json")
    enable_fastf1_live: bool = Field(default=True)
    fastf1_cache_dir: str = str(BASE_DIR / ".cache" / "fastf1")
    historical_cache_dir: str = str(BASE_DIR / "data" / "historical" / "2026")
    enable_historical_runtime_generation: bool = Field(default=False)
    sse_poll_interval_seconds: float = Field(default=1.0, ge=0.2, le=30.0)
    fia_documents_base_url: str = "http://localhost:8001"
    fia_documents_timeout_seconds: float = Field(default=6.0, ge=1.0, le=30.0)
    fia_default_feed_limit: int = Field(default=50, ge=1, le=500)

    model_config = SettingsConfigDict(env_prefix="F1_", extra="ignore")


settings = Settings()
