"""Service and deployment context helpers with exact version matching."""

from pathlib import Path

from opsdiary.settings import DATABASE_PATH
from opsdiary.storage import get_service_enrichment


def enrich_incident(
    service_id: str | None,
    environment: str | None,
    db_path: Path | str = DATABASE_PATH,
    deployment_reference: str | None = None,
) -> dict | None:
    """Resolve service context and keep exact transcript matches distinct from latest."""
    return get_service_enrichment(
        service_id,
        environment,
        db_path=db_path,
        deployment_reference=deployment_reference,
    )
