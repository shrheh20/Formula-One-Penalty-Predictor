"""Scheduled ingestion workflow for FIA decision documents."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from .db import Document, Signal, session_scope
from .document_pipeline import DocumentExtractionPipeline, EXTRACTION_VERSION
from .fia_scraper import FiaDocumentScraper, ScrapedDocument, deduplicate_documents
from .pdf_parser import PdfProcessingError, PdfProcessor
from .signals import SignalBuilder, upsert_signals_and_alerts

LOGGER = logging.getLogger(__name__)


class DocumentIngestionService:
    def __init__(
        self,
        scraper: FiaDocumentScraper | None = None,
        pdf_processor: PdfProcessor | None = None,
        extraction_pipeline: DocumentExtractionPipeline | None = None,
        signal_builder: SignalBuilder | None = None,
    ) -> None:
        self.scraper = scraper or FiaDocumentScraper()
        self.pdf_processor = pdf_processor or PdfProcessor(
            data_dir=os.getenv("FIA_DOCS_DIR", "data/fia_docs")
        )
        self.extraction_pipeline = extraction_pipeline or DocumentExtractionPipeline()
        self.signal_builder = signal_builder or SignalBuilder()

    def run_ingestion_cycle(self, apply_processing: bool = True) -> dict[str, Any]:
        scraped = deduplicate_documents(self.scraper.scrape_documents())

        stats = {
            "scraped": len(scraped),
            "created": 0,
            "updated": 0,
            "downloaded": 0,
            "processed": 0,
            "failed": 0,
            "timestamp": datetime.utcnow().isoformat(),
        }

        for item in scraped:
            try:
                result = self._upsert_document(item, apply_processing=apply_processing)
                for key in ("created", "updated", "downloaded", "processed", "failed"):
                    stats[key] += result.get(key, 0)
            except Exception:
                LOGGER.exception(
                    "Failed to ingest document doc=%s gp=%s",
                    item.doc_number,
                    item.grand_prix,
                )
                stats["failed"] += 1

        return stats

    def _upsert_document(self, item: ScrapedDocument, apply_processing: bool) -> dict[str, int]:
        with session_scope() as session:
            document = (
                session.query(Document)
                .filter(
                    Document.doc_number == item.doc_number,
                    Document.grand_prix == item.grand_prix,
                )
                .one_or_none()
            )

            created = 0
            updated = 0
            downloaded = 0
            processed = 0
            failed = 0

            if document is None:
                document = Document(
                    doc_number=item.doc_number,
                    title=item.title,
                    grand_prix=item.grand_prix,
                    published_time=item.published_time,
                    pdf_url=item.pdf_url,
                    local_file=None,
                    processed=False,
                    is_recalled=item.is_recalled,
                )
                session.add(document)
                session.flush()
                created = 1
                LOGGER.info(
                    "New document detected: %s / Doc %s - %s",
                    item.grand_prix,
                    item.doc_number,
                    item.title,
                )
            else:
                changed = False
                if document.title != item.title:
                    document.title = item.title
                    changed = True
                if document.published_time != item.published_time:
                    document.published_time = item.published_time
                    changed = True
                if document.pdf_url != item.pdf_url:
                    document.pdf_url = item.pdf_url
                    changed = True
                if document.is_recalled != item.is_recalled:
                    document.is_recalled = item.is_recalled
                    changed = True
                if item.is_recalled:
                    document.processed = False
                    document.extraction_status = "recalled"
                    document.needs_review = False
                if changed:
                    updated = 1

            should_process_pdf = (
                apply_processing
                and not item.is_recalled
                and bool(item.pdf_url)
                and (
                    not document.local_file
                    or not document.processed
                    or document.extraction_version != EXTRACTION_VERSION
                    or document.document_type is None
                )
            )

            has_existing_signals = (
                session.query(Signal.id).filter(Signal.document_id == document.id).first() is not None
            )

            if should_process_pdf:
                try:
                    local_file = self.pdf_processor.download_pdf(
                        grand_prix=item.grand_prix,
                        doc_number=item.doc_number,
                        pdf_url=item.pdf_url or "",
                    )
                    document.local_file = local_file
                    downloaded = 1

                    raw_text = self.pdf_processor.extract_text(local_file)
                    extraction = self.extraction_pipeline.extract(
                        title=item.title,
                        text=raw_text,
                        grand_prix=item.grand_prix,
                        doc_number=item.doc_number,
                        is_recalled=item.is_recalled,
                    )

                    document.raw_text = raw_text
                    document.document_type = extraction.document_type
                    document.extraction_status = extraction.extraction_status
                    document.extraction_version = extraction.extraction_version
                    document.extraction_confidence = extraction.extraction_confidence
                    document.needs_review = extraction.needs_review
                    document.parser_output = extraction.parser_output
                    document.extracted_data = extraction.extracted_data
                    document.ai_result = extraction.ai_result
                    document.processed = extraction.extraction_status in {"ready", "needs_review"}
                    signal_drafts = self.signal_builder.build(document)
                    upsert_signals_and_alerts(
                        session=session,
                        document=document,
                        drafts=signal_drafts,
                        builder=self.signal_builder,
                    )
                    processed = 1
                    LOGGER.info(
                        "AI extraction completed: %s / Doc %s (%s)",
                        item.grand_prix,
                        item.doc_number,
                        extraction.document_type,
                    )
                except PdfProcessingError as exc:
                    document.local_file = None
                    document.processed = False
                    document.extraction_status = "download_failed"
                    document.needs_review = True
                    failed = 1
                    LOGGER.warning(
                        "Broken PDF link or invalid PDF for %s / Doc %s: %s",
                        item.grand_prix,
                        item.doc_number,
                        exc,
                    )
                except Exception:
                    document.processed = False
                    document.extraction_status = "processing_failed"
                    document.needs_review = True
                    failed = 1
                    LOGGER.exception(
                        "Unexpected PDF processing failure for %s / Doc %s",
                        item.grand_prix,
                        item.doc_number,
                    )
            elif document.processed and document.extracted_data and not has_existing_signals:
                signal_drafts = self.signal_builder.build(document)
                upsert_signals_and_alerts(
                    session=session,
                    document=document,
                    drafts=signal_drafts,
                    builder=self.signal_builder,
                )
                processed = 1

            if item.is_recalled:
                document.extraction_status = "recalled"
                document.processed = False
                document.needs_review = False
                if document.extracted_data:
                    document.extracted_data["recalled"] = True
                    document.extracted_data["recalled_reason"] = "Portal row marked as recalled by FIA"
                LOGGER.info(
                    "Recalled document updated in database: %s / Doc %s",
                    item.grand_prix,
                    item.doc_number,
                )

            return {
                "created": created,
                "updated": updated,
                "downloaded": downloaded,
                "processed": processed,
                "failed": failed,
            }


class IngestionScheduler:
    def __init__(
        self,
        ingestion_service: DocumentIngestionService,
        interval_seconds: int = 300,
    ) -> None:
        self.ingestion_service = ingestion_service
        self.interval_seconds = interval_seconds
        self.scheduler = BackgroundScheduler()

    @property
    def running(self) -> bool:
        return bool(self.scheduler.running)

    def start(self) -> None:
        if self.scheduler.running:
            return
        self.scheduler.add_job(
            self.ingestion_service.run_ingestion_cycle,
            trigger="interval",
            seconds=self.interval_seconds,
            id="fia-document-monitor",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            next_run_time=datetime.utcnow(),
        )
        self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
