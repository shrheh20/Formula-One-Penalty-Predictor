"""Build and persist the precomputed 2026 historical dataset for Past Races."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from backend.config import settings
from backend.data_sources.fastf1_monitor import LiveRaceMonitor
from backend.services.component_service import ComponentTrackerService


def build_monitor(output_dir: Path) -> LiveRaceMonitor:
    component_service = ComponentTrackerService(
        data_source=settings.default_data_source,
        circuit_rankings_path=settings.circuit_rankings_path,
        source_manifest_path=settings.source_manifest_path,
    )
    return LiveRaceMonitor(
        component_service=component_service,
        enable_fastf1_live=settings.enable_fastf1_live,
        cache_dir=settings.fastf1_cache_dir,
        historical_cache_dir=str(output_dir),
        enable_historical_runtime_generation=True,
    )


async def generate_dataset(output_dir: Path, year: int, force: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    monitor = build_monitor(output_dir)

    schedule_path = output_dir / f"schedule_{year}.json"
    if force:
        if schedule_path.exists():
            schedule_path.unlink()
        for existing_weekend in output_dir.glob(f"weekend_{year}_*.json"):
            existing_weekend.unlink()

    events = await monitor.get_event_schedule(year)
    if not events:
        raise RuntimeError(f"No schedule returned for {year}.")

    print(f"Fetched schedule for {year} with {len(events)} events")
    included_events = []

    for index, event in enumerate(events, start=1):
        event_name = event["event_name"]
        weekend_path = output_dir / f"weekend_{year}_{monitor._slugify(event_name)}.json"
        print(f"[{index}/{len(events)}] Building {event_name}...")
        payload = await monitor.get_historical_weekend(year=year, gp_name=event_name)
        if _payload_has_meaningful_history(payload):
            included_events.append(event)
            session_count = len(payload.get("sessions", []))
            print(f"  Saved {weekend_path.name} with {session_count} sessions")
        else:
            if weekend_path.exists():
                weekend_path.unlink()
            print(f"  Skipped {event_name}: no usable historical session data yet")

    schedule_path.write_text(json.dumps(included_events, indent=2), encoding="utf-8")
    print(f"Saved filtered schedule with {len(included_events)} historical events to {schedule_path}")


def _payload_has_meaningful_history(payload: dict) -> bool:
    for session in payload.get("sessions", []):
        if session.get("lap_count", 0):
            return True
        if session.get("classification"):
            return True
        if session.get("fastest_lap"):
            return True
        if session.get("tyre_usage"):
            return True
        if session.get("incidents", {}).get("items"):
            return True
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2026, help="Season year to precompute")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(settings.historical_cache_dir),
        help="Directory to write precomputed historical JSON files into",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild schedule and weekend files even if they already exist",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(generate_dataset(output_dir=args.output_dir, year=args.year, force=args.force))


if __name__ == "__main__":
    main()
