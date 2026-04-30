"""Deterministic draft summarization for news intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .collectors.base import normalize_text
from .models import NewsArticle, NewsClaim, NewsCluster


@dataclass(slots=True)
class SummaryDraft:
    factual_summary: str
    strategy_impact_summary: str
    derived_insight: str
    citations_json: dict[str, Any]
    status: str


class DeterministicSummaryComposer:
    def compose_article_summary(
        self,
        article: NewsArticle,
        claims: list[NewsClaim],
    ) -> SummaryDraft | None:
        usable = [claim for claim in claims if not claim.needs_review and (claim.confidence or 0.0) >= 0.78]
        if not usable:
            return None

        top_claims = ordered_claims(usable)[:2]
        factual = " ".join(trim_sentence(claim.claim_text) for claim in top_claims)
        strategy = self._strategy_line(top_claims, article.grand_prix)
        insight = self._insight_line(top_claims, article.grand_prix)
        citations = {
            "claims": [claim_to_citation_payload(claim, article.id, article.canonical_url) for claim in top_claims],
        }
        return SummaryDraft(
            factual_summary=factual,
            strategy_impact_summary=strategy,
            derived_insight=insight,
            citations_json=citations,
            status="draft_ready",
        )

    def compose_cluster_summary(
        self,
        cluster: NewsCluster,
        canonical_claims: list[dict[str, Any]],
        *,
        cluster_review_status: str,
    ) -> SummaryDraft | None:
        usable = [claim for claim in canonical_claims if float(claim.get("confidence_max") or 0.0) >= 0.78]
        if not usable:
            return None

        top_claims = sorted(
            usable,
            key=lambda claim: (
                claim_priority_rank(claim.get("strategy_priority")),
                -float(claim.get("confidence_max") or 0.0),
                -int(claim.get("citation_count") or 0),
            ),
        )[:3]

        factual = " ".join(trim_sentence(str(claim.get("representative_text") or "")) for claim in top_claims[:2]).strip()
        strategy = self._cluster_strategy_line(top_claims, cluster.grand_prix)
        insight = self._cluster_insight_line(top_claims, cluster.grand_prix, cluster.cluster_type)
        status = "draft_ready" if cluster_review_status == "ready_for_review" else "draft_review"
        return SummaryDraft(
            factual_summary=factual,
            strategy_impact_summary=strategy,
            derived_insight=insight,
            citations_json={"claims": top_claims},
            status=status,
        )

    @staticmethod
    def _strategy_line(claims: list[NewsClaim], grand_prix: str | None) -> str:
        claim_types = {claim.claim_type for claim in claims}
        gp = grand_prix or "the weekend"
        if "grid_penalty" in claim_types or "power_unit_change" in claim_types:
            return f"This directly affects starting position and likely pushes teams toward damage-limitation strategy at {gp}."
        if "weather_forecast" in claim_types:
            return f"This changes tyre prep and qualifying/race risk planning for {gp}."
        if "upgrade" in claim_types:
            return f"This could shift balance between straight-line speed and cornering performance at {gp}."
        if "parc_ferme_or_setup" in claim_types:
            return f"This points to setup compromise risk, especially once parc ferme conditions lock teams in."
        return f"This should be monitored for strategy effects across qualifying and race preparation at {gp}."

    @staticmethod
    def _insight_line(claims: list[NewsClaim], grand_prix: str | None) -> str:
        claim_types = {claim.claim_type for claim in claims}
        gp = grand_prix or "this event"
        if "grid_penalty" in claim_types:
            return f"The key question for {gp} is whether the team accepts track-position loss early or chases recovery through setup and tyre offset."
        if "technical_regulation" in claim_types:
            return f"The main takeaway for {gp} is that teams may have fewer tactical tools available than before under the updated rules."
        return f"The important read for {gp} is how these signals reshape weekend preparation rather than just the headline itself."

    @staticmethod
    def _cluster_strategy_line(claims: list[dict[str, Any]], grand_prix: str | None) -> str:
        priorities = {str(claim.get("strategy_priority") or "") for claim in claims}
        gp = grand_prix or "the weekend"
        if "grid_penalties" in priorities:
            return f"Starting-position loss and recovery planning are the major strategy implications for {gp}."
        if "upgrades" in priorities:
            return f"Car-balance changes and relative pace shifts are the main strategy implications for {gp}."
        if "weather" in priorities:
            return f"Tyre windows, qualifying timing, and low-grip risk are the major strategy implications for {gp}."
        if "parc_ferme_setup" in priorities:
            return f"Setup lock-in and compromise management are the key strategy implications for {gp}."
        return f"The cluster points to actionable weekend-preparation changes for {gp}."

    @staticmethod
    def _cluster_insight_line(claims: list[dict[str, Any]], grand_prix: str | None, cluster_type: str | None) -> str:
        gp = grand_prix or "this race weekend"
        if cluster_type == "race_preview":
            return f"For {gp}, teams are converging on the same problem: how much performance to trade between qualifying speed and race robustness."
        if cluster_type == "grid_penalty":
            return f"For {gp}, the story is not just the penalty itself but which teams can turn that setback into an offset strategy opportunity."
        if cluster_type == "technical_regulation":
            return f"For {gp}, the bigger implication is reduced tactical flexibility under the updated technical framework."
        return f"For {gp}, this cluster matters because it changes how teams should frame the competitive picture rather than just one isolated headline."


def ordered_claims(claims: list[NewsClaim]) -> list[NewsClaim]:
    return sorted(
        claims,
        key=lambda claim: (
            claim_priority_rank(claim.strategy_priority),
            -(claim.confidence or 0.0),
            claim.id,
        ),
    )


def claim_priority_rank(priority: str | None) -> int:
    order = {
        "grid_penalties": 0,
        "upgrades": 1,
        "tyres": 2,
        "weather": 3,
        "reliability": 4,
        "parc_ferme_setup": 5,
        "technical_regulations": 6,
        "driver_market": 7,
    }
    return order.get((priority or "").strip(), 99)


def trim_sentence(text: str, max_len: int = 180) -> str:
    sentence = normalize_text(text)
    if len(sentence) <= max_len:
        return sentence
    return sentence[: max_len - 1].rstrip() + "..."


def claim_to_citation_payload(claim: NewsClaim, article_id: int, canonical_url: str) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "canonical_url": canonical_url,
        "claim_type": claim.claim_type,
        "strategy_priority": claim.strategy_priority,
        "claim_text": claim.claim_text,
        "confidence": claim.confidence,
        "citation_article_chunk_id": claim.citation_article_chunk_id,
        "citation_char_start": claim.citation_char_start,
        "citation_char_end": claim.citation_char_end,
    }
