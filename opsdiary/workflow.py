"""Application use cases for reviewed incident capture and analysis."""

from dataclasses import dataclass
from pathlib import Path

from opsdiary.enrichment import enrich_incident
from opsdiary.extraction import SYMPTOM_LABELS, extract_incident
from opsdiary.observability import observed_stage, trace_scope
from opsdiary.patterns import detect_patterns
from opsdiary.retrieval import retrieve_incidents, retrieve_runbooks
from opsdiary.reporting import build_incident_report
from opsdiary.schema import IncidentDraft
from opsdiary.settings import DATABASE_PATH
from opsdiary.storage import get_incident, save_incident


@dataclass(frozen=True)
class IncidentAnalysis:
    incident: dict
    service_context: dict | None
    pattern_result: dict
    related_records: list[dict]
    runbook_references: list[dict]
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

    def extract_candidate(
        self, transcript: str, trace_id: str | None = None
    ) -> IncidentDraft:
        with trace_scope(trace_id) as active_trace_id:
            with observed_stage("incident.extract"):
                draft = extract_incident(transcript, self.services)
            return draft.model_copy(update={"trace_id": active_trace_id})

    def save_reviewed(
        self,
        draft_data: IncidentDraft | dict,
        source: str,
        candidate_data: IncidentDraft | dict | None = None,
    ) -> str:
        """Validate reviewed fields at the application boundary before persistence."""
        supplied_trace_id = (
            draft_data.trace_id
            if isinstance(draft_data, IncidentDraft)
            else draft_data.get("trace_id")
        )
        with trace_scope(supplied_trace_id) as active_trace_id:
            metadata = {"source": source}
            with observed_stage("incident.save", metadata=metadata):
                draft = (
                    draft_data
                    if isinstance(draft_data, IncidentDraft)
                    else IncidentDraft.model_validate(draft_data)
                )
                candidate = (
                    draft
                    if candidate_data is None
                    else (
                        candidate_data
                        if isinstance(candidate_data, IncidentDraft)
                        else IncidentDraft.model_validate(candidate_data)
                    )
                )
                if draft.service_id and draft.service_id not in self.service_ids:
                    raise ValueError(f"Unknown service: {draft.service_id}")
                unknown_symptoms = set(draft.symptoms) - set(SYMPTOM_LABELS)
                if unknown_symptoms:
                    raise ValueError(
                        "Unknown symptom tags: " + ", ".join(sorted(unknown_symptoms))
                    )
                draft = draft.model_copy(update={"trace_id": active_trace_id})
                fields = (
                    "service_id", "environment", "severity", "symptoms",
                    "impact_summary", "deployment_reference",
                )
                candidate_fields = candidate.model_dump(mode="json", include=set(fields))
                confirmed_fields = draft.model_dump(mode="json", include=set(fields))
                review_audit = {
                    "candidate_fields": candidate_fields,
                    "confirmed_fields": confirmed_fields,
                    "changed_fields": [
                        field for field in fields
                        if candidate_fields[field] != confirmed_fields[field]
                    ],
                }
                incident_id = save_incident(
                    draft.model_dump(mode="json"),
                    db_path=self.db_path,
                    source=source,
                    review_audit=review_audit,
                )
                metadata["incident_id"] = incident_id
                return incident_id

    def analyze(self, incident_id: str) -> IncidentAnalysis | None:
        incident = get_incident(incident_id, db_path=self.db_path)
        if not incident:
            return None
        saved_trace_id = incident.get("extraction", {}).get("trace_id")
        with trace_scope(saved_trace_id):
            with observed_stage("incident.analysis", incident_id=incident_id):
                service_context = enrich_incident(
                    incident.get("service_id"),
                    incident.get("environment"),
                    db_path=self.db_path,
                    deployment_reference=incident.get("deployment_reference"),
                )
                pattern_result = detect_patterns(
                    incident.get("service_id"),
                    incident.get("environment"),
                    incident.get("symptoms", []),
                    as_of=incident.get("created_at"),
                    db_path=self.db_path,
                )
                exact_match_ids = {
                    match["incident_id"] for match in pattern_result["matches"]
                }
                with observed_stage("context.retrieve", incident_id=incident_id):
                    related_records = retrieve_incidents(
                        incident.get("transcript", ""),
                        service_id=incident.get("service_id"),
                        environment=incident.get("environment"),
                        exclude_incident_id=incident_id,
                        limit=5,
                        db_path=self.db_path,
                    )
                related_records = [
                    record for record in related_records
                    if record["incident_id"] not in exact_match_ids
                ]
                with observed_stage("context.runbook_retrieve", incident_id=incident_id):
                    runbook_references = retrieve_runbooks(
                        incident.get("transcript", ""),
                        service_id=incident.get("service_id"),
                        environment=incident.get("environment"),
                        symptoms=incident.get("symptoms", []),
                        limit=3,
                        db_path=self.db_path,
                    )
                report = build_incident_report(
                    incident, service_context, pattern_result, related_records,
                    runbook_references,
                )
                return IncidentAnalysis(
                    incident=incident,
                    service_context=service_context,
                    pattern_result=pattern_result,
                    related_records=related_records,
                    runbook_references=runbook_references,
                    summary=self._summary(incident),
                    report=report,
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
