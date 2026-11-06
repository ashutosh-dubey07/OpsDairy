"""Synthetic service/deployment enrichment helpers."""

from pathlib import Path

from opsdiary.settings import DATABASE_PATH
from opsdiary.storage import get_service_enrichment


def enrich_incident(service_id: str | None, environment: str | None, db_path: Path | str = DATABASE_PATH) -> dict | None:
    """Resolve a service and its most recent synthetic deployment."""
    return get_service_enrichment(service_id, environment, db_path)
