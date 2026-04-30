"""Pydantic schemas for news intelligence endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class IngestArticlesRequest(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["formula1_press"])
    limit_per_source: int = Field(default=10, ge=1, le=100)


class ReviewActionRequest(BaseModel):
    target_type: str = Field(..., pattern="^(article|cluster|task)$")
    target_id: int = Field(..., ge=1)
    action: str = Field(..., pattern="^(approve|reject)$")
    notes: str = Field(default="", max_length=2000)


class SourceStatusResponse(BaseModel):
    source_key: str
    display_name: str
    enabled: bool
    officiality_level: str
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_message: str | None = None


class ReviewTaskResponse(BaseModel):
    id: int
    target_type: str
    target_id: int
    reason_type: str
    reason_summary: str
    priority: str
    status: str
    resolution: str | None = None
    created_at: datetime | None = None


class ClusterPreviewResponse(BaseModel):
    cluster_id: int
    cluster_title: str
    cluster_type: str | None = None
    grand_prix: str | None = None
    review_status: str
    publication_status: str
    factual_summary: str | None = None
    strategy_impact_summary: str | None = None
    derived_insight: str | None = None


class ReviewActionResponse(BaseModel):
    target_type: str
    target_id: int
    action: str
    updated_review_status: str
    updated_publication_status: str
    affected_task_ids: list[int] = Field(default_factory=list)


class ArticlePreviewResponse(BaseModel):
    id: int
    headline: str
    canonical_url: str
    source_key: str
    source_display_name: str
    published_at: datetime | None = None
    officiality_level: str
    publication_status: str
    review_status: str
    chunk_status: str
    claim_status: str
    cluster_id: int | None = None
    grand_prix: str | None = None
    clean_text_preview: str | None = None
    factual_summary: str | None = None
    strategy_impact_summary: str | None = None
    derived_insight: str | None = None
