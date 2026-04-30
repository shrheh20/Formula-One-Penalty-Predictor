#!/usr/bin/env python3
"""Reset FIA document tables and rebuild them from the FIA source documents."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from env_loader import load_local_env

load_local_env()

from fia_documents.db import engine, init_db  # noqa: E402
from fia_documents.scheduler import DocumentIngestionService  # noqa: E402


def reset_tables() -> None:
    with engine.begin() as connection:
        dialect = engine.dialect.name
        if dialect == "postgresql":
            connection.execute(
                text(
                    "TRUNCATE TABLE alerts, signals, document_entities, documents RESTART IDENTITY"
                )
            )
            return

        for table_name in ("alerts", "signals", "document_entities", "documents"):
            connection.execute(text(f"DELETE FROM {table_name}"))


def clear_local_cache(data_dir: str) -> None:
    target = Path(data_dir)
    if not target.exists():
        return
    shutil.rmtree(target)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete FIA document rows and rebuild from the official FIA website in batches."
    )
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--pause-seconds", type=float, default=1.0)
    parser.add_argument("--clear-local-cache", action="store_true")
    parser.add_argument("--data-dir", default="data/fia_docs")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    init_db()

    if args.clear_local_cache:
        clear_local_cache(args.data_dir)

    print("Resetting FIA tables...")
    reset_tables()

    service = DocumentIngestionService()
    scraped = service.scraper.scrape_documents()
    if args.limit is not None:
        scraped = scraped[: args.limit]

    print(f"Rebuilding {len(scraped)} scraped documents in batches of {args.batch_size}...")
    result = service.ingest_scraped_documents(
        scraped_documents=scraped,
        apply_processing=True,
        batch_size=args.batch_size,
        pause_seconds=args.pause_seconds,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
