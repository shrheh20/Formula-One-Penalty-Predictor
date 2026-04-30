"""FastAPI surface for the FIA document ingestion service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .db import Alert, Document, Signal, get_db_session, init_db
from .document_pipeline import DocumentExtractionPipeline
from .insights import DocumentInsightsService
from .pdf_parser import PdfProcessor
from .scheduler import DocumentIngestionService, IngestionScheduler

LOGGER = logging.getLogger(__name__)


class ParseUrlRequest(BaseModel):
    pdf_url: str = Field(..., description="Public FIA PDF URL")
    title: str
    grand_prix: str
    doc_number: int
    is_recalled: bool = False


class ReprocessRequest(BaseModel):
    document_ids: list[int] = Field(default_factory=list)
    extraction_statuses: list[str] = Field(default_factory=list)
    grand_prix: str | None = None
    include_unknown: bool = False
    include_needs_review: bool = False
    limit: int | None = Field(default=None, ge=1, le=1000)
    run_ingestion: bool = True


class RawReprocessRequest(BaseModel):
    document_ids: list[int] = Field(default_factory=list)
    grand_prix: str | None = None
    batch_size: int = Field(default=10, ge=1, le=100)
    max_documents: int | None = Field(default=None, ge=1, le=5000)
    pause_seconds: float = Field(default=0.0, ge=0.0, le=30.0)
    include_recalled: bool = False
    clear_failed_ai_result: bool = True


def _serialize_document(document: Document) -> dict:
    extracted = document.extracted_data or {}
    return {
        "id": document.id,
        "doc_number": document.doc_number,
        "title": document.title,
        "grand_prix": document.grand_prix,
        "published_time": (
            document.published_time.isoformat() if document.published_time else None
        ),
        "pdf_url": document.pdf_url,
        "source_page_url": document.source_page_url,
        "local_file": document.local_file,
        "pdf_sha256": document.pdf_sha256,
        "downloaded_at": document.downloaded_at.isoformat() if document.downloaded_at else None,
        "processed": document.processed,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "updated_at": document.updated_at.isoformat() if document.updated_at else None,
        "is_recalled": document.is_recalled,
        "document_type": document.document_type,
        "document_family": document.document_family,
        "extraction_status": document.extraction_status,
        "extraction_version": document.extraction_version,
        "extraction_confidence": document.extraction_confidence,
        "needs_review": document.needs_review,
        "parser_output": document.parser_output,
        "extracted_data": document.extracted_data,
        "ai_result": document.ai_result,
        "dashboard_summary": document.dashboard_summary,
        "dashboard_summary_provider": document.dashboard_summary_provider,
        "dashboard_summary_version": document.dashboard_summary_version,
        "doc_type": extracted.get("doc_type"),
        "impact_level": extracted.get("impact_level"),
        "drivers_affected": extracted.get("drivers_affected") or [],
        "teams_affected": extracted.get("teams_affected") or [],
        "race_impact_summary": extracted.get("race_impact_summary") or document.dashboard_summary,
    }


def _serialize_signal(signal: Signal) -> dict:
    return {
        "id": signal.id,
        "document_id": signal.document_id,
        "signal_type": signal.signal_type,
        "category": signal.category,
        "grand_prix": signal.grand_prix,
        "session": signal.session,
        "driver": signal.driver,
        "team": signal.team,
        "car_number": signal.car_number,
        "severity": signal.severity,
        "status": signal.status,
        "entity_key": signal.entity_key,
        "published_time": signal.published_time.isoformat() if signal.published_time else None,
        "payload": signal.payload,
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
    }


def _serialize_alert(alert: Alert) -> dict:
    return {
        "id": alert.id,
        "signal_id": alert.signal_id,
        "document_id": alert.document_id,
        "category": alert.category,
        "priority": alert.priority,
        "title": alert.title,
        "message": alert.message,
        "status": alert.status,
        "grand_prix": alert.grand_prix,
        "published_time": alert.published_time.isoformat() if alert.published_time else None,
        "payload": alert.payload,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }


def create_app(
    ingestion_service: Optional[DocumentIngestionService] = None,
    scheduler: Optional[IngestionScheduler] = None,
) -> FastAPI:
    insights_service = DocumentInsightsService()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        if scheduler is not None:
            scheduler.start()
            LOGGER.info("FIA ingestion scheduler started")
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown()
                LOGGER.info("FIA ingestion scheduler stopped")

    app = FastAPI(
        title="FIA Document Monitor",
        version="1.0.0",
        description="Monitors FIA Formula One decision documents and stores new PDFs.",
        lifespan=lifespan,
    )

    app.state.ingestion_service = ingestion_service
    app.state.scheduler = scheduler

    @app.get("/health")
    def healthcheck() -> dict:
        return {
            "status": "ok",
            "scheduler_running": bool(scheduler and scheduler.running),
            "monitor_config": scheduler.describe() if scheduler is not None else {"enabled": False},
        }

    @app.get("/documents/latest")
    def get_latest_documents(
        limit: int = Query(default=25, ge=1, le=100),
        db: Session = Depends(get_db_session),
    ) -> dict:
        documents = (
            db.query(Document)
            .order_by(Document.published_time.desc().nullslast(), Document.id.desc())
            .limit(limit)
            .all()
        )
        return {"documents": [_serialize_document(document) for document in documents]}

    @app.get("/documents/grand-prix/{name}")
    def get_documents_by_grand_prix(
        name: str,
        limit: int = Query(default=100, ge=1, le=500),
        db: Session = Depends(get_db_session),
    ) -> dict:
        documents = (
            db.query(Document)
            .filter(Document.grand_prix.ilike(f"%{name}%"))
            .order_by(Document.published_time.desc().nullslast(), Document.doc_number.desc())
            .limit(limit)
            .all()
        )
        return {
            "grand_prix": name,
            "documents": [_serialize_document(document) for document in documents],
        }

    @app.get("/documents/review-queue")
    def get_review_queue(
        limit: int = Query(default=100, ge=1, le=500),
        grand_prix: str | None = Query(default=None),
        failed_only: bool = Query(default=False),
        unknown_only: bool = Query(default=False),
        needs_review_only: bool = Query(default=True),
        db: Session = Depends(get_db_session),
    ) -> dict:
        query = db.query(Document)
        if grand_prix:
            query = query.filter(Document.grand_prix.ilike(f"%{grand_prix}%"))
        if failed_only:
            query = query.filter(Document.extraction_status.in_(("download_failed", "processing_failed")))
        if unknown_only:
            query = query.filter((Document.document_type == "other") | (Document.document_family == "other"))
        if needs_review_only:
            query = query.filter(Document.needs_review.is_(True))

        documents = (
            query.order_by(Document.updated_at.desc(), Document.published_time.desc().nullslast(), Document.id.desc())
            .limit(limit)
            .all()
        )
        return {
            "count": len(documents),
            "documents": [_serialize_document(document) for document in documents],
        }

    @app.get("/insights/latest")
    def get_latest_insights(
        limit: int = Query(default=8, ge=1, le=25),
        grand_prix: str | None = Query(default=None),
        db: Session = Depends(get_db_session),
    ) -> dict:
        return insights_service.get_latest_insights(
            db,
            limit=limit,
            grand_prix=grand_prix,
        )

    @app.post("/documents/ingest")
    def run_ingestion(apply_processing: bool = True) -> dict:
        if ingestion_service is None:
            raise HTTPException(status_code=503, detail="Ingestion service is not configured")
        result = ingestion_service.run_ingestion_cycle(apply_processing=apply_processing)
        return result

    @app.post("/documents/reprocess")
    def reprocess_documents(payload: ReprocessRequest) -> dict:
        if ingestion_service is None:
            raise HTTPException(status_code=503, detail="Ingestion service is not configured")
        if not (
            payload.document_ids
            or payload.extraction_statuses
            or payload.grand_prix
            or payload.include_unknown
            or payload.include_needs_review
        ):
            raise HTTPException(
                status_code=400,
                detail="Provide at least one filter to avoid unintentionally reprocessing every document",
            )

        queued = ingestion_service.queue_documents_for_reprocessing(
            document_ids=payload.document_ids,
            extraction_statuses=payload.extraction_statuses,
            grand_prix=payload.grand_prix,
            include_unknown=payload.include_unknown,
            include_needs_review=payload.include_needs_review,
            limit=payload.limit,
        )
        result = {"queued": queued, "ingestion": None}
        if payload.run_ingestion and queued["queued"] > 0:
            result["ingestion"] = ingestion_service.run_ingestion_cycle(apply_processing=True)
        return result

    @app.post("/documents/reprocess-from-raw")
    def reprocess_documents_from_raw(payload: RawReprocessRequest) -> dict:
        if ingestion_service is None:
            raise HTTPException(status_code=503, detail="Ingestion service is not configured")
        if not payload.document_ids and not payload.grand_prix and payload.max_documents is None:
            raise HTTPException(
                status_code=400,
                detail="Provide document_ids, grand_prix, or max_documents to avoid unintentionally reprocessing every document",
            )
        return ingestion_service.reprocess_documents_from_raw(
            document_ids=payload.document_ids,
            grand_prix=payload.grand_prix,
            batch_size=payload.batch_size,
            max_documents=payload.max_documents,
            pause_seconds=payload.pause_seconds,
            include_recalled=payload.include_recalled,
            clear_failed_ai_result=payload.clear_failed_ai_result,
        )

    @app.get("/documents/{document_id}")
    def get_document(document_id: int, db: Session = Depends(get_db_session)) -> dict:
        document = db.query(Document).filter(Document.id == document_id).one_or_none()
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return _serialize_document(document)

    @app.get("/signals/latest")
    def get_latest_signals(
        limit: int = Query(default=50, ge=1, le=200),
        category: str | None = Query(default=None),
        db: Session = Depends(get_db_session),
    ) -> dict:
        query = db.query(Signal)
        if category:
            query = query.filter(Signal.category == category)
        signals = query.order_by(Signal.published_time.desc().nullslast(), Signal.id.desc()).limit(limit).all()
        return {"signals": [_serialize_signal(signal) for signal in signals]}

    @app.get("/alerts/latest")
    def get_latest_alerts(
        limit: int = Query(default=50, ge=1, le=200),
        priority: str | None = Query(default=None),
        db: Session = Depends(get_db_session),
    ) -> dict:
        query = db.query(Alert)
        if priority:
            query = query.filter(Alert.priority == priority)
        alerts = query.order_by(Alert.published_time.desc().nullslast(), Alert.id.desc()).limit(limit).all()
        return {"alerts": [_serialize_alert(alert) for alert in alerts]}

    @app.get("/predictor/feed")
    def get_predictor_feed(
        grand_prix: str | None = Query(default=None),
        db: Session = Depends(get_db_session),
    ) -> dict:
        query = db.query(Signal)
        if grand_prix:
            query = query.filter(Signal.grand_prix.ilike(f"%{grand_prix}%"))
        signals = query.order_by(Signal.published_time.desc().nullslast(), Signal.id.desc()).limit(250).all()

        component_signals = [signal for signal in signals if signal.category == "component"]
        steward_signals = [signal for signal in signals if signal.category == "stewards"]
        technical_signals = [signal for signal in signals if signal.category == "technical"]

        return {
            "grand_prix": grand_prix,
            "component_updates": [_serialize_signal(signal) for signal in component_signals],
            "steward_alerts": [_serialize_signal(signal) for signal in steward_signals],
            "technical_alerts": [_serialize_signal(signal) for signal in technical_signals],
            "all_signals": [_serialize_signal(signal) for signal in signals],
        }

    @app.post("/documents/debug/parse-url")
    def debug_parse_url(payload: ParseUrlRequest) -> dict:
        processor = PdfProcessor(data_dir="data/debug_docs")
        pipeline = DocumentExtractionPipeline()

        try:
            downloaded_pdf = processor.download_pdf(
                grand_prix=payload.grand_prix,
                doc_number=payload.doc_number,
                pdf_url=payload.pdf_url,
            )
            raw_text = processor.extract_text(downloaded_pdf.local_file)
            extraction = pipeline.extract(
                title=payload.title,
                text=raw_text,
                grand_prix=payload.grand_prix,
                doc_number=payload.doc_number,
                is_recalled=payload.is_recalled,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "pdf_url": payload.pdf_url,
            "local_file": downloaded_pdf.local_file,
            "pdf_sha256": downloaded_pdf.sha256,
            "document_type": extraction.document_type,
            "document_family": extraction.document_family,
            "extraction_status": extraction.extraction_status,
            "extraction_version": extraction.extraction_version,
            "extraction_confidence": extraction.extraction_confidence,
            "needs_review": extraction.needs_review,
            "parser_output": extraction.parser_output,
            "extracted_data": extraction.extracted_data,
            "ai_result": extraction.ai_result,
            "raw_text_preview": raw_text[:5000],
        }

    return app
