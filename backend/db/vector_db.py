"""Lightweight in-memory vector store abstraction for local testing."""

from __future__ import annotations

from collections import Counter
from math import sqrt
from typing import Any


def _tokenize(text: str) -> Counter[str]:
    return Counter(word.strip(".,:;!?()[]{}").lower() for word in text.split() if word.strip())


def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    shared = set(left) & set(right)
    numerator = sum(left[token] * right[token] for token in shared)
    left_norm = sqrt(sum(value * value for value in left.values()))
    right_norm = sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


class F1KnowledgeBase:
    """Testing-friendly semantic retrieval without external infrastructure."""

    def __init__(self) -> None:
        self._documents: list[dict[str, Any]] = []

    async def add_content(self, content_type: str, text: str, metadata: dict[str, Any]) -> None:
        self._documents.append(
            {
                "content_type": content_type,
                "text": text,
                "metadata": metadata,
                "embedding": _tokenize(text),
            }
        )

    async def semantic_search(
        self,
        query: str,
        content_types: list[str] | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        query_embedding = _tokenize(query)
        matches: list[dict[str, Any]] = []
        for document in self._documents:
            if content_types and document["content_type"] not in content_types:
                continue
            score = _cosine_similarity(query_embedding, document["embedding"])
            if score <= 0:
                continue
            matches.append(
                {
                    "score": round(score, 4),
                    "text": document["text"],
                    "metadata": document["metadata"],
                    "content_type": document["content_type"],
                }
            )
        matches.sort(key=lambda item: item["score"], reverse=True)
        return matches[:top_k]

    async def get_context_for_agent(self, agent_type: str, driver: str | None = None, team: str | None = None) -> list[dict[str, Any]]:
        query_map = {
            "penalty": f"component usage penalties {driver or team or ''}",
            "dnf": f"mechanical issue reliability {driver or team or ''}",
            "strategy": f"pit window tire strategy {driver or team or ''}",
        }
        return await self.semantic_search(query_map.get(agent_type, ""), top_k=5)

