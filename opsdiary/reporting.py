"""Build a plain Markdown brief from a saved incident and its supporting records."""

from opsdiary.extraction import SYMPTOM_LABELS


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" for line in (text or "").splitlines())


def build_incident_report(
    incident: dict,
    service: dict | None,
    pattern_result: dict,
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
    if incident.get("deployment_reference"):
        lines.extend(["", "## Deployment mentioned", "", incident["deployment_reference"]])

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
            f"Latest seeded deployment: {deployment['version']} ({deployment['environment']}) "
            f"at {deployment['deployed_at']} UTC; {deployment['deployment_id']}; "
            f"commit {deployment['commit_sha']}."
        )
        lines.append(f"Change note: {deployment['change_summary']}")
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
