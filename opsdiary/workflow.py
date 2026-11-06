"""Application use cases for reviewed incident capture and analysis."""

from dataclasses import dataclass
from pathlib import Path

from opsdiary.enrichment import enrich_incident
from opsdiary.extraction import SYMPTOM_LABELS, extract_incident
from opsdiary.patterns import detect_patterns
from opsdiary.reporting import build_incident_report
from opsdiary.schema import IncidentDraft
from opsdiary.settings import DATABASE_PATH
from opsdiary.storage import get_incident, save_incident


@dataclass(frozen=True)
class IncidentAnalysis:
    incident: dict
    service_context: dict | None
    pattern_result: dict
    summary: str
    report: str


class IncidentWorkflow:
    """Coordinate domain operations without depending on the Streamlit UI."""

    def __init__(self, services: list[dict], db_path: Path | str = DATABASE_PATH):
        self.services = list(services)
        self.service_ids = {service["service_id"] for service in self.services}
        self.service_names = {
            service["service_id"]: service["name"] for service in self.services
        }
        self.db_path = db_path

    def extract_candidate(self, transcript: str) -> IncidentDraft:
        return extract_incident(transcript, self.services)

    def save_reviewed(self, draft_data: IncidentDraft | dict, source: str) -> str:
        """Validate reviewed fields at the application boundary before persistence."""
        draft = (
            draft_data
            if isinstance(draft_data, IncidentDraft)
            else IncidentDraft.model_validate(draft_data)
        )
        if draft.service_id and draft.service_id not in self.service_ids:
            raise ValueError(f"Unknown service: {draft.service_id}")
        unknown_symptoms = set(draft.symptoms) - set(SYMPTOM_LABELS)
        if unknown_symptoms:
            raise ValueError("Unknown symptom tags: " + ", ".join(sorted(unknown_symptoms)))
        return save_incident(
            draft.model_dump(mode="json"),
            db_path=self.db_path,
            source=source,
        )

    def analyze(self, incident_id: str) -> IncidentAnalysis | None:
        incident = get_incident(incident_id, db_path=self.db_path)
        if not incident:
            return None
        service_context = enrich_incident(
            incident.get("service_id"),
            incident.get("environment"),
            db_path=self.db_path,
        )
        pattern_result = detect_patterns(
            incident.get("service_id"),
            incident.get("environment"),
            incident.get("symptoms", []),
            as_of=incident.get("created_at"),
            db_path=self.db_path,
        )
        return IncidentAnalysis(
            incident=incident,
            service_context=service_context,
            pattern_result=pattern_result,
            summary=self._summary(incident),
            report=build_incident_report(incident, service_context, pattern_result),
        )

    def _summary(self, incident: dict) -> str:
        service_name = self.service_names.get(incident.get("service_id"), "Unknown service")
        environment = incident.get("environment") or "unspecified environment"
        phrases = [f"{service_name} mein {environment} incident report hua."]
        if incident.get("severity"):
            phrases.append(f"Severity {incident['severity']} hai.")
        tags = [SYMPTOM_LABELS.get(tag, tag) for tag in incident.get("symptoms", [])]
        if tags:
            phrases.append("Reported symptoms: " + ", ".join(tags) + ".")
        if incident.get("impact_summary"):
            impact = incident["impact_summary"].rstrip(".!?")
            phrases.append("Impact: " + impact + ".")
        if incident.get("deployment_reference"):
            phrases.append("Mentioned deployment: " + incident["deployment_reference"] + ".")
        return " ".join(phrases)
