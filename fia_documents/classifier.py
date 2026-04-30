"""LLM-assisted document classification for FIA PDFs."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass

import requests

from .llm_client import normalize_chat_completions_url

CANONICAL_DOCUMENT_TYPES = [
    "steward_decision",
    "penalty_notice",
    "technical_directive",
    "race_director_notes",
    "car_display_procedure",
    "car_presentation_submissions",
    "scrutineering_report",
    "component_usage",
    "championship_points",
    "entry_list",
    "final_race_classification",
    "race_scrutineering",
    "infringement_race_deleted_lap_times",
    "provisional_race_classification",
    "final_starting_grid",
    "parc_ferme_parts_and_parameters_changes",
    "post_race_procedure",
    "pre_race_procedure",
    "provisional_starting_grid",
    "final_qualifying_classification",
    "p3_and_qualifying_scrutineering",
    "infringement_qualifying_deleted_lap_times",
    "decision_qualifying_sc2_sc1_times",
    "provisional_qualifying_classification",
    "infringement_free_practice_3_deleted_lap_times",
    "free_practice_1_classification",
    "free_practice_2_classification",
    "free_practice_3_classification",
    "final_sprint_qualifying_classification",
    "provisional_sprint_starting_grid",
    "post_sprint_procedure",
    "parc_ferme_issues",
    "final_sprint_starting_grid",
    "provisional_sprint_classification",
    "final_sprint_classification",
    "post_race_checks",
    "timetable",
    "new_pu_elements",
    "summons",
    "curfew",
    "post_qualifying_procedure",
    "competition_notes_pirelli_preview_v2",
    "other",
]

DOCUMENT_FAMILY_BY_TYPE = {
    "steward_decision": "steward_decision",
    "penalty_notice": "steward_decision",
    "summons": "steward_decision",
    "infringement_race_deleted_lap_times": "steward_decision",
    "infringement_qualifying_deleted_lap_times": "steward_decision",
    "infringement_free_practice_3_deleted_lap_times": "steward_decision",
    "decision_qualifying_sc2_sc1_times": "steward_decision",
    "technical_directive": "technical_directive",
    "component_usage": "component_allocation",
    "new_pu_elements": "component_allocation",
    "race_director_notes": "race_control",
    "competition_notes_pirelli_preview_v2": "race_control",
    "curfew": "race_control",
    "timetable": "race_control",
    "car_display_procedure": "procedure",
    "car_presentation_submissions": "procedure",
    "post_race_procedure": "procedure",
    "pre_race_procedure": "procedure",
    "post_qualifying_procedure": "procedure",
    "post_sprint_procedure": "procedure",
    "scrutineering_report": "scrutineering",
    "race_scrutineering": "scrutineering",
    "p3_and_qualifying_scrutineering": "scrutineering",
    "post_race_checks": "scrutineering",
    "parc_ferme_issues": "technical_compliance",
    "championship_points": "sporting_results",
    "entry_list": "sporting_results",
    "final_race_classification": "sporting_results",
    "provisional_race_classification": "sporting_results",
    "final_qualifying_classification": "sporting_results",
    "provisional_qualifying_classification": "sporting_results",
    "final_starting_grid": "sporting_results",
    "provisional_starting_grid": "sporting_results",
    "free_practice_1_classification": "sporting_results",
    "free_practice_2_classification": "sporting_results",
    "free_practice_3_classification": "sporting_results",
    "final_sprint_qualifying_classification": "sporting_results",
    "provisional_sprint_starting_grid": "sporting_results",
    "final_sprint_starting_grid": "sporting_results",
    "provisional_sprint_classification": "sporting_results",
    "final_sprint_classification": "sporting_results",
    "parc_ferme_parts_and_parameters_changes": "technical_compliance",
    "other": "other",
}

DOCUMENT_TYPE_DESCRIPTIONS = {
    "steward_decision": "Generic stewards decision document.",
    "penalty_notice": "Notice of a penalty, often grid or sporting.",
    "technical_directive": "Official FIA technical directive.",
    "race_director_notes": "Race director notes or event instructions.",
    "car_display_procedure": "Car display procedure note or media-delegate operating instruction.",
    "car_presentation_submissions": "Car presentation submissions document.",
    "scrutineering_report": "General scrutineering report.",
    "component_usage": "Power unit or component usage per driver.",
    "championship_points": "Championship points standings.",
    "entry_list": "Official FIA entry list.",
    "final_race_classification": "Final official race classification.",
    "race_scrutineering": "Race scrutineering report.",
    "infringement_race_deleted_lap_times": "Race deleted lap times infringement.",
    "provisional_race_classification": "Provisional race classification.",
    "final_starting_grid": "Final starting grid.",
    "parc_ferme_parts_and_parameters_changes": "Parts and parameters changed during parc ferme.",
    "post_race_procedure": "Post-race procedure document.",
    "pre_race_procedure": "Pre-race procedure document.",
    "provisional_starting_grid": "Provisional starting grid.",
    "final_qualifying_classification": "Final qualifying classification.",
    "p3_and_qualifying_scrutineering": "P3 and qualifying scrutineering report.",
    "infringement_qualifying_deleted_lap_times": "Qualifying deleted lap times infringement.",
    "decision_qualifying_sc2_sc1_times": "Qualifying SC2-SC1 times decision.",
    "provisional_qualifying_classification": "Provisional qualifying classification.",
    "infringement_free_practice_3_deleted_lap_times": "FP3 deleted lap times infringement.",
    "free_practice_1_classification": "Free Practice 1 classification.",
    "free_practice_2_classification": "Free Practice 2 classification.",
    "free_practice_3_classification": "Free Practice 3 classification.",
    "final_sprint_qualifying_classification": "Final sprint qualifying classification.",
    "provisional_sprint_starting_grid": "Provisional sprint starting grid.",
    "post_sprint_procedure": "Post-sprint procedure document.",
    "parc_ferme_issues": "Parc ferme issues document.",
    "final_sprint_starting_grid": "Final sprint starting grid.",
    "provisional_sprint_classification": "Provisional sprint classification.",
    "final_sprint_classification": "Final sprint classification.",
    "post_race_checks": "Post-race checks document.",
    "timetable": "Event timetable document.",
    "new_pu_elements": "New power unit elements for this competition.",
    "summons": "Formal FIA summons document.",
    "curfew": "Curfew or operational exemption note.",
    "post_qualifying_procedure": "Post-qualifying procedure document.",
    "competition_notes_pirelli_preview_v2": "Competition notes Pirelli preview v2.",
    "other": "No taxonomy match.",
}


@dataclass(slots=True)
class ClassificationResult:
    document_type: str
    document_family: str
    confidence: float
    provider: str
    rationale: str
    supporting_signals: list[str]


class FiaDocumentClassifier:
    def __init__(self) -> None:
        self.api_url = normalize_chat_completions_url(os.getenv("LLM_API_URL", ""))
        self.api_key = os.getenv("LLM_API_KEY", "").strip()
        self.model = os.getenv("LLM_MODEL", "qwen3.5:2b").strip()
        self.timeout = int(os.getenv("LLM_TIMEOUT_SECONDS", "45"))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.api_url and self.api_key and self.model)

    def classify(self, *, title: str, text: str) -> ClassificationResult:
        heuristic = self.classify_with_rules(title=title, text=text)
        if not self.llm_enabled:
            return heuristic
        if heuristic.confidence >= 0.94 and heuristic.document_type != "other":
            return heuristic

        llm_result = self._classify_with_llm(title=title, text=text, heuristic=heuristic)
        if llm_result is None:
            return heuristic
        if llm_result.confidence >= heuristic.confidence or heuristic.document_type == "other":
            return llm_result
        return heuristic

    @classmethod
    def classify_with_rules(cls, *, title: str, text: str) -> ClassificationResult:
        normalized_title = cls._normalize(title)
        normalized_text = cls._normalize(text[:6000])
        haystack = f"{normalized_title}\n{normalized_text}"

        heuristic_rules: list[tuple[re.Pattern[str], str, float, str]] = [
            (re.compile(r"\btechnical directive\b"), "technical_directive", 0.99, "title contains technical directive"),
            (
                re.compile(r"\bdecision\b.*\bqualifying\b.*\bsc2\b.*\bsc1\b"),
                "decision_qualifying_sc2_sc1_times",
                0.99,
                "title matches SC2-SC1 decision",
            ),
            (
                re.compile(r"\binfringement\b.*\bfree practice 3\b.*\bdeleted lap times\b"),
                "infringement_free_practice_3_deleted_lap_times",
                0.99,
                "title matches FP3 deleted lap times infringement",
            ),
            (
                re.compile(r"\binfringement\b.*\bqualifying\b.*\bdeleted lap times\b"),
                "infringement_qualifying_deleted_lap_times",
                0.99,
                "title matches qualifying deleted lap times infringement",
            ),
            (
                re.compile(r"\binfringement\b.*\brace\b.*\bdeleted lap times\b"),
                "infringement_race_deleted_lap_times",
                0.99,
                "title matches race deleted lap times infringement",
            ),
            (
                re.compile(r"\binfringement\b.*\bparc ferme\b"),
                "steward_decision",
                0.96,
                "title matches parc ferme infringement",
            ),
            (re.compile(r"\bsummons\b"), "summons", 0.99, "title contains summons"),
            (re.compile(r"\bdecision\b"), "steward_decision", 0.96, "title contains decision"),
            (re.compile(r"\binfringement\b"), "steward_decision", 0.94, "title contains infringement"),
            (
                re.compile(r"\bcompetition notes\b.*\bpirelli preview\b.*\bv2\b"),
                "competition_notes_pirelli_preview_v2",
                0.99,
                "title matches Pirelli preview notes",
            ),
            (re.compile(r"\brace director"), "race_director_notes", 0.98, "title references race director"),
            (re.compile(r"\bcar display procedure\b"), "car_display_procedure", 0.99, "title exact match"),
            (
                re.compile(r"\bcar presentation submissions\b"),
                "car_presentation_submissions",
                0.99,
                "title exact match",
            ),
            (re.compile(r"\bpost[- ]qualifying procedure\b"), "post_qualifying_procedure", 0.99, "procedure title"),
            (re.compile(r"\bpost[- ]race procedure\b"), "post_race_procedure", 0.99, "procedure title"),
            (re.compile(r"\bpre[- ]race procedure\b"), "pre_race_procedure", 0.99, "procedure title"),
            (re.compile(r"\bpost[- ]sprint procedure\b"), "post_sprint_procedure", 0.99, "procedure title"),
            (re.compile(r"\bcurfew\b"), "curfew", 0.98, "title contains curfew"),
            (re.compile(r"\btimetable\b"), "timetable", 0.99, "title contains timetable"),
            (re.compile(r"\bentry list\b"), "entry_list", 0.99, "title exact match"),
            (re.compile(r"\bnew pu elements\b"), "new_pu_elements", 0.99, "title contains new pu elements"),
            (
                re.compile(r"\b(power unit information|pu elements used per driver|component usage)\b"),
                "component_usage",
                0.96,
                "title matches component usage phrasing",
            ),
            (re.compile(r"\bchampionship points\b"), "championship_points", 0.99, "title contains championship points"),
            (re.compile(r"\bfinal race classification\b"), "final_race_classification", 0.99, "title exact match family"),
            (
                re.compile(r"\bprovisional race classification\b"),
                "provisional_race_classification",
                0.99,
                "title exact match family",
            ),
            (re.compile(r"\bfinal starting grid\b"), "final_starting_grid", 0.99, "title exact match family"),
            (
                re.compile(r"\bprovisional starting grid\b"),
                "provisional_starting_grid",
                0.99,
                "title exact match family",
            ),
            (
                re.compile(r"\bfinal qualifying classification\b"),
                "final_qualifying_classification",
                0.99,
                "title exact match family",
            ),
            (
                re.compile(r"\bprovisional qualifying classification\b"),
                "provisional_qualifying_classification",
                0.99,
                "title exact match family",
            ),
            (
                re.compile(r"\bfree practice 1 classification\b"),
                "free_practice_1_classification",
                0.99,
                "title exact match family",
            ),
            (
                re.compile(r"\bfree practice 2 classification\b"),
                "free_practice_2_classification",
                0.99,
                "title exact match family",
            ),
            (
                re.compile(r"\bfree practice 3 classification\b|\bfre practive 3 classification\b"),
                "free_practice_3_classification",
                0.98,
                "title matches FP3 classification",
            ),
            (
                re.compile(r"\bfinal sprint qualifying classification\b"),
                "final_sprint_qualifying_classification",
                0.99,
                "title exact match family",
            ),
            (
                re.compile(r"\bprovisional sprint starting grid\b"),
                "provisional_sprint_starting_grid",
                0.99,
                "title exact match family",
            ),
            (
                re.compile(r"\bfinal sprint starting grid\b"),
                "final_sprint_starting_grid",
                0.99,
                "title exact match family",
            ),
            (
                re.compile(r"\bprovisional sprint classification\b"),
                "provisional_sprint_classification",
                0.99,
                "title exact match family",
            ),
            (
                re.compile(r"\bfinal sprint classification\b"),
                "final_sprint_classification",
                0.99,
                "title exact match family",
            ),
            (
                re.compile(r"\bp3 and qualifying scrutineering\b"),
                "p3_and_qualifying_scrutineering",
                0.99,
                "title exact match family",
            ),
            (
                re.compile(r"\bpost[- ]race checks\b"),
                "post_race_checks",
                0.99,
                "title exact match family",
            ),
            (re.compile(r"\brace scrutineering\b"), "race_scrutineering", 0.99, "title exact match family"),
            (
                re.compile(r"\bscrutineering report\b|\bscrutineering\b"),
                "scrutineering_report",
                0.94,
                "title contains scrutineering",
            ),
            (
                re.compile(r"\bparts and parameters\b.*\bparc ferme\b|\bparc ferme\b.*\bparts and parameters\b"),
                "parc_ferme_parts_and_parameters_changes",
                0.97,
                "title references parc ferme parts and parameters",
            ),
            (
                re.compile(r"\bparc ferme issues\b|\bparc ferm[ée] issues\b"),
                "parc_ferme_issues",
                0.99,
                "title exact match family",
            ),
            (
                re.compile(r"\bpenalty notice\b|\bgrid penalty\b|\bpenalty\b"),
                "penalty_notice",
                0.78,
                "title contains penalty phrasing",
            ),
        ]

        for pattern, document_type, confidence, rationale in heuristic_rules:
            if pattern.search(haystack):
                return ClassificationResult(
                    document_type=document_type,
                    document_family=DOCUMENT_FAMILY_BY_TYPE.get(document_type, "other"),
                    confidence=confidence,
                    provider="rules",
                    rationale=rationale,
                    supporting_signals=[pattern.pattern],
                )

        return ClassificationResult(
            document_type="other",
            document_family="other",
            confidence=0.2,
            provider="rules",
            rationale="no taxonomy rule matched",
            supporting_signals=[],
        )

    def _classify_with_llm(
        self,
        *,
        title: str,
        text: str,
        heuristic: ClassificationResult,
    ) -> ClassificationResult | None:
        allowed = {
            doc_type: DOCUMENT_TYPE_DESCRIPTIONS[doc_type]
            for doc_type in CANONICAL_DOCUMENT_TYPES
        }
        prompt = {
            "task": "Classify this FIA Formula One document into exactly one allowed document_type.",
            "allowed_document_types": allowed,
            "heuristic_guess": {
                "document_type": heuristic.document_type,
                "document_family": heuristic.document_family,
                "confidence": heuristic.confidence,
                "rationale": heuristic.rationale,
            },
            "title": title,
            "text_excerpt": text[:12000],
            "response_schema": {
                "document_type": "one of allowed_document_types",
                "confidence": "0.0 to 1.0",
                "rationale": "short explanation",
                "supporting_signals": ["short strings"],
            },
        }

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
                            "You classify FIA Formula One documents into a fixed taxonomy. "
                            "Return JSON only. Never invent labels outside the allowed list."
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=True)},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)

        document_type = parsed.get("document_type", "other")
        if document_type not in CANONICAL_DOCUMENT_TYPES:
            document_type = "other"

        confidence = parsed.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0

        supporting_signals = parsed.get("supporting_signals") or []
        if not isinstance(supporting_signals, list):
            supporting_signals = [str(supporting_signals)]

        return ClassificationResult(
            document_type=document_type,
            document_family=DOCUMENT_FAMILY_BY_TYPE.get(document_type, "other"),
            confidence=max(0.0, min(1.0, confidence)),
            provider="llm",
            rationale=str(parsed.get("rationale") or "").strip() or "llm classification",
            supporting_signals=[str(item) for item in supporting_signals[:8]],
        )

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        return " ".join(normalized.lower().split())
