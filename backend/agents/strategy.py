"""Race strategy agent."""

from __future__ import annotations

from backend.agents.base import BaseAgent


class StrategyAgent(BaseAgent):
    """Provides first-pass strategic framing until live telemetry is connected."""

    async def analyze(self, race_state: dict) -> dict:
        drivers = race_state.get("drivers", [])
        highlighted = []
        for driver in drivers[:5]:
            pressure_components = [name for name, meta in driver.get("components", {}).items() if meta["status"] != "ok"]
            if not pressure_components:
                continue
            highlighted.append(
                {
                    "driver": driver["driver"],
                    "full_name": driver.get("full_name", driver["driver"]),
                    "team": driver.get("team"),
                    "strategy_flag": "protect-power-unit",
                    "recommendation": "Bias toward track position and reduced curb usage if race conditions allow.",
                    "pressure_components": pressure_components,
                }
            )
        return {
            "mode": race_state.get("mode", "snapshot"),
            "highlights": highlighted,
            "generated_from": "component-pressure heuristics until live tire and pace feeds are wired in",
        }
