"""Base classes for agent workflows."""

from __future__ import annotations

from typing import Any

from backend.db.vector_db import F1KnowledgeBase
from backend.services.component_service import ComponentTrackerService


class BaseAgent:
    """Base class for deterministic, testable agent behavior."""

    def __init__(self, component_service: ComponentTrackerService, knowledge_base: F1KnowledgeBase):
        self.component_service = component_service
        self.knowledge_base = knowledge_base

    async def gather_context(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def analyze(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

