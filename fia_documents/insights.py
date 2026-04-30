"""Derived dashboard insights for FIA documents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from .db import Document


FAMILY_LABELS = {
    "steward_decision": "Stewards",
    "component_allocation": "Power Unit",
    "technical_directive": "Technical",
    "technical_compliance": "Technical",
    "sporting_results": "Results",
    "scrutineering": "Scrutineering",
    "race_control": "Race Control",
    "procedure": "Procedure",
    "other": "Review",
}

IMPORTANCE_SCORES = {
    "high": 3,
    "medium": 2,
    "info": 1,
}


def _clean_names(values: list[Any] | None, limit: int = 3) -> list[str]:
    cleaned: list[str] = []
    for value in values or []:
        normalized = " ".join(str(value).split())
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
        if len(cleaned) >= limit:
            break
    return cleaned


def _importance_for(document: Document) -> str:
    if document.document_family in {"steward_decision", "technical_directive", "technical_compliance"}:
        return "high"
    if document.document_family in {"component_allocation", "sporting_results"}:
        return "medium"
    return "info"


def _is_competitive_state(document: Document) -> bool:
    return document.document_type in {
        "final_starting_grid",
        "provisional_starting_grid",
        "final_race_classification",
        "provisional_race_classification",
        "final_sprint_classification",
        "provisional_sprint_classification",
        "championship_points",
        "final_qualifying_classification",
        "provisional_qualifying_classification",
    }


def _what_happened_for(document: Document) -> str:
    extracted = document.extracted_data or {}
    title = document.title or "FIA document update"
    family = document.document_family or "other"
    session = extracted.get("session")
    penalty = extracted.get("penalty_type")
    document_type = document.document_type or ""

    if family == "steward_decision":
        if "summons" in title.lower():
            return "Stewards issued a summons linked to an on-weekend incident."
        if penalty:
            return f"Stewards published an official decision with a {penalty.replace('_', ' ')} outcome."
        return "Stewards published an official decision affecting the weekend."

    if family in {"technical_directive", "technical_compliance"}:
        if "parts and parameters" in title.lower() and ("parc ferme" in title.lower() or "parc ferm" in title.lower()):
            return "The FIA published an approved parc ferme parts and parameters change log."
        if "parc ferme" in title.lower() or "parc ferm" in title.lower():
            return "The FIA logged a technical update under parc ferme conditions."
        return "The FIA published a technical or compliance update."

    if family == "component_allocation":
        if "new pu elements" in title.lower():
            return "New power unit elements were declared for this competition."
        return "Power unit allocation information was updated."

    if family == "sporting_results":
        if document_type == "championship_points" or "championship points" in title.lower():
            return "Official championship standings were updated after the latest classified session."
        if document_type in {"final_starting_grid", "provisional_starting_grid", "final_sprint_starting_grid", "provisional_sprint_starting_grid"} or "starting grid" in title.lower():
            return f"The {title.lower()} confirmed the order for {session or 'the next competitive session'}."
        if document_type in {"final_race_classification", "provisional_race_classification", "final_sprint_classification", "provisional_sprint_classification", "final_qualifying_classification", "provisional_qualifying_classification"} or "classification" in title.lower():
            return f"{title} confirmed the official order for {session or 'the session'}."
        if document_type == "entry_list" or "entry list" in title.lower():
            return "The official entry list confirmed the weekend field and team entries."
        return f"{title} updated the official competitive record for the weekend."

    if family == "scrutineering":
        if session:
            return f"Scrutineering checks were published for {session}."
        return "The FIA published the latest scrutineering checks for the weekend."

    if family == "race_control":
        if "deleted lap" in title.lower():
            return "Race control confirmed deleted lap times affecting the running order."
        if "classification" in title.lower():
            return f"{title} adjusted the competitive order managed by race control."
        return f"{title} updated race control instructions for teams and officials."

    if family == "procedure":
        return "The FIA published a procedural update for the race weekend."

    return f"The FIA published {title.lower()}."


def _why_it_matters_for(document: Document) -> str:
    extracted = document.extracted_data or {}
    title = document.title or "FIA document update"
    family = document.document_family or "other"
    session = extracted.get("session")
    drivers = _clean_names(extracted.get("drivers"))
    teams = _clean_names(extracted.get("teams"))
    document_type = document.document_type or ""

    if family == "steward_decision":
        if drivers:
            return f"Why it matters: this directly affects steward exposure for {', '.join(drivers)}."
        return "Why it matters: this may change official steward status, penalties, or investigations."

    if family in {"technical_directive", "technical_compliance"}:
        if "parts and parameters" in title.lower() and ("parc ferme" in title.lower() or "parc ferm" in title.lower()):
            return "Why it matters: this records authorised setup or repair work and is not, by itself, a penalty notice."
        if teams:
            return f"Why it matters: compliance pressure now touches {', '.join(teams)}."
        return "Why it matters: this can affect car legality, setup freedom, or parc ferme status."

    if family == "component_allocation":
        return "Why it matters: power unit usage shapes future grid-penalty risk."

    if family == "sporting_results":
        if document_type == "championship_points" or "championship points" in title.lower():
            return "Why it matters: this locks in the official championship picture after the session."
        if document_type in {"final_starting_grid", "provisional_starting_grid", "final_sprint_starting_grid", "provisional_sprint_starting_grid"} or "starting grid" in title.lower():
            return "Why it matters: this locks the competitive order for lights out."
        if document_type in {"final_race_classification", "provisional_race_classification", "final_sprint_classification", "provisional_sprint_classification", "final_qualifying_classification", "provisional_qualifying_classification"} or "classification" in title.lower():
            return f"Why it matters: this confirms the official result for {session or 'the session'}."
        if document_type == "entry_list" or "entry list" in title.lower():
            return "Why it matters: this confirms who is officially entered for the weekend."
        return "Why it matters: this confirms the official competitive state."

    if family == "scrutineering":
        return "Why it matters: scrutineering can surface compliance or eligibility issues."

    if family in {"race_control", "procedure"}:
        return "Why it matters: teams may need to change operations or execution."

    return "Why it matters: this is part of the official FIA weekend record."


def _affected_entities_for(document: Document) -> str:
    extracted = document.extracted_data or {}
    session = extracted.get("session")
    drivers = _clean_names(extracted.get("drivers"))
    teams = _clean_names(extracted.get("teams"))
    grand_prix = document.grand_prix
    parts: list[str] = []
    if session:
        parts.append(f"Session: {session}")
    if drivers:
        parts.append(f"Drivers: {', '.join(drivers)}")
    elif teams:
        parts.append(f"Teams: {', '.join(teams)}")
    if not parts and grand_prix:
        parts.append(grand_prix)
    return " · ".join(parts)


def _priority_key(document: Document) -> tuple[int, datetime]:
    importance = _importance_for(document)
    published = document.published_time or datetime.fromtimestamp(0, tz=timezone.utc)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return (IMPORTANCE_SCORES.get(importance, 0), published)


class DocumentInsightsService:
    """Builds dashboard-friendly insight cards from parsed FIA documents."""

    def get_latest_insights(
        self,
        db: Session,
        *,
        limit: int = 8,
        grand_prix: str | None = None,
    ) -> dict[str, Any]:
        query = (
            db.query(Document)
            .filter(Document.extracted_data.is_not(None))
            .filter(Document.is_recalled.is_(False))
            .filter(Document.document_family.is_not(None))
            .order_by(Document.published_time.desc().nullslast(), Document.id.desc())
        )
        if grand_prix:
            query = query.filter(Document.grand_prix.ilike(f"%{grand_prix}%"))

        documents = query.limit(max(limit * 4, 24)).all()

        family_counts: dict[str, int] = {}
        for document in documents:
            family = document.document_family or "other"
            family_counts[family] = family_counts.get(family, 0) + 1

        ranked = sorted(documents, key=_priority_key, reverse=True)
        highlights: list[dict[str, Any]] = []
        for document in ranked[:limit]:
            extracted = document.extracted_data or {}
            family = document.document_family or "other"
            source = extracted.get("source") or {}
            classification = source.get("classification") or {}
            highlights.append(
                {
                    "document_id": document.id,
                    "doc_number": document.doc_number,
                    "title": document.title,
                    "grand_prix": document.grand_prix,
                    "published_time": (
                        document.published_time.isoformat() if document.published_time else None
                    ),
                    "document_type": document.document_type,
                    "document_family": family,
                    "category_label": FAMILY_LABELS.get(family, "Review"),
                    "importance": _importance_for(document),
                    "what_happened": _what_happened_for(document),
                    "why_it_matters": _why_it_matters_for(document),
                    "affected_entities": _affected_entities_for(document),
                    "drivers": _clean_names(extracted.get("drivers")),
                    "teams": _clean_names(extracted.get("teams")),
                    "session": extracted.get("session"),
                    "pdf_url": document.pdf_url,
                    "source_page_url": document.source_page_url,
                    "llm_used": bool(source.get("llm_used")),
                    "classification_provider": classification.get("provider") or "rules",
                    "is_competitive_state": _is_competitive_state(document),
                    "dashboard_summary": document.dashboard_summary,
                    "dashboard_summary_provider": document.dashboard_summary_provider,
                }
            )

        critical_highlights = [item for item in highlights if item["importance"] == "high"][:3]
        document_feed = sorted(
            highlights,
            key=lambda item: (item["published_time"] or "", item["importance"]),
            reverse=True,
        )

        headline_bits: list[str] = []
        if family_counts.get("steward_decision"):
            headline_bits.append(f"{family_counts['steward_decision']} steward action(s)")
        technical_count = family_counts.get("technical_compliance", 0) + family_counts.get("technical_directive", 0)
        if technical_count:
            headline_bits.append(f"{technical_count} technical update(s)")
        if any(item["is_competitive_state"] for item in highlights):
            headline_bits.append("official results or grid updates posted")

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "grand_prix": grand_prix,
            "headline": " · ".join(headline_bits) if headline_bits else "No major FIA actions in the latest batch.",
            "summary": {
                "documents_considered": len(documents),
                "highlights_returned": len(highlights),
                "critical_count": len(critical_highlights),
                "family_counts": family_counts,
            },
            "critical_highlights": critical_highlights,
            "document_feed": document_feed,
            "highlights": highlights,
        }
