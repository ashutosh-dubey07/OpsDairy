"""SQLite FTS5 retrieval for evidence-backed historical incident context."""

import json
import re
from pathlib import Path

from opsdiary.settings import DATABASE_PATH
from opsdiary.storage import connect


STOP_WORDS = {
    "a", "an", "and", "are", "after", "before", "by", "for", "from", "in", "is",
    "it", "ke", "ki", "ka", "ko", "me", "mein", "nahi", "not", "of", "on", "or",
    "the", "this", "to", "with", "aur", "hai", "hain", "tha", "thi", "ho",
    "raha", "rahe", "rahi", "issue", "incident", "service", "users", "user",
}
TOKEN_PATTERN = re.compile(r"[\w]+", re.UNICODE)


def _terms(text: str) -> list[str]:
    unique = dict.fromkeys(
        token for token in TOKEN_PATTERN.findall(text.casefold())
        if token not in STOP_WORDS and (len(token) > 1 or token in {"5xx", "4xx"})
    )
    return list(unique)[:16]


def _evidence_excerpt(transcript: str, terms: list[str], limit: int = 260) -> str:
    folded = transcript.casefold()
    positions = [folded.find(term) for term in terms if folded.find(term) >= 0]
    if not positions:
        return transcript[:limit]
    start = max(0, min(positions) - 65)
    end = min(len(transcript), start + limit)
    if start:
        start = transcript.find(" ", start)
        start = 0 if start < 0 else start + 1
    return transcript[start:end].strip()


def retrieve_incidents(
    query: str,
    *,
    service_id: str | None = None,
    environment: str | None = None,
    exclude_incident_id: str | None = None,
    limit: int = 5,
    db_path: Path | str = DATABASE_PATH,
) -> list[dict]:
    """Return lexical matches, optionally filtered by exact service/environment metadata."""
    terms = _terms(query)
    if not terms:
        return []

    filter_service_id = service_id or None
    filter_environment = environment or None
    filter_excluded_id = exclude_incident_id or None
    params: list[object] = [
        " OR ".join(f'"{term}"' for term in terms),
        filter_service_id,
        filter_service_id,
        filter_environment,
        filter_environment,
        filter_excluded_id,
        filter_excluded_id,
    ]
    bounded_limit = max(1, min(int(limit), 20))
    params.append(min(bounded_limit * 5, 100))

    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT i.incident_id, i.created_at, i.transcript, i.service_id,
                       i.environment, i.symptoms_json, i.deployment_id, i.source,
                       bm25(incident_search, 0.0, 1.0, 0.6, 0.0, 0.0, 0.2) AS rank
                FROM incident_search
                JOIN incidents AS i ON i.incident_id = incident_search.incident_id
                WHERE incident_search MATCH ?
                  AND (? IS NULL OR incident_search.service_id = ?)
                  AND (? IS NULL OR incident_search.environment = ?)
                  AND (? IS NULL OR incident_search.incident_id != ?)
                ORDER BY rank ASC, i.created_at DESC
                LIMIT ?""",
            params,
        ).fetchall()

    results = []
    minimum_matched_terms = 1 if len(terms) == 1 else 2
    for row in rows:
        transcript = row["transcript"]
        transcript_terms = set(_terms(transcript))
        matched_terms = [term for term in terms if term in transcript_terms]
        if len(matched_terms) < minimum_matched_terms:
            continue
        results.append(
            {
                "incident_id": row["incident_id"],
                "created_at": row["created_at"],
                "transcript": transcript,
                "evidence_excerpt": _evidence_excerpt(transcript, matched_terms),
                "matched_terms": matched_terms,
                "service_id": row["service_id"],
                "environment": row["environment"],
                "symptoms": json.loads(row["symptoms_json"]),
                "deployment_id": row["deployment_id"],
                "source": row["source"],
                "method": "sqlite-fts5-lexical",
            }
        )
    return results[:bounded_limit]


def retrieve_runbooks(
    query: str,
    *,
    service_id: str | None,
    environment: str | None = None,
    symptoms: list[str] | None = None,
    limit: int = 3,
    db_path: Path | str = DATABASE_PATH,
) -> list[dict]:
    """Return synthetic references for the confirmed service with lexical evidence.

    Service is mandatory so an unknown service cannot receive another team's guidance.
    A null runbook environment means the synthetic reference has no environment scope.
    """
    terms = _terms(query)
    if not service_id or not terms:
        return []

    filter_environment = environment or None
    params: list[object] = [
        " OR ".join(f'"{term}"' for term in terms),
        service_id,
        filter_environment,
        filter_environment,
    ]
    bounded_limit = max(1, min(int(limit), 10))
    params.append(min(bounded_limit * 5, 50))

    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT r.runbook_id, r.service_id, r.title, r.version, r.environment,
                       r.symptoms_json, r.keywords, r.body, r.source,
                       bm25(runbook_search, 0.0, 2.0, 1.0, 0.8, 0.0, 0.0) AS rank
                FROM runbook_search
                JOIN runbooks AS r ON r.runbook_id = runbook_search.runbook_id
                WHERE runbook_search MATCH ?
                  AND runbook_search.service_id = ?
                  AND (? IS NULL OR runbook_search.environment = '' OR runbook_search.environment = ?)
                ORDER BY rank ASC
                LIMIT ?""",
            params,
        ).fetchall()

    requested_symptoms = set(symptoms or [])
    minimum_matched_terms = 1 if len(terms) == 1 else 2
    results = []
    for row in rows:
        indexed_text = " ".join((row["title"], row["body"], row["keywords"]))
        indexed_terms = set(_terms(indexed_text))
        matched_terms = [term for term in terms if term in indexed_terms]
        if len(matched_terms) < minimum_matched_terms:
            continue
        runbook_symptoms = json.loads(row["symptoms_json"])
        matched_symptoms = sorted(requested_symptoms.intersection(runbook_symptoms))
        if requested_symptoms and not matched_symptoms:
            continue
        results.append(
            {
                "runbook_id": row["runbook_id"],
                "service_id": row["service_id"],
                "title": row["title"],
                "version": row["version"],
                "environment": row["environment"],
                "symptoms": runbook_symptoms,
                "matched_symptoms": matched_symptoms,
                "matched_terms": matched_terms,
                "body": row["body"],
                "source": row["source"],
                "method": "sqlite-fts5-lexical",
            }
        )
    results.sort(key=lambda item: (-len(item["matched_symptoms"]), -len(item["matched_terms"])))
    return results[:bounded_limit]
