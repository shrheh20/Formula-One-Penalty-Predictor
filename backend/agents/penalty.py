"""Penalty intelligence agent."""

from __future__ import annotations

from backend.agents.base import BaseAgent


class PenaltyAgent(BaseAgent):
    """Turns component pressure into concise penalty insights."""

    async def analyze(self, race_number: int) -> dict:
        predictions = self.component_service.get_predictions(race_number)
        return {
            "race_number": race_number,
            "high_risk": [item for item in predictions if item["penalty_probability"] >= 70],
            "moderate_risk": [item for item in predictions if 40 <= item["penalty_probability"] < 70],
            "summary": f"{len(predictions)} drivers currently show at least one penalty trigger.",
        }

