"""Application entrypoint for the FIA document monitor service."""

from __future__ import annotations

import logging
import os

import uvicorn

from fia_documents.api import create_app
from fia_documents.db import init_db
from fia_documents.scheduler import DocumentIngestionService, IngestionScheduler


def configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def build_app():
    configure_logging()
    init_db()

    ingestion_service = DocumentIngestionService()
    scheduler = IngestionScheduler(
        ingestion_service=ingestion_service,
        interval_seconds=int(os.getenv("SCRAPE_INTERVAL_SECONDS", "300")),
    )
    return create_app(ingestion_service=ingestion_service, scheduler=scheduler)


app = build_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
