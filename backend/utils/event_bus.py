"""Simple async event bus used by ingestion and orchestration workflows."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable


EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    """In-memory pub/sub for local development and tests."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers[event_type].append(handler)

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        handlers = self._subscribers.get(event_type, [])
        if not handlers:
            return
        await asyncio.gather(*(handler(data) for handler in handlers))

