"""Tests for the new FastAPI backend slice."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
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

    def get_latest_document_insights(self, limit: int = 8, grand_prix: str | None = None) -> dict:
        return {
            "grand_prix": grand_prix,
            "headline": "1 steward action(s)",
            "summary": {
                "documents_considered": 3,
                "highlights_returned": 1,
                "critical_count": 1,
                "family_counts": {"steward_decision": 1},
            },
            "critical_highlights": [
                {
                    "title": "Decision - Car 81",
                    "category_label": "Stewards",
                    "importance": "high",
                    "what_happened": "Stewards published an official decision affecting the weekend.",
                    "dashboard_summary": "Stewards reviewed Car 81 and issued an official decision that could affect the competitive picture.",
                    "why_it_matters": "Why it matters: this may change official steward status, penalties, or investigations.",
                    "affected_entities": "Drivers: Oscar Piastri",
                    "drivers": ["Oscar Piastri"],
                    "teams": [],
                    "published_time": "2026-03-29T12:16:00+00:00",
                }
            ],
            "document_feed": [
                {
                    "title": "Decision - Car 81",
                    "category_label": "Stewards",
                    "importance": "high",
                    "what_happened": "Stewards published an official decision affecting the weekend.",
                    "dashboard_summary": "Stewards reviewed Car 81 and issued an official decision that could affect the competitive picture.",
                    "why_it_matters": "Why it matters: this may change official steward status, penalties, or investigations.",
                    "affected_entities": "Drivers: Oscar Piastri",
                    "drivers": ["Oscar Piastri"],
                    "teams": [],
                    "published_time": "2026-03-29T12:16:00+00:00",
                }
            ],
            "highlights": [
                {
                    "title": "Decision - Car 81",
                    "category_label": "Stewards",
                    "what_happened": "Stewards published an official decision affecting the weekend.",
                    "dashboard_summary": "Stewards reviewed Car 81 and issued an official decision that could affect the competitive picture.",
                }
            ],
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

    def test_fia_updates_endpoint(self) -> None:
        response = client.get("/api/v2/intelligence/fia-updates?limit=4")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["highlights_returned"], 1)
        self.assertEqual(payload["highlights"][0]["category_label"], "Stewards")

    def test_embedded_fia_documents_health_endpoint(self) -> None:
        response = client.get("/fia-documents/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")

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

    def test_reference_events_uses_disk_cache_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            monitor = LiveRaceMonitor(
                component_service=ComponentTrackerService(
                    data_source=str(PROJECT_ROOT / "fia_2026_component_snapshot.csv"),
                    circuit_rankings_path=str(PROJECT_ROOT / "strategic_circuit_rankings_2026.json"),
                    source_manifest_path=str(PROJECT_ROOT / "fia_2026_document_sources.json"),
                ),
                enable_fastf1_live=False,
                cache_dir=str(PROJECT_ROOT / ".cache" / "fastf1-test"),
                historical_cache_dir=temp_dir,
            )
            cache_path = Path(temp_dir) / "schedule_2026.json"
            expected = [{"event_name": "Japanese Grand Prix", "country": "Japan"}]
            cache_path.write_text(json.dumps(expected), encoding="utf-8")

            with patch("backend.data_sources.fastf1_monitor.fastf1.get_event_schedule") as mocked_schedule:
                payload = asyncio.run(monitor.get_event_schedule(2026))

            self.assertEqual(payload, expected)
            mocked_schedule.assert_not_called()

    def test_historical_weekend_uses_disk_cache_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            monitor = LiveRaceMonitor(
                component_service=ComponentTrackerService(
                    data_source=str(PROJECT_ROOT / "fia_2026_component_snapshot.csv"),
                    circuit_rankings_path=str(PROJECT_ROOT / "strategic_circuit_rankings_2026.json"),
                    source_manifest_path=str(PROJECT_ROOT / "fia_2026_document_sources.json"),
                ),
                enable_fastf1_live=False,
                cache_dir=str(PROJECT_ROOT / ".cache" / "fastf1-test"),
                historical_cache_dir=temp_dir,
            )
            cache_path = Path(temp_dir) / "weekend_2026_japanese-grand-prix.json"
            expected = {
                "event_name": "Japanese Grand Prix",
                "official_event_name": "Formula 1 Japanese Grand Prix 2026",
                "sessions": [{"session_key": "R", "session_name": "Race"}],
                "cache_status": "fresh",
            }
            cache_path.write_text(json.dumps(expected), encoding="utf-8")

            with patch("backend.data_sources.fastf1_monitor.fastf1.get_event") as mocked_event:
                payload = asyncio.run(monitor.get_historical_weekend(2026, "Japanese Grand Prix"))

            self.assertEqual(payload["event_name"], expected["event_name"])
            self.assertEqual(payload["sessions"], expected["sessions"])
            mocked_event.assert_not_called()

    def test_historical_weekend_requires_precomputed_dataset_when_runtime_generation_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            monitor = LiveRaceMonitor(
                component_service=ComponentTrackerService(
                    data_source=str(PROJECT_ROOT / "fia_2026_component_snapshot.csv"),
                    circuit_rankings_path=str(PROJECT_ROOT / "strategic_circuit_rankings_2026.json"),
                    source_manifest_path=str(PROJECT_ROOT / "fia_2026_document_sources.json"),
                ),
                enable_fastf1_live=False,
                cache_dir=str(PROJECT_ROOT / ".cache" / "fastf1-test"),
                historical_cache_dir=temp_dir,
                enable_historical_runtime_generation=False,
            )

            with self.assertRaises(RuntimeError):
                asyncio.run(monitor.get_historical_weekend(2026, "Japanese Grand Prix"))


if __name__ == "__main__":
    unittest.main()
