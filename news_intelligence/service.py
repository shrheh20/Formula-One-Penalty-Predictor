"""Core ingestion services for news intelligence."""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from .chunking import chunk_text
from .claims import DeterministicClaimExtractor
from .clustering import NewsClusterer
from .collectors.base import (
    NewsCollector,
    ScrapedArticle,
    canonicalize_url,
    is_generic_listing_headline,
    is_hard_skip_content_type,
    normalize_text,
)
from .collectors.formula1_press import Formula1PressCollector
from .collectors.racingnews365 import RacingNews365F1Collector
from .collectors.sky_sports import SkySportsF1Collector
from .collectors.the_race import TheRaceF1Collector
from .config import news_settings
from .embeddings import EMBEDDING_DIMENSION, embed_text
from .models import NewsArticle, NewsArticleChunk, NewsClaim, NewsCluster, NewsIngestionRun, NewsReviewTask, NewsSource, NewsSummary
from .qdrant_client import NewsQdrantClient
from .summarizer import DeterministicSummaryComposer

LOGGER = logging.getLogger(__name__)


class NewsIngestionService:
    def __init__(
        self,
        collectors: dict[str, NewsCollector] | None = None,
        qdrant_client: NewsQdrantClient | None = None,
    ) -> None:
        self.collectors = collectors or {
            Formula1PressCollector.source_key: Formula1PressCollector(),
            TheRaceF1Collector.source_key: TheRaceF1Collector(),
            SkySportsF1Collector.source_key: SkySportsF1Collector(),
            RacingNews365F1Collector.source_key: RacingNews365F1Collector(),
        }
        self._qdrant_client = qdrant_client
        self.clusterer = NewsClusterer()
        self.claim_extractor = DeterministicClaimExtractor()
        self.summary_composer = DeterministicSummaryComposer()

    @property
    def qdrant_client(self) -> NewsQdrantClient:
        if self._qdrant_client is None:
            self._qdrant_client = NewsQdrantClient()
        return self._qdrant_client

    def ensure_source_records(self, db: Session) -> list[NewsSource]:
        records: list[NewsSource] = []
        for collector in self.collectors.values():
            source = db.query(NewsSource).filter(NewsSource.source_key == collector.source_key).one_or_none()
            if source is None:
                source = NewsSource(
                    source_key=collector.source_key,
                    display_name=collector.display_name,
                    source_type=collector.source_type,
                    officiality_level=collector.officiality_level,
                    base_url=collector.base_url,
                    enabled=True,
                    poll_interval_seconds=news_settings.news_default_poll_interval_seconds,
                )
                db.add(source)
                db.flush()
            else:
                source.display_name = collector.display_name
                source.source_type = collector.source_type
                source.officiality_level = collector.officiality_level
                source.base_url = collector.base_url
            records.append(source)
        return records

    def ensure_vector_collections(self) -> dict:
        results = {}
        for collection_name in (
            news_settings.news_qdrant_collection_chunks,
            news_settings.news_qdrant_collection_clusters,
            news_settings.news_qdrant_collection_fia_context,
        ):
            try:
                results[collection_name] = self.qdrant_client.ensure_collection(
                    collection_name,
                    vector_size=EMBEDDING_DIMENSION,
                )
            except Exception as exc:
                LOGGER.warning("Unable to ensure Qdrant collection %s: %s", collection_name, exc)
                results[collection_name] = {"ok": False, "error": str(exc)}
        return results

    def ingest_sources(self, db: Session, *, source_keys: list[str], limit_per_source: int) -> dict:
        self.ensure_source_records(db)
        vector_results = self.ensure_vector_collections()

        results = {
            "sources": [],
            "vector_collections": vector_results,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }

        for source_key in source_keys:
            collector = self.collectors.get(source_key)
            if collector is None:
                results["sources"].append(
                    {
                        "source_key": source_key,
                        "status": "skipped",
                        "error": "unknown_source",
                    }
                )
                continue

            source = db.query(NewsSource).filter(NewsSource.source_key == source_key).one()
            if not source.enabled:
                results["sources"].append(
                    {
                        "source_key": source_key,
                        "display_name": source.display_name,
                        "status": "skipped",
                        "error": "source_disabled",
                    }
                )
                continue
            run = NewsIngestionRun(source_id=source.id, status="running")
            db.add(run)
            db.flush()

            try:
                articles = collector.collect_latest(limit=limit_per_source)
                run.items_seen = len(articles)
                created = 0
                updated = 0
                skipped = 0
                failed = 0
                article_errors: list[dict[str, str]] = []
                for article in articles:
                    try:
                        with db.begin_nested():
                            prepared = self._prepare_article(article)
                            if prepared is None:
                                skipped += 1
                                continue
                            state = self._upsert_article(db=db, source=source, scraped=prepared)
                            if state == "created":
                                created += 1
                            elif state == "updated":
                                updated += 1
                            elif state == "skipped":
                                skipped += 1
                                continue
                            self._refresh_article_chunks(db=db, source=source, canonical_url=prepared.canonical_url)
                            refreshed_article = (
                                db.query(NewsArticle)
                                .filter(NewsArticle.canonical_url == prepared.canonical_url)
                                .one()
                            )
                            self.clusterer.assign_article(db, refreshed_article)
                            self._refresh_article_claims(db, refreshed_article)
                            self._refresh_review_tasks(db, refreshed_article)
                            self._refresh_summaries(db, refreshed_article)
                    except Exception as article_exc:
                        failed += 1
                        article_errors.append(
                            {
                                "headline": (article.headline or "")[:160],
                                "url": (article.canonical_url or "")[:255],
                                "error": str(article_exc)[:255],
                            }
                        )
                        LOGGER.warning(
                            "Article-level ingestion failure source=%s url=%s error=%s",
                            source_key,
                            article.canonical_url,
                            article_exc,
                        )

                source.last_success_at = datetime.now(timezone.utc)
                source.last_error_at = None
                source.last_error_message = None
                run.items_new = created
                run.items_updated = updated
                run.items_failed = failed
                run.status = "completed"
                run.payload = {
                    "article_urls": [article.canonical_url for article in articles],
                    "article_errors": article_errors[:10],
                    "items_skipped": skipped,
                }
                results["sources"].append(
                    {
                        "source_key": source_key,
                        "display_name": source.display_name,
                        "status": "completed",
                        "items_seen": len(articles),
                        "items_new": created,
                        "items_updated": updated,
                        "items_skipped": skipped,
                        "items_failed": failed,
                        "article_errors": article_errors[:5],
                    }
                )
            except Exception as exc:
                LOGGER.exception("News ingestion failed for source %s", source_key)
                source.last_error_at = datetime.now(timezone.utc)
                source.last_error_message = str(exc)
                run.status = "failed"
                run.error_message = str(exc)
                run.items_failed = 1
                results["sources"].append(
                    {
                        "source_key": source_key,
                        "display_name": source.display_name,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
            finally:
                run.run_finished_at = datetime.now(timezone.utc)
                db.flush()

        db.commit()
        return results

    def _prepare_article(self, scraped: ScrapedArticle) -> ScrapedArticle | None:
        canonical_url = canonicalize_url(scraped.canonical_url)
        headline = normalize_text(scraped.headline)
        clean_text = (scraped.clean_text or "").strip()
        raw_text = (scraped.raw_text or clean_text).strip()
        subheadline = normalize_text(scraped.subheadline or "")
        metadata = dict(scraped.metadata or {})
        metadata["content_type"] = scraped.content_type
        metadata["summary_eligible"] = bool(scraped.summary_eligible)

        if not canonical_url or not headline:
            return None
        if is_generic_listing_headline(headline):
            metadata["ingestion_skip_reason"] = "generic_listing_headline"
            return ScrapedArticle(
                external_id=scraped.external_id,
                canonical_url=canonical_url,
                headline=headline,
                subheadline=subheadline or None,
                author=scraped.author,
                published_at=scraped.published_at,
                raw_html=scraped.raw_html,
                raw_text=raw_text,
                clean_text=clean_text,
                content_type=scraped.content_type,
                summary_eligible=False,
                metadata=metadata,
            )
        if is_hard_skip_content_type(scraped.content_type):
            metadata["ingestion_skip_reason"] = "hard_skip_content_type"
            return ScrapedArticle(
                external_id=scraped.external_id,
                canonical_url=canonical_url,
                headline=headline,
                subheadline=subheadline or None,
                author=scraped.author,
                published_at=scraped.published_at,
                raw_html=scraped.raw_html,
                raw_text=raw_text,
                clean_text=clean_text,
                content_type=scraped.content_type,
                summary_eligible=False,
                metadata=metadata,
            )
        if len(clean_text) < 120:
            metadata["ingestion_skip_reason"] = "insufficient_clean_text"
            return ScrapedArticle(
                external_id=scraped.external_id,
                canonical_url=canonical_url,
                headline=headline,
                subheadline=subheadline or None,
                author=scraped.author,
                published_at=scraped.published_at,
                raw_html=scraped.raw_html,
                raw_text=raw_text,
                clean_text=clean_text,
                content_type=scraped.content_type,
                summary_eligible=False,
                metadata=metadata,
            )
        return ScrapedArticle(
            external_id=scraped.external_id,
            canonical_url=canonical_url,
            headline=headline,
            subheadline=subheadline or None,
            author=scraped.author,
            published_at=scraped.published_at,
            raw_html=scraped.raw_html,
            raw_text=raw_text,
            clean_text=clean_text,
            content_type=scraped.content_type,
            summary_eligible=scraped.summary_eligible,
            metadata=metadata,
        )

    def _upsert_article(self, *, db: Session, source: NewsSource, scraped: ScrapedArticle) -> str:
        if scraped.metadata.get("ingestion_skip_reason"):
            return "skipped"

        article = db.query(NewsArticle).filter(NewsArticle.canonical_url == scraped.canonical_url).one_or_none()
        content_hash = hashlib.sha256(scraped.clean_text.encode("utf-8")).hexdigest()
        grand_prix = scraped.metadata.get("grand_prix_hint")
        season = scraped.published_at.year if scraped.published_at else None
        review_status = "pending" if scraped.summary_eligible else "suppressed"
        parse_status = "parsed" if scraped.summary_eligible else "filtered"

        if article is None:
            article = NewsArticle(
                source_id=source.id,
                external_id=scraped.external_id,
                canonical_url=scraped.canonical_url,
                headline=scraped.headline,
                subheadline=scraped.subheadline,
                author=scraped.author,
                published_at=scraped.published_at,
                source_type=source.source_type,
                officiality_level=source.officiality_level,
                grand_prix=grand_prix,
                season=season,
                article_language="en",
                content_hash=content_hash,
                raw_html=scraped.raw_html,
                raw_text=scraped.raw_text,
                clean_text=scraped.clean_text,
                metadata_json=scraped.metadata,
                fetch_status="fetched",
                parse_status=parse_status,
                chunk_status="pending",
                claim_status="pending",
                cluster_status="pending",
                review_status=review_status,
                publication_status="blocked",
                first_seen_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc),
            )
            db.add(article)
            db.flush()
            return "created"

        if article.content_hash == content_hash:
            article.last_seen_at = datetime.now(timezone.utc)
            article.metadata_json = scraped.metadata
            db.flush()
            return "unchanged"

        article.external_id = scraped.external_id
        article.headline = scraped.headline
        article.subheadline = scraped.subheadline
        article.author = scraped.author
        article.published_at = scraped.published_at
        article.officiality_level = source.officiality_level
        article.source_type = source.source_type
        article.grand_prix = grand_prix
        article.season = season
        article.content_hash = content_hash
        article.raw_html = scraped.raw_html
        article.raw_text = scraped.raw_text
        article.clean_text = scraped.clean_text
        article.metadata_json = scraped.metadata
        article.fetch_status = "fetched"
        article.parse_status = parse_status
        article.chunk_status = "pending"
        article.claim_status = "pending"
        article.cluster_status = "pending"
        article.review_status = review_status
        article.publication_status = "blocked"
        article.last_seen_at = datetime.now(timezone.utc)
        db.flush()
        return "updated"

    def _refresh_article_claims(self, db: Session, article: NewsArticle) -> None:
        db.query(NewsClaim).filter(NewsClaim.article_id == article.id).delete()
        chunks = (
            db.query(NewsArticleChunk)
            .filter(NewsArticleChunk.article_id == article.id)
            .order_by(NewsArticleChunk.chunk_index.asc())
            .all()
        )
        if not chunks or article.review_status == "suppressed":
            article.claim_status = "suppressed" if article.review_status == "suppressed" else "empty"
            db.flush()
            return

        extracted = self.claim_extractor.extract_article_claims(article, chunks)
        for chunk, claim in extracted:
            db.add(
                NewsClaim(
                    article_id=article.id,
                    claim_type=claim.claim_type,
                    claim_text=claim.claim_text,
                    normalized_claim_key=self._normalized_claim_key(claim.claim_type, claim.claim_text, article.grand_prix),
                    claim_scope="article",
                    strategy_priority=claim.strategy_priority,
                    confidence=claim.confidence,
                    is_conflicting=False,
                    needs_review=claim.confidence < 0.78,
                    citation_article_chunk_id=chunk.id,
                    citation_char_start=claim.citation_start,
                    citation_char_end=claim.citation_end,
                    evidence_text=claim.claim_text,
                    affected_driver=claim.affected_driver,
                    affected_team=claim.affected_team,
                    affected_session=claim.affected_session,
                    grand_prix=article.grand_prix,
                    published_at=article.published_at,
                    payload=claim.payload,
                )
            )
        article.claim_status = "extracted" if extracted else "empty"
        db.flush()

    def _refresh_review_tasks(self, db: Session, article: NewsArticle) -> None:
        db.query(NewsReviewTask).filter(
            NewsReviewTask.target_type == "article",
            NewsReviewTask.target_id == article.id,
            NewsReviewTask.status == "open",
        ).delete(synchronize_session=False)

        claims = db.query(NewsClaim).filter(NewsClaim.article_id == article.id).all()
        summary_eligible = bool((article.metadata_json or {}).get("summary_eligible", True))

        reasons: list[tuple[str, str, str]] = []
        if not summary_eligible:
            reasons.append(("content_filtered", "Filtered content type should not be published automatically.", "low"))
        if article.claim_status in {"empty", "suppressed"}:
            reasons.append(("no_claims_extracted", "No publishable strategy-relevant claims were extracted from the article.", "medium"))
        if any(claim.needs_review or (claim.confidence or 0.0) < 0.78 for claim in claims):
            reasons.append(("low_confidence_claim", "One or more extracted claims fell below the confidence threshold.", "high"))

        cluster = db.query(NewsCluster).filter(NewsCluster.id == article.cluster_id).one_or_none() if article.cluster_id else None
        if cluster and cluster.review_status == "pending" and claims:
            cluster.review_status = "needs_review"
            cluster.publication_status = "blocked"

        if reasons:
            article.review_status = "needs_review"
            article.publication_status = "blocked"
            for reason_type, summary, priority in reasons:
                db.add(
                    NewsReviewTask(
                        target_type="article",
                        target_id=article.id,
                        reason_type=reason_type,
                        reason_summary=summary,
                        priority=priority,
                        status="open",
                        resolution=None,
                        agent_payload={
                            "article_id": article.id,
                            "source_key": (article.metadata_json or {}).get("source_key"),
                            "canonical_url": article.canonical_url,
                            "claim_status": article.claim_status,
                        },
                    )
                )
        else:
            article.review_status = "ready_for_review"
            article.publication_status = "blocked"
        if cluster:
            self._refresh_cluster_review_tasks(db, cluster)
        db.flush()

    @staticmethod
    def _normalized_claim_key(claim_type: str, claim_text: str, grand_prix: str | None) -> str:
        basis = f"{claim_type}::{grand_prix or 'global'}::{claim_text.lower().strip()}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()

    def _refresh_cluster_review_tasks(self, db: Session, cluster: NewsCluster) -> None:
        db.query(NewsReviewTask).filter(
            NewsReviewTask.target_type == "cluster",
            NewsReviewTask.target_id == cluster.id,
            NewsReviewTask.status == "open",
        ).delete(synchronize_session=False)

        claims = (
            db.query(NewsClaim, NewsArticle)
            .join(NewsArticle, NewsArticle.id == NewsClaim.article_id)
            .filter(NewsArticle.cluster_id == cluster.id)
            .all()
        )
        if not claims:
            cluster.review_status = "pending"
            cluster.publication_status = "blocked"
            return

        grouped: dict[str, list[tuple[NewsClaim, NewsArticle]]] = defaultdict(list)
        for claim, article in claims:
            grouped[claim.normalized_claim_key or f"{claim.claim_type}::{claim.id}"].append((claim, article))

        cluster_reasons: list[tuple[str, str, str]] = []
        high_impact_present = False
        conflict_present = False

        for _, group in grouped.items():
            claim_types = {claim.claim_type for claim, _ in group}
            sources = {(article.metadata_json or {}).get("source_key") for _, article in group}
            evidence_texts = {normalize_text((claim.evidence_text or "").lower()) for claim, _ in group if claim.evidence_text}
            if any(self._is_high_impact_claim_type(claim.claim_type) for claim, _ in group):
                high_impact_present = True
            if len(evidence_texts) > 1 and len(claim_types) == 1 and len(sources) > 1:
                conflict_present = True
                cluster_reasons.append(
                    (
                        "cross_source_conflict",
                        "Equivalent claims across sources diverge enough to require manual review.",
                        "high",
                    )
                )

        if high_impact_present and any((claim.confidence or 0.0) < 0.82 for claim, _ in claims):
            cluster_reasons.append(
                (
                    "high_impact_low_confidence",
                    "A high-impact claim in this cluster still has evidence below the publication confidence threshold.",
                    "high",
                )
            )
        elif any((claim.confidence or 0.0) < 0.78 for claim, _ in claims):
            cluster_reasons.append(
                (
                    "cluster_low_confidence",
                    "One or more claims in this cluster remain below the confidence threshold.",
                    "medium",
                )
            )

        if cluster_reasons:
            cluster.review_status = "needs_review"
            cluster.publication_status = "blocked"
            for reason_type, summary, priority in cluster_reasons:
                db.add(
                    NewsReviewTask(
                        target_type="cluster",
                        target_id=cluster.id,
                        reason_type=reason_type,
                        reason_summary=summary,
                        priority="high" if conflict_present or (high_impact_present and priority != "medium") else priority,
                        status="open",
                        resolution=None,
                        agent_payload={
                            "cluster_id": cluster.id,
                            "cluster_type": cluster.cluster_type,
                            "claims_considered": len(claims),
                            "grouped_claims": len(grouped),
                            "canonical_claims": [
                                self._canonical_claim_summary(group)
                                for group in grouped.values()
                            ],
                        },
                    )
                )
        else:
            cluster.review_status = "ready_for_review"
            cluster.publication_status = "blocked"

    @staticmethod
    def _is_high_impact_claim_type(claim_type: str) -> bool:
        return claim_type in {
            "grid_penalty",
            "power_unit_change",
            "upgrade",
            "weather_forecast",
            "parc_ferme_or_setup",
        }

    @staticmethod
    def _canonical_claim_summary(group: list[tuple[NewsClaim, NewsArticle]]) -> dict[str, Any]:
        primary_claim = max(group, key=lambda item: item[0].confidence or 0.0)[0]
        return {
            "normalized_claim_key": primary_claim.normalized_claim_key,
            "claim_type": primary_claim.claim_type,
            "strategy_priority": primary_claim.strategy_priority,
            "representative_text": primary_claim.claim_text,
            "confidence_max": max((claim.confidence or 0.0) for claim, _ in group),
            "confidence_min": min((claim.confidence or 0.0) for claim, _ in group),
            "citation_count": len(group),
            "sources": sorted({((article.metadata_json or {}).get("source_key") or "unknown") for _, article in group}),
            "article_ids": sorted({article.id for _, article in group}),
        }

    def _refresh_summaries(self, db: Session, article: NewsArticle) -> None:
        article_claims = (
            db.query(NewsClaim)
            .filter(NewsClaim.article_id == article.id)
            .order_by(NewsClaim.id.asc())
            .all()
        )
        self._delete_existing_summary(db, "article", article.id, "article_brief")
        article_summary = self.summary_composer.compose_article_summary(article, article_claims)
        if article_summary is not None:
            db.add(
                NewsSummary(
                    target_type="article",
                    target_id=article.id,
                    summary_kind="article_brief",
                    factual_summary=article_summary.factual_summary,
                    strategy_impact_summary=article_summary.strategy_impact_summary,
                    derived_insight=article_summary.derived_insight,
                    citations_json=article_summary.citations_json,
                    model_provider="deterministic",
                    model_name="rule-based-v1",
                    prompt_version="deterministic-claims-v1",
                    status=article_summary.status,
                )
            )

        if article.cluster_id is None:
            db.flush()
            return

        cluster = db.query(NewsCluster).filter(NewsCluster.id == article.cluster_id).one()
        grouped_claims = self._cluster_canonical_claims(db, cluster.id)
        self._delete_existing_summary(db, "cluster", cluster.id, "cluster_brief")
        cluster_summary = self.summary_composer.compose_cluster_summary(
            cluster,
            grouped_claims,
            cluster_review_status=cluster.review_status,
        )
        if cluster_summary is not None:
            db.add(
                NewsSummary(
                    target_type="cluster",
                    target_id=cluster.id,
                    summary_kind="cluster_brief",
                    factual_summary=cluster_summary.factual_summary,
                    strategy_impact_summary=cluster_summary.strategy_impact_summary,
                    derived_insight=cluster_summary.derived_insight,
                    citations_json=cluster_summary.citations_json,
                    model_provider="deterministic",
                    model_name="rule-based-v1",
                    prompt_version="deterministic-cluster-v1",
                    status=cluster_summary.status,
                )
            )
        db.flush()

    def _cluster_canonical_claims(self, db: Session, cluster_id: int) -> list[dict[str, Any]]:
        claims = (
            db.query(NewsClaim, NewsArticle)
            .join(NewsArticle, NewsArticle.id == NewsClaim.article_id)
            .filter(NewsArticle.cluster_id == cluster_id)
            .all()
        )
        grouped: dict[str, list[tuple[NewsClaim, NewsArticle]]] = defaultdict(list)
        for claim, article in claims:
            grouped[claim.normalized_claim_key or f"{claim.claim_type}::{claim.id}"].append((claim, article))
        return [self._canonical_claim_summary(group) for group in grouped.values()]

    @staticmethod
    def _delete_existing_summary(db: Session, target_type: str, target_id: int, summary_kind: str) -> None:
        db.query(NewsSummary).filter(
            NewsSummary.target_type == target_type,
            NewsSummary.target_id == target_id,
            NewsSummary.summary_kind == summary_kind,
        ).delete(synchronize_session=False)

    def apply_review_action(
        self,
        db: Session,
        *,
        target_type: str,
        target_id: int,
        action: str,
        notes: str = "",
    ) -> dict[str, Any]:
        if target_type == "task":
            task = db.query(NewsReviewTask).filter(NewsReviewTask.id == target_id).one_or_none()
            if task is None:
                raise ValueError("review_task_not_found")
            target_type = task.target_type
            target_id = task.target_id

        affected_task_ids: list[int] = []
        resolution = "approved" if action == "approve" else "rejected"

        if target_type == "article":
            article = db.query(NewsArticle).filter(NewsArticle.id == target_id).one_or_none()
            if article is None:
                raise ValueError("article_not_found")
            if action == "approve":
                article.review_status = "approved"
                article.publication_status = "approved"
            else:
                article.review_status = "rejected"
                article.publication_status = "rejected"
            affected_task_ids.extend(self._close_tasks(db, "article", article.id, resolution, notes))
            self._set_summary_status(db, "article", article.id, "published" if action == "approve" else "rejected")
            if article.cluster_id:
                cluster = db.query(NewsCluster).filter(NewsCluster.id == article.cluster_id).one_or_none()
                if cluster is not None and action == "reject":
                    cluster.review_status = "needs_review"
                    cluster.publication_status = "blocked"
            db.flush()
            return {
                "target_type": "article",
                "target_id": article.id,
                "action": action,
                "updated_review_status": article.review_status,
                "updated_publication_status": article.publication_status,
                "affected_task_ids": affected_task_ids,
            }

        if target_type == "cluster":
            cluster = db.query(NewsCluster).filter(NewsCluster.id == target_id).one_or_none()
            if cluster is None:
                raise ValueError("cluster_not_found")
            member_articles = db.query(NewsArticle).filter(NewsArticle.cluster_id == cluster.id).all()
            if action == "approve":
                cluster.review_status = "approved"
                cluster.publication_status = "approved"
                for article in member_articles:
                    if article.review_status not in {"rejected", "suppressed"}:
                        article.review_status = "approved"
                        article.publication_status = "approved"
            else:
                cluster.review_status = "rejected"
                cluster.publication_status = "rejected"
                for article in member_articles:
                    if article.review_status != "suppressed":
                        article.review_status = "rejected"
                        article.publication_status = "rejected"
            affected_task_ids.extend(self._close_tasks(db, "cluster", cluster.id, resolution, notes))
            affected_task_ids.extend(self._close_tasks(db, "article", None, resolution, notes, article_ids=[article.id for article in member_articles]))
            self._set_summary_status(db, "cluster", cluster.id, "published" if action == "approve" else "rejected")
            for article in member_articles:
                self._set_summary_status(db, "article", article.id, "published" if action == "approve" else "rejected")
            db.flush()
            return {
                "target_type": "cluster",
                "target_id": cluster.id,
                "action": action,
                "updated_review_status": cluster.review_status,
                "updated_publication_status": cluster.publication_status,
                "affected_task_ids": sorted(set(affected_task_ids)),
            }

        raise ValueError("unsupported_target_type")

    def _close_tasks(
        self,
        db: Session,
        target_type: str,
        target_id: int | None,
        resolution: str,
        notes: str,
        *,
        article_ids: list[int] | None = None,
    ) -> list[int]:
        query = db.query(NewsReviewTask).filter(NewsReviewTask.target_type == target_type, NewsReviewTask.status == "open")
        if article_ids is not None:
            query = query.filter(NewsReviewTask.target_id.in_(article_ids))
        elif target_id is not None:
            query = query.filter(NewsReviewTask.target_id == target_id)
        tasks = query.all()
        for task in tasks:
            task.status = "closed"
            task.resolution = resolution
            task.resolution_notes = notes or task.resolution_notes
            task.last_attempt_at = datetime.now(timezone.utc)
        return [task.id for task in tasks]

    @staticmethod
    def _set_summary_status(db: Session, target_type: str, target_id: int, status: str) -> None:
        summaries = db.query(NewsSummary).filter(NewsSummary.target_type == target_type, NewsSummary.target_id == target_id).all()
        for summary in summaries:
            summary.status = status

    def _refresh_article_chunks(self, *, db: Session, source: NewsSource, canonical_url: str) -> None:
        article = db.query(NewsArticle).filter(NewsArticle.canonical_url == canonical_url).one()
        text = (article.clean_text or "").strip()
        if not text:
            article.chunk_status = "empty"
            db.flush()
            return

        existing_chunks = db.query(NewsArticleChunk).filter(NewsArticleChunk.article_id == article.id).all()
        existing_ids = [chunk.qdrant_point_id for chunk in existing_chunks if chunk.qdrant_point_id]
        if existing_ids:
            try:
                self.qdrant_client.delete_points(news_settings.news_qdrant_collection_chunks, existing_ids)
            except Exception as exc:
                LOGGER.warning("Unable to delete prior Qdrant points for article %s: %s", article.id, exc)
        for chunk in existing_chunks:
            db.delete(chunk)
        db.flush()

        chunks = chunk_text(text)
        if not chunks:
            article.chunk_status = "empty"
            db.flush()
            return

        points: list[dict] = []
        chunk_records: list[NewsArticleChunk] = []
        for chunk in chunks:
            point_id = str(uuid.uuid4())
            record = NewsArticleChunk(
                article_id=article.id,
                chunk_index=chunk.chunk_index,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                token_count=chunk.token_count,
                chunk_text=chunk.text,
                embedding_provider="local-deterministic",
                embedding_model="hash-256",
                embedding_version="v1",
                qdrant_point_id=point_id,
            )
            db.add(record)
            chunk_records.append(record)
            points.append(
                {
                    "id": point_id,
                    "vector": embed_text(chunk.text),
                    "payload": {
                        "article_id": article.id,
                        "chunk_index": chunk.chunk_index,
                        "source_key": source.source_key,
                        "source_type": article.source_type,
                        "officiality_level": article.officiality_level,
                        "grand_prix": article.grand_prix,
                        "season": article.season,
                        "published_at": article.published_at.isoformat() if article.published_at else None,
                        "review_status": article.review_status,
                        "publication_status": article.publication_status,
                        "headline": article.headline,
                        "canonical_url": article.canonical_url,
                        "text": chunk.text,
                    },
                }
            )

        db.flush()
        try:
            self.qdrant_client.upsert_points(news_settings.news_qdrant_collection_chunks, points)
            article.chunk_status = "indexed"
        except Exception as exc:
            LOGGER.warning("Unable to upsert Qdrant points for article %s: %s", article.id, exc)
            article.chunk_status = "stored_unindexed"
        db.flush()
