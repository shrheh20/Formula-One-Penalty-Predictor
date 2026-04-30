"""Application entrypoint for the FIA document monitor service."""

from __future__ import annotations

import logging
import os

import uvicorn

from env_loader import load_local_env

load_local_env()

from fia_documents.api import create_app
from fia_documents.db import init_db
from fia_documents.scheduler import DocumentIngestionService, IngestionScheduler, parse_monitor_weekdays


def configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_app():
    configure_logging()
    init_db()

    ingestion_service = DocumentIngestionService()
    scheduler = None
    if _env_bool("FIA_MONITOR_ENABLED", True):
        scheduler = IngestionScheduler(
            ingestion_service=ingestion_service,
            interval_seconds=int(os.getenv("SCRAPE_INTERVAL_SECONDS", "300")),
            run_weekend_only=_env_bool("FIA_MONITOR_WEEKEND_ONLY", False),
            timezone_name=os.getenv("FIA_MONITOR_TIMEZONE", "America/Chicago"),
            active_weekdays=parse_monitor_weekdays(os.getenv("FIA_MONITOR_ACTIVE_DAYS")),
        )
    return create_app(ingestion_service=ingestion_service, scheduler=scheduler)


app = build_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8001")),
        reload=False,
    )
