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
            "evidence_ids": ["deadbeef"],
        }


def test_patch_generator_validates_and_persists_a_proposal(settings: Settings):
    repository = _ready_repository(settings)
    provider = FakePatchProvider()
    generator = PatchGenerator(settings, repository, provider)
    proposal = __import__("asyncio").run(
        generator.generate("Guard the crash and keep the change reviewable.")
    )
    diff = PatchValidator(settings, repository).validate(proposal)
    assert proposal.title == "Guard the null path"
    assert "example.py" in diff
    store = PatchStore(settings.database_path)
    record = store.create(repository, proposal)
    assert record.status == "pending_review"
    approved = store.transition(record.id, "approved", reviewer="human", reason="Looks safe.")
    assert approved.status == "approved"


def test_patch_validator_rejects_unsafe_paths(settings: Settings):
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
    with __import__("pytest").raises(ValueError):
        PatchValidator(settings, repository).validate(proposal)


def test_patch_api_accepts_a_review_decision(settings: Settings):
    repository = _ready_repository(settings)
    app = create_app(settings)
    client = TestClient(app)

    response = client.post(
        "/api/patches",
        json={
            "repository_id": repository.id,
            "description": "Add the missing safety review patch.",
            "evidence_ids": ["abc123"],
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
