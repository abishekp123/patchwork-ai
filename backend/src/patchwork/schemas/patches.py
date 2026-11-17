from pydantic import BaseModel, ConfigDict, Field

from patchwork.patches.engine import PatchProposal, PatchRecord
from patchwork.schemas.repositories import Page


class PatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    description: str = Field(min_length=1, max_length=8000)
    investigation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class PatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern=r"^(approve|reject)$")
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, min_length=1, max_length=2000)


class PatchResponse(BaseModel):
    patch: PatchRecord


class PatchPage(Page[PatchRecord]):
    pass


class PatchProposalResponse(BaseModel):
    proposal: PatchProposal
