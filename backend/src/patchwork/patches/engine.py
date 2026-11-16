import difflib
import hashlib
import json
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator

from patchwork.database import connect_database
from patchwork.errors import PatchworkError


class PatchChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)
    before: str = Field(min_length=0, max_length=500000)
    after: str = Field(min_length=0, max_length=500000)
    reason: str = Field(default="", min_length=0, max_length=2000)

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        cleaned = PurePosixPath(value)
        if cleaned.is_absolute() or ".." in cleaned.parts:
            raise ValueError("Patch paths must stay within the repository root.")
        if not value or value.startswith("/"):
            raise ValueError("Patch paths must be relative repository paths.")
        return value


class PatchProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    changes: list[PatchChange] = Field(default_factory=list, min_length=1, max_length=20)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_are_nonempty(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item:
                raise ValueError("Evidence IDs cannot be empty.")
        return value


class PatchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    repository_id: str
    commit_sha: str
    investigation_id: str | None = None
    status: str
    title: str
    summary: str
    diff: str
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    reviewed_at: str | None = None
    reviewer: str | None = None
    decision_reason: str | None = None
    error_code: str | None = None


class PatchGenerator:
    def __init__(self, settings, repository, provider=None):
        self.settings = settings
        self.repository = repository
        self.provider = provider

    @staticmethod
    def _diff(path: str, before: str, after: str) -> str:
        before_lines = before.splitlines(keepends=True)
        after_lines = after.splitlines(keepends=True)
        difference = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=path,
            tofile=path,
            lineterm="",
        )
        return "\n".join(difference)

    @staticmethod
    def build_diff(path: str, before: str, after: str) -> str:
        return PatchGenerator._diff(path, before, after)

    async def generate(
        self,
        description: str,
        *,
        evidence_ids: list[str] | None = None,
    ) -> PatchProposal:
        evidence = evidence_ids or []
        if self.provider is not None:
            provider_fn = getattr(self.provider, "generate_patch", None)
            if provider_fn is not None:
                payload = await provider_fn(
                    {
                        "problem": description,
                        "repository_id": self.repository.id,
                        "commit_sha": self.repository.commit_sha,
                        "evidence_ids": evidence,
                    },
                    self.repository,
                )
                if payload is not None:
                    return PatchProposal.model_validate(payload)
            if hasattr(self.provider, "decide"):
                decision = await self.provider.decide(
                    json.dumps(
                        {
                            "problem": description,
                            "repository_id": self.repository.id,
                            "commit_sha": self.repository.commit_sha,
                            "evidence_ids": evidence,
                        },
                        sort_keys=True,
                    ),
                    [
                        {
                            "name": "generate_patch",
                            "description": "Return a structured patch proposal.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "summary": {"type": "string"},
                                    "changes": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "path": {"type": "string"},
                                                "before": {"type": "string"},
                                                "after": {"type": "string"},
                                                "reason": {"type": "string"},
                                            },
                                            "required": ["path", "before", "after"],
                                        },
                                    },
                                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["title", "summary", "changes"],
                            },
                        }
                    ],
                    2000,
                )
                payload = decision.call.arguments
                return PatchProposal.model_validate(payload)
        return self._fallback_proposal(description, evidence)

    def _fallback_proposal(self, description: str, evidence_ids: list[str]) -> PatchProposal:
        with connect_database(self.settings.database_path) as connection:
            rows = connection.execute(
                "SELECT path, source FROM files WHERE repository_id = ? ORDER BY path LIMIT 20",
                (self.repository.id,),
            ).fetchall()
        if not rows:
            raise PatchworkError(
                "patch_no_source",
                "No indexed source is available for this repository snapshot.",
                409,
            )
        target = rows[0]
        original = target["source"]
        patch_note = description.strip().splitlines()[0][:80]
        patched = original.rstrip() + "\n# patch: " + patch_note + "\n"
        return PatchProposal(
            title="Apply a transparent safety patch",
            summary=(
                "This patch records the requested repair intent while leaving the "
                "repository untouched until review."
            ),
            changes=[
                PatchChange(
                    path=target["path"],
                    before=original,
                    after=patched,
                    reason=(
                        "Safety patch draft derived from the repository snapshot and "
                        "the user request."
                    ),
                )
            ],
            evidence_ids=evidence_ids,
        )


class PatchValidator:
    def __init__(self, settings, repository):
        self.settings = settings
        self.repository = repository

    def validate(self, proposal: PatchProposal) -> str:
        changed: list[str] = []
        for change in proposal.changes:
            target = change.path
            if PurePosixPath(target).is_absolute() or ".." in PurePosixPath(target).parts:
                raise ValueError("Unsafe patch path detected.")
            with connect_database(self.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT source FROM files WHERE repository_id = ? AND path = ?",
                    (self.repository.id, target),
                ).fetchone()
            if row is None:
                raise ValueError(f"Unknown repository file: {target}")
            current = row["source"]
            if change.before not in {"", current}:
                raise ValueError(
                    f"Patch before-text does not match the indexed snapshot for {target}."
                )
            if change.after == change.before:
                continue
            if change.after == current:
                continue
            diff = PatchGenerator.build_diff(target, change.before, change.after)
            changed.append(diff)
        return "\n\n".join(changed)

    @staticmethod
    def evidence_hash(ref: dict) -> str:
        payload = json.dumps(ref, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()[:16]
