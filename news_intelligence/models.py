"""SQLAlchemy models for the news intelligence subsystem."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class NewsSource(Base):
    __tablename__ = "news_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    officiality_level: Mapped[str] = mapped_column(String(32), nullable=False, default="secondary", index=True)
    base_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    poll_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class NewsIngestionRun(Base):
    __tablename__ = "news_ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("news_sources.id"), nullable=False, index=True)
    run_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now, index=True)
    run_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", index=True)
    items_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("news_sources.id"), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    canonical_url: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True, index=True)
    headline: Mapped[str] = mapped_column(String(512), nullable=False)
    subheadline: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    updated_at_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    officiality_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    grand_prix: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    session_hint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    article_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    raw_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    clean_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fetch_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    chunk_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    claim_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    cluster_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    publication_status: Mapped[str] = mapped_column(String(32), nullable=False, default="blocked", index=True)
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("news_clusters.id"), nullable=True, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class NewsArticleEntity(Base):
    __tablename__ = "news_article_entities"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "entity_type",
            "normalized_value",
            name="uq_news_article_entities_article_type_value",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_value: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_value: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class NewsArticleChunk(Base):
    __tablename__ = "news_article_chunks"
    __table_args__ = (
        UniqueConstraint("article_id", "chunk_index", name="uq_news_article_chunks_article_chunk"),
        UniqueConstraint("qdrant_point_id", name="uq_news_article_chunks_qdrant_point_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    qdrant_point_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class NewsClaim(Base):
    __tablename__ = "news_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id"), nullable=False, index=True)
    claim_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_claim_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    claim_scope: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy_priority: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_conflicting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    citation_article_chunk_id: Mapped[int | None] = mapped_column(ForeignKey("news_article_chunks.id"), nullable=True)
    citation_char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citation_char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_driver: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    affected_team: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    affected_session: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    grand_prix: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class NewsCluster(Base):
    __tablename__ = "news_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cluster_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    cluster_title: Mapped[str] = mapped_column(String(512), nullable=False)
    cluster_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    grand_prix: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    strategy_priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    conflict_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    official_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    secondary_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    publication_status: Mapped[str] = mapped_column(String(32), nullable=False, default="blocked", index=True)
    primary_article_id: Mapped[int | None] = mapped_column(ForeignKey("news_articles.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class NewsClusterMember(Base):
    __tablename__ = "news_cluster_members"
    __table_args__ = (
        UniqueConstraint("cluster_id", "article_id", name="uq_news_cluster_members_cluster_article"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("news_clusters.id"), nullable=False, index=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id"), nullable=False, index=True)
    membership_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class NewsSummary(Base):
    __tablename__ = "news_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    summary_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    factual_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    strategy_impact_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    derived_insight: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class NewsReviewTask(Base):
    __tablename__ = "news_review_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    reason_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason_summary: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="medium", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class NewsReprocessJob(Base):
    __tablename__ = "news_reprocess_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    run_after: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
