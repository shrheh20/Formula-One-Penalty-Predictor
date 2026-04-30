"""Production-style document routing, validation, and optional LLM extraction."""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import requests

from .classifier import FiaDocumentClassifier
from .llm_client import normalize_chat_completions_url

LOGGER = logging.getLogger(__name__)

EXTRACTION_VERSION = "2026.04.routed-v6"

SESSION_PATTERN = re.compile(
    r"\b(Free Practice 1|Free Practice 2|Free Practice 3|Practice 1|Practice 2|Practice 3|"
    r"Sprint Qualifying|Sprint Shootout|Sprint|Qualifying|Race)\b",
    re.IGNORECASE,
)
ARTICLE_PATTERN = re.compile(r"\bArticle[s]?\s+([A-Z0-9.()\- ,]+)", re.IGNORECASE)
CAR_NUMBER_PATTERN = re.compile(r"\bcar\s+(\d{1,3})\b", re.IGNORECASE)
GRID_PENALTY_PATTERN = re.compile(r"(\d+)\s*(?:place|grid)\s+grid penalty", re.IGNORECASE)
COMPONENT_CODE_PATTERN = re.compile(r"\((MGU-K|MGU-H|ICE|TC|ES|PU-CE|PU-ANC|EX)\)")
HEADERISH_VALUES = {
    "competitor",
    "competitor time",
    "time",
    "nat team",
    "manager",
    "ice tc",
    "adjustable bodywork",
}
HEADERISH_DRIVER_TOKENS = {
    "from",
    "to",
    "title",
    "description",
    "enclosed",
    "document",
    "date",
    "time",
    "page",
    "stewards",
    "all teams",
    "all officials",
    "formula one",
}
LLM_FIRST_TYPES = {
    "summons",
    "steward_decision",
    "penalty_notice",
    "infringement_race_deleted_lap_times",
    "infringement_qualifying_deleted_lap_times",
    "infringement_free_practice_3_deleted_lap_times",
    "car_display_procedure",
    "other",
}
COMPONENT_ORDER = ["ICE", "TC", "EXH", "MGU-K", "ES", "PU-CE", "PU-ANC"]
KNOWN_TEAMS = [
    "McLaren Mastercard F1 Team",
    "Mercedes-AMG PETRONAS F1 Team",
    "Oracle Red Bull Racing",
    "Scuderia Ferrari HP",
    "Atlassian Williams F1 Team",
    "Visa Cash App Racing Bulls F1 Team",
    "Aston Martin Aramco F1 Team",
    "TGR Haas F1 Team",
    "Audi Revolut F1 Team",
    "BWT Alpine F1 Team",
    "Cadillac Formula 1 Team",
    "McLaren Mercedes",
    "Mercedes",
    "Audi",
]
KNOWN_DRIVERS = [
    "Oscar Piastri",
    "Lando Norris",
    "George Russell",
    "Kimi Antonelli",
    "Max Verstappen",
    "Isack Hadjar",
    "Charles Leclerc",
    "Lewis Hamilton",
    "Alexander Albon",
    "Carlos Sainz",
    "Arvid Lindblad",
    "Liam Lawson",
    "Lance Stroll",
    "Fernando Alonso",
    "Esteban Ocon",
    "Oliver Bearman",
    "Nico Hülkenberg",
    "Nico Hulkenberg",
    "Gabriel Bortoleto",
    "Pierre Gasly",
    "Franco Colapinto",
    "Sergio Perez",
    "Valtteri Bottas",
    "Jak Crawford",
]


@dataclass(slots=True)
class ExtractionEnvelope:
    document_type: str
    document_family: str
    extraction_status: str
    extraction_version: str
    extraction_confidence: float
    needs_review: bool
    parser_output: dict[str, Any]
    extracted_data: dict[str, Any]
    ai_result: dict[str, Any] | None = None


