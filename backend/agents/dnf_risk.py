"""Reliability monitoring agent."""

from __future__ import annotations

from backend.agents.base import BaseAgent


class DNFRiskAgent(BaseAgent):
    """Approximates DNF risk from stressed component inventories."""

    async def analyze(self, race_number: int) -> dict:
        predictions = self.component_service.get_predictions(race_number)
        alerts = []
        for item in predictions:
            stressed_components = [comp for comp in item["components"].values() if comp["status"] != "ok"]
            if not stressed_components:
                continue
            risk_score = min(95.0, round(item["penalty_probability"] * 0.75 + len(stressed_components) * 5, 1))
            alerts.append(
                {
                    "driver": item["driver"],
                    "full_name": item.get("full_name", item["driver"]),
                    "team": item["team"],
                    "risk_score": risk_score,
                    "risk_level": "critical" if risk_score >= 75 else "warning",
                    "failure_modes": [comp for comp, meta in item["components"].items() if meta["status"] != "ok"],
                    "reasoning": item["reasons"],
                }
            )
        alerts.sort(key=lambda item: item["risk_score"], reverse=True)
        return {"race_number": race_number, "alerts": alerts[:10]}
