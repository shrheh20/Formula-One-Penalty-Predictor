"""Top-level orchestration across specialized agents."""

from __future__ import annotations

from backend.agents.dnf_risk import DNFRiskAgent
from backend.agents.penalty import PenaltyAgent
from backend.agents.strategy import StrategyAgent
from backend.data_sources.fastf1_monitor import LiveRaceMonitor


class OrchestratorAgent:
    """Composes specialized agents into preview and live outputs."""

    def __init__(
        self,
        penalty_agent: PenaltyAgent,
        dnf_agent: DNFRiskAgent,
        strategy_agent: StrategyAgent,
        live_race_monitor: LiveRaceMonitor,
    ) -> None:
        self.penalty_agent = penalty_agent
        self.dnf_agent = dnf_agent
        self.strategy_agent = strategy_agent
        self.live_race_monitor = live_race_monitor

    async def generate_race_preview(self, race_name: str, race_number: int) -> dict:
        penalties = await self.penalty_agent.analyze(race_number=race_number)
        dnf_risks = await self.dnf_agent.analyze(race_number=race_number)
        live_state = await self.live_race_monitor.get_current_state()
        strategy = await self.strategy_agent.analyze(race_state=live_state)
        return {
            "race_name": race_name,
            "race_number": race_number,
            "headline": f"{race_name}: penalty pressure shapes the weekend outlook.",
            "penalties": penalties,
            "dnf_risks": dnf_risks,
            "strategy": strategy,
        }

