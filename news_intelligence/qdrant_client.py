"""Qdrant wrapper supporting embedded local mode and remote mode."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from .config import news_settings


class NewsQdrantClient:
    def __init__(
        self,
        *,
        mode: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        path: str | None = None,
    ) -> None:
        self.mode = (mode or news_settings.news_qdrant_mode).strip().lower()
        self.timeout_seconds = timeout_seconds or news_settings.news_qdrant_timeout_seconds

        if self.mode == "local":
            root = Path(path or news_settings.news_qdrant_path)
            root.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(root))
            self.description = {"mode": "local", "path": str(root)}
        else:
            self.client = QdrantClient(
                url=(base_url or news_settings.news_qdrant_url).rstrip("/"),
                api_key=(api_key if api_key is not None else news_settings.news_qdrant_api_key).strip() or None,
                timeout=self.timeout_seconds,
            )
            self.description = {"mode": "remote", "url": (base_url or news_settings.news_qdrant_url).rstrip("/")}

    def health(self) -> dict[str, Any]:
        collections = self.client.get_collections().collections
        return {
            "available": True,
            **self.description,
            "collections": [{"name": collection.name} for collection in collections],
        }

    def ensure_collection(self, name: str, vector_size: int = 256, distance: str = "Cosine") -> dict[str, Any]:
        existing_names = {collection.name for collection in self.client.get_collections().collections}
        if name not in existing_names:
            self.client.create_collection(
                collection_name=name,
                vectors_config=qmodels.VectorParams(
                    size=vector_size,
                    distance=getattr(qmodels.Distance, distance.upper()),
                ),
            )
            status = "created"
        else:
            status = "exists"
        return {"ok": True, "status": status, "name": name, **self.description}

    def upsert_points(self, collection_name: str, points: list[dict]) -> dict[str, Any]:
        if not points:
            return {"ok": True, "status": "noop", "count": 0}
        self.client.upsert(
            collection_name=collection_name,
            points=[
                qmodels.PointStruct(
                    id=point["id"],
                    vector=point["vector"],
                    payload=point.get("payload") or {},
                )
                for point in points
            ],
            wait=True,
        )
        return {"ok": True, "status": "upserted", "count": len(points)}

    def delete_points(self, collection_name: str, point_ids: list[str]) -> dict[str, Any]:
        if not point_ids:
            return {"ok": True, "status": "noop", "count": 0}
        self.client.delete(
            collection_name=collection_name,
            points_selector=qmodels.PointIdsList(points=point_ids),
            wait=True,
        )
        return {"ok": True, "status": "deleted", "count": len(point_ids)}

