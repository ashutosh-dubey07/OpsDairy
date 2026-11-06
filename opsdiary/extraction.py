"""Small deterministic Hinglish-friendly incident field extractor."""

import re
from collections.abc import Iterable

from opsdiary.schema import Environment, IncidentDraft, Severity

SYMPTOM_LABELS = {
    "http_5xx": "HTTP 5xx / server errors",
    "latency": "High latency / slow responses",
    "timeouts": "Request timeouts",
    "payment_failures": "Payment or checkout failures",
    "db_pool_exhaustion": "Database connection pool pressure",
    "queue_backlog": "Queue backlog or lag",
    "auth_failures": "Authentication or login failures",
}

SYMPTOM_PATTERNS = {
    "http_5xx": re.compile(r"\b(?:5xx|5\d\d|server errors?|internal server errors?)\b", re.I),
    "latency": re.compile(r"\b(?:latency|slow(?:\s+(?:chal|response|responses|ho|hai))?|laggy|delay|dheere)\b", re.I),
    "timeouts": re.compile(r"\b(?:timeouts?|timed out|time out)\b", re.I),
    "payment_failures": re.compile(r"\b(?:payments?\s+(?:fail\w*|error\w*)|payment decline\w*|checkout fail\w*|payments complete nahi)\b", re.I),
    "db_pool_exhaustion": re.compile(r"\b(?:connection pool|db pool|database pool|too many connections)\b", re.I),
    "queue_backlog": re.compile(r"\b(?:queue backlog|queue lag|backlog)\b", re.I),
    "auth_failures": re.compile(r"\b(?:login fail\w*|auth(?:entication)? errors?|unauthorized|401 errors?)\b", re.I),
}

SEVERITY_PATTERNS = (
    (Severity.SEV1, re.compile(r"\b(?:sev[- ]?1|p1|critical severity)\b", re.I)),
    (Severity.SEV2, re.compile(r"\b(?:sev[- ]?2|p2|high severity)\b", re.I)),
    (Severity.SEV3, re.compile(r"\b(?:sev[- ]?3|p3|medium severity)\b", re.I)),
    (Severity.SEV4, re.compile(r"\b(?:sev[- ]?4|p4|low severity)\b", re.I)),
)

ENVIRONMENT_PATTERNS = (
    (Environment.PRODUCTION, re.compile(r"\b(?:production|prod)\b", re.I)),
    (Environment.STAGING, re.compile(r"\b(?:staging|stage)\b", re.I)),
    (Environment.DEVELOPMENT, re.compile(r"\b(?:development|dev)\b", re.I)),
)

DEPLOYMENT_VERSION_PATTERN = re.compile(
    r"\b(?:deploy(?:ment|ed)?|release|version)\b(?:\s+\w+){0,3}\s+(v?\d+(?:\.\d+){1,3}(?:[-+][\w.-]+)?)\b",
    re.I,
)
IMPACT_CUES = re.compile(
    r"\b(?:users?|customers?|orders?|payments?|traffic|impact|fail\w*|down|unavailable)\b",
    re.I,
)


def _service_match(transcript: str, services: Iterable[dict]) -> tuple[str | None, str | None]:
    text = transcript.casefold()
    candidates: list[tuple[int, str, str]] = []
    for service in services:
        for alias in [service["service_id"], service["name"], *service.get("aliases", [])]:
            alias = str(alias).strip()
            if not alias:
                continue
            match = re.search(r"(?<![\w])" + re.escape(alias.casefold()) + r"(?![\w])", text)
            if match:
                candidates.append((match.start(), service["service_id"], alias))
    if not candidates:
        return None, None
    _, service_id, alias = min(candidates, key=lambda item: (item[0], -len(item[2])))
    return service_id, alias


def _evidence_for(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    start = max(0, match.start() - 45)
    end = min(len(text), match.end() + 45)
    return text[start:end].strip()


def _impact_sentence(transcript: str) -> str | None:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", transcript) if part.strip()]
    for sentence in sentences:
        if IMPACT_CUES.search(sentence):
            return sentence[:400]
    return None


def extract_incident(transcript: str, services: Iterable[dict]) -> IncidentDraft:
    """Return conservative candidates. Unclear fields stay empty for operator review."""
    cleaned = transcript.strip()
    if not cleaned:
        raise ValueError("Enter a synthetic transcript before extracting incident fields.")

    service_id, service_alias = _service_match(cleaned, services)
    evidence: dict[str, str] = {}
    if service_alias:
        evidence["service_id"] = service_alias

    environment = None
    for candidate, pattern in ENVIRONMENT_PATTERNS:
        if snippet := _evidence_for(pattern, cleaned):
            environment = candidate
            evidence["environment"] = snippet
            break

    severity = None
    for candidate, pattern in SEVERITY_PATTERNS:
        if snippet := _evidence_for(pattern, cleaned):
            severity = candidate
            evidence["severity"] = snippet
            break

    symptoms: list[str] = []
    symptom_evidence: dict[str, str] = {}
    for tag, pattern in SYMPTOM_PATTERNS.items():
        snippet = _evidence_for(pattern, cleaned)
        if snippet:
            symptoms.append(tag)
            symptom_evidence[tag] = snippet
    if symptom_evidence:
        evidence["symptoms"] = " | ".join(
            f"{SYMPTOM_LABELS[tag]}: {snippet}" for tag, snippet in symptom_evidence.items()
        )

    version_match = DEPLOYMENT_VERSION_PATTERN.search(cleaned)
    deployment_reference = version_match.group(1) if version_match else None
    if version_match:
        evidence["deployment_reference"] = _evidence_for(DEPLOYMENT_VERSION_PATTERN, cleaned) or ""

    impact_summary = _impact_sentence(cleaned)
    if impact_summary:
        evidence["impact_summary"] = impact_summary

    return IncidentDraft(
        transcript=cleaned,
        service_id=service_id,
        environment=environment,
        severity=severity,
        symptoms=symptoms,
        impact_summary=impact_summary,
        deployment_reference=deployment_reference,
        evidence=evidence,
    )
