"""FastF1-backed live session monitor with a safe local fallback."""

from __future__ import annotations

from asyncio import TimeoutError as AsyncTimeoutError, to_thread, wait_for
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import fastf1
    from fastf1 import exceptions as fastf1_exceptions
except ImportError:  # pragma: no cover - optional dependency
    fastf1 = None
    fastf1_exceptions = None

from backend.services.component_service import ComponentTrackerService


class LiveRaceMonitor:
    """Provides a normalized race-state view for the API layer."""

    SUPPORTED_HISTORY_YEAR = 2026
    HISTORICAL_EVENT_TIMEOUT_SECONDS = 15
    HISTORICAL_SESSION_TIMEOUT_SECONDS = 25

    SESSION_ALIASES = {
        "FP1": "FP1",
        "FP2": "FP2",
        "FP3": "FP3",
        "P1": "FP1",
        "P2": "FP2",
        "P3": "FP3",
        "PRACTICE 1": "FP1",
        "PRACTICE 2": "FP2",
        "PRACTICE 3": "FP3",
        "Q": "Q",
        "QUALI": "Q",
        "QUALIFYING": "Q",
        "S": "S",
        "SS": "SS",
        "SQ": "SQ",
        "SPRINT": "S",
        "SPRINT SHOOTOUT": "SS",
        "SPRINT QUALIFYING": "SQ",
        "R": "R",
        "RACE": "R",
    }

    def __init__(
        self,
        component_service: ComponentTrackerService,
        enable_fastf1_live: bool = False,
        cache_dir: str | None = None,
    ):
        self.component_service = component_service
        self.enable_fastf1_live = enable_fastf1_live and fastf1 is not None
        self.cache_dir = cache_dir
        self._cache_enabled = False
        self._cache_error: str | None = None
        self._configure_fastf1_cache()

    async def get_current_state(
        self,
        year: int | None = None,
        gp_name: str | None = None,
        session_type: str = "R",
    ) -> dict[str, Any]:
        normalized_session = self._normalize_session_type(session_type)
        if self.enable_fastf1_live and year and gp_name:
            try:
                return await self._load_fastf1_state(
                    year=year,
                    gp_name=gp_name,
                    session_type=normalized_session,
                )
            except Exception as exc:  # pragma: no cover - relies on optional runtime dependency
                fallback = self._build_snapshot_state()
                fallback["live_support"]["status"] = "fallback"
                fallback["live_support"]["error"] = str(exc)
                fallback["session"]["year"] = year
                fallback["session"]["grand_prix"] = gp_name
                fallback["session"]["session_type"] = normalized_session
                return fallback
        return self._build_snapshot_state(
            year=year,
            gp_name=gp_name,
            session_type=normalized_session,
        )

    async def get_event_schedule(self, year: int) -> list[dict[str, Any]]:
        if fastf1 is None:
            return []

        schedule = await to_thread(fastf1.get_event_schedule, year)
        events: list[dict[str, Any]] = []
        for _, row in schedule.iterrows():
            event_name = str(row.get("EventName") or "")
            official_event_name = str(row.get("OfficialEventName") or event_name)
            event_format = str(row.get("EventFormat") or "")
            searchable_text = f"{event_name} {official_event_name} {event_format}".lower()
            if "testing" in searchable_text:
                continue

            sessions = []
            for index in range(1, 6):
                session_name = row.get(f"Session{index}")
                if session_name and session_name == session_name:
                    sessions.append(str(session_name))

            events.append(
                {
                    "round_number": int(row["RoundNumber"]) if row.get("RoundNumber") == row.get("RoundNumber") else None,
                    "event_name": event_name,
                    "official_event_name": official_event_name,
                    "location": str(row.get("Location") or ""),
                    "country": str(row.get("Country") or ""),
                    "event_format": event_format,
                    "sessions": sessions,
                }
            )

        return events

    async def get_historical_weekend(self, year: int, gp_name: str) -> dict[str, Any]:
        if fastf1 is None:
            raise RuntimeError("FastF1 is not installed")
        if year != self.SUPPORTED_HISTORY_YEAR:
            raise ValueError(f"Historical explorer currently supports {self.SUPPORTED_HISTORY_YEAR} only")

        event = await wait_for(
            to_thread(fastf1.get_event, year, gp_name),
            timeout=self.HISTORICAL_EVENT_TIMEOUT_SECONDS,
        )
        available_sessions = self._extract_available_sessions(event)
        sessions: list[dict[str, Any]] = []

        for session_label in available_sessions:
            session = None
            try:
                session = await wait_for(
                    to_thread(fastf1.get_session, year, gp_name, session_label),
                    timeout=self.HISTORICAL_SESSION_TIMEOUT_SECONDS,
                )
                await wait_for(
                    to_thread(
                        partial(
                            session.load,
                            telemetry=False,
                            weather=True,
                            messages=False,
                        )
                    ),
                    timeout=self.HISTORICAL_SESSION_TIMEOUT_SECONDS,
                )
                sessions.append(self._summarize_historical_session(session, session_label))
            except AsyncTimeoutError:
                sessions.append(
                    self._build_partial_historical_session(
                        session,
                        session_label,
                        TimeoutError(
                            f"Timed out after {self.HISTORICAL_SESSION_TIMEOUT_SECONDS}s while loading this FastF1 session"
                        ),
                    )
                )
            except Exception as exc:
                sessions.append(
                    self._build_partial_historical_session(
                        session,
                        session_label,
                        exc,
                    )
                )

        return {
            "year": year,
            "event_name": str(getattr(event, "EventName", gp_name)),
            "official_event_name": str(getattr(event, "OfficialEventName", getattr(event, "EventName", gp_name))),
            "location": str(getattr(event, "Location", "")),
            "country": str(getattr(event, "Country", "")),
            "event_format": str(getattr(event, "EventFormat", "")),
            "sessions": sessions,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _load_fastf1_state(self, year: int, gp_name: str, session_type: str) -> dict[str, Any]:
        session = await to_thread(fastf1.get_session, year, gp_name, session_type)
        await to_thread(
            partial(
                session.load,
                telemetry=False,
                weather=True,
                messages=True,
            )
        )
        laps = session.laps.pick_accurate()
        results = getattr(session, "results", None)
        weather_data = getattr(session, "weather_data", None)
        weather = weather_data.tail(1).to_dict("records") if weather_data is not None and not weather_data.empty else []
        live_snapshot = self._extract_position_snapshot(laps)
        classification = self._extract_classification(results)
        message_count = self._extract_message_count(session)
        return {
            "mode": "fastf1",
            "session": {
                "year": year,
                "grand_prix": gp_name,
                "session_type": session_type,
                "session_name": getattr(session, "name", session_type),
            },
            "lap_count": int(laps["LapNumber"].max()) if not laps.empty else 0,
            "weather": weather[0] if weather else {},
            "messages_seen": message_count,
            "positions": live_snapshot,
            "drivers": live_snapshot,
            "classification": classification,
            "live_snapshot": live_snapshot,
            "classification_source": "session.results",
            "live_snapshot_source": "session.laps.pick_accurate()",
            "live_support": self.get_live_support_status(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _build_snapshot_state(
        self,
        year: int | None = None,
        gp_name: str | None = None,
        session_type: str = "R",
    ) -> dict[str, Any]:
        drivers = self.component_service.get_live_driver_summary()
        at_risk = sorted(
            drivers,
            key=lambda item: sum(1 for comp in item["components"].values() if comp["status"] != "ok"),
            reverse=True,
        )
        return {
            "mode": "snapshot",
            "session": {
                "year": year or datetime.now(timezone.utc).year,
                "grand_prix": gp_name,
                "session_type": session_type,
                "session_name": session_type,
            },
            "lap_count": None,
            "weather": {},
            "messages_seen": 0,
            "drivers": at_risk[:10],
            "positions": [],
            "classification": [],
            "live_snapshot": [],
            "classification_source": "not_available",
            "live_snapshot_source": "component_tracker_snapshot",
            "live_support": self.get_live_support_status(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_live_support_status(self) -> dict[str, Any]:
        return {
            "requested": self.enable_fastf1_live,
            "available": fastf1 is not None,
            "cache_dir": self.cache_dir,
            "cache_enabled": self._cache_enabled,
            "status": "enabled" if self.enable_fastf1_live else "disabled",
            "cache_error": self._cache_error,
        }

    def _configure_fastf1_cache(self) -> None:
        if fastf1 is None or not self.cache_dir:
            return
        try:
            cache_path = Path(self.cache_dir)
            cache_path.mkdir(parents=True, exist_ok=True)
            fastf1.Cache.enable_cache(str(cache_path))
            self._cache_enabled = True
        except Exception as exc:  # pragma: no cover - environment specific
            self._cache_enabled = False
            self._cache_error = str(exc)

    def _normalize_session_type(self, session_type: str) -> str:
        if not session_type:
            return "R"
        return self.SESSION_ALIASES.get(session_type.strip().upper(), session_type.strip().upper())

    def _extract_position_snapshot(self, laps: Any) -> list[dict[str, Any]]:
        if laps is None or laps.empty:
            return []
        latest = laps.sort_values(["LapNumber", "Time"]).groupby("Driver", dropna=True).tail(1).copy()
        max_lap = latest["LapNumber"].max() if "LapNumber" in latest else None
        if max_lap == max_lap:
            latest = latest[latest["LapNumber"] >= max_lap - 1]
        latest = latest.sort_values(["Position", "LapNumber", "Time"], na_position="last")
        latest = latest.drop_duplicates(subset=["Position"], keep="first")
        snapshot: list[dict[str, Any]] = []
        for _, row in latest.head(10).iterrows():
            snapshot.append(self._build_driver_snapshot(row))
        return snapshot

    def _build_driver_snapshot(self, row: Any) -> dict[str, Any]:
        driver_code = row.get("Driver")
        metadata = self.component_service.tracker.driver_info.get(driver_code, {})
        return {
            "driver": driver_code,
            "full_name": metadata.get("full_name", driver_code),
            "team": metadata.get("team"),
            "team_color": metadata.get("team_color"),
            "position": int(row["Position"]) if row.get("Position") == row.get("Position") else None,
            "lap": int(row["LapNumber"]) if row.get("LapNumber") == row.get("LapNumber") else None,
            "compound": row.get("Compound"),
            "stint": int(row["Stint"]) if row.get("Stint") == row.get("Stint") else None,
        }

    def _extract_classification(self, results: Any) -> list[dict[str, Any]]:
        if results is None or len(results) == 0:
            return []

        classification: list[dict[str, Any]] = []
        try:
            results_frame = results.sort_values("Position", na_position="last")
        except Exception:
            results_frame = results

        for _, row in results_frame.iterrows():
            position = row.get("Position")
            if position != position:
                continue
            classification.append(
                {
                    "position": int(position),
                    "driver": row.get("Abbreviation") or row.get("BroadcastName") or row.get("DriverNumber"),
                    "full_name": row.get("FullName") or row.get("BroadcastName") or row.get("Abbreviation"),
                    "team": row.get("TeamName"),
                    "team_color": row.get("TeamColor"),
                    "driver_number": row.get("DriverNumber"),
                    "status": row.get("Status"),
                    "grid_position": int(row["GridPosition"]) if row.get("GridPosition") == row.get("GridPosition") else None,
                    "q1": str(row.get("Q1")) if row.get("Q1") == row.get("Q1") else None,
                    "q2": str(row.get("Q2")) if row.get("Q2") == row.get("Q2") else None,
                    "q3": str(row.get("Q3")) if row.get("Q3") == row.get("Q3") else None,
                    "time": str(row.get("Time")) if row.get("Time") == row.get("Time") else None,
                    "points": float(row["Points"]) if row.get("Points") == row.get("Points") else None,
                }
            )
        return classification

    def _extract_message_count(self, session: Any) -> int:
        for attribute_name in ("messages", "race_control_messages", "session_status"):
            value = getattr(session, attribute_name, None)
            if value is None:
                continue
            try:
                return len(value)
            except TypeError:
                continue
        return 0

    def _extract_available_sessions(self, event: Any) -> list[str]:
        sessions: list[str] = []
        for index in range(1, 6):
            session_name = event.get(f"Session{index}") if hasattr(event, "get") else getattr(event, f"Session{index}", None)
            if session_name and session_name == session_name:
                sessions.append(str(session_name))
        return sessions

    def _safe_session_property(self, session: Any, name: str) -> Any:
        try:
            return getattr(session, name, None)
        except Exception as exc:
            if fastf1_exceptions is not None and isinstance(exc, fastf1_exceptions.DataNotLoadedError):
                return None
            raise

    def _summarize_historical_session(self, session: Any, session_label: str) -> dict[str, Any]:
        laps = self._safe_session_property(session, "laps")
        results = self._safe_session_property(session, "results")
        weather_data = self._safe_session_property(session, "weather_data")
        race_control_messages = self._safe_session_property(session, "race_control_messages")
        normalized_session_key = self._normalize_session_type(session_label)
        classification = self._build_historical_classification(laps, results)
        fastest_lap = self._extract_fastest_lap(laps)
        weather_summary = self._extract_weather_summary(weather_data)
        tyre_usage = self._extract_tyre_usage(laps)
        top_gainers = self._extract_position_delta(classification)
        timing_bars = self._build_timing_bars(
            classification,
            fastest_lap,
            normalized_session_key,
        )
        incidents = self._extract_incidents(
            race_control_messages=race_control_messages,
            classification=classification,
            session_key=normalized_session_key,
        )

        return {
            "session_key": normalized_session_key,
            "session_name": getattr(session, "name", session_label),
            "session_label": session_label,
            "lap_count": int(laps["LapNumber"].max()) if laps is not None and not laps.empty else 0,
            "weather": weather_summary,
            "classification": classification,
            "fastest_lap": fastest_lap,
            "tyre_usage": tyre_usage,
            "top_gainers": top_gainers[:5],
            "timing_bars": timing_bars,
            "incidents": incidents,
            "is_race_like": normalized_session_key in {"R", "S"},
            "is_qualifying_like": normalized_session_key in {"Q", "SQ", "SS"},
        }

    def _build_partial_historical_session(self, session: Any, session_label: str, exc: Exception) -> dict[str, Any]:
        normalized_key = self._normalize_session_type(session_label)
        return {
            "session_key": normalized_key,
            "session_name": getattr(session, "name", session_label) if session is not None else session_label,
            "session_label": session_label,
            "lap_count": 0,
            "weather": {},
            "classification": [],
            "fastest_lap": None,
            "tyre_usage": [],
            "top_gainers": [],
            "timing_bars": [],
            "incidents": {"dnf_count": 0, "incident_count": 0, "items": []},
            "is_race_like": normalized_key in {"R", "S"},
            "is_qualifying_like": normalized_key in {"Q", "SQ", "SS"},
            "load_error": str(exc),
        }

    def _build_historical_classification(self, laps: Any, results: Any) -> list[dict[str, Any]]:
        fastest_by_driver = self._extract_fastest_lap_by_driver(laps)
        if results is None or len(results) == 0:
            return fastest_by_driver

        classification = self._extract_classification(results)
        if not classification:
            return fastest_by_driver

        fastest_lookup = {item["driver"]: item for item in fastest_by_driver}
        merged: list[dict[str, Any]] = []
        for item in classification:
            fastest = fastest_lookup.get(item.get("driver"))
            merged.append(
                {
                    **item,
                    "fastest_lap_time": fastest.get("fastest_lap_time") if fastest else None,
                    "fastest_lap_compound": fastest.get("fastest_lap_compound") if fastest else None,
                    "fastest_lap_number": fastest.get("fastest_lap_number") if fastest else None,
                }
            )
        return merged[:10]

    def _extract_fastest_lap(self, laps: Any) -> dict[str, Any] | None:
        cleaned_laps = self._prepare_fastest_lap_laps(laps)
        if cleaned_laps is None or cleaned_laps.empty:
            return None
        try:
            fastest = cleaned_laps.pick_fastest()
        except Exception:
            return None
        if fastest is None or getattr(fastest, "empty", False):
            return None
        driver_code = fastest.get("Driver")
        metadata = self.component_service.tracker.driver_info.get(driver_code, {})
        lap_time = fastest.get("LapTime")
        return {
            "driver": driver_code,
            "full_name": metadata.get("full_name", driver_code),
            "team": metadata.get("team"),
            "lap_time": str(lap_time) if lap_time == lap_time else None,
            "compound": fastest.get("Compound"),
            "lap_number": int(fastest["LapNumber"]) if fastest.get("LapNumber") == fastest.get("LapNumber") else None,
        }

    def _extract_fastest_lap_by_driver(self, laps: Any) -> list[dict[str, Any]]:
        cleaned_laps = self._prepare_fastest_lap_laps(laps)
        if cleaned_laps is None or cleaned_laps.empty or "LapTime" not in cleaned_laps:
            return []

        valid = cleaned_laps.dropna(subset=["Driver", "LapTime"]).copy()
        if valid.empty:
            return []

        valid = valid.sort_values(["LapTime", "LapNumber"], na_position="last")
        fastest_rows = valid.groupby("Driver", dropna=True).head(1).copy()
        fastest_rows = fastest_rows.sort_values(["LapTime", "LapNumber"], na_position="last")

        leaderboard: list[dict[str, Any]] = []
        for index, (_, row) in enumerate(fastest_rows.iterrows(), start=1):
            driver_code = row.get("Driver")
            metadata = self.component_service.tracker.driver_info.get(driver_code, {})
            lap_time = row.get("LapTime")
            leaderboard.append(
                {
                    "position": index,
                    "driver": driver_code,
                    "full_name": metadata.get("full_name", driver_code),
                    "team": metadata.get("team"),
                    "team_color": metadata.get("team_color"),
                    "status": "Fastest lap ranking",
                    "grid_position": None,
                    "q1": None,
                    "q2": None,
                    "q3": None,
                    "time": str(lap_time) if lap_time == lap_time else None,
                    "points": None,
                    "fastest_lap_time": str(lap_time) if lap_time == lap_time else None,
                    "fastest_lap_compound": row.get("Compound"),
                    "fastest_lap_number": int(row["LapNumber"]) if row.get("LapNumber") == row.get("LapNumber") else None,
                }
            )
        return leaderboard

    def _prepare_fastest_lap_laps(self, laps: Any) -> Any:
        if laps is None or getattr(laps, "empty", True):
            return laps

        filtered = laps
        try:
            accurate = filtered.pick_accurate()
            if accurate is not None and not accurate.empty:
                filtered = accurate
        except Exception:
            pass

        try:
            quick = filtered.pick_quicklaps()
            if quick is not None and not quick.empty:
                filtered = quick
        except Exception:
            pass

        try:
            lap_seconds = filtered["LapTime"].dt.total_seconds()
            plausible = filtered[lap_seconds >= 45].copy()
            if not plausible.empty:
                filtered = plausible
        except Exception:
            pass

        return filtered

    def _extract_weather_summary(self, weather_data: Any) -> dict[str, Any]:
        if weather_data is None or weather_data.empty:
            return {}
        return {
            "air_temp_avg": round(float(weather_data["AirTemp"].mean()), 1) if "AirTemp" in weather_data else None,
            "track_temp_avg": round(float(weather_data["TrackTemp"].mean()), 1) if "TrackTemp" in weather_data else None,
            "humidity_avg": round(float(weather_data["Humidity"].mean()), 1) if "Humidity" in weather_data else None,
            "wind_speed_avg": round(float(weather_data["WindSpeed"].mean()), 1) if "WindSpeed" in weather_data else None,
            "rainfall_seen": bool(weather_data["Rainfall"].fillna(False).any()) if "Rainfall" in weather_data else False,
        }

    def _extract_tyre_usage(self, laps: Any) -> list[dict[str, Any]]:
        if laps is None or laps.empty or "Compound" not in laps:
            return []
        counts = (
            laps["Compound"]
            .dropna()
            .value_counts()
            .sort_values(ascending=False)
        )
        return [
            {"compound": str(compound), "laps": int(count)}
            for compound, count in counts.items()
        ]

    def _extract_position_delta(self, classification: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deltas = []
        for item in classification:
            if item.get("grid_position") is None or item.get("position") is None:
                continue
            delta = item["grid_position"] - item["position"]
            deltas.append({**item, "delta": delta})
        deltas.sort(key=lambda item: item["delta"], reverse=True)
        return deltas

    def _build_timing_bars(
        self,
        classification: list[dict[str, Any]],
        fastest_lap: dict[str, Any] | None,
        session_key: str,
    ) -> list[dict[str, Any]]:
        if not classification:
            return []

        def parse_time_value(item: dict[str, Any]) -> float | None:
            primary_keys = (
                ("fastest_lap_time",)
                if session_key in {"R", "S"}
                else ("q3", "q2", "q1", "fastest_lap_time", "time")
            )
            for key in primary_keys:
                raw = item.get(key)
                if not raw:
                    continue
                try:
                    return pd.to_timedelta(raw).total_seconds()
                except Exception:
                    continue
            if fastest_lap and item.get("driver") == fastest_lap.get("driver"):
                try:
                    return pd.to_timedelta(fastest_lap["lap_time"]).total_seconds()
                except Exception:
                    return None
            return None

        parsed = []
        for item in classification:
            seconds = parse_time_value(item)
            if seconds is None:
                continue
            parsed.append({**item, "seconds": seconds})

        if not parsed:
            return []

        baseline = min(item["seconds"] for item in parsed)
        bars = []
        for item in parsed:
            bars.append(
                {
                    "driver": item["driver"],
                    "full_name": item["full_name"],
                    "position": item["position"],
                    "gap_seconds": round(item["seconds"] - baseline, 3),
                }
            )
        return bars

    def _extract_incidents(
        self,
        race_control_messages: Any,
        classification: list[dict[str, Any]],
        session_key: str,
    ) -> dict[str, Any]:
        classification_by_driver: dict[str, dict[str, Any]] = {}
        for item in classification:
            for candidate in (
                item.get("driver"),
                item.get("full_name"),
            ):
                if candidate:
                    classification_by_driver[str(candidate).strip().lower()] = item

        dnf_items: list[dict[str, Any]] = []
        for item in classification:
            status = str(item.get("status") or "").strip()
            if not status:
                continue
            normalized = status.lower()
            if normalized in {"finished", "classified"} or normalized.startswith("+"):
                continue
            dnf_items.append(
                {
                    "type": "dnf",
                    "driver": item.get("full_name") or item.get("driver"),
                    "detail": status,
                    "subtype": "retirement",
                    "control_state": "classification",
                    "classification_outcome": status,
                    "raw_category": None,
                    "raw_flag": None,
                    "raw_scope": None,
                    "raw_status": None,
                    "raw_sector": None,
                    "raw_racing_number": item.get("driver"),
                    "raw_message": status,
                    "raw_driver": item.get("driver"),
                }
            )

        incident_items: list[dict[str, Any]] = []
        if race_control_messages is not None and not getattr(race_control_messages, "empty", True):
            subtype_patterns = {
                "crash": ("crash", "hit the barrier", "into the barrier", "into the wall"),
                "collision": ("collision", "contact"),
                "spin": ("spun", "spin"),
                "debris": ("debris",),
                "stopped": ("stopped", "stops"),
                "investigation": ("noted", "under investigation", "investigation"),
                "track_limits": ("track limits",),
                "restart": ("restart", "resumed"),
            }
            for _, row in race_control_messages.iterrows():
                message = str(row.get("Message") or row.get("message") or "").strip()
                if not message:
                    continue
                lowered = message.lower()
                incident_type = None
                subtype = None
                control_state = None

                if "virtual safety car" in lowered or "vsc" in lowered:
                    incident_type = "safety_car"
                    subtype = "virtual_safety_car"
                    control_state = "VSC"
                elif "safety car" in lowered:
                    incident_type = "safety_car"
                    subtype = "safety_car"
                    control_state = "SC"
                elif "red flag" in lowered:
                    incident_type = "flag"
                    subtype = "red_flag"
                    control_state = "Red flag"
                elif "double yellow" in lowered:
                    incident_type = "flag"
                    subtype = "double_yellow"
                    control_state = "Double yellow"
                elif "yellow" in lowered:
                    incident_type = "flag"
                    subtype = "yellow_flag"
                    control_state = "Yellow"

                for candidate_type, patterns in subtype_patterns.items():
                    if any(pattern in lowered for pattern in patterns):
                        subtype = candidate_type
                        if incident_type is None:
                            incident_type = "incident" if candidate_type not in {"investigation", "track_limits", "restart"} else candidate_type
                        break
                if incident_type is None:
                    continue

                driver_value = row.get("Driver") or row.get("driver")
                driver_name = self._resolve_incident_driver(driver_value, message, classification)
                classification_item = classification_by_driver.get(str(driver_name or "").strip().lower())
                classification_outcome = classification_item.get("status") if classification_item else None
                session_time = row.get("Time") or row.get("time")
                lap_value = row.get("LapNumber")
                if lap_value != lap_value:
                    lap_value = row.get("Lap")
                incident_items.append(
                    {
                        "type": incident_type,
                        "driver": driver_name,
                        "detail": message,
                        "lap": int(lap_value) if lap_value == lap_value else None,
                        "subtype": subtype or incident_type,
                        "control_state": control_state or self._infer_control_state(message),
                        "classification_outcome": classification_outcome,
                        "session_time": str(session_time) if session_time not in {None, ""} else None,
                        "raw_category": row.get("Category") or row.get("category"),
                        "raw_flag": row.get("Flag") or row.get("flag"),
                        "raw_scope": row.get("Scope") or row.get("scope"),
                        "raw_status": row.get("Status") or row.get("status"),
                        "raw_sector": row.get("Sector") or row.get("sector"),
                        "raw_racing_number": row.get("RacingNumber") or row.get("racing_number"),
                        "raw_message": message,
                        "raw_driver": driver_value,
                    }
                )

        all_items = dnf_items + incident_items
        if session_key not in {"R", "S"}:
            all_items = incident_items
        else:
            all_items = sorted(
                all_items,
                key=lambda item: (
                    item.get("lap") is None,
                    item.get("lap") if item.get("lap") is not None else 10**9,
                    str(item.get("session_time") or ""),
                ),
            )

        return {
            "dnf_count": len(dnf_items),
            "incident_count": len(incident_items),
            "items": all_items,
        }

    def _resolve_incident_driver(
        self,
        driver_value: Any,
        message: str,
        classification: list[dict[str, Any]],
    ) -> str | None:
        if driver_value:
            driver_text = str(driver_value).strip()
            for item in classification:
                if driver_text in {str(item.get("driver") or "").strip(), str(item.get("full_name") or "").strip()}:
                    return item.get("full_name") or item.get("driver")
            return driver_text

        lowered = message.lower()
        for item in classification:
            for candidate in (item.get("full_name"), item.get("driver")):
                if candidate and str(candidate).lower() in lowered:
                    return item.get("full_name") or item.get("driver")
        return None

    def _infer_control_state(self, message: str) -> str | None:
        lowered = message.lower()
        if "virtual safety car" in lowered or "vsc" in lowered:
            return "VSC"
        if "safety car" in lowered:
            return "SC"
        if "red flag" in lowered:
            return "Red flag"
        if "double yellow" in lowered:
            return "Double yellow"
        if "yellow" in lowered:
            return "Yellow"
        if "green flag" in lowered:
            return "Green"
        return None
