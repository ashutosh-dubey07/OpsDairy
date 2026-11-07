"""Build a plain Markdown brief from a saved incident and its supporting records."""

from opsdiary.extraction import SYMPTOM_LABELS


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" for line in (text or "").splitlines())


def build_incident_report(
    incident: dict,
    service: dict | None,
    pattern_result: dict,
    related_records: list[dict] | None = None,
    runbook_references: list[dict] | None = None,
) -> str:
    service_name = service.get("name") if service else "Unknown"
    symptom_labels = [SYMPTOM_LABELS.get(tag, tag) for tag in incident.get("symptoms", [])]
    lines = [
        f"# Incident {incident['incident_id']}",
        "",
        f"- Created: {incident.get('created_at', 'unknown')} UTC",
        f"- Source: {incident.get('source', 'unknown')}",
        f"- Service: {service_name} ({incident.get('service_id') or 'unconfirmed'})",
        f"- Environment: {incident.get('environment') or 'unspecified'}",
        f"- Severity: {incident.get('severity') or 'unspecified'}",
        "",
        "## Reported symptoms",
        "",
    ]
    if symptom_labels:
        lines.extend(f"- {label}" for label in symptom_labels)
    else:
        lines.append("No symptoms were confirmed.")

    if incident.get("impact_summary"):
        lines.extend(["", "## Impact note", "", incident["impact_summary"]])
    deployment_reference = incident.get("deployment_reference")
    if deployment_reference:
        lines.extend(["", "## Deployment reference verification", ""])
        referenced = service.get("referenced_deployment") if service else None
        if referenced:
            lines.append(
                f"Transcript version {deployment_reference} matched catalog deployment "
                f"{referenced['deployment_id']} ({referenced['version']}, commit "
                f"{referenced['commit_sha']})."
            )
        else:
            lines.append(
                f"Transcript mentions {deployment_reference}; no exact deployment version "
                "matched this service and environment in the catalog."
            )

    deployment = service.get("latest_deployment") if service else None
    lines.extend(["", "## Service and deployment context", ""])
    if service:
        lines.append(
            f"Owner: {service['owner']} | Criticality: {service['criticality']} | "
            f"Repository: {service['repository']}"
        )
    else:
        lines.append("No service catalog match was confirmed.")
    if deployment:
        lines.append(
            f"Latest catalog deployment (context only): {deployment['version']} "
            f"({deployment['environment']}) "
            f"at {deployment['deployed_at']} UTC; {deployment['deployment_id']}; "
            f"commit {deployment['commit_sha']}."
        )
        lines.append(
            "This record is not confirmation that the deployment caused the incident. "
            f"Change note: {deployment['change_summary']}"
        )
    else:
        lines.append("No deployment record matched this service and environment.")

    matches = pattern_result.get("matches", [])
    lines.extend(["", "## Matching historical records", ""])
    if matches:
        lines.append(
            f"{len(matches)} prior records matched within the last "
            f"{pattern_result.get('lookback_days', 30)} days. These are historical matches, not a prediction."
        )
        for match in matches:
            tags = ", ".join(
                SYMPTOM_LABELS.get(tag, tag) for tag in match.get("matched_symptoms", [])
            )
            lines.extend(
                [
                    "",
                    f"### {match['incident_id']} - {match['created_at']} UTC - {tags}",
                    "",
                    _quote(match.get("transcript", "")),
                ]
            )
            if match.get("deployment_id"):
                lines.append(f"\nLinked deployment: {match['deployment_id']}")
    else:
        lines.append("No prior records matched the selected service, environment, and symptoms.")

    lines.extend(["", "## Additional transcript search evidence", ""])
    if related_records:
        lines.append(
            "These records were retrieved by lexical transcript search. They are supporting "
            "references, not confirmation of a shared cause."
        )
        for record in related_records:
            matched_terms = ", ".join(record.get("matched_terms", [])) or "text match"
            lines.extend(
                [
                    "",
                    f"### {record['incident_id']} - {record['created_at']} UTC",
                    f"Matched terms: {matched_terms}",
                    "",
                    _quote(record.get("evidence_excerpt") or record.get("transcript", "")),
                ]
            )
            if record.get("deployment_id"):
                lines.append(f"\nCatalog deployment: {record['deployment_id']}")
    else:
        lines.append("No additional transcript search matches were found.")

    lines.extend(["", "## Synthetic runbook references", ""])
    if runbook_references:
        lines.append(
            "These bundled checklists are synthetic examples retrieved for this service. "
            "They are not approved operational instructions; verify against the service's real runbook."
        )
        for runbook in runbook_references:
            lines.extend(
                [
                    "",
                    f"### {runbook['title']} ({runbook['runbook_id']}, {runbook['version']})",
                    f"Matched terms: {', '.join(runbook.get('matched_terms', [])) or 'text match'}",
                ]
            )
            if runbook.get("matched_symptoms"):
                lines.append(f"Matched symptoms: {', '.join(runbook['matched_symptoms'])}")
            lines.extend(["", runbook["body"]])
    else:
        lines.append("No synthetic runbook reference matched this confirmed service and transcript.")

    lines.extend(
        [
            "",
            "## Original transcript",
            "",
            _quote(incident.get("transcript", "")),
            "",
            "---",
            "Generated from saved OpsDiary records. Historical matches are not predictions.",
            "",
        ]
    )
    return "\n".join(lines)
