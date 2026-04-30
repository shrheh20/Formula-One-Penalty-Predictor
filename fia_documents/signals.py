"""Signal and alert generation for parsed FIA documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .db import Alert, Document, Signal


@dataclass(slots=True)
class SignalDraft:
    signal_type: str
    category: str
    grand_prix: str
    session: str | None
    driver: str | None
    team: str | None
    car_number: int | None
    severity: str
    status: str
    entity_key: str
    published_time: Any
    payload: dict[str, Any]


@dataclass(slots=True)
class AlertDraft:
    category: str
    priority: str
    title: str
    message: str
    status: str
    grand_prix: str
    published_time: Any
    payload: dict[str, Any]


class SignalBuilder:
    def build(self, document: Document) -> list[SignalDraft]:
        extracted = document.extracted_data or {}
        document_type = document.document_type or extracted.get("document_type") or "other"
        document_family = document.document_family or extracted.get("document_family") or "other"

        builders = {
            "new_pu_elements": self._build_component_change_signals,
            "component_usage": self._build_component_usage_signals,
            "entry_list": self._build_session_result_signal,
            "championship_points": self._build_points_signal,
            "parc_ferme_parts_and_parameters_changes": self._build_parc_ferme_signal,
            "parc_ferme_issues": self._build_parc_ferme_signal,
            "technical_directive": self._build_parc_ferme_signal,
            "post_race_checks": self._build_parc_ferme_signal,
        }
        builder = builders.get(document_type)
        if builder is not None:
            return builder(document, extracted)
        if document_family == "steward_decision":
            return self._build_steward_matter_signals(document, extracted)
        if document_family == "sporting_results":
            return self._build_session_result_signal(document, extracted)
        if document_family in {"scrutineering", "technical_compliance", "technical_directive"}:
            return self._build_parc_ferme_signal(document, extracted)
        if document_family == "component_allocation":
            return self._build_component_usage_signals(document, extracted)
        return self._build_document_posted_signal(document, extracted)

    def build_alert(self, signal: SignalDraft) -> AlertDraft | None:
        category_titles = {
            "component": "Component update",
            "stewards": "Steward update",
            "results": "Official result posted",
            "technical": "Technical issue",
            "standings": "Standings update",
            "documents": "New FIA document",
        }
        title_prefix = category_titles.get(signal.category, "FIA update")
        subject = signal.driver or signal.team or signal.payload.get("title") or signal.signal_type.replace("_", " ")
        title = f"{title_prefix}: {subject}"

        if signal.signal_type == "component_change":
            component = signal.payload.get("component")
            previous = signal.payload.get("previously_used")
            message = (
                f"{signal.driver or 'A driver'} has a new {component} logged by the FIA"
                f"{f' after {previous} previously used units' if previous is not None else ''}."
            )
        elif signal.signal_type == "investigation_opened":
            message = f"{signal.driver or 'A driver'} is under steward review: {signal.payload.get('incident_summary', 'investigation opened')}."
        elif signal.signal_type == "steward_decision_issued":
            message = signal.payload.get("verdict_summary") or f"New steward decision posted for {signal.driver or 'the event'}."
        elif signal.signal_type == "session_result_posted":
            message = f"Official {signal.session or 'session'} results posted for {signal.grand_prix}."
        elif signal.signal_type == "standings_updated":
            message = f"Official championship standings updated after {signal.grand_prix}."
        elif signal.signal_type == "technical_issue_logged":
            message = signal.payload.get("incident_summary") or "A new technical issue has been logged by the FIA."
        else:
            message = f"New FIA document posted for {signal.grand_prix}: {signal.payload.get('title', 'update available')}."

        return AlertDraft(
            category=signal.category,
            priority=signal.severity,
            title=title[:255],
            message=message,
            status="open",
            grand_prix=signal.grand_prix,
            published_time=signal.published_time,
            payload=signal.payload,
        )

    def _base_payload(self, document: Document, extracted: dict[str, Any]) -> dict[str, Any]:
        return {
            "document_id": document.id,
            "doc_number": document.doc_number,
            "title": document.title,
            "document_type": document.document_type,
            "document_family": document.document_family,
            "incident_summary": extracted.get("incident_summary"),
            "verdict_summary": extracted.get("verdict_summary"),
            "penalty_type": extracted.get("penalty_type"),
            "grid_penalty_places": extracted.get("grid_penalty_places"),
        }

    def _build_component_change_signals(self, document: Document, extracted: dict[str, Any]) -> list[SignalDraft]:
        signals: list[SignalDraft] = []
        for entry in extracted.get("entries", []) or []:
            if not isinstance(entry, dict):
                continue
            component = entry.get("component")
            driver = entry.get("driver")
            signals.append(
                SignalDraft(
                    signal_type="component_change",
                    category="component",
                    grand_prix=document.grand_prix,
                    session=extracted.get("session"),
                    driver=driver,
                    team=entry.get("team"),
                    car_number=entry.get("car_number"),
                    severity="medium",
                    status="active",
                    entity_key=f"{document.grand_prix}:{driver or 'unknown'}:{component or 'component'}",
                    published_time=document.published_time,
                    payload={**self._base_payload(document, extracted), **entry},
                )
            )
        return signals or self._build_document_posted_signal(document, extracted)

    def _build_component_usage_signals(self, document: Document, extracted: dict[str, Any]) -> list[SignalDraft]:
        signals: list[SignalDraft] = []
        for entry in extracted.get("entries", []) or []:
            if not isinstance(entry, dict):
                continue
            signals.append(
                SignalDraft(
                    signal_type="component_usage_snapshot",
                    category="component",
                    grand_prix=document.grand_prix,
                    session=extracted.get("session"),
                    driver=entry.get("driver"),
                    team=entry.get("team"),
                    car_number=entry.get("car_number"),
                    severity="low",
                    status="active",
                    entity_key=f"{document.grand_prix}:{entry.get('driver') or 'unknown'}:usage",
                    published_time=document.published_time,
                    payload={**self._base_payload(document, extracted), **entry},
                )
            )
        return signals or self._build_document_posted_signal(document, extracted)

    def _build_steward_matter_signals(self, document: Document, extracted: dict[str, Any]) -> list[SignalDraft]:
        signal_type = "investigation_opened" if document.document_type == "summons" else "steward_decision_issued"
        return [
            SignalDraft(
                signal_type=signal_type,
                category="stewards",
                grand_prix=document.grand_prix,
                session=extracted.get("session"),
                driver=(extracted.get("drivers") or [None])[0],
                team=(extracted.get("teams") or [None])[0],
                car_number=(extracted.get("car_numbers") or [None])[0],
                severity="high",
                status="active",
                entity_key=f"{document.grand_prix}:{document.doc_number}:{signal_type}",
                published_time=document.published_time,
                payload=self._base_payload(document, extracted),
            )
        ]

    def _build_session_result_signal(self, document: Document, extracted: dict[str, Any]) -> list[SignalDraft]:
        return [
            SignalDraft(
                signal_type="session_result_posted",
                category="results",
                grand_prix=document.grand_prix,
                session=extracted.get("session"),
                driver=None,
                team=None,
                car_number=None,
                severity="medium",
                status="active",
                entity_key=f"{document.grand_prix}:{document.document_type}:{document.doc_number}",
                published_time=document.published_time,
                payload=self._base_payload(document, extracted),
            )
        ]

    def _build_points_signal(self, document: Document, extracted: dict[str, Any]) -> list[SignalDraft]:
        return [
            SignalDraft(
                signal_type="standings_updated",
                category="standings",
                grand_prix=document.grand_prix,
                session=extracted.get("session"),
                driver=None,
                team=None,
                car_number=None,
                severity="medium",
                status="active",
                entity_key=f"{document.grand_prix}:standings:{document.doc_number}",
                published_time=document.published_time,
                payload=self._base_payload(document, extracted),
            )
        ]

    def _build_parc_ferme_signal(self, document: Document, extracted: dict[str, Any]) -> list[SignalDraft]:
        return [
            SignalDraft(
                signal_type="technical_issue_logged",
                category="technical",
                grand_prix=document.grand_prix,
                session=extracted.get("session"),
                driver=(extracted.get("drivers") or [None])[0],
                team=(extracted.get("teams") or [None])[0],
                car_number=(extracted.get("car_numbers") or [None])[0],
                severity="high",
                status="active",
                entity_key=f"{document.grand_prix}:{document.doc_number}:technical",
                published_time=document.published_time,
                payload=self._base_payload(document, extracted),
            )
        ]

    def _build_document_posted_signal(self, document: Document, extracted: dict[str, Any]) -> list[SignalDraft]:
        return [
            SignalDraft(
                signal_type="document_posted",
                category="documents",
                grand_prix=document.grand_prix,
                session=extracted.get("session"),
                driver=None,
                team=None,
                car_number=None,
                severity="low",
                status="active",
                entity_key=f"{document.grand_prix}:{document.doc_number}:document",
                published_time=document.published_time,
                payload=self._base_payload(document, extracted),
            )
        ]


def upsert_signals_and_alerts(session, document: Document, drafts: list[SignalDraft], builder: SignalBuilder) -> None:
    session.query(Alert).filter(Alert.document_id == document.id).delete()
    session.query(Signal).filter(Signal.document_id == document.id).delete()

    seen_keys: set[tuple[str, str]] = set()
    for draft in drafts:
        key = (draft.signal_type, draft.entity_key)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        signal = Signal(
            document_id=document.id,
            signal_type=draft.signal_type,
            category=draft.category,
            grand_prix=draft.grand_prix,
            session=draft.session,
            driver=draft.driver,
            team=draft.team,
            car_number=draft.car_number,
            severity=draft.severity,
            status=draft.status,
            entity_key=draft.entity_key,
            published_time=draft.published_time,
            payload=draft.payload,
        )
        session.add(signal)
        session.flush()

        alert_draft = builder.build_alert(draft)
        if alert_draft is None:
            continue
        alert = Alert(
            signal_id=signal.id,
            document_id=document.id,
            category=alert_draft.category,
            priority=alert_draft.priority,
            title=alert_draft.title,
            message=alert_draft.message,
            status=alert_draft.status,
            grand_prix=alert_draft.grand_prix,
            published_time=alert_draft.published_time,
            payload=alert_draft.payload,
        )
        session.add(alert)
