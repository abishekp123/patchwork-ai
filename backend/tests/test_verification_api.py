import time

from fastapi.testclient import TestClient

from patchwork.api.verifications import sandbox_from_request
from patchwork.config import Settings
from patchwork.database import initialize_database
from patchwork.ingestion.discovery import SourceFile
from patchwork.intelligence.models import Import, ParsedFile, Symbol
from patchwork.main import create_app
from patchwork.patches.engine import PatchChange, PatchProposal
from patchwork.patches.store import PatchStore
from patchwork.repositories.store import RepositoryStore
from patchwork.schemas.verifications import VerificationRequest
from patchwork.verifications.sandbox import FakeSandboxAdapter


def _ready_repository(settings: Settings):
    initialize_database(settings.database_path)
    store = RepositoryStore(settings.database_path)
    repository, token = store.claim("https://github.com/example/python-project", "a" * 40, 10)
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
    return store.publish(repository.id, token, [parsed], {}, "fixture.git")


def test_verification_api_lifecycle_for_approved_patch(settings: Settings):
    repository = _ready_repository(settings)
    proposal = PatchProposal(
        title="Guard the bug path",
        summary="This patch keeps the reviewed repair traceable.",
        changes=[
            PatchChange(
                path="example.py",
                before="def bug():\n    return 1\n",
                after="def bug():\n    return 2\n",
                reason="Exercise the verification lifecycle.",
            )
        ],
        evidence_ids=[],
    )
    patch = PatchStore(settings.database_path).create(repository, proposal)
    approved = PatchStore(settings.database_path).transition(
        patch.id,
        "approved",
        reviewer="human",
        reason="Ready for verification.",
    )

    app = create_app(settings)
    app.dependency_overrides[sandbox_from_request] = lambda: FakeSandboxAdapter()
    with TestClient(app) as client:
        response = client.post(
            f"/api/patches/{approved.id}/verifications",
            json={"sandbox_mode": "docker", "baseline_command": "python -m pytest -q"},
        )
        assert response.status_code == 201, response.text
        verification_id = response.json()["verification"]["id"]

        for _ in range(50):
            poll = client.get(f"/api/verifications/{verification_id}")
            if poll.json()["verification"]["status"] == "COMPLETED":
                break
            time.sleep(0.05)

        item = client.get(f"/api/verifications/{verification_id}").json()["verification"]
        assert item["status"] == "COMPLETED"
        assert item["comparison"] is not None
        assert item["comparison"]["status"] in {"UNCHANGED", "IMPROVED", "REGRESSED", "FAILED"}

        listing = client.get(f"/api/patches/{approved.id}/verifications")
        assert listing.status_code == 200
        assert any(record["id"] == verification_id for record in listing.json()["items"])

        results = client.get(f"/api/verifications/{verification_id}/results")
        assert results.status_code == 200
        assert results.json()["verification_id"] == verification_id


def test_verification_api_rejects_unapproved_patch(settings: Settings):
    repository = _ready_repository(settings)
    proposal = PatchProposal(
        title="Pending review",
        summary="This patch is not approved yet.",
        changes=[
            PatchChange(
                path="example.py",
                before="def bug():\n    return 1\n",
                after="def bug():\n    return 2\n",
                reason="Verified patch not approved.",
            )
        ],
        evidence_ids=[],
    )
    patch = PatchStore(settings.database_path).create(repository, proposal)

    with TestClient(create_app(settings)) as client:
        response = client.post(
            f"/api/patches/{patch.id}/verifications",
            json={"sandbox_mode": "docker"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "patch_not_approved"


def test_sandbox_status_api_reports_docker_mode(settings: Settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/verification/sandbox-status")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["mode"] == "docker"
        assert "available" in payload


def test_verification_request_defaults_to_real_docker_execution():
    assert VerificationRequest().sandbox_mode == "docker"


def test_public_api_rejects_fake_and_configuration(settings: Settings):
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(sandbox_mode="fake")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/patches/" + "a" * 32 + "/verifications", json={"sandbox_mode": "fake"}
        )
        assert response.status_code == 422


def test_docker_unavailable_never_falls_back(settings: Settings, monkeypatch):
    from patchwork.verifications.sandbox import SandboxAdapter
    from patchwork.verifications.store import VerificationStore

    repository = _ready_repository(settings)
    proposal = PatchProposal(
        title="Boundary",
        summary="Docker is required",
        changes=[
            PatchChange(
                path="example.py",
                before="def bug():\n    return 1\n",
                after="def bug():\n    return 2\n",
                reason="Fixture",
            )
        ],
    )
    patch = PatchStore(settings.database_path).create(repository, proposal)
    PatchStore(settings.database_path).transition(
        patch.id, "approved", reviewer="human", reason="Test fixture"
    )
    monkeypatch.setattr(SandboxAdapter, "available", lambda self: False)
    with TestClient(create_app(settings)) as client:
        status = client.get("/api/verification/sandbox-status").json()
        assert status["mode"] == "docker" and not status["available"]
        response = client.post(f"/api/patches/{patch.id}/verifications", json={})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "sandbox_unavailable"
    assert (
        VerificationStore(settings.database_path).list_for_patch(patch.id, limit=20, offset=0)[1]
        == 0
    )
