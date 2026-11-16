import difflib
import hashlib
import json
import re
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator

from patchwork.database import connect_database
from patchwork.errors import PatchworkError
from patchwork.ingestion.validation import validate_path


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
        try:
            normalized = validate_path(value)
        except PatchworkError as error:
            raise ValueError(error.message) from error
        if cleaned.is_absolute() or ".." in cleaned.parts:
            raise ValueError("Patch paths must stay within the repository root.")
        if not value or value.startswith("/") or normalized != value:
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
            if not re.fullmatch(r"[0-9a-f]{16}", item):
                raise ValueError("Evidence IDs must be 16-character lowercase hex values.")
        if len(set(value)) != len(value):
            raise ValueError("Evidence IDs must be unique.")
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
        evidence = list(dict.fromkeys(evidence_ids or []))
        if self.provider is not None:
            try:
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
                                        "evidence_ids": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                    "required": ["title", "summary", "changes"],
                                },
                            }
                        ],
                        2000,
                    )
                    payload = decision.call.arguments
                    return PatchProposal.model_validate(payload)
            except (PatchworkError, TypeError, ValueError, TimeoutError):
                pass
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

    def _valid_evidence_ids(self) -> set[str]:
        with connect_database(self.settings.database_path) as connection:
            rows = connection.execute(
                "SELECT path, source FROM files WHERE repository_id = ? ORDER BY path",
                (self.repository.id,),
            ).fetchall()
        valid: set[str] = set()
        for row in rows:
            path = row["path"]
            source = row["source"]
            lines = source.splitlines() or [""]
            total = len(lines)
            for start in range(1, total + 1):
                end = min(start + 99, total)
                while end >= start:
                    ref = {
                        "repository_id": self.repository.id,
                        "commit_sha": self.repository.commit_sha,
                        "path": path,
                        "start_line": start,
                        "end_line": end,
                    }
                    valid.add(self.evidence_hash(ref))
                    end -= 1
        return valid

    def validate(self, proposal: PatchProposal) -> str:
        changed: list[str] = []
        seen_paths: set[str] = set()
        evidence = list(dict.fromkeys(proposal.evidence_ids))
        valid_evidence = self._valid_evidence_ids()
        missing = [item for item in evidence if item not in valid_evidence]
        if missing:
            raise ValueError("Fabricated or stale evidence IDs are not valid for this snapshot.")
        for change in proposal.changes:
            try:
                target = validate_path(change.path)
            except PatchworkError as error:
                raise ValueError(error.message) from error
            if target in seen_paths:
                raise ValueError(f"Duplicate patch change for {target}.")
            seen_paths.add(target)
            if not target.lower().endswith(".py"):
                raise ValueError(f"Unsupported file modification: {target}")
            if (
                len(change.before.encode("utf-8")) > 500000
                or len(change.after.encode("utf-8")) > 500000
            ):
                raise ValueError(f"Unsupported patch size for {target}.")
            with connect_database(self.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT path, source, content_hash, size_bytes "
                    "FROM files WHERE repository_id = ? AND path = ?",
                    (self.repository.id, target),
                ).fetchone()
            if row is None:
                raise ValueError(f"Unknown repository file: {target}")
            current_source = row["source"]
            if row["size_bytes"] > 1_000_000:
                raise ValueError(f"Unsupported file modification: {target}")
            if row["content_hash"] and re.fullmatch(r"[0-9a-f]{64}", str(row["content_hash"])):
                if (
                    hashlib.sha256(current_source.encode("utf-8")).hexdigest()
                    != row["content_hash"]
                ):
                    raise ValueError(f"Stale source content detected for {target}.")
            if change.before not in {"", current_source}:
                raise ValueError(
                    f"Patch before-text does not match the indexed snapshot for {target}."
                )
            if change.after == current_source or change.after == change.before:
                raise ValueError(f"No-op change detected for {target}.")
            try:
                compile(change.after, target, "exec")
            except SyntaxError as error:
                raise ValueError(
                    f"Syntax-invalid patch content for {target}: {error.msg}"
                ) from error
            diff = PatchGenerator.build_diff(target, change.before, change.after)
            changed.append(diff)
        return "\n\n".join(changed)

    @staticmethod
    def evidence_hash(ref: dict) -> str:
        payload = json.dumps(ref, sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:16]
