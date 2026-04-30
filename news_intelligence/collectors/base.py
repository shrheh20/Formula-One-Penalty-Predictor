"""Base collector primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import re
from typing import Protocol


@dataclass(slots=True)
class ScrapedArticle:
    external_id: str
    canonical_url: str
    headline: str
    subheadline: str | None
    author: str | None
    published_at: datetime | None
    raw_html: str
    raw_text: str
    clean_text: str
    content_type: str = "news"
    summary_eligible: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class NewsCollector(Protocol):
    source_key: str
    display_name: str
    source_type: str
    officiality_level: str
    base_url: str

    def collect_latest(self, *, limit: int = 10) -> list[ScrapedArticle]:
        ...


DROP_QUERY_PARAMS = {
    "sid",
    "output",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
}

CONTENT_TYPE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("podcast", ("podcast", "listen to", "audio episode")),
    ("video", ("video", "watch:", "highlights")),
    ("live_blog", ("live blog", "live updates")),
    ("quiz", ("quiz", "tricky questions")),
    ("fantasy", ("f1 fantasy", "fantasy")),
    ("technical", ("tech review", "technical", "upgrade", "aerodynamic", "floor", "rear wing", "suspension")),
    ("weather", ("weather forecast", "rain", "wet weather")),
    ("tyres", ("tyres", "tires", "compound")),
    ("analysis", ("risk perspective", "state of play", "how", "why", "analysis")),
]

NOISE_PHRASES = {
    "most read",
    "join the conversation!",
    "in this article",
    "skip to content",
    "rather watch the podcast? then click here!",
    "latest videos",
    "sign up for the daily digest and/or weekly newsletter",
    "about racingnews365",
}

HARD_SKIP_CONTENT_TYPES = {"podcast", "video", "live_blog", "quiz"}


def canonicalize_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in DROP_QUERY_PARAMS and not key.startswith("utm_")
    ]
    cleaned = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path.rstrip("/") or parts.path,
            urlencode(filtered_query, doseq=True),
            "",
        )
    )
    return cleaned


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def dedupe_lines(lines: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    return deduped


def is_noise_text(text: str) -> bool:
    lowered = normalize_text(text).lower()
    if not lowered:
        return True
    if lowered in NOISE_PHRASES:
        return True
    if lowered.startswith("please use chrome browser"):
        return True
    if lowered.startswith("never miss a thing from the formula 1 season"):
        return True
    if lowered.startswith("explore the latest f1 results"):
        return True
    if lowered.startswith("a variant with just the race and qualifying"):
        return True
    return False


def detect_content_type(*parts: str) -> str:
    blob = " ".join(normalize_text(part).lower() for part in parts if part).strip()
    for label, needles in CONTENT_TYPE_RULES:
        if any(needle in blob for needle in needles):
            return label
    return "news"


def is_summary_eligible(content_type: str, text: str) -> bool:
    text_length = len((text or "").strip())
    if text_length < 240:
        return False
    return content_type not in HARD_SKIP_CONTENT_TYPES


def is_hard_skip_content_type(content_type: str) -> bool:
    return (content_type or "").strip().lower() in HARD_SKIP_CONTENT_TYPES


def is_generic_listing_headline(headline: str) -> bool:
    lowered = normalize_text(headline).lower()
    return lowered in {
        "formula 1 news",
        "f1 news",
        "formula one news",
        "latest news",
    }
