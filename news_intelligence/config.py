"""Runtime settings for the news intelligence subsystem."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_QDRANT_PATH = PROJECT_ROOT / "data" / "news_intelligence" / "qdrant"


class NewsSettings(BaseSettings):
    news_database_url: str = "postgresql+psycopg://postgres:password@localhost:5432/news_intelligence"
    news_qdrant_mode: str = "local"
    news_qdrant_url: str = "http://127.0.0.1:6333"
    news_qdrant_api_key: str = ""
    news_qdrant_path: str = str(DEFAULT_QDRANT_PATH)
    news_qdrant_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    news_qdrant_collection_chunks: str = "news_article_chunks"
    news_qdrant_collection_clusters: str = "news_cluster_summaries"
    news_qdrant_collection_fia_context: str = "fia_context_chunks"
    news_default_poll_interval_seconds: int = Field(default=1800, ge=60, le=86400)
    news_fetch_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    news_user_agent: str = (
        "F1-PenaltyPredictor-NewsIntelligence/1.0 "
        "(contact: local-development; source: Formula-One-Penalty-Predictor)"
    )
    news_formula1_press_url: str = "https://www.formula1.com/en/latest"
    news_sky_sports_f1_url: str = "https://www.skysports.com/f1/news"
    news_the_race_f1_url: str = "https://www.the-race.com/category/formula-1/"
    news_racingnews365_f1_url: str = "https://racingnews365.com/f1-news"
    news_active_timezone: str = "America/Chicago"

    model_config = SettingsConfigDict(env_file=str(DEFAULT_ENV_FILE), extra="ignore")


news_settings = NewsSettings()
