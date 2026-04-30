"""Deterministic claim extraction for Formula One news stories."""

from __future__ import annotations

import re
from dataclasses import dataclass

from news_intelligence.collectors.base import normalize_text

from .models import NewsArticle, NewsArticleChunk

CLAIM_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("grid_penalty", "grid_penalties", re.compile(r"\b(?:five|ten|\d+)[-\s]place grid penalty\b|\bgrid penalty\b", re.IGNORECASE)),
    ("power_unit_change", "grid_penalties", re.compile(r"\bpower unit\b|\bengine change\b|\bcomponent change\b", re.IGNORECASE)),
    ("upgrade", "upgrades", re.compile(r"\bupgrade(?:d|s)?\b|\bnew floor\b|\brear wing\b|\bfront wing\b|\bsuspension\b", re.IGNORECASE)),
    ("tyre_compound", "tyres", re.compile(r"\btyres?\b|\btires?\b|\bcompound\b|\bsofts\b|\bmediums\b|\bhards\b", re.IGNORECASE)),
    ("weather_forecast", "weather", re.compile(r"\bweather\b|\brain\b|\bwet weather\b|\blow grip\b", re.IGNORECASE)),
    ("technical_regulation", "technical_regulations", re.compile(r"\bregulation(?:s)?\b|\btechnical regulation\b|\bboost mode\b|\btechnical directive\b", re.IGNORECASE)),
    ("parc_ferme_or_setup", "parc_ferme_setup", re.compile(r"\bparc ferme\b|\bsetup\b|\btrade-?off\b|\btrade offs\b", re.IGNORECASE)),
    ("reliability_concern", "reliability", re.compile(r"\breliability\b|\bfailure\b|\bissue\b|\bproblem\b", re.IGNORECASE)),
    ("driver_market", "driver_market", re.compile(r"\bfuture\b|\bstay\b|\bjoin\b|\bcontract\b", re.IGNORECASE)),
]

DRIVER_PATTERN = re.compile(
    r"\b(Verstappen|Hamilton|Leclerc|Norris|Piastri|Russell|Antonelli|Alonso|Stroll|Sainz|Albon|Gasly|Ocon|Lawson|Hadjar|Hulkenberg|Bortoleto|Bearman|Colapinto|Herta|Lindblad)\b",
    re.IGNORECASE,
)
TEAM_PATTERN = re.compile(
    r"\b(McLaren|Mercedes|Ferrari|Red Bull|Williams|Aston Martin|Racing Bulls|Alpine|Haas|Sauber|Audi|Cadillac)\b",
    re.IGNORECASE,
)
SESSION_PATTERN = re.compile(
    r"\b(Practice|FP1|FP2|FP3|Qualifying|Sprint Qualifying|Sprint Shootout|Sprint|Race)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ExtractedClaim:
    claim_type: str
    strategy_priority: str
    claim_text: str
    confidence: float
    citation_start: int
    citation_end: int
    affected_driver: str | None
    affected_team: str | None
    affected_session: str | None
    payload: dict


class DeterministicClaimExtractor:
    def extract_article_claims(
        self,
        article: NewsArticle,
        chunks: list[NewsArticleChunk],
    ) -> list[tuple[NewsArticleChunk, ExtractedClaim]]:
        text = f"{article.headline}. {article.clean_text or ''}".strip()
        article_driver = self._first_match(DRIVER_PATTERN, text)
        article_team = self._first_match(TEAM_PATTERN, text)
        article_session = self._first_match(SESSION_PATTERN, text)

        extracted: list[tuple[NewsArticleChunk, ExtractedClaim]] = []
        seen_keys: set[tuple[str, str]] = set()

        for chunk in chunks:
            chunk_text = chunk.chunk_text or ""
            for claim_type, strategy_priority, pattern in CLAIM_PATTERNS:
                for match in pattern.finditer(chunk_text):
                    sentence, start, end = sentence_window(chunk_text, match.start(), match.end())
                    normalized_sentence = normalize_claim_text(sentence)
                    key = (claim_type, normalized_sentence)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    extracted.append(
                        (
                            chunk,
                            ExtractedClaim(
                                claim_type=claim_type,
                                strategy_priority=strategy_priority,
                                claim_text=sentence,
                                confidence=self._confidence_for(claim_type, sentence),
                                citation_start=start,
                                citation_end=end,
                                affected_driver=self._first_match(DRIVER_PATTERN, sentence) or article_driver,
                                affected_team=self._first_match(TEAM_PATTERN, sentence) or article_team,
                                affected_session=self._first_match(SESSION_PATTERN, sentence) or article_session,
                                payload={
                                    "pattern_match": match.group(0),
                                    "normalized_claim_text": normalized_sentence,
                                    "content_type": (article.metadata_json or {}).get("content_type"),
                                    "summary_eligible": (article.metadata_json or {}).get("summary_eligible", True),
                                },
                            ),
                        )
                    )
        return extracted

    @staticmethod
    def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
        match = pattern.search(text or "")
        return match.group(1) if match else None

    @staticmethod
    def _confidence_for(claim_type: str, sentence: str) -> float:
        baseline = {
            "grid_penalty": 0.88,
            "power_unit_change": 0.82,
            "upgrade": 0.8,
            "tyre_compound": 0.82,
            "weather_forecast": 0.78,
            "technical_regulation": 0.86,
            "parc_ferme_or_setup": 0.75,
            "reliability_concern": 0.68,
            "driver_market": 0.65,
        }.get(claim_type, 0.6)
        lowered = sentence.lower()
        if "expected" in lowered or "could" in lowered or "considering" in lowered:
            baseline -= 0.08
        if "confirmed" in lowered or "bans" in lowered or "will" in lowered:
            baseline += 0.04
        return max(0.35, min(baseline, 0.98))


def sentence_window(text: str, start: int, end: int) -> tuple[str, int, int]:
    left = text.rfind(".", 0, start)
    right = text.find(".", end)
    sentence_start = 0 if left == -1 else left + 1
    sentence_end = len(text) if right == -1 else right + 1
    sentence = text[sentence_start:sentence_end].strip()
    local_start = sentence.find(text[start:end])
    if local_start == -1:
        local_start = 0
    local_end = min(local_start + len(text[start:end]), len(sentence))
    return sentence, local_start, local_end


def normalize_claim_text(text: str) -> str:
    lowered = normalize_text(text).lower()
    lowered = lowered.replace("five-place", "grid penalty")
    lowered = lowered.replace("ten-place", "grid penalty")
    lowered = lowered.replace("sprint qualifying", "qualifying")
    lowered = lowered.replace("trade-offs", "tradeoff").replace("trade-off", "tradeoff")
    lowered = re.sub(r"\bmiami grand prix\b", "miami", lowered)
    lowered = re.sub(r"\bthe\b|\ba\b|\ban\b", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered
