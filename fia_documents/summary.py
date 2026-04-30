"""Race-impact summaries for FIA documents."""

from __future__ import annotations

import os
import re
from typing import Any

import requests

from .llm_client import extract_message_text, normalize_chat_completions_url, resolve_chat_setting


DASHBOARD_SUMMARY_VERSION = "2026.04.race-impact-v1"
DEFAULT_NO_IMPACT_SUMMARY = "### Race Impact\n\n- No meaningful performance or sporting impact."
TITLE_TYPE_RULES: list[tuple[str, str]] = [
    ("championship points", "CHAMPIONSHIP_UPDATE"),
    ("final race classification", "FINAL_RACE_RESULT"),
    ("race scrutineering", "SCRUTINEERING_REPORT"),
    ("infringement race deleted lap times", "RACE_TRACK_LIMITS"),
    ("provisional race classification", "PROVISIONAL_RESULT"),
    ("final starting grid", "FINAL_GRID"),
    ("parts replaced during parc ferme", "PARC_FERME_CHANGE"),
    ("post-race procedure", "PROCEDURE"),
    ("pre-race procedure", "PROCEDURE"),
    ("provisional starting grid", "PROVISIONAL_GRID"),
    ("final qualifying classification", "QUALIFYING_RESULT"),
    ("p3 and qualifying scrutineering", "SCRUTINEERING_REPORT"),
    ("infringement qualifying deleted lap times", "QUALI_TRACK_LIMITS"),
    ("decision qualifying sc2 sc1 times", "STEWARDS_DECISION"),
    ("provisional qualifying classification", "PROVISIONAL_QUALI"),
    ("free practice classifications", "PRACTICE_RESULT"),
    ("free practice 1 classification", "PRACTICE_RESULT"),
    ("free practice 2 classification", "PRACTICE_RESULT"),
    ("free practice 3 classification", "PRACTICE_RESULT"),
    ("new pu elements for this competition", "PU_USAGE"),
    ("summons", "SUMMONS"),
    ("curfew", "ADMIN"),
    ("post qualifying procedure", "PROCEDURE"),
    ("competition notes pirelli preview", "TYRE_BRIEFING"),
    ("car display procedure", "PROCEDURE"),
    ("car presentation submissions", "ADMIN"),
    ("entry list", "ENTRY_LIST"),
    ("sprint qualifying classification", "SPRINT_RESULT"),
    ("sprint grid", "SPRINT_GRID"),
    ("sprint classification", "SPRINT_RESULT"),
    ("post race checks", "SCRUTINEERING_REPORT"),
    ("decision", "STEWARDS_DECISION"),
    ("timetable", "ADMIN"),
]
LEGACY_TYPE_MAP = {
    "championship_points": "CHAMPIONSHIP_UPDATE",
    "final_race_classification": "FINAL_RACE_RESULT",
    "race_scrutineering": "SCRUTINEERING_REPORT",
    "scrutineering_report": "SCRUTINEERING_REPORT",
    "infringement_race_deleted_lap_times": "RACE_TRACK_LIMITS",
    "provisional_race_classification": "PROVISIONAL_RESULT",
    "final_starting_grid": "FINAL_GRID",
    "parc_ferme_parts_and_parameters_changes": "PARC_FERME_CHANGE",
    "parc_ferme_issues": "PARC_FERME_CHANGE",
    "post_race_procedure": "PROCEDURE",
    "pre_race_procedure": "PROCEDURE",
    "provisional_starting_grid": "PROVISIONAL_GRID",
    "final_qualifying_classification": "QUALIFYING_RESULT",
    "p3_and_qualifying_scrutineering": "SCRUTINEERING_REPORT",
    "infringement_qualifying_deleted_lap_times": "QUALI_TRACK_LIMITS",
    "decision_qualifying_sc2_sc1_times": "STEWARDS_DECISION",
    "provisional_qualifying_classification": "PROVISIONAL_QUALI",
    "free_practice_1_classification": "PRACTICE_RESULT",
    "free_practice_2_classification": "PRACTICE_RESULT",
    "free_practice_3_classification": "PRACTICE_RESULT",
    "new_pu_elements": "PU_USAGE",
    "component_usage": "PU_USAGE",
    "summons": "SUMMONS",
    "curfew": "CURFEW",
    "post_qualifying_procedure": "PROCEDURE",
    "competition_notes_pirelli_preview_v2": "TYRE_BRIEFING",
    "car_display_procedure": "PROCEDURE",
    "car_presentation_submissions": "ADMIN",
    "entry_list": "ENTRY_LIST",
    "final_sprint_qualifying_classification": "SPRINT_RESULT",
    "provisional_sprint_starting_grid": "SPRINT_GRID",
    "final_sprint_starting_grid": "SPRINT_GRID",
    "provisional_sprint_classification": "SPRINT_RESULT",
    "final_sprint_classification": "SPRINT_RESULT",
    "post_race_checks": "SCRUTINEERING_REPORT",
    "steward_decision": "STEWARDS_DECISION",
    "penalty_notice": "STEWARDS_DECISION",
    "timetable": "TIMETABLE",
}
NO_IMPACT_DOC_TYPES = {
    "ENTRY_LIST",
    "ADMIN",
    "TIMETABLE",
    "PROCEDURE",
    "CURFEW",
    "PRACTICE_RESULT",
}
LLM_ANALYSIS_DOC_TYPES = {
    "SCRUTINEERING_REPORT",
    "PARC_FERME_CHANGE",
    "PU_USAGE",
    "TYRE_BRIEFING",
    "STEWARDS_DECISION",
    "FINAL_GRID",
    "FINAL_RACE_RESULT",
    "RACE_TRACK_LIMITS",
    "QUALI_TRACK_LIMITS",
}
IMPACT_LEVELS = {
    "STEWARDS_DECISION": "HIGH",
    "FINAL_GRID": "HIGH",
    "FINAL_RACE_RESULT": "HIGH",
    "RACE_TRACK_LIMITS": "HIGH",
    "QUALI_TRACK_LIMITS": "HIGH",
    "CHAMPIONSHIP_UPDATE": "HIGH",
    "PROVISIONAL_RESULT": "HIGH",
    "PROVISIONAL_GRID": "HIGH",
    "QUALIFYING_RESULT": "HIGH",
    "PROVISIONAL_QUALI": "HIGH",
    "SPRINT_RESULT": "HIGH",
    "SPRINT_GRID": "HIGH",
    "PU_USAGE": "MEDIUM",
    "PARC_FERME_CHANGE": "MEDIUM",
    "TYRE_BRIEFING": "MEDIUM",
    "SCRUTINEERING_REPORT": "LOW",
}
TEAM_ALIASES = {
    "McLaren Mastercard F1 Team": "McLaren",
    "McLaren Mercedes": "McLaren",
    "Mercedes-AMG PETRONAS F1 Team": "Mercedes",
    "Oracle Red Bull Racing": "Red Bull",
    "Scuderia Ferrari HP": "Ferrari",
    "Atlassian Williams F1 Team": "Williams",
    "Visa Cash App Racing Bulls F1 Team": "Racing Bulls",
    "Aston Martin Aramco F1 Team": "Aston Martin",
    "TGR Haas F1 Team": "Haas",
    "Audi Revolut F1 Team": "Audi",
    "BWT Alpine F1 Team": "Alpine",
    "Cadillac Formula 1 Team": "Cadillac",
}
DRIVER_TEAM_MAP = {
    "Oscar Piastri": "McLaren",
    "Lando Norris": "McLaren",
    "George Russell": "Mercedes",
    "Kimi Antonelli": "Mercedes",
    "Max Verstappen": "Red Bull",
    "Yuki Tsunoda": "Red Bull",
    "Charles Leclerc": "Ferrari",
    "Lewis Hamilton": "Ferrari",
    "Alexander Albon": "Williams",
    "Carlos Sainz": "Williams",
    "Isack Hadjar": "Racing Bulls",
    "Liam Lawson": "Racing Bulls",
    "Fernando Alonso": "Aston Martin",
    "Lance Stroll": "Aston Martin",
    "Esteban Ocon": "Haas",
    "Oliver Bearman": "Haas",
    "Nico Hulkenberg": "Audi",
    "Nico Hülkenberg": "Audi",
    "Gabriel Bortoleto": "Audi",
    "Pierre Gasly": "Alpine",
    "Franco Colapinto": "Alpine",
    "Jack Doohan": "Alpine",
}


def _clean_names(values: list[Any] | None) -> list[str]:
    cleaned: list[str] = []
    for value in values or []:
        normalized = " ".join(str(value).split())
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned


def _normalize_team(team: str) -> str:
    normalized = " ".join(team.split())
    return TEAM_ALIASES.get(normalized, normalized)


def _driver_team_pairs_from_text(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    known_drivers = sorted(DRIVER_TEAM_MAP, key=len, reverse=True)
    known_teams = sorted({*TEAM_ALIASES, *TEAM_ALIASES.values()}, key=len, reverse=True)
    for line in lines:
        if not re.match(r"^\d{1,2}\b", line):
            continue
        for driver in known_drivers:
            if driver not in line:
                continue
            driver_start = line.find(driver)
            team = ""
            prefix = line[:driver_start].strip()
            for candidate in known_teams:
                if candidate in prefix:
                    team = _normalize_team(candidate)
                    break
            if not team:
                team = DRIVER_TEAM_MAP.get(driver, "")
            if team and (driver, team) not in pairs:
                pairs.append((driver, team))
            break
    return pairs


def _build_entity_context(extracted_data: dict[str, Any], text: str) -> tuple[list[str], list[str], list[str]]:
    drivers = _clean_names(extracted_data.get("drivers"))
    teams = [_normalize_team(team) for team in _clean_names(extracted_data.get("teams"))]
    pairs = _driver_team_pairs_from_text(text)

    if not pairs:
        for driver in drivers:
            team = DRIVER_TEAM_MAP.get(driver)
            if team:
                pairs.append((driver, team))

    for driver, team in pairs:
        if driver not in drivers:
            drivers.append(driver)
        if team and team not in teams:
            teams.append(team)

    known_entities: list[str] = []
    for driver in drivers:
        team = ""
        for pair_driver, pair_team in pairs:
            if pair_driver == driver:
                team = pair_team
                break
        if not team:
            team = DRIVER_TEAM_MAP.get(driver, "")
        known_entities.append(f"**{driver} ({team})**" if team else f"**{driver}**")

    return drivers, teams, known_entities


def _detect_doc_type(title: str, document_type: str | None) -> str:
    normalized_title = title.lower().strip()
    for keyword, doc_type in TITLE_TYPE_RULES:
        if keyword in normalized_title:
            return doc_type
    if document_type:
        return LEGACY_TYPE_MAP.get(document_type, document_type.upper())
    return "OTHER"


def _impact_level_for(doc_type: str) -> str:
    return IMPACT_LEVELS.get(doc_type, "LOW")


def _format_entity_mentions(text: str, drivers: list[str], teams: list[str]) -> str:
    formatted = text
    for driver in sorted(drivers, key=len, reverse=True):
        team = DRIVER_TEAM_MAP.get(driver)
        if not team:
            continue
        full_marker = f"**{driver} ({team})**"
        formatted = re.sub(
            rf"(?<!\*)\b{re.escape(driver)}\s*\(\s*{re.escape(team)}\s*\)(?!\*)",
            full_marker,
            formatted,
        )
        formatted = re.sub(
            rf"(?<!\*)\b{re.escape(driver)}\b(?!\s*\()",
            full_marker,
            formatted,
        )
    return formatted


def _limit_words(text: str, max_words: int = 120) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    trimmed = " ".join(words[:max_words]).rstrip()
    if trimmed.endswith((".", "!", "?")):
        return trimmed
    return f"{trimmed}."


def _heuristic_impact_summary(
    *,
    title: str,
    doc_type: str,
    drivers: list[str],
    teams: list[str],
    extracted_data: dict[str, Any],
) -> str:
    if doc_type in NO_IMPACT_DOC_TYPES:
        return DEFAULT_NO_IMPACT_SUMMARY

    penalty = extracted_data.get("penalty_type")
    session = extracted_data.get("session")
    lines: list[str] = []
    primary_driver = drivers[0] if drivers else None
    primary_team = DRIVER_TEAM_MAP.get(primary_driver, "") if primary_driver else ""
    actor = f"**{primary_driver} ({primary_team})**" if primary_driver and primary_team else None

    if doc_type == "PU_USAGE" and actor:
        lines.append(f"- {actor} has new power unit elements logged, increasing future grid-penalty exposure.")
    elif doc_type == "PARC_FERME_CHANGE" and actor:
        lines.append(
            f"- {actor} is named in an FIA parc ferme change log covering approved replacements or setup changes."
        )
        lines.append(
            "- This document usually records authorised operational work, not an automatic penalty or technical breach."
        )
    elif doc_type == "PARC_FERME_CHANGE":
        lines.append("- The FIA logged approved parts or parameter changes under parc ferme conditions.")
        lines.append("- Treat this as an operational update unless the document explicitly states a sanction or compliance failure.")
    elif doc_type in {"RACE_TRACK_LIMITS", "QUALI_TRACK_LIMITS"} and actor:
        lines.append(f"- {actor} had lap-time deletions recorded, which can reshape the official order for {session or 'the session'}.")
    elif doc_type in {"FINAL_GRID", "FINAL_RACE_RESULT", "PROVISIONAL_RESULT", "PROVISIONAL_GRID", "QUALIFYING_RESULT", "PROVISIONAL_QUALI", "SPRINT_RESULT", "SPRINT_GRID"}:
        lines.append(f"- {title} updates the official competitive order and should be monitored for direct classification or grid consequences.")
    elif doc_type == "STEWARDS_DECISION" and actor:
        lines.append(f"- {actor} is named in a steward decision with potential sporting consequences.")
    elif doc_type == "SCRUTINEERING_REPORT":
        subject = actor or "named cars"
        lines.append(f"- {subject} remain under technical or scrutineering monitoring with no confirmed sporting change stated here.")
    elif doc_type == "TYRE_BRIEFING":
        subject = ", ".join(f"**{team}**" for team in teams[:2]) if teams else "teams"
        lines.append(f"- {subject} receive tyre allocation guidance that may influence stint planning and compound strategy.")
    elif doc_type == "CHAMPIONSHIP_UPDATE":
        lines.append("- Championship points were updated, affecting the title and points picture after the classified result.")

    if penalty and doc_type not in {"RACE_TRACK_LIMITS", "QUALI_TRACK_LIMITS"}:
        penalty_text = str(penalty).replace("_", " ")
        lines.append(f"- Steward outcome recorded: {penalty_text}.")

    if not lines:
        return DEFAULT_NO_IMPACT_SUMMARY
    return "### Race Impact\n\n" + "\n".join(lines[:3])


def _clean_race_impact_output(content: str, *, drivers: list[str], teams: list[str]) -> str:
    normalized = content.replace("\r", "").strip()
    normalized = normalized.replace("```markdown", "").replace("```", "").strip()
    if "No meaningful performance or sporting impact." in normalized:
        return DEFAULT_NO_IMPACT_SUMMARY

    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    bullet_lines: list[str] = []
    for line in lines:
        if line.lower() == "### race impact":
            continue
        if line.startswith("- "):
            bullet_lines.append(line)
        elif line.startswith("* "):
            bullet_lines.append(f"- {line[2:].strip()}")
        elif line:
            bullet_lines.append(f"- {line.lstrip('-* ').strip()}")

    cleaned_bullets: list[str] = []
    for line in bullet_lines:
        formatted = _format_entity_mentions(line, drivers, teams)
        cleaned_bullets.append(_limit_words(" ".join(formatted.split())))

    body = "\n".join(cleaned_bullets[:4]).strip()
    if not body:
        return DEFAULT_NO_IMPACT_SUMMARY

    result = f"### Race Impact\n\n{body}"
    if len(result.split()) > 122:
        header = "### Race Impact"
        available_words = 120 - len(header.split())
        trimmed_body = _limit_words(body, max_words=max(available_words, 1))
        result = f"{header}\n\n{trimmed_body}"
    return result


def _is_summary_acceptable(summary: str) -> bool:
    normalized = summary.strip()
    if not normalized.startswith("### Race Impact"):
        return False
    if normalized == DEFAULT_NO_IMPACT_SUMMARY:
        return True
    body_lines = [line for line in normalized.splitlines() if line.startswith("- ")]
    return bool(body_lines)


class DashboardSummaryClient:
    """Generates race-impact-only summaries and metadata for FIA documents."""

    def __init__(self) -> None:
        self.api_url = normalize_chat_completions_url(
            resolve_chat_setting("SUMMARY_LLM_API_URL", "MISTRAL_API_URL", "LLM_API_URL")
        )
        self.api_key = resolve_chat_setting("SUMMARY_LLM_API_KEY", "MISTRAL_API_KEY", "LLM_API_KEY")
        self.model = resolve_chat_setting(
            "SUMMARY_LLM_MODEL",
            "MISTRAL_MODEL",
            "LLM_MODEL",
            default="mistral-small-2603",
        )
        self.timeout = int(os.getenv("LLM_TIMEOUT_SECONDS", "45"))

    @property
    def enabled(self) -> bool:
        return bool(self.api_url and self.api_key and self.model)

    def summarize(
        self,
        *,
        title: str,
        grand_prix: str,
        document_type: str | None,
        document_family: str | None,
        raw_text: str,
        extracted_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        del grand_prix, document_family

        extracted_data = extracted_data or {}
        doc_type = _detect_doc_type(title, document_type)
        impact_level = _impact_level_for(doc_type)
        drivers_affected, teams_affected, known_entities = _build_entity_context(extracted_data, raw_text)

        base_result = {
            "doc_type": doc_type,
            "impact_level": impact_level,
            "drivers_affected": drivers_affected,
            "teams_affected": teams_affected,
            "version": DASHBOARD_SUMMARY_VERSION,
        }

        if doc_type in NO_IMPACT_DOC_TYPES:
            return {
                **base_result,
                "summary": DEFAULT_NO_IMPACT_SUMMARY,
                "race_impact_summary": DEFAULT_NO_IMPACT_SUMMARY,
                "provider": "rule_based",
            }

        heuristic_summary = _heuristic_impact_summary(
            title=title,
            doc_type=doc_type,
            drivers=drivers_affected,
            teams=teams_affected,
            extracted_data=extracted_data,
        )

        if not self.enabled or doc_type not in LLM_ANALYSIS_DOC_TYPES:
            return {
                **base_result,
                "summary": heuristic_summary,
                "race_impact_summary": heuristic_summary,
                "provider": "fallback",
            }

        prompt = (
            "You are a Formula 1 regulatory intelligence analyst.\n\n"
            "Your task is to extract ONLY the race impact from an FIA document.\n\n"
            "Ignore procedural language, inspection lists, and administrative text.\n\n"
            "For parc ferme change logs, distinguish approved replacements or setup changes from penalties or technical breaches.\n"
            "Do not imply illegality or sanctions unless the document explicitly says so.\n\n"
            "Focus only on:\n\n"
            "- penalties\n"
            "- grid changes\n"
            "- deleted lap times\n"
            "- power unit changes\n"
            "- parc fermé repairs\n"
            "- scrutineering investigations\n"
            "- tyre strategy implications\n"
            "- championship implications\n\n"
            "Output rules:\n\n"
            "Start with:\n"
            "### Race Impact\n\n"
            "Bullet points only.\n\n"
            "Maximum 120 words.\n\n"
            "Highlight driver and team names using:\n"
            "**Driver Name (Team)**\n\n"
            "If the document has no operational effect on the race weekend, write exactly:\n\n"
            "No meaningful performance or sporting impact.\n\n"
            f"Document type:\n{doc_type}\n\n"
            f"Known entities:\n{known_entities}\n\n"
            f"Document text:\n{raw_text[:18000]}"
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
                            "You extract race-impact intelligence from FIA Formula One documents. "
                            "Return the requested markdown only."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = extract_message_text(payload)
        summary = _clean_race_impact_output(
            content,
            drivers=drivers_affected,
            teams=teams_affected,
        )
        if not _is_summary_acceptable(summary):
            summary = heuristic_summary
            provider = "fallback"
        else:
            provider = "llm"
        return {
            **base_result,
            "summary": summary,
            "race_impact_summary": summary,
            "provider": provider,
        }
