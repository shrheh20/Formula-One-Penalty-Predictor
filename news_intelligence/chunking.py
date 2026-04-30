"""Utilities for article chunking."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TextChunk:
    chunk_index: int
    char_start: int
    char_end: int
    text: str
    token_count: int


def chunk_text(text: str, *, target_chars: int = 1800, overlap_chars: int = 250) -> list[TextChunk]:
    normalized = (text or "").strip()
    if not normalized:
        return []

    paragraphs = [segment.strip() for segment in normalized.split("\n\n") if segment.strip()]
    if not paragraphs:
        paragraphs = [normalized]

    chunks: list[TextChunk] = []
    cursor = 0
    chunk_index = 0
    buffer = ""
    buffer_start = 0

    def flush_buffer(current: str, start: int, index: int) -> TextChunk | None:
        cleaned = current.strip()
        if not cleaned:
            return None
        offset = normalized.find(cleaned, start)
        if offset == -1:
            offset = start
        end = offset + len(cleaned)
        return TextChunk(
            chunk_index=index,
            char_start=offset,
            char_end=end,
            text=cleaned,
            token_count=len(cleaned.split()),
        )

    for paragraph in paragraphs:
        if not buffer:
            buffer = paragraph
            buffer_start = cursor
        elif len(buffer) + 2 + len(paragraph) <= target_chars:
            buffer = f"{buffer}\n\n{paragraph}"
        else:
            chunk = flush_buffer(buffer, buffer_start, chunk_index)
            if chunk is not None:
                chunks.append(chunk)
                chunk_index += 1
            overlap = buffer[-overlap_chars:].strip()
            buffer = f"{overlap}\n\n{paragraph}" if overlap else paragraph
            buffer_start = max(cursor - len(overlap), 0)
        cursor += len(paragraph) + 2

    chunk = flush_buffer(buffer, buffer_start, chunk_index)
    if chunk is not None:
        chunks.append(chunk)
    return chunks

