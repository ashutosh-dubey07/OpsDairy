"""Validated data structures shared by extraction and persistence."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Environment(str, Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


class Severity(str, Enum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


class IncidentDraft(BaseModel):
    """Candidate incident fields plus the transcript evidence behind them."""

    model_config = ConfigDict(use_enum_values=True)

    transcript: str = Field(min_length=1, max_length=10000)
    service_id: str | None = None
    environment: Environment | None = None
    severity: Severity | None = None
    symptoms: list[str] = Field(default_factory=list)
    impact_summary: str | None = None
    deployment_reference: str | None = None
    evidence: dict[str, str] = Field(default_factory=dict)
