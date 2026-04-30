"""Service layer that maps FIA document signals into predictor-ready context."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.data_sources.fia_documents_client import FIADocumentsClient
from backend.services.component_service import ComponentTrackerService


class FIAIntelligenceService:
    """Bridges parsed FIA document outputs into the predictor backend."""

    def __init__(self, client: FIADocumentsClient, component_service: ComponentTrackerService):
        self.client = client
        self.component_service = component_service

    def get_service_health(self) -> dict[str, Any]:
        try:
            payload = self.client.get_health()
            return {
                "available": True,
                "upstream_health": payload,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        except httpx.HTTPError as exc:
            return {
                "available": False,
                "error": str(exc),
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }

    def get_predictor_feed(
        self,
        race_number: int,
        limit: int,
        grand_prix: str | None = None,
    ) -> dict[str, Any]:
        predictions = self.component_service.get_predictions(race_number=race_number)

        try:
            fia_payload = self.client.get_predictor_feed(limit=limit, grand_prix=grand_prix)
            fia_signals = fia_payload.get("signals", [])
            fia_alerts = fia_payload.get("alerts", [])
            available = True
            error = None
        except httpx.HTTPError as exc:
            fia_signals = []
            fia_alerts = []
            available = False
            error = str(exc)

        drivers_with_open_steward_actions: dict[str, int] = defaultdict(int)
        for signal in fia_signals:
            if signal.get("signal_type") in {"investigation_opened", "steward_decision_issued"}:
                driver_name = signal.get("driver")
                if driver_name:
                    drivers_with_open_steward_actions[driver_name] += 1

        enriched_predictions: list[dict[str, Any]] = []
        for prediction in predictions:
            driver = prediction.get("driver")
            enriched_predictions.append(
                {
                    **prediction,
                    "steward_signal_count": drivers_with_open_steward_actions.get(driver, 0),
                    "has_live_steward_attention": drivers_with_open_steward_actions.get(driver, 0) > 0,
                }
            )

        return {
            "race_number": race_number,
            "grand_prix": grand_prix,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "upstream_available": available,
            "upstream_error": error,
            "predictions": enriched_predictions,
            "fia_signals": fia_signals,
            "fia_alerts": fia_alerts,
            "summary": {
                "predictions_count": len(enriched_predictions),
                "fia_signals_count": len(fia_signals),
                "fia_alerts_count": len(fia_alerts),
                "drivers_with_steward_attention": len(drivers_with_open_steward_actions),
            },
        }

    def get_recent_steward_alerts(self, limit: int = 10, grand_prix: str | None = None) -> dict[str, Any]:
        try:
            payload = self.client.get_alerts(limit=limit, grand_prix=grand_prix, category="stewards")
            alerts = payload.get("alerts", [])
            available = True
            error = None
        except httpx.HTTPError as exc:
            alerts = []
            available = False
            error = str(exc)

        return {
            "grand_prix": grand_prix,
            "upstream_available": available,
            "upstream_error": error,
            "alerts": alerts,
            "count": len(alerts),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_latest_document_insights(
        self,
        limit: int = 8,
        grand_prix: str | None = None,
    ) -> dict[str, Any]:
        try:
            payload = self.client.get_insights(limit=limit, grand_prix=grand_prix)
            available = True
            error = None
        except httpx.HTTPError as exc:
            payload = {
                "headline": "FIA document insights unavailable.",
                "summary": {
                    "documents_considered": 0,
                    "highlights_returned": 0,
                    "needs_review_count": 0,
                    "family_counts": {},
                },
                "highlights": [],
            }
            available = False
            error = str(exc)

        return {
            "grand_prix": grand_prix,
            "upstream_available": available,
            "upstream_error": error,
            **payload,
        }
