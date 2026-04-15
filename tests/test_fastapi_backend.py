"""Tests for the new FastAPI backend slice."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.api.main import app  # noqa: E402
from backend.api.dependencies import get_fia_intelligence_service, get_live_race_monitor  # noqa: E402
from backend.data_sources.fastf1_monitor import LiveRaceMonitor  # noqa: E402
from backend.services.component_service import ComponentTrackerService  # noqa: E402


def _build_snapshot_monitor() -> LiveRaceMonitor:
    return LiveRaceMonitor(
        component_service=ComponentTrackerService(
            data_source=str(PROJECT_ROOT / "fia_2026_component_snapshot.csv"),
            circuit_rankings_path=str(PROJECT_ROOT / "strategic_circuit_rankings_2026.json"),
            source_manifest_path=str(PROJECT_ROOT / "fia_2026_document_sources.json"),
        ),
        enable_fastf1_live=False,
        cache_dir=str(PROJECT_ROOT / ".cache" / "fastf1-test"),
    )


app.dependency_overrides[get_live_race_monitor] = _build_snapshot_monitor


class _FakeFIAIntelligenceService:
    def get_service_health(self) -> dict:
        return {"available": True, "upstream_health": {"status": "ok"}}

    def get_recent_steward_alerts(self, limit: int = 10, grand_prix: str | None = None) -> dict:
        return {
            "grand_prix": grand_prix,
            "alerts": [{"title": "Steward update: Car 81", "priority": "high"}],
            "count": 1,
            "upstream_available": True,
            "upstream_error": None,
        }

    def get_predictor_feed(self, race_number: int, limit: int, grand_prix: str | None = None) -> dict:
        return {
            "race_number": race_number,
            "grand_prix": grand_prix,
            "predictions": [{"driver": "Lando Norris", "penalty_probability": 32}],
            "fia_signals": [{"signal_type": "investigation_opened"}],
            "fia_alerts": [{"title": "Steward update: Car 81"}],
            "summary": {"predictions_count": 1, "fia_signals_count": 1, "fia_alerts_count": 1},
            "upstream_available": True,
            "upstream_error": None,
        }


app.dependency_overrides[get_fia_intelligence_service] = _FakeFIAIntelligenceService
client = TestClient(app)


class FastAPIBackendTests(unittest.TestCase):
    def test_health_endpoint(self) -> None:
        response = client.get("/api/v2/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "healthy")
        self.assertGreater(payload["drivers_loaded"], 0)
        self.assertIn("live_support", payload)

    def test_preview_endpoint(self) -> None:
        response = client.get("/api/v2/preview/bahrain?race_number=4")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["race_name"], "bahrain")
        self.assertIn("penalties", payload)
        self.assertIn("dnf_risks", payload)
        self.assertIn("strategy", payload)

    def test_sse_commentary_endpoint(self) -> None:
        with client.stream("GET", "/api/v2/stream/commentary?limit=2&poll_interval=0.2") as response:
            chunks = list(response.iter_text())
        text = "".join(chunks)
        self.assertEqual(response.status_code, 200)
        self.assertIn("data:", text)
        self.assertIn('"kind": "commentary"', text)

    def test_steward_alerts_endpoint(self) -> None:
        response = client.get("/api/v2/intelligence/steward-alerts?grand_prix=Japanese%20Grand%20Prix")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["grand_prix"], "Japanese Grand Prix")

    def test_predictor_feed_endpoint(self) -> None:
        response = client.get("/api/v2/intelligence/predictor-feed?race_number=5&limit=10")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["race_number"], 5)
        self.assertEqual(len(payload["predictions"]), 1)
        self.assertEqual(payload["summary"]["fia_alerts_count"], 1)

    def test_legacy_health_endpoint(self) -> None:
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["status"], "healthy")

    def test_legacy_predictions_endpoint(self) -> None:
        response = client.get("/api/predictions?race=4")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertIn("predictions", payload)

    def test_live_race_state_snapshot_metadata(self) -> None:
        response = client.get("/api/v2/live/race-state?year=2026&gp_name=Monaco&session_type=quali")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("race_state", payload)
        race_state = payload["race_state"]
        self.assertEqual(race_state["session"]["year"], 2026)
        self.assertEqual(race_state["session"]["grand_prix"], "Monaco")
        self.assertEqual(race_state["session"]["session_type"], "Q")
        self.assertIn("live_support", race_state)

    def test_reference_events_filters_testing_entries(self) -> None:
        schedule = pd.DataFrame(
            [
                {
                    "RoundNumber": 0,
                    "EventName": "Pre-Season Testing",
                    "OfficialEventName": "Formula 1 Pre-Season Testing 2026",
                    "Location": "Sakhir",
                    "Country": "Bahrain",
                    "EventFormat": "testing",
                    "Session1": "Day 1",
                },
                {
                    "RoundNumber": 1,
                    "EventName": "Australia",
                    "OfficialEventName": "Formula 1 Australian Grand Prix 2026",
                    "Location": "Melbourne",
                    "Country": "Australia",
                    "EventFormat": "conventional",
                    "Session1": "Practice 1",
                    "Session2": "Practice 2",
                    "Session3": "Practice 3",
                    "Session4": "Qualifying",
                    "Session5": "Race",
                },
            ]
        )

        with patch("backend.data_sources.fastf1_monitor.fastf1.get_event_schedule", return_value=schedule):
            response = client.get("/api/v2/reference/events?year=2026")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["events"][0]["event_name"], "Australia")

    def test_session_normalization_supports_full_fastf1_names(self) -> None:
        monitor = _build_snapshot_monitor()
        self.assertEqual(monitor._normalize_session_type("Practice 1"), "FP1")
        self.assertEqual(monitor._normalize_session_type("Practice 2"), "FP2")
        self.assertEqual(monitor._normalize_session_type("Practice 3"), "FP3")
        self.assertEqual(monitor._normalize_session_type("Sprint Shootout"), "SS")
        self.assertEqual(monitor._normalize_session_type("Sprint Qualifying"), "SQ")

    def test_extract_incidents_includes_context_fields_and_crash_detection(self) -> None:
        monitor = _build_snapshot_monitor()
        classification = [
            {"driver": "BEA", "full_name": "Oliver Bearman", "status": "Accident"},
            {"driver": "VER", "full_name": "Max Verstappen", "status": "Finished"},
        ]
        race_control_messages = pd.DataFrame(
            [
                {
                    "Message": "Crash for Bearman at Turn 1. Yellow flags.",
                    "LapNumber": 12,
                    "Time": "00:18:22",
                    "Driver": None,
                    "Category": "Flag",
                    "Flag": "YELLOW",
                    "Scope": "Track",
                    "Status": "Deployed",
                    "Sector": 1,
                    "RacingNumber": "87",
                }
            ]
        )

        payload = monitor._extract_incidents(
            race_control_messages=race_control_messages,
            classification=classification,
            session_key="R",
        )

        self.assertEqual(payload["dnf_count"], 1)
        self.assertEqual(payload["incident_count"], 1)
        dnf_item = next(item for item in payload["items"] if item["type"] == "dnf")
        crash_item = next(item for item in payload["items"] if item["subtype"] == "crash")
        self.assertEqual(dnf_item["classification_outcome"], "Accident")
        self.assertEqual(crash_item["driver"], "Oliver Bearman")
        self.assertEqual(crash_item["subtype"], "crash")
        self.assertEqual(crash_item["control_state"], "Yellow")
        self.assertEqual(crash_item["classification_outcome"], "Accident")
        self.assertEqual(crash_item["lap"], 12)
        self.assertEqual(crash_item["raw_category"], "Flag")
        self.assertEqual(crash_item["raw_flag"], "YELLOW")
        self.assertEqual(crash_item["raw_scope"], "Track")


if __name__ == "__main__":
    unittest.main()
