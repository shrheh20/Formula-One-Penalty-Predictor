"""PDF download and text extraction helpers."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)


class PdfProcessingError(RuntimeError):
    pass


class PdfProcessor:
    def __init__(self, data_dir: str = "data/fia_docs", timeout: int = 60) -> None:
        self.data_dir = Path(data_dir)
        self.timeout = timeout
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
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def download_pdf(self, grand_prix: str, doc_number: int, pdf_url: str) -> str:
        safe_grand_prix = self._slugify(grand_prix)
        target_dir = self.data_dir / safe_grand_prix
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"doc_{doc_number}.pdf"

        response = self.session.get(pdf_url, timeout=self.timeout)
        response.raise_for_status()
        content = response.content

        if len(content) <= 1024:
            raise PdfProcessingError(f"Downloaded file is too small for {pdf_url}")
        if not content.startswith(b"%PDF"):
            raise PdfProcessingError(f"Downloaded file is not a valid PDF for {pdf_url}")

        target_path.write_bytes(content)
        LOGGER.info("PDF downloaded: %s", target_path)
        return str(target_path.resolve())

    def extract_text(self, local_file: str) -> str:
        text_parts: list[str] = []
        with fitz.open(local_file) as document:
            for page in document:
                page_text = page.get_text("text", sort=True)
                if page_text:
                    text_parts.append(f"\n--- PAGE {page.number + 1} ---\n{page_text}")
        return "\n".join(text_parts).strip()

    @staticmethod
    def _slugify(value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return cleaned or "unknown_grand_prix"
