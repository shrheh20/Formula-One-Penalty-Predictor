"""Collector for Sky Sports Formula 1 news."""

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
    dedupe_lines,
    detect_content_type,
    is_noise_text,
    is_summary_eligible,
    normalize_text,
)
from news_intelligence.config import news_settings


class SkySportsF1Collector:
    source_key = "sky_sports_f1"
    display_name = "Sky Sports Formula 1"
    source_type = "news"
    officiality_level = "secondary"

    def __init__(self, base_url: str | None = None, timeout_seconds: float | None = None) -> None:
        self.base_url = base_url or news_settings.news_sky_sports_f1_url
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
        soup = BeautifulSoup(response.text, "html.parser")

        article_links: list[str] = []
        for anchor in soup.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            if not href.startswith("/f1/news/"):
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

        headline_node = soup.select_one("h1")
        headline = self._clean_text(headline_node.get_text(" ", strip=True)) if headline_node else ""
        if not headline:
            return None

        body_nodes = soup.select("div.sdc-article-body p")
        lines: list[str] = []
        for node in body_nodes:
            text = self._clean_text(node.get_text(" ", strip=True))
            if not text or text == "F1" or is_noise_text(text):
                continue
            lines.append(text)
        clean_text = "\n\n".join(dedupe_lines(lines)).strip()
        if not clean_text:
            return None

        published_at = self._extract_published_at(soup, html)
        author = self._extract_author(soup, html)
        grand_prix = self._extract_grand_prix(f"{headline}\n{clean_text}")
        content_type = detect_content_type(headline, article_url, clean_text)
        parsed = urlparse(article_url)
        external_id = parsed.path.strip("/").split("/")[-1] or article_url
        subheadline = self._extract_subheadline(soup, clean_text)

        return ScrapedArticle(
            external_id=external_id,
            canonical_url=article_url,
            headline=headline,
            subheadline=subheadline,
            author=author,
            published_at=published_at,
            raw_html=html,
            raw_text=clean_text,
            clean_text=clean_text,
            content_type=content_type,
            summary_eligible=is_summary_eligible(content_type, clean_text),
            metadata={
                "listing_url": self.base_url,
                "source_key": self.source_key,
                "grand_prix_hint": grand_prix,
            },
        )

    def _extract_subheadline(self, soup: BeautifulSoup, fallback_text: str) -> str | None:
        meta = soup.select_one('meta[name="description"]')
        if meta and meta.get("content"):
            return self._clean_text(meta["content"])
        first_paragraph = fallback_text.split("\n\n", 1)[0].strip()
        return first_paragraph or None

    @staticmethod
    def _extract_published_at(soup: BeautifulSoup, html: str) -> datetime | None:
        for selector in (
            'meta[property="article:published_time"]',
            'meta[name="article:published_time"]',
        ):
            node = soup.select_one(selector)
            if node and node.get("content"):
                parsed = SkySportsF1Collector._parse_datetime(node["content"])
                if parsed is not None:
                    return parsed

        json_ld = SkySportsF1Collector._extract_json_ld(html)
        items = json_ld if isinstance(json_ld, list) else [json_ld]
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("datePublished", "dateCreated"):
                value = item.get(key)
                if isinstance(value, str):
                    parsed = SkySportsF1Collector._parse_datetime(value)
                    if parsed is not None:
                        return parsed
        return None

    @staticmethod
    def _extract_author(soup: BeautifulSoup, html: str) -> str | None:
        for selector in ('meta[name="author"]', 'meta[property="article:author"]'):
            node = soup.select_one(selector)
            if node and node.get("content"):
                return node["content"].strip()

        json_ld = SkySportsF1Collector._extract_json_ld(html)
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
    def _extract_grand_prix(text: str) -> str | None:
        match = re.search(r"\b([A-Z][A-Za-z0-9'.-]+ Grand Prix)\b", text)
        return match.group(1) if match else None

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
