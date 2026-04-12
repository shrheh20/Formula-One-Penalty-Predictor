"""
F1 Component Tracker - FIA-backed 2026 data model
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pandas as pd


class F1ComponentTracker:
    """
    Tracks FIA power unit component usage using the published 2026 official documents.

    The current repo snapshot uses the completed 2026 rounds published as of
    April 11, 2026:
    - Australia
    - China
    - Japan

    The local CSV is a season-to-date snapshot reconstructed from FIA Technical
    Delegate reports rather than a hand-entered sample.
    """

    DEFAULT_DATA_SOURCE = "fia_2026_component_snapshot.csv"
    DEFAULT_SOURCE_MANIFEST = "fia_2026_document_sources.json"
    DEFAULT_CIRCUIT_RANKINGS = "strategic_circuit_rankings_2026.json"

    # 2026 effective limits used by this MVP.
    # These reflect the currently published FIA Technical Delegate reports and
    # the 2026 PU sporting framework used by the race documents.
    COMPONENT_LIMITS = {
        "ICE": 4,
        "TC": 4,
        "EXH": 4,
        "MGU-K": 3,
        "ES": 3,
        "PU-CE": 3,
        "PU-ANC": 6,
    }

    COMPONENT_RISK = {
        "limit_reached": 95,
        "final_unit": 55,
    }

    DRIVER_METADATA = {
        "PIA": {"full_name": "Oscar Piastri", "team_color": "#FF8000"},
        "NOR": {"full_name": "Lando Norris", "team_color": "#FF8000"},
        "RUS": {"full_name": "George Russell", "team_color": "#00D2BE"},
        "ANT": {"full_name": "Kimi Antonelli", "team_color": "#00D2BE"},
        "VER": {"full_name": "Max Verstappen", "team_color": "#1E41FF"},
        "HAD": {"full_name": "Isack Hadjar", "team_color": "#1E41FF"},
        "LEC": {"full_name": "Charles Leclerc", "team_color": "#DC0000"},
        "HAM": {"full_name": "Lewis Hamilton", "team_color": "#DC0000"},
        "ALB": {"full_name": "Alex Albon", "team_color": "#1868DB"},
        "SAI": {"full_name": "Carlos Sainz", "team_color": "#1868DB"},
        "LIN": {"full_name": "Arvid Lindblad", "team_color": "#2B5CFF"},
        "LAW": {"full_name": "Liam Lawson", "team_color": "#2B5CFF"},
        "STR": {"full_name": "Lance Stroll", "team_color": "#006F62"},
        "ALO": {"full_name": "Fernando Alonso", "team_color": "#006F62"},
        "OCO": {"full_name": "Esteban Ocon", "team_color": "#9FA3A8"},
        "BEA": {"full_name": "Oliver Bearman", "team_color": "#9FA3A8"},
        "HUL": {"full_name": "Nico Hulkenberg", "team_color": "#C1121F"},
        "BOR": {"full_name": "Gabriel Bortoleto", "team_color": "#C1121F"},
        "GAS": {"full_name": "Pierre Gasly", "team_color": "#FF5AAF"},
        "COL": {"full_name": "Franco Colapinto", "team_color": "#FF5AAF"},
        "PER": {"full_name": "Sergio Perez", "team_color": "#0F2D52"},
        "BOT": {"full_name": "Valtteri Bottas", "team_color": "#0F2D52"},
    }

    TEAM_BADGE_LABELS = {
        "McLaren": "MCL",
        "Mercedes": "MER",
        "Red Bull": "RBR",
        "Ferrari": "FER",
        "Williams": "WIL",
        "Racing Bulls": "RB",
        "Aston Martin": "AMR",
        "Haas": "HAA",
        "Sauber": "SAU",
        "Alpine": "ALP",
        "Cadillac": "CAD",
    }

    TEAM_BADGE_SLUGS = {
        "McLaren Mercedes": "mclaren",
        "Mercedes": "mercedes",
        "Red Bull Racing RB Ford": "red-bull-racing",
        "Ferrari": "ferrari",
        "Atlassian Williams Mercedes": "williams",
        "Racing Bulls RB Ford": "racing-bulls",
        "Aston Martin Aramco Honda": "aston-martin",
        "Haas Ferrari": "haas",
        "Audi": "audi",
        "Alpine Mercedes": "alpine",
        "Cadillac Ferrari": "cadillac",
    }

    STATIC_ROOT = Path("static")
    DRIVER_PHOTO_DIR = STATIC_ROOT / "driver-photos"
    TEAM_BADGE_DIR = STATIC_ROOT / "team-badges"
    SIDECAR_DIR = STATIC_ROOT / "sidecar"
    DRIVER_PHOTO_EXTENSIONS = (".webp", ".png", ".jpg", ".jpeg", ".svg")
    TEAM_BADGE_EXTENSIONS = (".png", ".webp", ".svg")
    SIDECAR_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg")
    COMPONENT_DISPLAY = {
        "ICE": "Internal Combustion Engine",
        "TC": "Turbocharger",
        "MGU-K": "Motor Generator Unit-Kinetic",
        "ES": "Energy Store",
        "PU-CE": "Control Electronics",
        "PU-ANC": "Ancillaries",
        "EXH": "Exhaust",
    }

    def __init__(self):
        self.component_data = {}
        self.driver_info = {}
        self.drivers = []
        self.current_season = datetime.now().year
        self.data_source = self.DEFAULT_DATA_SOURCE
        self.source_manifest_path = self.DEFAULT_SOURCE_MANIFEST
        self.circuit_rankings_path = self.DEFAULT_CIRCUIT_RANKINGS

    def scrape_fia_documents(self, race_number=None):
        """
        Return the local FIA source manifest for the published 2026 rounds.

        The manifest contains the official FIA event pages plus the exact
        Technical Delegate reports used to build the current season snapshot.
        """
        return self.get_source_manifest()

    def load_component_data(self, csv_path):
        """
        Load component usage from CSV.

        Supported formats:
        1. Snapshot format:
           Driver,Car_Number,Team,Component_Type,Count,Limit,...
        2. Legacy event-log format:
           Driver,Team,Race,Component_Type,Component_Number,Status
        """
        df = pd.read_csv(csv_path)
        self.data_source = csv_path

        self.component_data = {}
        self.driver_info = {}

        if "Count" in df.columns:
            return self._load_snapshot_data(df)

        return self._load_legacy_event_data(df)

    def _load_snapshot_data(self, df):
        """Load a season snapshot reconstructed from FIA documents."""
        for driver in df["Driver"].unique():
            driver_df = df[df["Driver"] == driver].copy()
            first_row = driver_df.iloc[0]
            team_name = first_row["Team"] if "Team" in driver_df.columns else None
            team_color = self.DRIVER_METADATA.get(driver, {}).get("team_color", "#374151")

            self.driver_info[driver] = {
                "driver": driver,
                "full_name": self.DRIVER_METADATA.get(driver, {}).get("full_name", driver),
                "car_number": int(first_row["Car_Number"]) if "Car_Number" in driver_df.columns else None,
                "team": team_name,
                "team_color": team_color,
                "team_badge_url": self._get_team_badge_url(team_name),
                "sidecar_url": self._get_sidecar_url(team_name),
                "photo_url": self._get_driver_photo_url(driver),
                "as_of_race": first_row["As_Of_Race"] if "As_Of_Race" in driver_df.columns else None,
                "as_of_date": first_row["As_Of_Date"] if "As_Of_Date" in driver_df.columns else None,
            }

            self.component_data[driver] = self._process_snapshot_components(driver_df)

        self.drivers = sorted(self.component_data.keys())
        return self.component_data

    def _process_snapshot_components(self, driver_df):
        """Process a snapshot CSV into the internal component structure."""
        components = {}

        for comp_type, default_limit in self.COMPONENT_LIMITS.items():
            comp_df = driver_df[driver_df["Component_Type"] == comp_type]

            if comp_df.empty:
                components[comp_type] = {
                    "count": 0,
                    "limit": default_limit,
                    "components": [],
                }
                continue

            record = comp_df.iloc[0].to_dict()
            limit = int(record["Limit"]) if "Limit" in record and not pd.isna(record["Limit"]) else default_limit

            components[comp_type] = {
                "count": int(record["Count"]),
                "limit": limit,
                "components": [record],
            }

        return components

    def _load_legacy_event_data(self, df):
        """Load the original event-log style CSV."""
        for driver in df["Driver"].unique():
            driver_df = df[df["Driver"] == driver].copy()
            first_row = driver_df.iloc[0]
            team_name = first_row["Team"] if "Team" in driver_df.columns else None
            team_color = self.DRIVER_METADATA.get(driver, {}).get("team_color", "#374151")

            self.driver_info[driver] = {
                "driver": driver,
                "full_name": self.DRIVER_METADATA.get(driver, {}).get("full_name", driver),
                "car_number": None,
                "team": team_name,
                "team_color": team_color,
                "team_badge_url": self._get_team_badge_url(team_name),
                "sidecar_url": self._get_sidecar_url(team_name),
                "photo_url": self._get_driver_photo_url(driver),
                "as_of_race": None,
                "as_of_date": None,
            }

            self.component_data[driver] = self._process_legacy_components(driver_df)

        self.drivers = sorted(self.component_data.keys())
        return self.component_data

    def _process_legacy_components(self, driver_df):
        """Process the original row-per-component-change data for one driver."""
        components = {}

        for comp_type, limit in self.COMPONENT_LIMITS.items():
            comp_df = driver_df[driver_df["Component_Type"] == comp_type]
            components[comp_type] = {
                "count": len(comp_df),
                "limit": limit,
                "components": comp_df.to_dict("records"),
            }

        return components

    def get_source_manifest(self):
        """Load the local FIA source manifest."""
        manifest_path = Path(self.source_manifest_path)

        if not manifest_path.exists():
            return {}

        with manifest_path.open() as manifest_file:
            return json.load(manifest_file)

    def get_component_allocations(self):
        """Return the current tracked 2026 component allocations for the dashboard."""
        allocations = [
            {
                "component": "ICE",
                "display_name": self.COMPONENT_DISPLAY["ICE"],
                "allocation": self.COMPONENT_LIMITS["ICE"],
                "article_reference": "3 (+1 bonus) for 2026",
                "note": "The F1 article explains 2026 as three core allocations plus one bonus allocation.",
            },
            {
                "component": "TC",
                "display_name": self.COMPONENT_DISPLAY["TC"],
                "allocation": self.COMPONENT_LIMITS["TC"],
                "article_reference": "3 (+1 bonus) for 2026",
                "note": "Turbochargers follow the same 2026 three-plus-bonus structure.",
            },
            {
                "component": "MGU-K",
                "display_name": self.COMPONENT_DISPLAY["MGU-K"],
                "allocation": self.COMPONENT_LIMITS["MGU-K"],
                "article_reference": "2 (+1 bonus) for 2026",
                "note": "The tracker surfaces the effective on-car limit of three units in 2026.",
            },
            {
                "component": "ES",
                "display_name": self.COMPONENT_DISPLAY["ES"],
                "allocation": self.COMPONENT_LIMITS["ES"],
                "article_reference": "2 (+1 bonus) for 2026",
                "note": "Energy Store uses the same effective three-unit ceiling this season.",
            },
            {
                "component": "PU-CE",
                "display_name": self.COMPONENT_DISPLAY["PU-CE"],
                "allocation": self.COMPONENT_LIMITS["PU-CE"],
                "article_reference": "CE: 2 (+1 bonus) for 2026",
                "note": "F1 labels this component CE; FIA delegate reports label it PU-CE.",
            },
            {
                "component": "EXH",
                "display_name": self.COMPONENT_DISPLAY["EXH"],
                "allocation": self.COMPONENT_LIMITS["EXH"],
                "article_reference": "3 (+1 bonus) for 2026",
                "note": "Exhaust follows the same effective four-unit ceiling in 2026.",
            },
            {
                "component": "PU-ANC",
                "display_name": self.COMPONENT_DISPLAY["PU-ANC"],
                "allocation": self.COMPONENT_LIMITS["PU-ANC"],
                "article_reference": "Not listed in the F1 article table",
                "note": "This tracker includes FIA delegate-report ancillaries because they appear in the 2026 technical documents used for the live dataset.",
            },
        ]

        return {
            "season": 2026,
            "title": "2026 component allocations",
            "reference_title": "The beginner’s guide to F1 power unit penalties",
            "reference_url": "https://www.formula1.com/en/latest/article/the-beginners-guide-to-formula-1-engine-and-gearbox-penalties.2TSy7BFgEvdNLojGLWS3F1",
            "summary": "The official F1 explainer describes 2026 allocations as the standard component counts plus a one-season bonus allocation. This tracker shows the effective totals used in the live FIA-backed dataset.",
            "allocations": allocations,
        }

    def _resolve_static_asset(self, directory, basename, extensions, fallback=None):
        """Resolve a static asset by basename and supported extensions."""
        if basename:
            for extension in extensions:
                candidate = directory / f"{basename}{extension}"
                if candidate.exists():
                    return f"/{candidate.as_posix()}"

        if fallback:
            fallback_path = directory / fallback
            if fallback_path.exists():
                return f"/{fallback_path.as_posix()}"

        return None

    def _get_driver_photo_url(self, driver_code):
        """Resolve a driver photo from /static/driver-photos by driver code."""
        return self._resolve_static_asset(
            self.DRIVER_PHOTO_DIR,
            driver_code.lower(),
            self.DRIVER_PHOTO_EXTENSIONS,
            fallback="default-driver.svg",
        )

    def _get_team_badge_url(self, team_name):
        """Resolve a team badge from /static/team-badges by team slug."""
        team_slug = self.TEAM_BADGE_SLUGS.get(team_name)
        return self._resolve_static_asset(
            self.TEAM_BADGE_DIR,
            team_slug,
            self.TEAM_BADGE_EXTENSIONS,
            fallback="default-team.svg",
        )

    def _get_sidecar_url(self, team_name):
        """Resolve a side-view car image from /static/sidecar by team slug."""
        team_slug = self.TEAM_BADGE_SLUGS.get(team_name)
        if team_slug == "red-bull-racing":
            team_slug = "redbull"
        elif team_slug == "racing-bulls":
            team_slug = "racingbulls"
        elif team_slug == "aston-martin":
            team_slug = "astonmartin"

        return self._resolve_static_asset(
            self.SIDECAR_DIR,
            team_slug,
            self.SIDECAR_EXTENSIONS,
        )

    def predict_penalties(self, upcoming_race_number):
        """
        Predict grid penalty probability for each driver using 2026 counts.

        The predictor is intentionally simple:
        - At allocation limit: 95% risk
        - On final permitted unit: 55% risk
        """
        predictions = []

        for driver, components in self.component_data.items():
            component_risks = []
            reasons = []
            at_risk_components = []

            for comp_type, data in components.items():
                limit = data["limit"]
                count = data["count"]

                if limit is None:
                    continue

                if count >= limit:
                    component_risks.append(self.COMPONENT_RISK["limit_reached"])
                    reasons.append(f"{comp_type} limit reached ({count}/{limit})")
                    at_risk_components.append(
                        {
                            "component": comp_type,
                            "count": count,
                            "limit": limit,
                            "status": "critical",
                        }
                    )
                elif count == limit - 1:
                    component_risks.append(self.COMPONENT_RISK["final_unit"])
                    reasons.append(f"{comp_type} on final unit ({count}/{limit})")
                    at_risk_components.append(
                        {
                            "component": comp_type,
                            "count": count,
                            "limit": limit,
                            "status": "warning",
                        }
                    )

            if component_risks:
                penalty_probability = self._combine_component_risks(component_risks)
                driver_meta = self.driver_info.get(driver, {})
                penalty_scenarios = self._build_penalty_scenarios(at_risk_components)

                predictions.append(
                    {
                        "driver": driver,
                        "full_name": driver_meta.get("full_name", driver),
                        "team": driver_meta.get("team"),
                        "team_color": driver_meta.get("team_color"),
                        "team_badge_url": driver_meta.get("team_badge_url"),
                        "sidecar_url": driver_meta.get("sidecar_url"),
                        "photo_url": driver_meta.get("photo_url"),
                        "car_number": driver_meta.get("car_number"),
                        "penalty_probability": penalty_probability,
                        "reasons": reasons,
                        "penalty_summary": penalty_scenarios["summary"],
                        "penalty_prediction": penalty_scenarios["prediction"],
                        "penalty_cases": penalty_scenarios["cases"],
                        "components": {
                            comp_type: {
                                "count": data["count"],
                                "limit": data["limit"],
                                "status": "critical" if data["count"] >= data["limit"] else
                                "warning" if data["count"] == data["limit"] - 1 else "ok",
                            }
                            for comp_type, data in components.items()
                            if data["limit"] is not None
                        },
                        "recommendation": self._get_recommendation(penalty_probability),
                    }
                )

        return sorted(predictions, key=lambda x: x["penalty_probability"], reverse=True)

    def _combine_component_risks(self, component_risks):
        """Combine component warnings into a single driver-level probability."""
        no_penalty_probability = 1.0

        for risk in component_risks:
            no_penalty_probability *= (1 - risk / 100)

        return round((1 - no_penalty_probability) * 100, 1)

    def _get_recommendation(self, probability):
        """Generate recommendation based on penalty probability."""
        if probability >= 90:
            return "IMMINENT - Penalty expected this race or next"
        if probability >= 70:
            return "HIGH - Strategic penalty likely within 2 races"
        if probability >= 40:
            return "MODERATE - Monitor closely"
        return "LOW - No immediate concern"

    def _build_penalty_scenarios(self, at_risk_components):
        """Summarize what the next power unit changes could mean on the grid."""
        component_count = len(at_risk_components)

        if component_count == 0:
            return {"summary": "No immediate penalty trigger", "prediction": "No immediate penalty trigger.", "cases": []}

        component_labels = ", ".join(item["component"] for item in at_risk_components[:3])

        if component_count == 1:
            summary = "One more vulnerable element would likely mean a 10-place grid drop."
            prediction = "10-place grid drop"
        elif component_count == 2:
            summary = "Two vulnerable elements in the same weekend would likely add up to a 15-place grid drop."
            prediction = "15-place cumulative grid drop"
        else:
            summary = "Three or more vulnerable elements in one weekend would likely push this car to a back-of-grid start."
            prediction = "Back-of-grid start"

        cases = []
        for item in at_risk_components:
            if item["status"] == "critical":
                trigger = f"Another {item['component']} is introduced"
            else:
                trigger = f"The final {item['component']} is exceeded"

            cases.append(
                {
                    "component": item["component"],
                    "trigger": trigger,
                    "standalone_penalty": "10-place grid drop if this is the only newly penalized element",
                }
            )

        if component_count >= 2:
            combined_penalty = (
                "15-place cumulative drop for two new penalized elements in one event"
                if component_count == 2
                else "Back-of-grid risk if three or more new penalized elements are fitted together"
            )
            cases.append(
                {
                    "component": "Combined",
                    "trigger": "Multiple vulnerable elements are changed in the same event",
                    "standalone_penalty": combined_penalty,
                }
            )

        return {"summary": summary, "prediction": prediction, "cases": cases}

    def get_strategic_circuits(self):
        """Circuits where taking a penalty is least costly."""
        rankings_path = Path(self.circuit_rankings_path)

        if rankings_path.exists():
            with rankings_path.open() as rankings_file:
                return json.load(rankings_file)

        return {
            "best_for_penalties": [],
            "worst_for_penalties": [],
            "methodology": {
                "note": "No generated circuit ranking file found yet. Run build_strategic_circuits.py to create one."
            },
        }

    def generate_report(self, race_name, race_number):
        """Generate a comprehensive penalty prediction report."""
        predictions = self.predict_penalties(race_number)
        circuits = self.get_strategic_circuits()

        return {
            "race": race_name,
            "race_number": race_number,
            "generated_at": datetime.now().isoformat(),
            "data_source": self.data_source,
            "source_manifest": self.source_manifest_path,
            "high_risk_drivers": [p for p in predictions if p["penalty_probability"] >= 50],
            "moderate_risk_drivers": [p for p in predictions if 30 <= p["penalty_probability"] < 50],
            "strategic_circuit_analysis": circuits,
            "betting_insights": self._generate_betting_insights(predictions, race_name),
        }

    def _generate_betting_insights(self, predictions, race_name):
        """Generate simple betting insights from high-risk penalty predictions."""
        insights = []

        for pred in predictions:
            if pred["penalty_probability"] >= 70:
                insights.append(
                    {
                        "driver": pred["driver"],
                        "team": pred.get("team"),
                        "market": "Grid Position",
                        "insight": "Likely to start from back - avoid podium/top-6 bets",
                        "confidence": "HIGH",
                    }
                )
                insights.append(
                    {
                        "driver": pred["driver"],
                        "team": pred.get("team"),
                        "market": "DNF/Reliability",
                        "insight": "Increased DNF risk if new components are stressed immediately",
                        "confidence": "MEDIUM",
                    }
                )

        return insights


if __name__ == "__main__":
    tracker = F1ComponentTracker()
    tracker.load_component_data(tracker.DEFAULT_DATA_SOURCE)
    print("F1 Component Tracker initialized with FIA-backed 2026 data")
    print(f"Drivers loaded: {len(tracker.component_data)}")
    print("Top predictions:", json.dumps(tracker.predict_penalties(4)[:5], indent=2))
