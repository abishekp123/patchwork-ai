import asyncio
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from patchwork.config import Settings
from patchwork.database import initialize_database
from patchwork.ingestion.discovery import SourceFile
from patchwork.intelligence.models import Import, ParsedFile, Symbol
from patchwork.main import create_app
from patchwork.patches.engine import (
    PatchChange,
    PatchGenerator,
    PatchProposal,
    PatchValidator,
)
from patchwork.patches.store import PatchStore
from patchwork.repositories.store import RepositoryStore


def _ready_repository(settings: Settings):
    initialize_database(settings.database_path)
    store = RepositoryStore(settings.database_path)
    repository, token = store.claim("https://github.com/example/python-project", "a" * 40, 10)
    assert token is not None
    parsed = ParsedFile(
        file=SourceFile(
            path="example.py",
            content_hash="abc123",
            size_bytes=20,
            encoding="utf-8",
            source="def bug():\n    return 1\n",
        ),
        has_errors=False,
        symbols=(
            Symbol(
                path="example.py",
                name="bug",
                qualified_name="bug",
                kind="function",
                parent=None,
                start_line=1,
                end_line=2,
                start_byte=0,
                end_byte=12,
            ),
        ),
        imports=(
            Import(
                path="example.py",
                module_name="os",
                imported_name="path",
                alias=None,
                relative_level=0,
                scope=None,
                start_line=1,
                end_line=1,
                start_byte=0,
                statement="import os",
            ),
        ),
    )
    ready = store.publish(repository.id, token, [parsed], {}, "fixture.git")
    return ready


class FakePatchProvider:
    async def generate_patch(self, payload, repository):
        source = "def bug():\n    return 1\n"
        evidence = _evidence_id(repository.id, repository.commit_sha, "example.py", 1, 2)
        return {
            "title": "Guard the null path",
            "summary": "This patch adds explicit defensive handling for the failure path.",
            "changes": [
                {
                    "path": "example.py",
                    "before": source,
                    "after": source + "# patch: guard null path\n",
                    "reason": "Preserve safe review output while documenting the fix.",
                }
            ],
            "evidence_ids": [evidence],
        }


def _evidence_id(
    repository_id: str,
    commit_sha: str,
    path: str,
    start_line: int,
    end_line: int,
) -> str:
    ref = {
        "repository_id": repository_id,
        "commit_sha": commit_sha,
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
    }
    return hashlib.sha256(json.dumps(ref, sort_keys=True).encode()).hexdigest()[:16]


def test_patch_generator_validates_and_persists_a_proposal(settings: Settings):
    repository = _ready_repository(settings)
    provider = FakePatchProvider()
    generator = PatchGenerator(settings, repository, provider)
    proposal = asyncio.run(generator.generate("Guard the crash and keep the change reviewable."))
    diff = PatchValidator(settings, repository).validate(proposal)
    assert proposal.title == "Guard the null path"
    assert "example.py" in diff
    store = PatchStore(settings.database_path)
    record = store.create(repository, proposal)
    assert record.status == "pending_review"
    approved = store.transition(record.id, "approved", reviewer="human", reason="Looks safe.")
    assert approved.status == "approved"


def test_patch_validator_rejects_fabricated_and_cross_snapshot_evidence(
    settings: Settings,
):
    repository = _ready_repository(settings)
    valid = _evidence_id(repository.id, repository.commit_sha, "example.py", 1, 1)
    other = {
        "repository_id": "b" * 64,
        "commit_sha": "c" * 40,
        "path": "example.py",
        "start_line": 1,
        "end_line": 1,
    }
    proposal = PatchProposal(
        title="Evidence guard",
        summary="Reject stale or fabricated evidence references.",
        changes=[
            PatchChange(
                path="example.py",
                before="def bug():\n    return 1\n",
                after="def bug():\n    return 1\n# patch: evidence check\n",
                reason="Adds traceability.",
            )
        ],
        evidence_ids=[
            valid,
            hashlib.sha256(json.dumps(other, sort_keys=True).encode()).hexdigest()[:16],
        ],
    )
    with pytest.raises(ValueError, match="Fabricated or stale evidence"):
        PatchValidator(settings, repository).validate(proposal)


def test_patch_validator_rejects_unsafe_paths_and_duplication(settings: Settings):
    repository = _ready_repository(settings)
    proposal = PatchProposal.model_construct(
        title="Unsafe patch",
        summary="Should reject traversal paths.",
        changes=[
            PatchChange.model_construct(
                path="../example.py",
                before="def bug():\n    return 1\n",
                after="def bug():\n    return 2\n",
                reason="Not safe.",
            )
        ],
    )
    with pytest.raises(ValueError):
        PatchValidator(settings, repository).validate(proposal)

    duplicate = PatchProposal(
        title="Duplicates",
        summary="Reject repeated path edits.",
        changes=[
            PatchChange(
                path="example.py",
                before="def bug():\n    return 1\n",
                after="def bug():\n    return 2\n",
                reason="One edit.",
            ),
            PatchChange(
                path="example.py",
                before="def bug():\n    return 1\n",
                after="def bug():\n    return 3\n",
                reason="Duplicate edit.",
            ),
        ],
    )
    with pytest.raises(ValueError, match="Duplicate patch change"):
        PatchValidator(settings, repository).validate(duplicate)


