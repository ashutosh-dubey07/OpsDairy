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
    service_id: str | None = Field(default=None, max_length=100)
    environment: Environment | None = None
    severity: Severity | None = None
    symptoms: list[str] = Field(default_factory=list, max_length=20)
    impact_summary: str | None = Field(default=None, max_length=2000)
    deployment_reference: str | None = Field(default=None, max_length=120)
    evidence: dict[str, str] = Field(default_factory=dict, max_length=20)
    trace_id: str | None = Field(default=None, min_length=1, max_length=64)
