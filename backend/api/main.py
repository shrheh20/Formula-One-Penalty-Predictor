"""FastAPI entrypoint for the F1 Intelligence Platform."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.agents.orchestrator import OrchestratorAgent
from backend.agents.dnf_risk import DNFRiskAgent
from backend.api.dependencies import (
    get_component_service,
    get_dnf_agent,
    get_event_bus,
    get_fia_intelligence_service,
    get_live_race_monitor,
    get_orchestrator,
)
from backend.config import settings
from backend.data_sources.fastf1_monitor import LiveRaceMonitor
from backend.services.component_service import ComponentTrackerService
from backend.services.fia_intelligence_service import FIAIntelligenceService
from backend.utils.event_bus import EventBus

app = FastAPI(title=settings.app_name, version=settings.app_version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "static"
DASHBOARD_FILE = PROJECT_ROOT / "dashboard.html"
LIVE_PREVIEW_FILE = PROJECT_ROOT / "live_intelligence_preview.html"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def serve_dashboard() -> FileResponse:
    return FileResponse(DASHBOARD_FILE)


@app.get("/dashboard")
async def serve_dashboard_alias() -> FileResponse:
    return FileResponse(DASHBOARD_FILE)


@app.get("/dashboard.html")
async def serve_dashboard_file() -> FileResponse:
    return FileResponse(DASHBOARD_FILE)


@app.get("/live-preview")
async def serve_live_preview() -> FileResponse:
    return FileResponse(LIVE_PREVIEW_FILE)


@app.get("/api/v2/health")
async def health_check(
    component_service: Annotated[ComponentTrackerService, Depends(get_component_service)],
    live_race_monitor: Annotated[LiveRaceMonitor, Depends(get_live_race_monitor)] = None,
    fia_intelligence: Annotated[FIAIntelligenceService, Depends(get_fia_intelligence_service)] = None,
) -> dict:
    fia_health = await asyncio.to_thread(fia_intelligence.get_service_health)
    return {
        **component_service.get_health_snapshot(),
        "live_support": live_race_monitor.get_live_support_status(),
        "fia_documents_support": fia_health,
    }


@app.get("/api/v2/live/race-state")
async def get_live_race_state(
    race_number: int = Query(default=4, ge=1),
    year: int | None = Query(default=None),
    gp_name: str | None = Query(default=None),
    session_type: str = Query(default="R"),
    live_race_monitor: Annotated[LiveRaceMonitor, Depends(get_live_race_monitor)] = None,
    orchestrator: Annotated[OrchestratorAgent, Depends(get_orchestrator)] = None,
) -> dict:
    state = await live_race_monitor.get_current_state(year=year, gp_name=gp_name, session_type=session_type)
    strategy_analysis = await orchestrator.strategy_agent.analyze(race_state=state)
    return {
        "race_state": state,
        "strategy_insights": strategy_analysis,
        "race_number": race_number,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v2/live/reliability-alerts")
async def get_reliability_alerts(
    race_number: int = Query(default=4, ge=1),
    dnf_agent: Annotated[DNFRiskAgent, Depends(get_dnf_agent)] = None,
) -> dict:
    return await dnf_agent.analyze(race_number=race_number)


@app.get("/api/v2/reference/events")
async def get_reference_events(
    year: int = Query(..., ge=2018),
    live_race_monitor: Annotated[LiveRaceMonitor, Depends(get_live_race_monitor)] = None,
) -> dict:
    events = await live_race_monitor.get_event_schedule(year=year)
    return {"year": year, "events": events}


@app.get("/api/v2/history/weekend")
async def get_historical_weekend(
    gp_name: str = Query(...),
    year: int = Query(default=2026, ge=2026, le=2026),
    live_race_monitor: Annotated[LiveRaceMonitor, Depends(get_live_race_monitor)] = None,
) -> dict:
    return await live_race_monitor.get_historical_weekend(year=year, gp_name=gp_name)


@app.get("/api/v2/preview/{race_name}")
async def get_race_preview(
    race_name: str,
    race_number: int = Query(default=4, ge=1),
    orchestrator: Annotated[OrchestratorAgent, Depends(get_orchestrator)] = None,
) -> dict:
    return await orchestrator.generate_race_preview(race_name=race_name, race_number=race_number)


@app.get("/api/v2/component-allocations")
async def get_component_allocations(
    component_service: Annotated[ComponentTrackerService, Depends(get_component_service)],
) -> dict:
    return component_service.get_component_allocations()


@app.get("/api/v2/sources")
async def get_sources(
    component_service: Annotated[ComponentTrackerService, Depends(get_component_service)],
) -> dict:
    return {"success": True, "sources": component_service.get_source_manifest()}


@app.get("/api/health")
async def legacy_health_check(
    component_service: Annotated[ComponentTrackerService, Depends(get_component_service)],
) -> dict:
    return {
        "success": True,
        "status": "healthy",
        "drivers_loaded": len(component_service.tracker.component_data),
    }


@app.get("/api/predictions")
async def legacy_predictions(
    race: int = Query(default=4, ge=1),
    component_service: Annotated[ComponentTrackerService, Depends(get_component_service)] = None,
) -> dict:
    return {
        "success": True,
        "race_number": race,
        "predictions": component_service.get_predictions(race_number=race),
    }


@app.get("/api/drivers")
async def legacy_drivers(
    component_service: Annotated[ComponentTrackerService, Depends(get_component_service)],
) -> dict:
    return {
        "success": True,
        "drivers": component_service.get_live_driver_summary(),
    }


@app.get("/api/circuits")
async def legacy_circuits(
    component_service: Annotated[ComponentTrackerService, Depends(get_component_service)],
) -> dict:
    return {
        "success": True,
        "circuits": component_service.tracker.get_strategic_circuits(),
    }


@app.get("/api/v2/intelligence/steward-alerts")
async def get_steward_alerts(
    limit: int = Query(default=10, ge=1, le=100),
    grand_prix: str | None = Query(default=None),
    fia_intelligence: Annotated[FIAIntelligenceService, Depends(get_fia_intelligence_service)] = None,
) -> dict:
    return await asyncio.to_thread(
        fia_intelligence.get_recent_steward_alerts,
        limit,
        grand_prix,
    )


@app.get("/api/v2/intelligence/predictor-feed")
async def get_predictor_intelligence_feed(
    race_number: int = Query(default=4, ge=1),
    limit: int = Query(default=settings.fia_default_feed_limit, ge=1, le=500),
    grand_prix: str | None = Query(default=None),
    fia_intelligence: Annotated[FIAIntelligenceService, Depends(get_fia_intelligence_service)] = None,
) -> dict:
    return await asyncio.to_thread(
        fia_intelligence.get_predictor_feed,
        race_number,
        limit,
        grand_prix,
    )


@app.get("/api/v2/stream/commentary")
async def stream_live_commentary(
    limit: int = Query(default=5, ge=1, le=25),
    poll_interval: float = Query(default=settings.sse_poll_interval_seconds, ge=0.2, le=30.0),
    live_race_monitor: Annotated[LiveRaceMonitor, Depends(get_live_race_monitor)] = None,
) -> StreamingResponse:
    async def event_generator():
        for sequence in range(limit):
            insight = {
                "sequence": sequence + 1,
                "kind": "commentary",
                "payload": await live_race_monitor.get_current_state(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            yield f"data: {json.dumps(insight)}\n\n"
            await asyncio.sleep(poll_interval)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/v2/webhooks/fia-document")
async def fia_document_webhook(
    document: dict,
    background_tasks: BackgroundTasks,
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
) -> dict:
    background_tasks.add_task(event_bus.publish, "fia_document_published", document)
    return {"status": "processing", "document": document}
