"""Scheduled ingestion workflow for FIA decision documents."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import or_

from .db import Document, DocumentEntity, Signal, session_scope
from .document_pipeline import DocumentExtractionPipeline, EXTRACTION_VERSION
from .fia_scraper import FiaDocumentScraper, ScrapedDocument, deduplicate_documents
from .pdf_parser import PdfProcessingError, PdfProcessor
from .signals import SignalBuilder, upsert_signals_and_alerts
from .summary import DASHBOARD_SUMMARY_VERSION, DashboardSummaryClient

LOGGER = logging.getLogger(__name__)


def parse_monitor_weekdays(raw_value: str | None) -> tuple[int, ...]:
    if not raw_value:
        return (4, 5, 6)
    weekdays: list[int] = []
    for chunk in raw_value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            weekday = int(chunk)
        except ValueError:
            continue
        if 0 <= weekday <= 6 and weekday not in weekdays:
            weekdays.append(weekday)
    return tuple(weekdays or (4, 5, 6))


class DocumentIngestionService:
    def __init__(
        self,
        scraper: FiaDocumentScraper | None = None,
        pdf_processor: PdfProcessor | None = None,
        extraction_pipeline: DocumentExtractionPipeline | None = None,
        signal_builder: SignalBuilder | None = None,
        summary_client: DashboardSummaryClient | None = None,
    ) -> None:
        self.scraper = scraper or FiaDocumentScraper()
        self.pdf_processor = pdf_processor or PdfProcessor(
            data_dir=os.getenv("FIA_DOCS_DIR", "data/fia_docs")
        )
        self.extraction_pipeline = extraction_pipeline or DocumentExtractionPipeline()
        self.signal_builder = signal_builder or SignalBuilder()
        self.summary_client = summary_client or DashboardSummaryClient()

    def run_ingestion_cycle(self, apply_processing: bool = True) -> dict[str, Any]:
        scraped = deduplicate_documents(self.scraper.scrape_documents())
        return self.ingest_scraped_documents(
            scraped_documents=scraped,
            apply_processing=apply_processing,
        )

    def ingest_scraped_documents(
        self,
        *,
        scraped_documents: list[ScrapedDocument],
        apply_processing: bool = True,
        batch_size: int | None = None,
        pause_seconds: float = 0.0,
    ) -> dict[str, Any]:
        scraped = deduplicate_documents(scraped_documents)

        stats = {
            "scraped": len(scraped),
            "created": 0,
            "updated": 0,
            "downloaded": 0,
            "processed": 0,
            "failed": 0,
            "timestamp": datetime.utcnow().isoformat(),
        }

        effective_batch_size = batch_size or len(scraped) or 1
        effective_batch_size = max(1, effective_batch_size)
        stats["batches"] = 0

        for start in range(0, len(scraped), effective_batch_size):
            batch = scraped[start : start + effective_batch_size]
            stats["batches"] += 1
            for item in batch:
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
            if pause_seconds > 0 and start + effective_batch_size < len(scraped):
                time.sleep(pause_seconds)

        return stats

    def queue_documents_for_reprocessing(
        self,
        *,
        document_ids: list[int] | None = None,
        extraction_statuses: list[str] | None = None,
        grand_prix: str | None = None,
        include_unknown: bool = False,
        include_needs_review: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        document_ids = document_ids or []
        extraction_statuses = extraction_statuses or []

        with session_scope() as session:
            query = session.query(Document)

            if document_ids:
                query = query.filter(Document.id.in_(document_ids))
            if extraction_statuses:
                query = query.filter(Document.extraction_status.in_(extraction_statuses))
            if grand_prix:
                query = query.filter(Document.grand_prix.ilike(f"%{grand_prix}%"))

            review_filters = []
            if include_unknown:
                review_filters.extend(
                    [
                        Document.document_type == "other",
                        Document.document_family == "other",
                    ]
                )
            if include_needs_review:
                review_filters.append(Document.needs_review.is_(True))
            if review_filters:
                query = query.filter(or_(*review_filters))

            query = query.order_by(Document.updated_at.desc(), Document.id.desc())
            if limit is not None:
                query = query.limit(limit)

            documents = query.all()
            for document in documents:
                document.processed = False
                document.extraction_status = None
                document.extraction_version = None
                document.extraction_confidence = None
                document.needs_review = True

            return {
                "queued": len(documents),
                "document_ids": [document.id for document in documents],
            }

    def reprocess_documents_from_raw(
        self,
        *,
        document_ids: list[int] | None = None,
        grand_prix: str | None = None,
        batch_size: int = 10,
        max_documents: int | None = None,
        pause_seconds: float = 0.0,
        include_recalled: bool = False,
        clear_failed_ai_result: bool = True,
    ) -> dict[str, Any]:
        document_ids = document_ids or []
        batch_size = max(1, batch_size)

        total_seen = 0
        total_processed = 0
        total_failed = 0
        total_skipped = 0
        batches = 0
        last_id = 0
        processed_document_ids: list[int] = []
        failed_document_ids: list[int] = []

        while True:
            remaining = None if max_documents is None else max(max_documents - total_seen, 0)
            if remaining == 0:
                break

            with session_scope() as session:
                query = session.query(Document).filter(Document.raw_text.is_not(None))
                if document_ids:
                    query = query.filter(Document.id.in_(document_ids))
                if grand_prix:
                    query = query.filter(Document.grand_prix.ilike(f"%{grand_prix}%"))
                if not include_recalled:
                    query = query.filter(Document.is_recalled.is_(False))
                if last_id:
                    query = query.filter(Document.id > last_id)

                docs = (
                    query.order_by(Document.id.asc())
                    .limit(min(batch_size, remaining) if remaining is not None else batch_size)
                    .all()
                )

                if not docs:
                    break

                batches += 1
                for document in docs:
                    last_id = document.id
                    total_seen += 1

                    raw_text = (document.raw_text or "").strip()
                    if not raw_text:
                        total_skipped += 1
                        continue

                    try:
                        extraction = self.extraction_pipeline.extract(
                            title=document.title,
                            text=raw_text,
                            grand_prix=document.grand_prix,
                            doc_number=document.doc_number,
                            is_recalled=document.is_recalled,
                        )

                        document.document_type = extraction.document_type
                        document.document_family = extraction.document_family
                        document.extraction_status = extraction.extraction_status
                        document.extraction_version = extraction.extraction_version
                        document.extraction_confidence = extraction.extraction_confidence
                        document.needs_review = extraction.needs_review
                        document.parser_output = extraction.parser_output
                        document.extracted_data = extraction.extracted_data
                        document.ai_result = extraction.ai_result
                        if clear_failed_ai_result and (
                            document.ai_result and document.ai_result.get("provider") == "failed"
                        ):
                            document.ai_result = None

                        summary = self.summary_client.summarize(
                            title=document.title,
                            grand_prix=document.grand_prix,
                            document_type=extraction.document_type,
                            document_family=extraction.document_family,
                            raw_text=raw_text,
                            extracted_data=extraction.extracted_data,
                        )
                        document.extracted_data = {
                            **(document.extracted_data or {}),
                            "doc_type": summary["doc_type"],
                            "impact_level": summary["impact_level"],
                            "drivers_affected": summary["drivers_affected"],
                            "teams_affected": summary["teams_affected"],
                            "race_impact_summary": summary["race_impact_summary"],
                        }
                        document.dashboard_summary = summary["summary"]
                        document.dashboard_summary_provider = summary["provider"]
                        document.dashboard_summary_version = summary["version"]
                        document.processed = extraction.extraction_status in {"ready", "needs_review"}

                        self._sync_document_entities(session=session, document=document)
                        signal_drafts = self.signal_builder.build(document)
                        upsert_signals_and_alerts(
                            session=session,
                            document=document,
                            drafts=signal_drafts,
                            builder=self.signal_builder,
                        )

                        total_processed += 1
                        processed_document_ids.append(document.id)
                    except Exception:
                        document.processed = False
                        document.extraction_status = "processing_failed"
                        document.needs_review = True
                        total_failed += 1
                        failed_document_ids.append(document.id)
                        LOGGER.exception(
                            "Raw-text reprocessing failed for %s / Doc %s",
                            document.grand_prix,
                            document.doc_number,
                        )

            if pause_seconds > 0:
                time.sleep(pause_seconds)

        return {
            "mode": "raw_text_reprocess",
            "batches": batches,
            "seen": total_seen,
            "processed": total_processed,
            "failed": total_failed,
            "skipped": total_skipped,
            "processed_document_ids": processed_document_ids,
            "failed_document_ids": failed_document_ids,
        }

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
                    source_page_url=item.source_page_url,
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
                if document.source_page_url != item.source_page_url:
                    document.source_page_url = item.source_page_url
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
                    or document.dashboard_summary_version != DASHBOARD_SUMMARY_VERSION
                    or not document.dashboard_summary
                )
            )

            has_existing_signals = (
                session.query(Signal.id).filter(Signal.document_id == document.id).first() is not None
            )

            if should_process_pdf:
                try:
                    downloaded_pdf = self.pdf_processor.download_pdf(
                        grand_prix=item.grand_prix,
                        doc_number=item.doc_number,
                        pdf_url=item.pdf_url or "",
                    )
                    document.local_file = downloaded_pdf.local_file
                    document.pdf_sha256 = downloaded_pdf.sha256
                    document.downloaded_at = downloaded_pdf.downloaded_at
                    downloaded = 1

                    raw_text = self.pdf_processor.extract_text(downloaded_pdf.local_file)
                    extraction = self.extraction_pipeline.extract(
                        title=item.title,
                        text=raw_text,
                        grand_prix=item.grand_prix,
                        doc_number=item.doc_number,
                        is_recalled=item.is_recalled,
                    )

                    document.raw_text = raw_text
                    document.document_type = extraction.document_type
                    document.document_family = extraction.document_family
                    document.extraction_status = extraction.extraction_status
                    document.extraction_version = extraction.extraction_version
                    document.extraction_confidence = extraction.extraction_confidence
                    document.needs_review = extraction.needs_review
                    document.parser_output = extraction.parser_output
                    document.extracted_data = extraction.extracted_data
                    document.ai_result = extraction.ai_result
                    summary = self.summary_client.summarize(
                        title=item.title,
                        grand_prix=item.grand_prix,
                        document_type=extraction.document_type,
                        document_family=extraction.document_family,
                        raw_text=raw_text,
                        extracted_data=extraction.extracted_data,
                    )
                    document.extracted_data = {
                        **(document.extracted_data or {}),
                        "doc_type": summary["doc_type"],
                        "impact_level": summary["impact_level"],
                        "drivers_affected": summary["drivers_affected"],
                        "teams_affected": summary["teams_affected"],
                        "race_impact_summary": summary["race_impact_summary"],
                    }
                    document.dashboard_summary = summary["summary"]
                    document.dashboard_summary_provider = summary["provider"]
                    document.dashboard_summary_version = summary["version"]
                    document.processed = extraction.extraction_status in {"ready", "needs_review"}
                    self._sync_document_entities(session=session, document=document)
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
                        extraction.document_family,
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
                document.dashboard_summary = None
                document.dashboard_summary_provider = None
                document.dashboard_summary_version = None
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

    @staticmethod
    def _sync_document_entities(session, document: Document) -> None:
        extracted = document.extracted_data or {}
        session.query(DocumentEntity).filter(DocumentEntity.document_id == document.id).delete()

        entity_specs = (
            ("driver", extracted.get("drivers") or []),
            ("team", extracted.get("teams") or []),
        )
        for entity_type, values in entity_specs:
            for value in values:
                normalized = " ".join(str(value).split())
                if not normalized:
                    continue
                session.add(
                    DocumentEntity(
                        document_id=document.id,
                        entity_type=entity_type,
                        entity_value=normalized,
                        entity_role=document.document_family,
                        confidence=document.extraction_confidence,
                        payload={
                            "document_type": document.document_type,
                            "document_family": document.document_family,
                            "grand_prix": document.grand_prix,
                            "doc_number": document.doc_number,
                        },
                    )
                )


class IngestionScheduler:
    def __init__(
        self,
        ingestion_service: DocumentIngestionService,
        interval_seconds: int = 300,
        run_weekend_only: bool = False,
        timezone_name: str = "UTC",
        active_weekdays: tuple[int, ...] = (4, 5, 6),
    ) -> None:
        self.ingestion_service = ingestion_service
        self.interval_seconds = interval_seconds
        self.run_weekend_only = run_weekend_only
        self.timezone_name = timezone_name
        self.active_weekdays = active_weekdays
        self.scheduler = BackgroundScheduler()
        self.monitor_timezone = self._resolve_timezone(timezone_name)

    @property
    def running(self) -> bool:
        return bool(self.scheduler.running)

    @staticmethod
    def _resolve_timezone(timezone_name: str):
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            LOGGER.warning("Unknown FIA monitor timezone '%s'; falling back to UTC", timezone_name)
            return timezone.utc

    def describe(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "interval_seconds": self.interval_seconds,
            "run_weekend_only": self.run_weekend_only,
            "timezone": self.timezone_name,
            "active_weekdays": list(self.active_weekdays),
        }

    def _should_run_now(self) -> bool:
        if not self.run_weekend_only:
            return True
        now = datetime.now(self.monitor_timezone)
        return now.weekday() in self.active_weekdays

    def _run_job(self) -> dict[str, Any]:
        if not self._should_run_now():
            now = datetime.now(self.monitor_timezone)
            LOGGER.info(
                "Skipping FIA ingestion outside active monitor window weekday=%s timezone=%s",
                now.weekday(),
                self.timezone_name,
            )
            return {
                "skipped": True,
                "reason": "outside_active_monitor_window",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        return self.ingestion_service.run_ingestion_cycle()

    def start(self) -> None:
        if self.scheduler.running:
            return
        self.scheduler.add_job(
            self._run_job,
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
