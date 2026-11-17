from pydantic import BaseModel, ConfigDict, Field

from patchwork.schemas.repositories import Page
from patchwork.verifications.models import VerificationRecord, VerificationResult


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_command: str | None = Field(default=None, min_length=1, max_length=200)
    patched_command: str | None = Field(default=None, min_length=1, max_length=200)
    sandbox_mode: str = Field(default="docker", pattern=r"^(fake|docker)$")


class VerificationResponse(BaseModel):
    verification: VerificationRecord


class VerificationResultResponse(BaseModel):
    verification_id: str
    result: VerificationResult | None = None


class VerificationPage(Page[VerificationRecord]):
    pass


class SandboxStatusResponse(BaseModel):
    available: bool
    mode: str
    reason: str | None = None
