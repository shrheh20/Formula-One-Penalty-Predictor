"""Collector for Formula 1 latest news articles."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from news_intelligence.collectors.base import (
    ScrapedArticle,
    canonicalize_url,
    detect_content_type,
    is_summary_eligible,
    normalize_text,
)
from news_intelligence.config import news_settings


class Formula1PressCollector:
    source_key = "formula1_press"
    display_name = "Formula 1 Latest News"
    source_type = "official_news"
    officiality_level = "official"

    def __init__(self, base_url: str | None = None, timeout_seconds: float | None = None) -> None:
        self.base_url = base_url or "https://www.formula1.com/en/latest"
        self.timeout_seconds = timeout_seconds or news_settings.news_fetch_timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": news_settings.news_user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def collect_latest(self, *, limit: int = 10) -> list[ScrapedArticle]:
        response = self.session.get(self.base_url, timeout=self.timeout_seconds)
        response.raise_for_status()
        listing_html = response.text
        soup = BeautifulSoup(listing_html, "html.parser")

        article_links: list[str] = []
        for anchor in soup.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            if not href or not href.startswith("/en/latest/article/"):
                continue
            absolute_url = canonicalize_url(urljoin(self.base_url, href))
            if absolute_url not in article_links:
                article_links.append(absolute_url)
            if len(article_links) >= limit:
                break

        articles: list[ScrapedArticle] = []
        for article_url in article_links:
            article = self._fetch_article(article_url)
            if article is not None:
                articles.append(article)
        return articles

    def _fetch_article(self, article_url: str) -> ScrapedArticle | None:
        response = self.session.get(article_url, timeout=self.timeout_seconds)
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        headline = self._extract_headline(soup)
        if not headline:
            return None

        published_at = self._extract_published_at(soup, html)
        article_text = self._extract_article_text(soup)
        if not article_text:
            return None
        content_type = detect_content_type(headline, article_url, article_text)

        parsed = urlparse(article_url)
        external_id = parsed.path.strip("/").split("/")[-1] or article_url
        grand_prix = self._extract_grand_prix(article_text)

        lines = [segment.strip() for segment in article_text.split("\n\n") if segment.strip()]
        subheadline = lines[0] if lines else None

        return ScrapedArticle(
            external_id=external_id,
            canonical_url=article_url,
            headline=headline,
            subheadline=subheadline,
            author=self._extract_author(soup, html),
            published_at=published_at,
            raw_html=html,
            raw_text=article_text,
            clean_text=article_text,
            content_type=content_type,
            summary_eligible=is_summary_eligible(content_type, article_text),
            metadata={
                "listing_url": self.base_url,
                "source_key": self.source_key,
                "grand_prix_hint": grand_prix,
            },
        )

    @staticmethod
    def _extract_headline(soup: BeautifulSoup) -> str | None:
        for selector in ("h1", "title"):
            node = soup.select_one(selector)
            if node:
                text = " ".join(node.get_text(" ", strip=True).split())
                if text:
                    return text.replace(" | Formula 1®", "").replace(" | Formula 1", "").strip()
        return None

    @staticmethod
    def _extract_published_at(soup: BeautifulSoup, html: str) -> datetime | None:
        for selector in (
            'meta[property="article:published_time"]',
            'meta[name="article:published_time"]',
            'meta[name="parsely-pub-date"]',
        ):
            node = soup.select_one(selector)
            if node and node.get("content"):
                parsed = Formula1PressCollector._parse_datetime(node["content"])
                if parsed is not None:
                    return parsed

        json_ld = Formula1PressCollector._extract_json_ld(html)
        if isinstance(json_ld, list):
            for item in json_ld:
                parsed = Formula1PressCollector._datetime_from_json_ld(item)
                if parsed is not None:
                    return parsed
        elif isinstance(json_ld, dict):
            parsed = Formula1PressCollector._datetime_from_json_ld(json_ld)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _extract_author(soup: BeautifulSoup, html: str) -> str | None:
        for selector in ('meta[name="author"]', 'meta[property="article:author"]'):
            node = soup.select_one(selector)
            if node and node.get("content"):
                return node["content"].strip()

        json_ld = Formula1PressCollector._extract_json_ld(html)
        items = json_ld if isinstance(json_ld, list) else [json_ld]
        for item in items:
            if not isinstance(item, dict):
                continue
            author = item.get("author")
            if isinstance(author, dict) and isinstance(author.get("name"), str):
                return author["name"].strip()
            if isinstance(author, list):
                for author_item in author:
                    if isinstance(author_item, dict) and isinstance(author_item.get("name"), str):
                        return author_item["name"].strip()
        return None

    @staticmethod
    def _extract_article_text(soup: BeautifulSoup) -> str:
        selectors = [
            'article p',
            '[data-testid="article-body"] p',
            'main p',
        ]
        lines: list[str] = []
        for selector in selectors:
            nodes = soup.select(selector)
            if not nodes:
                continue
            for node in nodes:
                text = Formula1PressCollector._clean_text(node.get_text(" ", strip=True))
                if not text:
                    continue
                if text.startswith("Watch:") or text.startswith("Listen to"):
                    continue
                lines.append(text)
            if lines:
                break

        deduped: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if line in seen:
                continue
            seen.add(line)
            deduped.append(line)
        return "\n\n".join(deduped).strip()

    @staticmethod
    def _extract_grand_prix(text: str) -> str | None:
        match = re.search(r"\b([A-Z][A-Za-z0-9'.-]+ Grand Prix)\b", text)
        return match.group(1) if match else None

    @staticmethod
    def _extract_json_ld(html: str) -> dict | list | None:
        matches = re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        for payload in matches:
            candidate = payload.strip()
            if not candidate:
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _datetime_from_json_ld(item: dict) -> datetime | None:
        if not isinstance(item, dict):
            return None
        for key in ("datePublished", "dateCreated", "uploadDate"):
            value = item.get(key)
            if isinstance(value, str):
                parsed = Formula1PressCollector._parse_datetime(value)
                if parsed is not None:
                    return parsed
        return None

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        value = (value or "").strip()
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _clean_text(value: str) -> str:
        return normalize_text(value)
