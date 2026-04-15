"""Dependency container for the FastAPI app."""

from __future__ import annotations

from functools import lru_cache

from backend.agents.dnf_risk import DNFRiskAgent
from backend.agents.orchestrator import OrchestratorAgent
from backend.agents.penalty import PenaltyAgent
from backend.agents.strategy import StrategyAgent
from backend.config import settings
from backend.data_sources.fia_documents_client import FIADocumentsClient
from backend.data_sources.fastf1_monitor import LiveRaceMonitor
from backend.db.vector_db import F1KnowledgeBase
from backend.services.component_service import ComponentTrackerService
from backend.services.fia_intelligence_service import FIAIntelligenceService
from backend.utils.event_bus import EventBus


@lru_cache
def get_component_service() -> ComponentTrackerService:
    return ComponentTrackerService(
        data_source=settings.default_data_source,
        circuit_rankings_path=settings.circuit_rankings_path,
        source_manifest_path=settings.source_manifest_path,
    )


@lru_cache
def get_knowledge_base() -> F1KnowledgeBase:
    return F1KnowledgeBase()


@lru_cache
def get_event_bus() -> EventBus:
    return EventBus()


@lru_cache
def get_live_race_monitor() -> LiveRaceMonitor:
    return LiveRaceMonitor(
        component_service=get_component_service(),
        enable_fastf1_live=settings.enable_fastf1_live,
        cache_dir=settings.fastf1_cache_dir,
        historical_cache_dir=settings.historical_cache_dir,
        enable_historical_runtime_generation=settings.enable_historical_runtime_generation,
    )


@lru_cache
def get_fia_documents_client() -> FIADocumentsClient:
    return FIADocumentsClient(
        base_url=settings.fia_documents_base_url,
        timeout_seconds=settings.fia_documents_timeout_seconds,
    )


@lru_cache
def get_fia_intelligence_service() -> FIAIntelligenceService:
    return FIAIntelligenceService(
        client=get_fia_documents_client(),
        component_service=get_component_service(),
    )


@lru_cache
def get_penalty_agent() -> PenaltyAgent:
    return PenaltyAgent(get_component_service(), get_knowledge_base())


@lru_cache
def get_dnf_agent() -> DNFRiskAgent:
    return DNFRiskAgent(get_component_service(), get_knowledge_base())


@lru_cache
def get_strategy_agent() -> StrategyAgent:
    return StrategyAgent(get_component_service(), get_knowledge_base())


@lru_cache
def get_orchestrator() -> OrchestratorAgent:
    return OrchestratorAgent(
        penalty_agent=get_penalty_agent(),
        dnf_agent=get_dnf_agent(),
        strategy_agent=get_strategy_agent(),
        live_race_monitor=get_live_race_monitor(),
    )
