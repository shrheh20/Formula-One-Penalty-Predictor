"""HTTP client for consuming the external FIA documents service."""

from __future__ import annotations

from typing import Any

import httpx


class FIADocumentsClient:
    """Reads normalized FIA parsing outputs from the dedicated FIA service."""

    def __init__(self, base_url: str, timeout_seconds: float = 6.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_health(self) -> dict[str, Any]:
        return self._get_json("/health")

    def get_predictor_feed(
        self,
        limit: int = 50,
        grand_prix: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if grand_prix:
            params["grand_prix"] = grand_prix
        if category:
            params["category"] = category
        return self._get_json("/predictor/feed", params=params)

    def get_alerts(
        self,
        limit: int = 25,
        grand_prix: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if grand_prix:
            params["grand_prix"] = grand_prix
        if category:
            params["category"] = category
        return self._get_json("/alerts/latest", params=params)

    def get_signals(
        self,
        limit: int = 25,
        grand_prix: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if grand_prix:
            params["grand_prix"] = grand_prix
        if category:
            params["category"] = category
        return self._get_json("/signals/latest", params=params)

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {"data": payload}
