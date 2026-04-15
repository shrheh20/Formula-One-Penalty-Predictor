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
from .pdf_parser import PdfProcessor
from .scheduler import DocumentIngestionService, IngestionScheduler

LOGGER = logging.getLogger(__name__)


class ParseUrlRequest(BaseModel):
    pdf_url: str = Field(..., description="Public FIA PDF URL")
    title: str
    grand_prix: str
    doc_number: int
    is_recalled: bool = False


def _serialize_document(document: Document) -> dict:
    return {
        "id": document.id,
        "doc_number": document.doc_number,
        "title": document.title,
        "grand_prix": document.grand_prix,
        "published_time": (
            document.published_time.isoformat() if document.published_time else None
        ),
        "pdf_url": document.pdf_url,
        "local_file": document.local_file,
        "processed": document.processed,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "updated_at": document.updated_at.isoformat() if document.updated_at else None,
        "is_recalled": document.is_recalled,
        "document_type": document.document_type,
        "extraction_status": document.extraction_status,
        "extraction_version": document.extraction_version,
        "extraction_confidence": document.extraction_confidence,
        "needs_review": document.needs_review,
        "parser_output": document.parser_output,
        "extracted_data": document.extracted_data,
        "ai_result": document.ai_result,
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

    @app.get("/documents/{document_id}")
    def get_document(document_id: int, db: Session = Depends(get_db_session)) -> dict:
        document = db.query(Document).filter(Document.id == document_id).one_or_none()
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return _serialize_document(document)

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

    @app.post("/documents/ingest")
    def run_ingestion(apply_processing: bool = True) -> dict:
        if ingestion_service is None:
            raise HTTPException(status_code=503, detail="Ingestion service is not configured")
        result = ingestion_service.run_ingestion_cycle(apply_processing=apply_processing)
        return result

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
            local_file = processor.download_pdf(
                grand_prix=payload.grand_prix,
                doc_number=payload.doc_number,
                pdf_url=payload.pdf_url,
            )
            raw_text = processor.extract_text(local_file)
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
            "local_file": local_file,
            "document_type": extraction.document_type,
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
