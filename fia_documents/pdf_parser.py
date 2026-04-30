"""PDF download and text extraction helpers."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)

try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text
except ModuleNotFoundError:  # pragma: no cover - exercised only when dependency is absent
    pdfminer_extract_text = None


class PdfProcessingError(RuntimeError):
    pass


@dataclass(slots=True)
class DownloadedPdf:
    local_file: str
    sha256: str
    size_bytes: int
    downloaded_at: datetime


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

    def download_pdf(self, grand_prix: str, doc_number: int, pdf_url: str) -> DownloadedPdf:
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
        return DownloadedPdf(
            local_file=str(target_path.resolve()),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            downloaded_at=datetime.now(timezone.utc),
        )

    def extract_text(self, local_file: str) -> str:
        if pdfminer_extract_text is None:
            raise PdfProcessingError(
                "pdfminer.six is not installed. Add it to the environment to enable PDF parsing."
            )

        try:
            text = pdfminer_extract_text(local_file)
        except Exception as exc:  # pragma: no cover - dependency/parser exceptions vary
            raise PdfProcessingError(f"Unable to parse PDF text from {local_file}: {exc}") from exc

        normalized = "\n".join(line.rstrip() for line in text.splitlines())
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        if not normalized:
            raise PdfProcessingError(f"No extractable text found in {local_file}")
        return normalized

    @staticmethod
    def _slugify(value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return cleaned or "unknown_grand_prix"
