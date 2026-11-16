from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["fake", "docker"] = "fake"
    image: str = "python:3.12-slim"
    memory_mb: int = Field(default=512, ge=64, le=4096)
    cpus: float = Field(default=1.0, ge=0.25, le=8.0)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    network_disabled: bool = True
    read_only_root: bool = True
    no_new_privileges: bool = True
    user: str = "65532:65532"
    workdir: str = "/workspace"
    extra_args: list[str] = Field(default_factory=list, max_length=20)


class VerificationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exit_code: int | None = None
    duration_ms: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0
    error_code: str | None = None


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "IMPROVED",
        "REGRESSED",
        "UNCHANGED",
        "INCONCLUSIVE",
        "FAILED",
        "SANDBOX_UNAVAILABLE",
    ]
    classification: str
    reason: str
    baseline: VerificationSummary
    patched: VerificationSummary
    diff_summary: dict[str, int] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list, max_length=50)


class VerificationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    patch_id: str
    repository_id: str
    commit_sha: str
    status: Literal[
        "CREATED",
        "PREPARING",
        "RUNNING_BASELINE",
        "RUNNING_PATCHED",
        "COMPARING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    ]
    sandbox_mode: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    baseline_summary: VerificationSummary | None = None
    patched_summary: VerificationSummary | None = None
    comparison: VerificationResult | None = None
    error_code: str | None = None
    execution_logs: list[str] = Field(default_factory=list, max_length=50)
