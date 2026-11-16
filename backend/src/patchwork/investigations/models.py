from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Search(Strict):
    query: str = Field(min_length=1, max_length=200)


class Symbols(Strict):
    name: str = Field(min_length=1, max_length=512)
    exact: bool


class FileRange(Strict):
    path: str = Field(min_length=1, max_length=4096)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class Imports(Strict):
    path: str = Field(min_length=1, max_length=4096)


class Finding(Strict):
    statement: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(max_length=10)


class ReportDraft(Strict):
    summary: str = Field(min_length=1, max_length=2000)
    facts: list[Finding] = Field(max_length=15)
    hypotheses: list[Finding] = Field(max_length=10)
    next_steps: list[str] = Field(max_length=10)
    limitations: list[str] = Field(max_length=10)


class Call(Strict):
    name: str
    arguments: dict


class Decision(Strict):
    call: Call
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    usage_available: bool = False


class InvestigationRequest(Strict):
    repository_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    description: str = Field(min_length=1, max_length=8000)


Status = Literal[
    "CREATED",
    "CONTEXT_RETRIEVAL",
    "INVESTIGATING",
    "EVIDENCE_REVIEW",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "BUDGET_EXHAUSTED",
]
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"}


class Investigation(BaseModel):
    id: str
    repository_id: str
    commit_sha: str
    description: str
    status: Status
    created_at: str
    updated_at: str
    completed_at: str | None
    report: dict | None
    error_code: str | None