class LlmExtractionClient:
    """Optional JSON extractor against an OpenAI-compatible chat endpoint."""

    def __init__(self) -> None:
        self.api_url = normalize_chat_completions_url(os.getenv("LLM_API_URL", ""))
        self.api_key = os.getenv("LLM_API_KEY", "").strip()
        self.model = os.getenv("LLM_MODEL", "qwen3.5:2b").strip()
        self.timeout = int(os.getenv("LLM_TIMEOUT_SECONDS", "45"))

    @property
    def enabled(self) -> bool:
        return bool(self.api_url and self.api_key and self.model)

    def extract(self, *, metadata: dict[str, Any], text: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        required_schema = {
            "document_type": metadata["document_type"],
            "session": None,
            "car_numbers": [],
            "drivers": [],
            "teams": [],
            "articles_cited": [],
            "penalty_type": None,
            "grid_penalty_places": None,
            "lap_time_deleted": False,
            "incident_summary": None,
            "verdict_summary": None,
            "table_rows": [],
            "unknown_document_signals": [],
            "confidence": 0.0,
        }
        prompt = (
            "Extract structured data from an FIA Formula One PDF. Return valid JSON only. "
            "Use null or empty arrays when a value is not explicit in the source. "
            "Never copy table headers as values.\n"
            f"Portal metadata: {json.dumps(metadata, ensure_ascii=True)}\n"
            f"Required schema: {json.dumps(required_schema, ensure_ascii=True)}\n"
            f"Document text:\n{text[:18000]}"
        )

        response = requests.post(
            self.api_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You extract structured fields from FIA regulatory documents. "
                            "Return JSON only."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        result = json.loads(content)
        result["provider"] = "llm"
        return result


class DocumentExtractionPipeline:
    def __init__(
        self,
        llm_client: LlmExtractionClient | None = None,
        classifier: FiaDocumentClassifier | None = None,
    ) -> None:
        self.llm_client = llm_client or LlmExtractionClient()
        self.classifier = classifier or FiaDocumentClassifier()

    def extract(
        self,
        *,
        title: str,
        text: str,
        grand_prix: str,
        doc_number: int,
        is_recalled: bool,
    ) -> ExtractionEnvelope:
        classification = self.classifier.classify(title=title, text=text)
        document_type = classification.document_type
        document_family = classification.document_family
        parser_output = self._deterministic_parse(
            document_type=document_type,
            document_family=document_family,
            title=title,
            text=text,
            grand_prix=grand_prix,
            doc_number=doc_number,
        )

        ai_result: dict[str, Any] | None = None
        should_use_llm = (
            document_type in LLM_FIRST_TYPES
            or parser_output["confidence"] < 0.7
            or bool(parser_output["unknown_document_signals"])
        )
        if should_use_llm:
            ai_result = self._extract_with_llm(
                metadata={
                    "grand_prix": grand_prix,
                    "doc_number": doc_number,
                    "title": title,
                    "document_type": document_type,
                    "document_family": document_family,
                    "classification_provider": classification.provider,
                },
                text=text,
            )

        extracted = self._merge_outputs(parser_output=parser_output, ai_result=ai_result)
        validation = self._validate_extracted(
            document_type=document_type,
            document_family=document_family,
            extracted=extracted,
        )

        if is_recalled:
            extracted["recalled"] = True
            extracted["recalled_reason"] = "Portal row marked as recalled by FIA"
            return ExtractionEnvelope(
                document_type=document_type,
                document_family=document_family,
                extraction_status="recalled",
                extraction_version=EXTRACTION_VERSION,
                extraction_confidence=0.0,
                needs_review=False,
                parser_output=parser_output,
                extracted_data=extracted,
                ai_result=ai_result,
            )

        confidence = min(
            0.99,
            max(parser_output["confidence"], ai_result.get("confidence", 0.0) if ai_result else 0.0),
        )
        needs_review = bool(
            validation["issues"]
            or document_type == "other"
            or parser_output["unknown_document_signals"]
            or confidence < 0.65
        )
        extracted["validation_issues"] = validation["issues"]
        extracted["source"] = {
            "parser_strategy": parser_output["parser_strategy"],
            "llm_used": bool(ai_result and ai_result.get("provider") == "llm"),
            "document_type": document_type,
            "document_family": document_family,
            "classification": {
                "provider": classification.provider,
                "confidence": classification.confidence,
                "rationale": classification.rationale,
                "supporting_signals": classification.supporting_signals,
            },
        }

        return ExtractionEnvelope(
            document_type=document_type,
            document_family=document_family,
            extraction_status="needs_review" if needs_review else "ready",
            extraction_version=EXTRACTION_VERSION,
            extraction_confidence=confidence,
            needs_review=needs_review,
            parser_output=parser_output,
            extracted_data=extracted,
            ai_result=ai_result,
        )

    @staticmethod
    def classify_document(*, title: str, text: str) -> str:
        return FiaDocumentClassifier.classify_with_rules(title=title, text=text).document_type

    @staticmethod
    def classify_document_family(*, title: str, text: str, document_type: str) -> str:
        return FiaDocumentClassifier.classify_with_rules(title=title, text=text).document_family

    def _deterministic_parse(
        self,
        *,
        document_type: str,
        document_family: str,
        title: str,
        text: str,
        grand_prix: str,
        doc_number: int,
    ) -> dict[str, Any]:
        normalized = " ".join(text.split())
        parser_output = {
            "grand_prix": grand_prix,
            "doc_number": doc_number,
            "title": title,
            "document_type": document_type,
            "document_family": document_family,
            "session": self._extract_session(title=title, text=normalized),
            "car_numbers": sorted({int(match) for match in CAR_NUMBER_PATTERN.findall(f"{title} {normalized}")}),
            "drivers": [],
            "teams": [],
            "articles_cited": self._extract_articles(text),
            "penalty_type": self._infer_penalty_type(title=title, text=normalized),
            "grid_penalty_places": self._extract_grid_penalty(title=title, text=normalized),
            "lap_time_deleted": "deleted lap time" in normalized.lower() or "deleted lap time" in title.lower(),
            "incident_summary": self._extract_incident_summary(title=title, text=normalized),
            "verdict_summary": self._extract_verdict_summary(normalized),
            "table_rows": [],
            "unknown_document_signals": [],
            "parser_strategy": "generic",
            "confidence": 0.45,
        }

        if document_type in {
            "summons",
            "steward_decision",
            "penalty_notice",
            "infringement_race_deleted_lap_times",
            "infringement_qualifying_deleted_lap_times",
            "infringement_free_practice_3_deleted_lap_times",
            "decision_qualifying_sc2_sc1_times",
        }:
            parser_output.update(self._parse_stewards_document(text=text, title=title))
        elif document_type == "new_pu_elements":
            parser_output.update(self._parse_component_table(text, title))
        elif document_type == "component_usage":
            parser_output.update(self._parse_pu_usage_table(text, title))
        elif document_type == "entry_list":
            parser_output.update(self._parse_entry_list(text))
        elif document_type == "championship_points":
            parser_output.update(self._parse_championship_points(text=text, title=title))
        elif document_type in {
            "final_race_classification",
            "provisional_race_classification",
            "final_qualifying_classification",
            "provisional_qualifying_classification",
            "final_starting_grid",
            "provisional_starting_grid",
            "final_sprint_qualifying_classification",
            "provisional_sprint_starting_grid",
            "final_sprint_starting_grid",
            "provisional_sprint_classification",
            "final_sprint_classification",
            "free_practice_1_classification",
            "free_practice_2_classification",
            "free_practice_3_classification",
        }:
            parser_output.update(self._parse_classification_table(text, title, document_type))
        elif document_type in {
            "curfew",
            "timetable",
            "race_director_notes",
            "car_display_procedure",
            "car_presentation_submissions",
            "competition_notes_pirelli_preview_v2",
            "pre_race_procedure",
            "post_race_procedure",
            "post_qualifying_procedure",
            "post_sprint_procedure",
            "parc_ferme_parts_and_parameters_changes",
            "parc_ferme_issues",
            "scrutineering_report",
            "race_scrutineering",
            "p3_and_qualifying_scrutineering",
        }:
            parser_output.update(self._parse_operational_document(text=text, title=title, document_type=document_type))
        elif document_type in {"technical_directive", "post_race_checks"}:
            parser_output.update(self._parse_technical_report(text=text, title=title, document_type=document_type))
        else:
            parser_output["unknown_document_signals"].extend(
                [
                    "unmapped_document_family",
                    f"unknown_document_title:{self._normalize_unknown_signal(title)}",
                ]
            )
            parser_output["parser_strategy"] = "generic-fallback"
            parser_output["confidence"] = 0.3

        return parser_output

    def _extract_with_llm(self, *, metadata: dict[str, Any], text: str) -> dict[str, Any] | None:
        try:
            result = self.llm_client.extract(metadata=metadata, text=text)
            if result is None:
                return {"provider": "disabled", "confidence": 0.0, "reason": "llm_not_configured"}
            return result
        except Exception as exc:
            LOGGER.warning("LLM extraction failed for doc %s: %s", metadata["doc_number"], exc)
            return {"provider": "failed", "confidence": 0.0, "reason": str(exc)}

    @staticmethod
    def _merge_outputs(parser_output: dict[str, Any], ai_result: dict[str, Any] | None) -> dict[str, Any]:
        merged = {
            "document_type": parser_output["document_type"],
            "document_family": parser_output.get("document_family", "other"),
            "session": parser_output["session"],
            "car_numbers": parser_output["car_numbers"],
            "drivers": parser_output["drivers"],
            "teams": parser_output["teams"],
            "articles_cited": parser_output["articles_cited"],
            "penalty_type": parser_output["penalty_type"],
            "grid_penalty_places": parser_output["grid_penalty_places"],
            "lap_time_deleted": parser_output["lap_time_deleted"],
            "incident_summary": parser_output["incident_summary"],
            "verdict_summary": parser_output["verdict_summary"],
            "entries": parser_output.get("entries", []),
            "table_rows": parser_output["table_rows"],
            "unknown_document_signals": parser_output["unknown_document_signals"],
        }
        if not ai_result:
            return merged

        for key in (
            "document_type",
            "document_family",
            "session",
            "car_numbers",
            "drivers",
            "teams",
            "articles_cited",
            "penalty_type",
            "grid_penalty_places",
            "lap_time_deleted",
            "incident_summary",
            "verdict_summary",
            "entries",
            "table_rows",
            "unknown_document_signals",
        ):
            ai_value = ai_result.get(key)
            if ai_value not in (None, "", [], {}):
                merged[key] = ai_value
        merged["drivers"] = DocumentExtractionPipeline._normalize_named_entities(
            merged.get("drivers"),
            entity_type="driver",
        )
        merged["teams"] = DocumentExtractionPipeline._normalize_named_entities(
            merged.get("teams"),
            entity_type="team",
        )
        merged["car_numbers"] = DocumentExtractionPipeline._normalize_car_numbers(merged.get("car_numbers"))
        return merged

    @staticmethod
    def _validate_extracted(
        *,
        document_type: str,
        document_family: str,
        extracted: dict[str, Any],
    ) -> dict[str, Any]:
        issues: list[str] = []

        for key in ("drivers", "teams"):
            cleaned_values: list[str] = []
            for value in extracted.get(key) or []:
                normalized = " ".join(str(value).split())
                lowered = normalized.lower()
                if not normalized:
                    continue
                if lowered in HEADERISH_VALUES:
                    issues.append(f"discarded_header_value:{key}:{normalized}")
                    continue
                if key == "drivers":
                    if any(re.search(rf"\b{re.escape(token)}\b", lowered) for token in HEADERISH_DRIVER_TOKENS):
                        issues.append(f"discarded_driver_boilerplate:{normalized[:40]}")
                        continue
                    if len(normalized) > 60:
                        issues.append(f"overlong_driver_value:{normalized[:40]}")
                        continue
                if key == "teams" and len(normalized) > 120:
                    issues.append(f"overlong_team_value:{normalized[:40]}")
                    continue
                cleaned_values.append(normalized)
            extracted[key] = list(dict.fromkeys(cleaned_values))

        if document_family == "steward_decision" and not extracted.get("incident_summary"):
            issues.append("missing_incident_summary")
        if document_type == "championship_points":
            standings = (extracted.get("entries") or {}).get("drivers_standings", [])
            positions = [entry.get("position") for entry in standings if isinstance(entry, dict)]
            valid_positions = [position for position in positions if isinstance(position, int)]
            if not standings:
                issues.append("missing_championship_standings")
            elif any(position < 1 or position > 22 for position in valid_positions):
                issues.append("invalid_championship_position_range")
            elif len(set(valid_positions)) != len(valid_positions):
                issues.append("duplicate_championship_positions")
        if document_type == "other":
            issues.append("unknown_document_type")
        if document_family == "other":
            issues.append("unknown_document_family")
        taxonomy_unknown_signals = {
            signal
            for signal in extracted.get("unknown_document_signals") or []
            if signal == "unmapped_document_family" or str(signal).startswith("unknown_document_title:")
        }
        if taxonomy_unknown_signals:
            issues.append("unknown_document_requires_taxonomy_review")

        return {"issues": issues}

    @staticmethod
    def _normalize_named_entities(values: Any, *, entity_type: str) -> list[str]:
        if not isinstance(values, list):
            return []

        normalized: list[str] = []
        preferred_keys = ("driver", "name") if entity_type == "driver" else ("team", "constructor", "name")
        for value in values:
            if isinstance(value, dict):
                extracted = None
                for key in preferred_keys:
                    candidate = value.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        extracted = candidate
                        break
                value = extracted or ""
            if isinstance(value, (int, float)):
                value = str(value)
            if not isinstance(value, str):
                continue
            cleaned = " ".join(value.split())
            if cleaned:
                normalized.append(cleaned)
        return list(dict.fromkeys(normalized))

    @staticmethod
    def _normalize_car_numbers(values: Any) -> list[int]:
        if not isinstance(values, list):
            return []
        normalized: list[int] = []
        for value in values:
            if isinstance(value, str) and value.isdigit():
                normalized.append(int(value))
            elif isinstance(value, int):
                normalized.append(value)
        return sorted(set(normalized))

    @staticmethod
    def _normalize_unknown_signal(value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return cleaned[:80] or "untitled"

    @staticmethod
    def _extract_session(*, title: str, text: str) -> str | None:
        match = SESSION_PATTERN.search(f"{title} {text}")
        return match.group(1) if match else None

    @staticmethod
    def _extract_articles(text: str) -> list[str]:
        articles = re.findall(
            r"Article[s]?\s+([A-Z0-9.()]+(?:\s*(?:and|,)\s*[A-Z0-9.()]+)*)",
            text,
            re.IGNORECASE,
        )
        return sorted({" ".join(match.split()) for match in articles})

    @staticmethod
    def _extract_grid_penalty(*, title: str, text: str) -> int | None:
        match = GRID_PENALTY_PATTERN.search(f"{title} {text}")
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_incident_summary(*, title: str, text: str) -> str | None:
        stripped = re.sub(r"^(Summons|Decision|Infringement)\s*-\s*", "", title, flags=re.IGNORECASE)
        if stripped != title:
            return stripped.strip()
        match = re.search(
            r"(alleged [^.]+|incident [^.]+|impeding [^.]+|deleted lap times[^.]*|unsafe release[^.]*)",
            text,
            re.IGNORECASE,
        )
        return match.group(1).strip() if match else title

    @staticmethod
    def _extract_verdict_summary(text: str) -> str | None:
        for pattern in (
            r"(the stewards[^.]+decide[^.]+\.)",
            r"(no further action[^.]*\.)",
            r"([^.]+reprimand[^.]*\.)",
            r"([^.]+grid penalty[^.]*\.)",
        ):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return " ".join(match.group(1).split())
        return None

    @staticmethod
    def _infer_penalty_type(*, title: str, text: str) -> str | None:
        haystack = f"{title} {text}".lower()
        mapping = {
            "summons": "summons",
            "deleted lap times": "deleted_lap_times",
            "deleted lap time": "deleted_lap_times",
            "grid penalty": "grid_penalty",
            "reprimand": "reprimand",
            "warning": "warning",
            "fine": "fine",
            "no further action": "no_further_action",
            "disqualified": "disqualification",
            "infringement": "infringement",
        }
        for needle, penalty_type in mapping.items():
            if needle in haystack:
                return penalty_type
        return None

    def _parse_stewards_document(self, *, text: str, title: str) -> dict[str, Any]:
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        no_driver = self._extract_labeled_value(lines, "No / Driver")
        competitor = self._extract_labeled_value(lines, "Competitor")
        session = self._extract_labeled_value(lines, "Session")
        fact = self._extract_labeled_value(lines, "Fact")
        infringement = self._extract_labeled_value(lines, "Infringement")
        decision = self._extract_labeled_value(lines, "Decision")
        reason = self._extract_labeled_value(lines, "Reason")

        drivers: list[str] = []
        car_numbers: list[int] = []
        if no_driver:
            match = re.search(r"(\d{1,3})\s*-\s*(.+)$", no_driver)
            if match:
                car_numbers.append(int(match.group(1)))
                drivers.append(match.group(2).strip())

        teams: list[str] = []
        if competitor:
            teams.append(competitor)
        else:
            for line in lines:
                known_team = self._find_known_team(line)
                if known_team:
                    teams.append(known_team)
                    break

        return {
            "drivers": drivers,
            "teams": teams,
            "car_numbers": sorted(set(car_numbers)) or self._extract_car_numbers_from_title(title),
            "session": session or self._extract_session(title=title, text=text),
            "articles_cited": self._extract_articles(infringement or text),
            "incident_summary": fact or self._extract_incident_summary(title=title, text=text),
            "verdict_summary": decision or reason or None,
            "penalty_type": self._infer_penalty_type(
                title=title,
                text=f"{decision or ''} {infringement or ''} {reason or ''}",
            ),
            "parser_strategy": "stewards-hybrid",
            "confidence": 0.85 if drivers or teams else 0.45,
        }

    def _parse_entry_list(self, text: str) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        entry_section = False
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            if "No." in raw_line and "Driver" in raw_line and "Constructor" in raw_line:
                entry_section = True
                continue
            if not entry_section:
                continue
            if (
                "In addition to the list of cars" in line
                or line.startswith("Page ")
                or line.startswith("Doc ")
            ):
                break
            if not re.match(r"^\d{1,3}\s+[A-Z]{3}\s+", line):
                continue
            parsed = self._parse_entry_list_line(line)
            if parsed:
                rows.append(parsed)

        return {
            "drivers": [row["driver"] for row in rows],
            "teams": [row["team"] for row in rows],
            "car_numbers": sorted({row["car_number"] for row in rows}),
            "entries": rows,
            "table_rows": rows,
            "parser_strategy": "entry-list-table",
            "confidence": 0.9 if len(rows) >= 20 else 0.6 if len(rows) >= 10 else 0.45,
            "unknown_document_signals": [] if rows else ["entry_list_parse_sparse"],
        }

    def _parse_component_table(self, text: str, title: str) -> dict[str, Any]:
        rows: list[str] = []
        entries: list[dict[str, Any]] = []
        current_component: str | None = None

        for raw_line in text.splitlines():
            cleaned = " ".join(raw_line.split())
            if not cleaned:
                continue

            component_match = COMPONENT_CODE_PATTERN.search(cleaned)
            if component_match:
                current_component = component_match.group(1)
                rows.append(cleaned)
                continue

            if cleaned.startswith("Number Car Driver Previously used"):
                rows.append(cleaned)
                continue

            entry = self._parse_component_row(cleaned, current_component)
            if entry:
                entries.append(entry)
                rows.append(cleaned)
                continue

            if current_component and (
                "remainder of the Competition" in cleaned
                or "in conformity with" in cleaned
            ):
                rows.append(cleaned)

        return {
            "drivers": [entry["driver"] for entry in entries],
            "teams": [entry["team"] for entry in entries],
            "car_numbers": sorted({entry["car_number"] for entry in entries}),
            "entries": entries,
            "table_rows": rows[:80],
            "parser_strategy": "component-table",
            "confidence": 0.92 if entries else 0.45,
            "incident_summary": title,
            "unknown_document_signals": [] if entries else ["component_table_not_found"],
        }

    def _parse_pu_usage_table(self, text: str, title: str) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        rows: list[str] = []
        for raw_line in text.splitlines():
            cleaned = " ".join(raw_line.split())
            if not re.match(r"^\d{1,3}\s+", cleaned):
                continue
            numbers = re.findall(r"\d+", cleaned)
            if len(numbers) < 8:
                continue

            counts = [int(value) for value in numbers[-7:]]
            prefix = cleaned[: cleaned.rfind(numbers[-7])].strip()
            car_match = re.match(r"^(?P<car_number>\d{1,3})\s+(?P<body>.+)$", prefix)
            if not car_match:
                continue

            body = car_match.group("body")
            driver = self._find_known_driver(body)
            team = self._find_known_team(body)
            if not driver or not team:
                continue

            entry = {
                "car_number": int(car_match.group("car_number").lstrip("0") or "0"),
                "driver": driver,
                "team": team,
                "usage": dict(zip(COMPONENT_ORDER, counts)),
            }
            entries.append(entry)
            rows.append(cleaned)

        return {
            "drivers": [entry["driver"] for entry in entries],
            "teams": [entry["team"] for entry in entries],
            "car_numbers": sorted({entry["car_number"] for entry in entries}),
            "entries": entries,
            "table_rows": rows,
            "parser_strategy": "pu-usage-table",
            "confidence": 0.9 if len(entries) >= 10 else 0.45,
            "incident_summary": title,
            "unknown_document_signals": [] if entries else ["pu_usage_table_not_found"],
        }

    @staticmethod
    def _parse_component_row(line: str, current_component: str | None) -> dict[str, Any] | None:
        if not current_component:
            return None

        parts = line.split()
        if len(parts) < 5:
            return None
        if not parts[0].isdigit() or not parts[-1].isdigit():
            return None

        car_number = int(parts[0].lstrip("0") or "0")
        previously_used = int(parts[-1])
        middle = parts[1:-1]
        if len(middle) < 3:
            return None

        # FIA technical delegate tables consistently end rows with the driver's first and last name.
        driver_parts = middle[-2:]
        team_parts = middle[:-2]
        if not team_parts:
            return None

        return {
            "component": current_component,
            "car_number": car_number,
            "team": " ".join(team_parts).strip(),
            "driver": " ".join(driver_parts).strip(),
            "previously_used": previously_used,
        }

    def _parse_classification_table(self, text: str, title: str, document_type: str) -> dict[str, Any]:
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        sampled_rows: list[str] = []
        entries: list[dict[str, Any]] = []
        for line in lines:
            if not re.match(r"^\d{1,2}\s+\d{1,3}\s+", line):
                continue
            parsed = self._parse_classification_or_grid_row(line, document_type=document_type)
            if parsed:
                entries.append(parsed)
                sampled_rows.append(line)
        return {
            "drivers": [entry["driver"] for entry in entries if entry.get("driver")],
            "teams": [entry["team"] for entry in entries if entry.get("team")],
            "car_numbers": sorted({entry["car_number"] for entry in entries if entry.get("car_number") is not None}),
            "entries": entries,
            "table_rows": sampled_rows,
            "parser_strategy": "classification-table",
            "confidence": 0.88 if len(entries) >= 10 else 0.65 if entries else 0.45,
            "incident_summary": title,
            "unknown_document_signals": [] if entries else ["classification_rows_not_found"],
        }

    def _parse_championship_points(self, *, text: str, title: str) -> dict[str, Any]:
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        driver_entries: list[dict[str, Any]] = []
        entrant_entries: list[dict[str, Any]] = []

        driver_aliases = self._driver_abbreviation_map()
        current_section: str | None = None

        for line in lines:
            upper_line = line.upper()
            if upper_line.startswith("DRIVER TOTAL"):
                current_section = "drivers"
                continue
            if upper_line.startswith("ENTRANT TOTAL"):
                current_section = "entrants"
                continue
            if line.startswith("Page ") or line.startswith("Doc "):
                continue

            if current_section == "drivers":
                entry = self._parse_championship_driver_line(line, driver_aliases)
                if entry and not any(existing.get("driver") == entry["driver"] for existing in driver_entries):
                    driver_entries.append(entry)
                    continue
            elif current_section == "entrants":
                entry = self._parse_championship_team_line(line)
                if entry and not any(existing.get("team") == entry["team"] for existing in entrant_entries):
                    entrant_entries.append(entry)

        drivers = [entry["driver"] for entry in driver_entries]
        teams = [entry["team"] for entry in entrant_entries if entry.get("team")]
        table_rows = [line for line in lines if "TOTAL" in line or self._find_known_driver(line) or self._find_known_team(line)]

        return {
            "drivers": drivers,
            "teams": list(dict.fromkeys(teams)),
            "car_numbers": [],
            "entries": {
                "drivers_standings": driver_entries,
                "entrant_standings": entrant_entries,
            },
            "table_rows": table_rows[:80],
            "incident_summary": title,
            "verdict_summary": None,
            "parser_strategy": "championship-points-table",
            "confidence": 0.9 if driver_entries else 0.55,
            "unknown_document_signals": [] if driver_entries else ["championship_points_rows_not_found"],
        }

    def _parse_operational_document(self, *, text: str, title: str, document_type: str) -> dict[str, Any]:
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        section_lines = self._extract_section_lines(lines)
        topics = self._extract_topics(text)
        enclosed = self._extract_labeled_value(lines, "Enclosed")
        description = self._extract_labeled_value(lines, "Description")
        entries: list[dict[str, Any]] = []
        if section_lines:
            entries.extend({"section": line} for line in section_lines[:20])
        if topics:
            entries.extend({"topic": topic} for topic in topics[:20] if {"topic": topic} not in entries)

        drivers: list[str] = []
        for line in lines:
            driver = self._find_known_driver(line)
            if driver and driver not in drivers:
                drivers.append(driver)
        teams = self._extract_teams(text)
        confidence = 0.8 if section_lines or topics or description or enclosed else 0.6

        return {
            "drivers": drivers,
            "teams": teams,
            "car_numbers": sorted(
                {
                    *self._extract_car_numbers_from_title(title),
                    *[int(match) for match in re.findall(r"\b(\d{1,3})\b", " ".join(section_lines[:10])) if int(match) < 200],
                }
            ),
            "entries": entries,
            "table_rows": section_lines[:50],
            "incident_summary": description or title,
            "verdict_summary": enclosed,
            "parser_strategy": f"{document_type}-metadata",
            "confidence": confidence,
            "unknown_document_signals": [] if confidence >= 0.75 else [f"{document_type}_metadata_sparse"],
        }

    def _parse_technical_report(self, *, text: str, title: str, document_type: str) -> dict[str, Any]:
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        relevant_rows: list[str] = []
        entries: list[dict[str, Any]] = []

        for line in lines:
            if any(keyword in line.lower() for keyword in ("car ", "driver", "team", "power unit", "checked", "found")):
                relevant_rows.append(line)
            driver = self._find_known_driver(line)
            team = self._find_known_team(line)
            if driver or team:
                entry = {
                    "driver": driver,
                    "team": team,
                    "car_numbers": self._extract_car_numbers_from_title(line),
                    "summary": line,
                }
                if entry not in entries:
                    entries.append(entry)

        drivers = [entry["driver"] for entry in entries if entry.get("driver")]
        teams = [entry["team"] for entry in entries if entry.get("team")]
        car_numbers = sorted(
            {
                *self._extract_car_numbers_from_title(title),
                *[number for entry in entries for number in entry.get("car_numbers", [])],
            }
        )

        return {
            "drivers": drivers,
            "teams": teams,
            "car_numbers": car_numbers,
            "entries": entries[:20],
            "table_rows": relevant_rows[:50],
            "incident_summary": title,
            "verdict_summary": self._extract_verdict_summary(" ".join(relevant_rows)) or self._extract_labeled_value(lines, "Description"),
            "parser_strategy": f"{document_type}-report",
            "confidence": 0.82 if relevant_rows else 0.55,
            "unknown_document_signals": [] if relevant_rows else [f"{document_type}_rows_not_found"],
        }

    @staticmethod
    def _extract_named_people(text: str, limit: int = 6) -> list[str]:
        candidates = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text)
        results: list[str] = []
        for candidate in candidates:
            if candidate.lower() in {"formula one", "race director", "technical delegate"}:
                continue
            if candidate not in results:
                results.append(candidate)
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _extract_section_lines(lines: list[str]) -> list[str]:
        sections: list[str] = []
        for line in lines:
            if len(line) < 6 or len(line) > 180:
                continue
            if re.match(r"^(Title|Description|Enclosed|From|To|Date|Time)\b", line):
                continue
            if re.match(r"^[A-Z0-9][A-Z0-9 '&/,\-()]{5,}$", line):
                sections.append(line.title() if line.isupper() else line)
                continue
            if re.match(r"^(The following|Track limits|Pit lane|Emergency exits|Battery containment|Red zone)", line, re.IGNORECASE):
                sections.append(line)
        return list(dict.fromkeys(sections))

    @staticmethod
    def _extract_topics(text: str) -> list[str]:
        topic_patterns = [
            r"Circuit Map",
            r"Pit Lane Drawing",
            r"Emergency Exits Map",
            r"Battery Containment Area",
            r"Red Zone",
            r"Pirelli Preview",
            r"Parc Ferm[ée]",
            r"Championship Points",
            r"Competition Visa",
            r"Power Unit Information",
            r"Car Presentation",
            r"Curfew",
        ]
        topics: list[str] = []
        for pattern in topic_patterns:
            for match in re.findall(pattern, text, re.IGNORECASE):
                normalized = " ".join(str(match).split())
                if normalized not in topics:
                    topics.append(normalized)
        return topics

    @staticmethod
    def _extract_teams(text: str) -> list[str]:
        team_patterns = [
            r"(McLaren Mastercard F1 Team)",
            r"(Mercedes-AMG PETRONAS F1 Team)",
            r"(Oracle Red Bull Racing)",
            r"(Scuderia Ferrari HP)",
            r"(Atlassian Williams F1 Team)",
            r"(Visa Cash App Racing Bulls F1 Team)",
            r"(Aston Martin Aramco F1 Team)",
            r"(TGR Haas F1 Team)",
            r"(Audi Revolut F1 Team)",
            r"(BWT Alpine F1 Team)",
            r"(Cadillac Formula 1 Team)",
        ]
        teams: list[str] = []
        for pattern in team_patterns:
            for match in re.findall(pattern, text):
                if match not in teams:
                    teams.append(match)
        return teams

    @staticmethod
    def _extract_labeled_value(lines: list[str], label: str) -> str | None:
        for index, line in enumerate(lines):
            if line.startswith(label):
                value = line[len(label):].strip(" :")
                if value:
                    return value
                if index + 1 < len(lines):
                    return lines[index + 1].strip()
        return None

    @staticmethod
    def _extract_car_numbers_from_title(title: str) -> list[int]:
        return sorted({int(match) for match in re.findall(r"Car\s+(\d{1,3})", title, re.IGNORECASE)})

    @staticmethod
    def _normalize_search(value: str) -> str:
        ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())

    def _find_known_driver(self, text: str) -> str | None:
        normalized = self._normalize_search(text)
        for driver in sorted(KNOWN_DRIVERS, key=len, reverse=True):
            if self._normalize_search(driver) in normalized:
                return driver
        return None

    def _find_known_team(self, text: str) -> str | None:
        normalized = self._normalize_search(text)
        aliases = [
            ("McLaren Mastercard F1 Team", "McLaren Mastercard F1 Team"),
            ("McLaren Mercedes", "McLaren Mastercard F1 Team"),
            ("McLaren", "McLaren Mastercard F1 Team"),
            ("Mercedes-AMG PETRONAS F1 Team", "Mercedes-AMG PETRONAS F1 Team"),
            ("Mercedes-AMG", "Mercedes-AMG PETRONAS F1 Team"),
            ("Mercedes", "Mercedes-AMG PETRONAS F1 Team"),
            ("Oracle Red Bull Racing", "Oracle Red Bull Racing"),
            ("Red Bull Racing", "Oracle Red Bull Racing"),
            ("Oracle", "Oracle Red Bull Racing"),
            ("Scuderia Ferrari HP", "Scuderia Ferrari HP"),
            ("Scuderia", "Scuderia Ferrari HP"),
            ("Ferrari", "Scuderia Ferrari HP"),
            ("Atlassian Williams F1 Team", "Atlassian Williams F1 Team"),
            ("Atlassian", "Atlassian Williams F1 Team"),
            ("Williams", "Atlassian Williams F1 Team"),
            ("Visa Cash App Racing Bulls F1 Team", "Visa Cash App Racing Bulls F1 Team"),
            ("Visa", "Visa Cash App Racing Bulls F1 Team"),
            ("Racing Bulls", "Visa Cash App Racing Bulls F1 Team"),
            ("Aston Martin Aramco F1 Team", "Aston Martin Aramco F1 Team"),
            ("Aston", "Aston Martin Aramco F1 Team"),
            ("TGR Haas F1 Team", "TGR Haas F1 Team"),
            ("TGR", "TGR Haas F1 Team"),
            ("Haas", "TGR Haas F1 Team"),
            ("Audi Revolut F1 Team", "Audi Revolut F1 Team"),
            ("Audi Revolut", "Audi Revolut F1 Team"),
            ("Audi", "Audi Revolut F1 Team"),
            ("BWT Alpine F1 Team", "BWT Alpine F1 Team"),
            ("BWT", "BWT Alpine F1 Team"),
            ("Alpine", "BWT Alpine F1 Team"),
            ("Cadillac Formula 1 Team", "Cadillac Formula 1 Team"),
            ("Cadillac", "Cadillac Formula 1 Team"),
        ]
        for alias, canonical in aliases:
            if self._normalize_search(alias) in normalized:
                return canonical
        return None

    def _parse_entry_list_line(self, line: str) -> dict[str, Any] | None:
        match = re.match(r"^(?P<car_number>\d{1,3})\s+(?P<code>[A-Z]{3})\s+(?P<rest>.+)$", line)
        if not match:
            return None

        rest = match.group("rest")
        driver = self._find_known_driver(rest)
        if not driver:
            return None
        driver_index = rest.find(driver)
        remainder = rest[driver_index + len(driver):].strip()
        parts = remainder.split(maxsplit=1)
        if len(parts) != 2:
            return None
        nationality, rest = parts
        if not re.fullmatch(r"[A-Z]{3}", nationality):
            return None

        constructor = None
        team = None
        for token, canonical_team in self._constructor_team_aliases():
            if rest.endswith(token):
                constructor = token
                team = canonical_team
                break

        if not constructor:
            canonical_team = self._find_known_team(rest)
            if not canonical_team:
                return None
            constructor = rest
            team = canonical_team

        return {
            "car_number": int(match.group("car_number").lstrip("0") or "0"),
            "driver_code": match.group("code"),
            "driver": driver,
            "nationality": nationality,
            "team": team,
            "constructor": constructor,
        }

    def _parse_classification_or_grid_row(self, line: str, *, document_type: str) -> dict[str, Any] | None:
        head = re.match(r"^(?P<position>\d{1,2})\s+(?P<car_number>\d{1,3})\s+(?P<body>.+)$", line)
        if not head:
            return None

        body = head.group("body")
        driver = self._find_known_driver(body)
        team = self._find_known_team(body)
        times = re.findall(r"\d:\d{2}\.\d{3}", body)
        if not driver and not team:
            return None

        return {
            "position": int(head.group("position")),
            "car_number": int(head.group("car_number").lstrip("0") or "0"),
            "driver": driver,
            "team": team,
            "best_time": times[-1] if times else None,
            "times": times,
            "document_subtype": document_type,
        }

    @staticmethod
    def _driver_abbreviation_map() -> dict[str, str]:
        mapping: dict[str, str] = {}
        for driver in KNOWN_DRIVERS:
            parts = driver.replace("ü", "u").replace("Ü", "U").split()
            if len(parts) >= 2:
                mapping[f"{parts[0][0].upper()}. {parts[-1].upper()}"] = driver
                mapping[f"{parts[0][0].upper()} {parts[-1].upper()}"] = driver
        return mapping

    @staticmethod
    def _constructor_team_aliases() -> list[tuple[str, str]]:
        return [
            ("McLaren Mercedes", "McLaren Mastercard F1 Team"),
            ("Mercedes", "Mercedes-AMG PETRONAS F1 Team"),
            ("Red Bull Racing Red Bull Ford", "Oracle Red Bull Racing"),
            ("Ferrari", "Scuderia Ferrari HP"),
            ("Atlassian Williams Mercedes", "Atlassian Williams F1 Team"),
            ("Racing Bulls Red Bull Ford", "Visa Cash App Racing Bulls F1 Team"),
            ("Aston Martin Aramco Honda", "Aston Martin Aramco F1 Team"),
            ("Haas Ferrari", "TGR Haas F1 Team"),
            ("Audi", "Audi Revolut F1 Team"),
            ("Alpine Mercedes", "BWT Alpine F1 Team"),
            ("Cadillac Ferrari", "Cadillac Formula 1 Team"),
        ]

    def _parse_championship_driver_line(
        self, line: str, driver_aliases: dict[str, str]
    ) -> dict[str, Any] | None:
        driver = self._find_known_driver(line)
        if not driver:
            for abbr, mapped_driver in driver_aliases.items():
                if abbr in line:
                    driver = mapped_driver
                    break
        if not driver:
            return None

        numbers = [int(value) for value in re.findall(r"\b\d+\b", line)]
        if not numbers:
            return None

        position = next((value for value in numbers if 1 <= value <= 30), None)
        total_points = numbers[-1]
        if position == total_points and len(numbers) >= 2:
            total_points = numbers[-2]

        return {
            "driver": driver,
            "position": position,
            "total_points": total_points,
            "raw_line": line,
        }
        return None

    def _parse_championship_team_line(self, line: str) -> dict[str, Any] | None:
        team = self._find_known_team(line)
        if not team:
            return None

        numbers = [int(value) for value in re.findall(r"\b\d+\b", line)]
        position = next((value for value in numbers if 1 <= value <= 30), None)
        total_points = numbers[-1] if numbers else None
        if position == total_points and len(numbers) >= 2:
            total_points = numbers[-2]

        return {
            "team": team,
            "position": position,
            "total_points": total_points,
            "raw_line": line,
        }
