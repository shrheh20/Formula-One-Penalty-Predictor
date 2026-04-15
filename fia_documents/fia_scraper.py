"""Scraper for the FIA Formula One decision documents portal."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)

FIA_DOCUMENTS_URL = (
    "https://www.fia.com/documents/championships/"
    "fia-formula-one-world-championship-14/season/season-2026-2072"
)
BASE_URL = "https://www.fia.com"
DEFAULT_EVENT_PAGE_URLS = [
    "https://www.fia.com/documents/championships/fia-formula-one-world-championship-14/season/season-2026-2072/event/Australian%20Grand%20Prix",
    "https://www.fia.com/documents/championships/fia-formula-one-world-championship-14/season/season-2026-2072/event/Chinese%20Grand%20Prix",
]

DOC_TITLE_PATTERN = re.compile(r"^(?:Recalled\s*-\s*)?Doc\s+(?P<number>\d+)\s*-\s*(?P<title>.+)$")


@dataclass(slots=True)
class ScrapedDocument:
    doc_number: int
    title: str
    grand_prix: str
    published_time: datetime | None
    pdf_url: str | None
    is_recalled: bool = False

    @property
    def source_key(self) -> tuple[int, str]:
        return (self.doc_number, self.grand_prix)


class FiaDocumentScraper:
    """Scrape and normalize FIA document rows from the season page."""

    def __init__(
        self,
        page_url: str = FIA_DOCUMENTS_URL,
        timeout: int = 30,
        extra_page_urls: list[str] | None = None,
    ) -> None:
        self.page_url = page_url
        self.timeout = timeout
        self.extra_page_urls = extra_page_urls or list(DEFAULT_EVENT_PAGE_URLS)
        self.session = self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "fia-document-monitor/1.0 (+https://example.invalid; "
                    "contact=ops@example.invalid)"
                )
            }
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def scrape_documents(self) -> list[ScrapedDocument]:
        page_urls = [self.page_url, *self.extra_page_urls]
        documents: list[ScrapedDocument] = []
        for page_url in page_urls:
            html = self.fetch_html(page_url)
            documents.extend(self.parse_documents(html))
        return documents

    def parse_documents(self, html: str) -> list[ScrapedDocument]:
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one("div.decision-document-list")
        if container is None:
            raise ValueError("Unable to find FIA decision document list")

        documents: list[ScrapedDocument] = []
        for event_node in container.select("ul.event-wrapper > li"):
            event_title = event_node.select_one("div.event-title")
            if event_title is None:
                continue

            grand_prix = self._normalize_whitespace(event_title.get_text(" ", strip=True))
            if not grand_prix:
                continue

            for row in event_node.select("li.document-row"):
                parsed = self._parse_document_row(grand_prix, row)
                if parsed is not None:
                    documents.append(parsed)

        LOGGER.info("Scraped %s FIA document rows", len(documents))
        return documents

    def fetch_html(self, page_url: str | None = None) -> str:
        target_url = page_url or self.page_url
        response = self.session.get(target_url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def _parse_document_row(self, grand_prix: str, row) -> ScrapedDocument | None:
        title_node = row.select_one("div.title")
        if title_node is None:
            return None

        raw_title = self._normalize_whitespace(title_node.get_text(" ", strip=True))
        match = DOC_TITLE_PATTERN.match(raw_title)
        if match is None:
            LOGGER.warning("Skipping unparseable document title: %s", raw_title)
            return None

        published_node = row.select_one(".published .date-display-single")
        published_time = self._parse_published_time(
            self._normalize_whitespace(published_node.get_text(" ", strip=True))
            if published_node is not None
            else None
        )

        anchor = row.select_one("a[href]")
        pdf_url = urljoin(BASE_URL, anchor["href"]) if anchor is not None else None
        is_recalled = row.select_one("div.recalled-document") is not None

        return ScrapedDocument(
            doc_number=int(match.group("number")),
            title=match.group("title").strip(),
            grand_prix=grand_prix,
            published_time=published_time,
            pdf_url=pdf_url,
            is_recalled=is_recalled,
        )

    @staticmethod
    def _parse_published_time(raw_value: str | None) -> datetime | None:
        if not raw_value:
            return None
        return datetime.strptime(raw_value, "%d.%m.%y %H:%M")

    @staticmethod
    def _normalize_whitespace(value: str) -> str:
        return " ".join(value.split())


def deduplicate_documents(documents: Iterable[ScrapedDocument]) -> list[ScrapedDocument]:
    """Keep the newest version of each document key within a scrape run."""

    deduped: dict[tuple[int, str], ScrapedDocument] = {}
    for document in documents:
        current = deduped.get(document.source_key)
        if current is None:
            deduped[document.source_key] = document
            continue

        if document.published_time and (
            current.published_time is None or document.published_time >= current.published_time
        ):
            deduped[document.source_key] = document

    return list(deduped.values())
