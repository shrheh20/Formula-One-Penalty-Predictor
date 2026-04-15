"""Shared domain service built on top of the existing component tracker."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from component_tracker import F1ComponentTracker


class ComponentTrackerService:
    """Thin service wrapper so the new backend can reuse the current tracker."""

    def __init__(self, data_source: str, circuit_rankings_path: str, source_manifest_path: str):
        self.tracker = F1ComponentTracker()
        self.tracker.circuit_rankings_path = circuit_rankings_path
        self.tracker.source_manifest_path = source_manifest_path
        self.tracker.load_component_data(data_source)

    def get_health_snapshot(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "drivers_loaded": len(self.tracker.component_data),
            "data_source": self.tracker.data_source,
            "source_manifest": self.tracker.source_manifest_path,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_live_driver_summary(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for driver, components in self.tracker.component_data.items():
            metadata = self.tracker.driver_info.get(driver, {})
            summaries.append(
                {
                    "driver": driver,
                    "full_name": metadata.get("full_name", driver),
                    "team": metadata.get("team"),
                    "team_color": metadata.get("team_color"),
                    "car_number": metadata.get("car_number"),
                    "photo_url": metadata.get("photo_url"),
                    "team_badge_url": metadata.get("team_badge_url"),
                    "sidecar_url": metadata.get("sidecar_url"),
                    "components": {
                        comp_type: {
                            "count": data["count"],
                            "limit": data["limit"],
                            "status": (
                                "critical"
                                if data["count"] >= data["limit"]
                                else "warning"
                                if data["count"] == data["limit"] - 1
                                else "ok"
                            ),
                        }
                        for comp_type, data in components.items()
                        if data["limit"] is not None
                    },
                }
            )
        return summaries

    def get_predictions(self, race_number: int) -> list[dict[str, Any]]:
        return self.tracker.predict_penalties(race_number)

    def get_report(self, race_name: str, race_number: int) -> dict[str, Any]:
        return self.tracker.generate_report(race_name, race_number)

    def get_component_allocations(self) -> dict[str, Any]:
        return self.tracker.get_component_allocations()

    def get_source_manifest(self) -> dict[str, Any]:
        return self.tracker.get_source_manifest()
