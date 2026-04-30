"""Shared helpers for OpenAI-compatible LLM endpoints."""

from __future__ import annotations

import os
from typing import Any


def normalize_chat_completions_url(raw_url: str) -> str:
    """Accept a server base URL, `/v1`, or a full chat completions URL."""

    url = (raw_url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return f"{url}/chat/completions"
    return f"{url}/v1/chat/completions"


def resolve_chat_setting(*names: str, default: str = "") -> str:
    """Return the first non-empty environment value from a list of names."""

    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def extract_message_text(payload: dict[str, Any]) -> str:
    """Extract assistant text from chat-completions style payloads."""

    choices = payload.get("choices") or []
    if not choices:
        return ""

    message = choices[0].get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
                continue
            nested_text = item.get("content")
            if isinstance(nested_text, str):
                parts.append(nested_text)
        return "\n".join(part for part in parts if part).strip()

    return ""