def test_patch_validator_rejects_noop_and_syntax_invalid_changes(settings: Settings):
    repository = _ready_repository(settings)
    no_op = PatchProposal(
        title="Noop",
        summary="Reject any change that does not modify the file.",
        changes=[
            PatchChange(
                path="example.py",
                before="def bug():\n    return 1\n",
                after="def bug():\n    return 1\n",
                reason="No effect.",
            )
        ],
    )
    with pytest.raises(ValueError, match="No-op change detected"):
        PatchValidator(settings, repository).validate(no_op)

    invalid = PatchProposal(
        title="Invalid",
        summary="Reject syntax-invalid content.",
        changes=[
            PatchChange(
                path="example.py",
                before="def bug():\n    return 1\n",
                after="def bug(:\n    return 1\n",
                reason="Bad syntax.",
            )
        ],
    )
    with pytest.raises(ValueError, match="Syntax-invalid patch content"):
        PatchValidator(settings, repository).validate(invalid)


def test_patch_validator_rejects_stale_source_or_hash_mismatch(settings: Settings):
    repository = _ready_repository(settings)
    with pytest.raises(ValueError, match="Patch before-text"):
        PatchValidator(settings, repository).validate(
            PatchProposal(
                title="Stale source",
                summary="Reject mismatched repository content.",
                changes=[
                    PatchChange(
                        path="example.py",
                        before="def bug():\n    return 99\n",
                        after="def bug():\n    return 100\n",
                        reason="Changed content.",
                    )
                ],
                evidence_ids=[],
            )
        )

    with pytest.raises(ValueError, match="Unsupported file modification"):
        PatchValidator(settings, repository).validate(
            PatchProposal(
                title="Unsupported",
                summary="Reject non-Python file edits.",
                changes=[
                    PatchChange(
                        path="notes.txt",
                        before="hello",
                        after="goodbye",
                        reason="Not allowed.",
                    )
                ],
            )
        )


def test_patch_generator_handles_malformed_provider_output(settings: Settings):
    repository = _ready_repository(settings)

    class MalformedProvider:
        async def generate_patch(self, payload, repository):
            raise TimeoutError("slow")

    generator = PatchGenerator(settings, repository, MalformedProvider())
    proposal = asyncio.run(generator.generate("Make a safe fallback patch.", evidence_ids=[]))
    assert proposal.title == "Apply a transparent safety patch"
    assert proposal.changes[0].path == "example.py"

    class BadProvider:
        async def decide(self, context, tools, max_output):
            class BadDecision:
                call = type(
                    "Call",
                    (),
                    {"arguments": {"title": "oops", "summary": "bad", "changes": "not-a-list"}},
                )()

            return BadDecision()

    fallback = PatchGenerator(settings, repository, BadProvider())
    repaired = asyncio.run(fallback.generate("Still safe with malformed model output."))
    assert repaired.title == "Apply a transparent safety patch"


def test_patch_api_accepts_a_review_decision(settings: Settings):
    repository = _ready_repository(settings)
    app = create_app(settings)
    client = TestClient(app)

    response = client.post(
        "/api/patches",
        json={
            "repository_id": repository.id,
            "description": "Add the missing safety review patch.",
            "evidence_ids": [],
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    patch_id = payload["patch"]["id"]
    assert payload["patch"]["status"] == "pending_review"

    approved = client.post(
        f"/api/patches/{patch_id}/approve",
        json={"decision": "approve", "reviewer": "human", "reason": "Looks safe."},
    )
    assert approved.status_code == 200, approved.text
    data = approved.json()["patch"]
    assert data["status"] == "approved"
    assert data["reviewer"] == "human"

    repeat = client.post(
        f"/api/patches/{patch_id}/approve",
        json={"decision": "approve", "reviewer": "human2", "reason": "Again."},
    )
    assert repeat.status_code == 409, repeat.text

    reject = client.post(
        f"/api/patches/{patch_id}/reject",
        json={"decision": "reject", "reviewer": "human3", "reason": "Already resolved."},
    )
    assert reject.status_code == 409, reject.text


def test_fake_provider_integration_workflow(settings: Settings):
    repository = _ready_repository(settings)
    evidence_id = _evidence_id(repository.id, repository.commit_sha, "example.py", 1, 2)

    class FakeIntegratedProvider:
        async def generate_patch(self, payload, repository):
            return {
                "title": "Guard the null path",
                "summary": "Validate source before proving the fix.",
                "changes": [
                    {
                        "path": "example.py",
                        "before": "def bug():\n    return 1\n",
                        "after": "def bug():\n    return 1\n# patch: safe review\n",
                        "reason": "Document the patch in the snapshot.",
                    }
                ],
                "evidence_ids": [evidence_id],
            }

    proposal = asyncio.run(
        PatchGenerator(settings, repository, FakeIntegratedProvider()).generate(
            "Document the reviewable change.", evidence_ids=[evidence_id]
        )
    )
    diff = PatchValidator(settings, repository).validate(proposal)
    assert evidence_id in proposal.evidence_ids
    assert "example.py" in diff
    record = PatchStore(settings.database_path).create(repository, proposal)
    approved = PatchStore(settings.database_path).transition(
        record.id, "approved", reviewer="reviewer", reason="Deterministic validation passed."
    )
    assert approved.status == "approved"
