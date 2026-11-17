from pydantic import BaseModel, ConfigDict, Field

from patchwork.investigations.models import Investigation
from patchwork.schemas.repositories import Page


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    description: str = Field(min_length=1, max_length=8000)


class InvestigationStep(BaseModel):
    sequence: int
    created_at: str
    data: dict


class InvestigationStepPage(Page[InvestigationStep]):
    pass


class InvestigationResponse(BaseModel):
    investigation: Investigation


class ProviderStatus(BaseModel):
    available: bool
    provider: str
    model: str
    reason: str | None = None
