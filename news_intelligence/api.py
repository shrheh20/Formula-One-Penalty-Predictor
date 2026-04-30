"""FastAPI surface for the news intelligence subsystem."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from .db import get_db_session, init_db
from .models import NewsArticle, NewsCluster, NewsReviewTask, NewsSource, NewsSummary
from .schemas import (
    ArticlePreviewResponse,
    ClusterPreviewResponse,
    IngestArticlesRequest,
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewTaskResponse,
    SourceStatusResponse,
)
from .service import NewsIngestionService


def create_app(ingestion_service: NewsIngestionService | None = None) -> FastAPI:
    service = ingestion_service or NewsIngestionService()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        yield

    app = FastAPI(
        title="News Intelligence Monitor",
        version="1.0.0",
        description="Ingests multi-source Formula 1 news into a source-grounded intelligence store.",
        lifespan=lifespan,
    )

    @app.get("/health")
    def healthcheck(db: Session = Depends(get_db_session)) -> dict:
        source_count = db.query(NewsSource).count()
        article_count = db.query(NewsArticle).count()
        try:
            qdrant = service.qdrant_client.health()
        except Exception as exc:
            qdrant = {"available": False, "error": str(exc)}
        return {
            "status": "ok",
            "sources_registered": source_count,
            "articles_stored": article_count,
            "qdrant": qdrant,
        }

    @app.get("/sources", response_model=list[SourceStatusResponse])
    def list_sources(db: Session = Depends(get_db_session)) -> list[SourceStatusResponse]:
        service.ensure_source_records(db)
        db.commit()
        sources = db.query(NewsSource).order_by(NewsSource.display_name.asc()).all()
        return [
            SourceStatusResponse(
                source_key=source.source_key,
                display_name=source.display_name,
                enabled=source.enabled,
                officiality_level=source.officiality_level,
                last_success_at=source.last_success_at,
                last_error_at=source.last_error_at,
                last_error_message=source.last_error_message,
            )
            for source in sources
        ]

    @app.post("/articles/ingest")
    def ingest_articles(payload: IngestArticlesRequest, db: Session = Depends(get_db_session)) -> dict:
        if not payload.sources:
            raise HTTPException(status_code=400, detail="At least one source must be provided")
        return service.ingest_sources(
            db,
            source_keys=payload.sources,
            limit_per_source=payload.limit_per_source,
        )

    @app.get("/articles/latest", response_model=list[ArticlePreviewResponse])
    def latest_articles(
        limit: int = Query(default=25, ge=1, le=100),
        published_only: bool = Query(default=False),
        db: Session = Depends(get_db_session),
    ) -> list[ArticlePreviewResponse]:
        query = db.query(NewsArticle, NewsSource).join(NewsSource, NewsSource.id == NewsArticle.source_id)
        if published_only:
            query = query.filter(NewsArticle.publication_status == "approved")
        rows = query.order_by(NewsArticle.published_at.desc().nullslast(), NewsArticle.id.desc()).limit(limit).all()
        summary_map = {
            summary.target_id: summary
            for summary in db.query(NewsSummary)
            .filter(NewsSummary.target_type == "article", NewsSummary.summary_kind == "article_brief")
            .all()
        }
        return [
            ArticlePreviewResponse(
                id=article.id,
                headline=article.headline,
                canonical_url=article.canonical_url,
                source_key=source.source_key,
                source_display_name=source.display_name,
                published_at=article.published_at,
                officiality_level=article.officiality_level,
                publication_status=article.publication_status,
                review_status=article.review_status,
                chunk_status=article.chunk_status,
                claim_status=article.claim_status,
                cluster_id=article.cluster_id,
                grand_prix=article.grand_prix,
                clean_text_preview=(article.clean_text or "")[:280] or None,
                factual_summary=summary_map.get(article.id).factual_summary if summary_map.get(article.id) else None,
                strategy_impact_summary=summary_map.get(article.id).strategy_impact_summary if summary_map.get(article.id) else None,
                derived_insight=summary_map.get(article.id).derived_insight if summary_map.get(article.id) else None,
            )
            for article, source in rows
        ]

    @app.get("/clusters/latest", response_model=list[ClusterPreviewResponse])
    def latest_clusters(
        limit: int = Query(default=25, ge=1, le=100),
        published_only: bool = Query(default=False),
        db: Session = Depends(get_db_session),
    ) -> list[ClusterPreviewResponse]:
        query = db.query(NewsCluster)
        if published_only:
            query = query.filter(NewsCluster.publication_status == "approved")
        clusters = query.order_by(NewsCluster.latest_published_at.desc().nullslast(), NewsCluster.id.desc()).limit(limit).all()
        summary_map = {
            (summary.target_id): summary
            for summary in db.query(NewsSummary)
            .filter(NewsSummary.target_type == "cluster", NewsSummary.summary_kind == "cluster_brief")
            .all()
        }
        return [
            ClusterPreviewResponse(
                cluster_id=cluster.id,
                cluster_title=cluster.cluster_title,
                cluster_type=cluster.cluster_type,
                grand_prix=cluster.grand_prix,
                review_status=cluster.review_status,
                publication_status=cluster.publication_status,
                factual_summary=summary_map.get(cluster.id).factual_summary if summary_map.get(cluster.id) else None,
                strategy_impact_summary=summary_map.get(cluster.id).strategy_impact_summary if summary_map.get(cluster.id) else None,
                derived_insight=summary_map.get(cluster.id).derived_insight if summary_map.get(cluster.id) else None,
            )
            for cluster in clusters
        ]

    @app.get("/review-queue", response_model=list[ReviewTaskResponse])
    def review_queue(
        limit: int = Query(default=50, ge=1, le=200),
        db: Session = Depends(get_db_session),
    ) -> list[ReviewTaskResponse]:
        tasks = (
            db.query(NewsReviewTask)
            .order_by(NewsReviewTask.created_at.desc(), NewsReviewTask.id.desc())
            .limit(limit)
            .all()
        )
        return [
            ReviewTaskResponse(
                id=task.id,
                target_type=task.target_type,
                target_id=task.target_id,
                reason_type=task.reason_type,
                reason_summary=task.reason_summary,
                priority=task.priority,
                status=task.status,
                resolution=task.resolution,
                created_at=task.created_at,
            )
            for task in tasks
        ]

    @app.post("/review/action", response_model=ReviewActionResponse)
    def review_action(payload: ReviewActionRequest, db: Session = Depends(get_db_session)) -> ReviewActionResponse:
        try:
            result = service.apply_review_action(
                db,
                target_type=payload.target_type,
                target_id=payload.target_id,
                action=payload.action,
                notes=payload.notes,
            )
            db.commit()
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
        return ReviewActionResponse(**result)

    return app
