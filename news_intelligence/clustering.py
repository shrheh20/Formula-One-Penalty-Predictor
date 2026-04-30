"""Cluster assignment for stored news stories."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .embeddings import embed_text
from .models import NewsArticle, NewsCluster, NewsClusterMember

TEAM_KEYWORDS = {
    "mclaren",
    "mercedes",
    "ferrari",
    "red bull",
    "redbull",
    "williams",
    "aston martin",
    "racing bulls",
    "rb",
    "alpine",
    "haas",
    "sauber",
    "audi",
    "cadillac",
}

DRIVER_KEYWORDS = {
    "verstappen",
    "hamilton",
    "leclerc",
    "norris",
    "piastri",
    "russell",
    "antonelli",
    "alonso",
    "stroll",
    "sainz",
    "albon",
    "gasly",
    "ocon",
    "lawson",
    "hadjar",
    "hulkenberg",
    "bortoleto",
    "bearman",
    "colapinto",
    "tsunoda",
    "herta",
    "lindblad",
}

SESSION_KEYWORDS = {
    "practice",
    "fp1",
    "fp2",
    "fp3",
    "qualifying",
    "sprint",
    "sprint qualifying",
    "sprint shootout",
    "race",
}

TOPIC_KEYWORDS = {
    "power unit",
    "engine",
    "grid penalty",
    "penalty",
    "upgrade",
    "floor",
    "rear wing",
    "front wing",
    "suspension",
    "weather",
    "rain",
    "tyres",
    "tires",
    "compound",
    "boost mode",
    "regulation",
    "technical directive",
    "livery",
    "parc ferme",
    "setup",
    "reliability",
}

ALLOWED_CROSS_STORY_TYPES: dict[str, set[str]] = {
    "technical_regulation": {"weather", "reliability"},
    "race_preview": {"weather", "tyre_compound"},
    "live_weekend_update": {"race_preview"},
    "upgrade": {"technical_regulation"},
    "weather": {"race_preview"},
    "tyre_compound": {"race_preview"},
}

CONTENT_TYPE_MISMATCHES = {
    ("podcast", "technical"),
    ("podcast", "weather"),
    ("podcast", "tyres"),
    ("podcast", "grid_penalty"),
    ("video", "technical"),
    ("video", "grid_penalty"),
    ("quiz", "technical"),
    ("quiz", "weather"),
}

TYPE_THRESHOLDS = {
    "grid_penalty": 0.58,
    "upgrade": 0.63,
    "technical_regulation": 0.62,
    "weather": 0.68,
    "tyre_compound": 0.68,
    "driver_market": 0.66,
    "race_preview": 0.56,
    "feature": 0.76,
    "general": 0.74,
}

GRAND_PRIX_ALIASES = {
    "miami": "Miami Grand Prix",
    "monaco": "Monaco Grand Prix",
    "monza": "Italian Grand Prix",
    "silverstone": "British Grand Prix",
    "spa": "Belgian Grand Prix",
    "suzuka": "Japanese Grand Prix",
    "zandvoort": "Dutch Grand Prix",
    "singapore": "Singapore Grand Prix",
    "austin": "United States Grand Prix",
    "vegas": "Las Vegas Grand Prix",
    "melbourne": "Australian Grand Prix",
    "montreal": "Canadian Grand Prix",
    "hungaroring": "Hungarian Grand Prix",
    "imola": "Emilia Romagna Grand Prix",
    "barcelona": "Spanish Grand Prix",
    "jeddah": "Saudi Arabian Grand Prix",
    "bahrain": "Bahrain Grand Prix",
    "interlagos": "Sao Paulo Grand Prix",
    "qatar": "Qatar Grand Prix",
    "abu dhabi": "Abu Dhabi Grand Prix",
    "shanghai": "Chinese Grand Prix",
    "mexico city": "Mexico City Grand Prix",
}


@dataclass(slots=True)
class ArticleFeatures:
    story_type: str
    content_type: str
    grand_prix: str | None
    teams: set[str]
    drivers: set[str]
    sessions: set[str]
    topics: set[str]
    keywords: set[str]
    summary_eligible: bool
    similarity_text: str


@dataclass(slots=True)
class ClusterFeatures:
    story_type: str
    content_type: str
    grand_prix: str | None
    teams: set[str]
    drivers: set[str]
    sessions: set[str]
    topics: set[str]
    keywords: set[str]
    similarity_text: str


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


class NewsClusterer:
    def assign_article(self, db: Session, article: NewsArticle) -> NewsCluster:
        article_features = self._article_features(article)

        cluster_candidates = (
            db.query(NewsCluster)
            .order_by(NewsCluster.latest_published_at.desc().nullslast(), NewsCluster.id.desc())
            .limit(80)
            .all()
        )

        article_vector = embed_text(article_features.similarity_text)
        best_cluster: NewsCluster | None = None
        best_score = -1.0

        for cluster in cluster_candidates:
            cluster_articles = self._cluster_articles(db, cluster.id)
            if not cluster_articles:
                continue
            cluster_features = self._cluster_features(cluster, cluster_articles)
            if not self._story_types_compatible(article_features.story_type, cluster_features.story_type):
                continue
            if self._content_types_conflict(article_features.content_type, cluster_features.content_type):
                continue

            score = self._cluster_match_score(article_features, cluster_features, article_vector)
            threshold = max(
                TYPE_THRESHOLDS.get(article_features.story_type, TYPE_THRESHOLDS["general"]),
                TYPE_THRESHOLDS.get(cluster_features.story_type, TYPE_THRESHOLDS["general"]),
            )
            if score >= threshold and score > best_score:
                best_score = score
                best_cluster = cluster

        if best_cluster is not None:
            self._upsert_membership(db, best_cluster, article, best_score, is_primary=False)
            best_cluster.latest_published_at = max_dt(best_cluster.latest_published_at, article.published_at)
            best_cluster.freshness_score = self._freshness_score(best_cluster.latest_published_at)
            best_cluster.confidence_score = max(best_cluster.confidence_score, min(best_score, 0.99))
            best_cluster.strategy_priority_score = max(
                best_cluster.strategy_priority_score,
                self._strategy_score(article_features.story_type, article_features.topics),
            )
            if article.officiality_level == "official":
                best_cluster.official_evidence_count += 1
            else:
                best_cluster.secondary_evidence_count += 1
            article.cluster_status = "clustered"
            article.cluster_id = best_cluster.id
            return best_cluster

        cluster = NewsCluster(
            cluster_key=self._cluster_key(article, article_features),
            cluster_title=article.headline,
            cluster_type=article_features.story_type,
            grand_prix=article_features.grand_prix,
            season=article.season,
            strategy_priority_score=self._strategy_score(article_features.story_type, article_features.topics),
            freshness_score=self._freshness_score(article.published_at),
            confidence_score=0.6,
            conflict_score=0.0,
            official_evidence_count=1 if article.officiality_level == "official" else 0,
            secondary_evidence_count=0 if article.officiality_level == "official" else 1,
            latest_published_at=article.published_at,
            review_status="pending",
            publication_status="blocked",
            primary_article_id=article.id,
        )
        db.add(cluster)
        db.flush()
        self._upsert_membership(db, cluster, article, 1.0, is_primary=True)
        article.cluster_status = "clustered"
        article.cluster_id = cluster.id
        return cluster

    def _cluster_match_score(
        self,
        article: ArticleFeatures,
        cluster: ClusterFeatures,
        article_vector: list[float],
    ) -> float:
        cluster_vector = embed_text(cluster.similarity_text)
        score = _cosine_similarity(article_vector, cluster_vector)
        score += overlap_score(article.keywords, cluster.keywords) * 0.14
        score += overlap_score(article.topics, cluster.topics) * 0.18
        score += overlap_score(article.teams, cluster.teams) * 0.18
        score += overlap_score(article.drivers, cluster.drivers) * 0.18
        score += overlap_score(article.sessions, cluster.sessions) * 0.10

        if article.story_type == cluster.story_type:
            score += 0.08
        if article.grand_prix and cluster.grand_prix and article.grand_prix == cluster.grand_prix:
            score += 0.12
        elif article.grand_prix and cluster.grand_prix and article.grand_prix != cluster.grand_prix:
            score -= 0.20

        if (
            article.story_type == "race_preview"
            and cluster.story_type == "race_preview"
            and article.grand_prix
            and cluster.grand_prix
            and article.grand_prix == cluster.grand_prix
        ):
            score += 0.10
            shared_preview_terms = article.keywords & cluster.keywords & {
                "strategy",
                "weekend",
                "sprint",
                "qualifying",
                "grip",
                "setup",
                "parc",
                "ferme",
                "trade",
                "offs",
                "tradeoffs",
            }
            if shared_preview_terms:
                score += 0.06

        if not self._entity_anchor_present(article, cluster):
            score -= 0.18

        if article.content_type != cluster.content_type:
            score -= 0.06
        if article.story_type == "feature" and cluster.story_type == "feature" and article.grand_prix != cluster.grand_prix:
            score -= 0.10

        return max(score, -1.0)

    def _entity_anchor_present(self, article: ArticleFeatures, cluster: ClusterFeatures) -> bool:
        if article.story_type in {"weather", "tyre_compound", "race_preview"}:
            return bool(article.grand_prix and cluster.grand_prix and article.grand_prix == cluster.grand_prix)
        if article.story_type in {"grid_penalty", "upgrade", "driver_market"}:
            return bool(
                (article.drivers and cluster.drivers and article.drivers & cluster.drivers)
                or (article.teams and cluster.teams and article.teams & cluster.teams)
                or (article.topics and cluster.topics and article.topics & cluster.topics)
            )
        if article.story_type == "technical_regulation":
            return bool(article.topics and cluster.topics and article.topics & cluster.topics)
        return bool(
            (article.grand_prix and cluster.grand_prix and article.grand_prix == cluster.grand_prix)
            or (article.teams and cluster.teams and article.teams & cluster.teams)
            or (article.drivers and cluster.drivers and article.drivers & cluster.drivers)
        )

    @staticmethod
    def _cluster_articles(db: Session, cluster_id: int) -> list[NewsArticle]:
        return (
            db.query(NewsArticle)
            .filter(NewsArticle.cluster_id == cluster_id)
            .order_by(NewsArticle.published_at.desc().nullslast(), NewsArticle.id.desc())
            .limit(8)
            .all()
        )

    def _cluster_features(self, cluster: NewsCluster, articles: list[NewsArticle]) -> ClusterFeatures:
        article_features = [self._article_features(article) for article in articles]
        teams = set().union(*(feature.teams for feature in article_features)) if article_features else set()
        drivers = set().union(*(feature.drivers for feature in article_features)) if article_features else set()
        sessions = set().union(*(feature.sessions for feature in article_features)) if article_features else set()
        topics = set().union(*(feature.topics for feature in article_features)) if article_features else set()
        keywords = set().union(*(feature.keywords for feature in article_features)) if article_features else set()
        grand_prix = cluster.grand_prix or next((feature.grand_prix for feature in article_features if feature.grand_prix), None)
        story_type = cluster.cluster_type or dominant_value([feature.story_type for feature in article_features]) or "general"
        content_type = dominant_value([feature.content_type for feature in article_features]) or "news"
        similarity_text = " ".join(
            part
            for part in [cluster.cluster_title] + [article.headline for article in articles[:4]]
            if part
        )
        return ClusterFeatures(
            story_type=story_type,
            content_type=content_type,
            grand_prix=grand_prix,
            teams=teams,
            drivers=drivers,
            sessions=sessions,
            topics=topics,
            keywords=keywords,
            similarity_text=similarity_text,
        )

    def _article_features(self, article: NewsArticle) -> ArticleFeatures:
        content_type = (
            ((article.metadata_json or {}).get("content_type") or "").strip().lower()
            or "news"
        )
        summary_eligible = bool((article.metadata_json or {}).get("summary_eligible", True))
        grand_prix = article.grand_prix or extract_grand_prix(article.headline, article.clean_text or "")
        teams = extract_terms(f"{article.headline}\n{article.clean_text or ''}", TEAM_KEYWORDS)
        drivers = extract_terms(f"{article.headline}\n{article.clean_text or ''}", DRIVER_KEYWORDS)
        sessions = extract_terms(f"{article.headline}\n{article.clean_text or ''}", SESSION_KEYWORDS)
        topics = extract_terms(f"{article.headline}\n{article.clean_text or ''}", TOPIC_KEYWORDS)
        story_type = self._story_type(article, content_type, topics, sessions, grand_prix)
        keywords = keyword_set(article.headline, article.subheadline or "", article.clean_text or "")
        similarity_text = " ".join(
            part for part in [article.headline, article.subheadline or "", article.clean_text or ""] if part
        )
        return ArticleFeatures(
            story_type=story_type,
            content_type=content_type,
            grand_prix=grand_prix,
            teams=teams,
            drivers=drivers,
            sessions=sessions,
            topics=topics,
            keywords=keywords,
            summary_eligible=summary_eligible,
            similarity_text=similarity_text,
        )

    def _story_type(
        self,
        article: NewsArticle,
        content_type: str,
        topics: set[str],
        sessions: set[str],
        grand_prix: str | None,
    ) -> str:
        text = f"{article.headline} {article.subheadline or ''} {article.clean_text or ''}".lower()
        if "grid penalty" in text or "five-place" in text or ("penalty" in text and "grid" in text):
            return "grid_penalty"
        if "weather forecast" in text or "wet weather" in text or ("weather" in text and article.grand_prix):
            return "weather"
        if "tyres" in text or "tires" in text or "compound" in text:
            return "tyre_compound"
        if "boost mode" in text or "technical regulation" in text or "regulation" in text:
            return "technical_regulation"
        if {"upgrade", "floor", "rear wing", "front wing", "suspension"} & topics:
            return "upgrade"
        if "future" in text or "stay" in text or "join" in text or "contract" in text:
            return "driver_market"
        if content_type in {"podcast", "video", "quiz", "fantasy"}:
            return "feature"
        if grand_prix and (
            "preview" in text
            or "how" in text
            or "tackle" in text
            or "welcome to" in text
            or "strategy hinges" in text
            or "parc ferme" in text
            or "trade-off" in text
            or "trade offs" in text
            or "trade-offs" in text
        ):
            return "race_preview"
        if sessions:
            return "live_weekend_update"
        return "general"

    @staticmethod
    def _upsert_membership(
        db: Session,
        cluster: NewsCluster,
        article: NewsArticle,
        membership_score: float,
        *,
        is_primary: bool,
    ) -> None:
        existing = (
            db.query(NewsClusterMember)
            .filter(NewsClusterMember.cluster_id == cluster.id)
            .filter(NewsClusterMember.article_id == article.id)
            .one_or_none()
        )
        if existing is None:
            db.add(
                NewsClusterMember(
                    cluster_id=cluster.id,
                    article_id=article.id,
                    membership_score=membership_score,
                    is_primary=is_primary,
                )
            )
        else:
            existing.membership_score = membership_score
            existing.is_primary = is_primary

    @staticmethod
    def _story_types_compatible(left: str, right: str) -> bool:
        if left == right:
            return True
        return right in ALLOWED_CROSS_STORY_TYPES.get(left, set()) or left in ALLOWED_CROSS_STORY_TYPES.get(right, set())

    @staticmethod
    def _content_types_conflict(left: str, right: str) -> bool:
        if left == right:
            return False
        pair = tuple(sorted((left, right)))
        return pair in {tuple(sorted(item)) for item in CONTENT_TYPE_MISMATCHES}

    @staticmethod
    def _cluster_key(article: NewsArticle, features: ArticleFeatures) -> str:
        base = (
            f"{features.story_type}::{features.grand_prix or 'global'}::"
            f"{article.headline.lower()}::{article.published_at or datetime.now(timezone.utc)}"
        )
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
        return f"cluster-{digest}"

    @staticmethod
    def _strategy_score(story_type: str, topics: set[str]) -> float:
        if story_type == "grid_penalty" or "power unit" in topics:
            return 1.0
        if story_type == "upgrade":
            return 0.9
        if story_type == "tyre_compound":
            return 0.8
        if story_type == "weather":
            return 0.75
        if "reliability" in topics:
            return 0.65
        if story_type == "technical_regulation":
            return 0.7
        return 0.35

    @staticmethod
    def _freshness_score(published_at: datetime | None) -> float:
        if published_at is None:
            return 0.0
        normalized = ensure_utc(published_at)
        age_hours = max((datetime.now(timezone.utc) - normalized).total_seconds() / 3600.0, 0.0)
        return max(0.0, 1.0 - min(age_hours / 72.0, 1.0))


def dominant_value(values: list[str]) -> str | None:
    counts: dict[str, int] = {}
    for value in values:
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def max_dt(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return ensure_utc(right) if right is not None else None
    if right is None:
        return ensure_utc(left)
    return max(ensure_utc(left), ensure_utc(right))


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def keyword_set(*parts: str) -> set[str]:
    text = " ".join(parts).lower()
    words = set(re.findall(r"[a-z0-9]+", text))
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "after",
        "before",
        "ahead",
        "will",
        "puts",
        "team",
        "formula",
        "one",
    }
    return {word for word in words if len(word) > 2 and word not in stop}


def overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    union = len(left | right)
    if union == 0:
        return 0.0
    return intersection / union


def extract_terms(text: str, vocabulary: set[str]) -> set[str]:
    lowered = text.lower()
    found: set[str] = set()
    for term in vocabulary:
        if term in lowered:
            found.add(term)
    return found


def extract_grand_prix(*parts: str) -> str | None:
    text = " ".join(part for part in parts if part)
    match = re.search(r"\b([A-Z][A-Za-z0-9'.-]+ Grand Prix)\b", text)
    if match:
        return match.group(1)
    lowered = text.lower()
    for alias, label in GRAND_PRIX_ALIASES.items():
        if alias in lowered:
            return label
    return None
