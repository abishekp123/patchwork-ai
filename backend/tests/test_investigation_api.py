import time
from collections.abc import Iterator

import pytest
from conftest import PUBLIC_URL
from fastapi.testclient import TestClient

from patchwork.api.repositories import git_client_type
from patchwork.config import Settings
from patchwork.ingestion.git import GitClient
from patchwork.investigations.models import Call, Decision
from patchwork.investigations.provider import FakeProvider
from patchwork.main import create_app


@pytest.fixture
def api(settings: Settings, client_type: type[GitClient]) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[git_client_type] = lambda: client_type
    with TestClient(app) as client:
        yield client


def test_investigation_history_background_execution_and_provider_status(
    api: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    repository = api.post("/api/repositories", json={"url": PUBLIC_URL}).json()["repository"]
    status = api.get("/api/investigations/provider-status")
    assert status.status_code == 200
    assert status.json()["available"] is False
    assert "OPENAI_API_KEY" in status.json()["reason"]

    provider = FakeProvider(
        [
            Decision(
                call=Call(
                    name="finish_report",
                    arguments={
                        "summary": "The source snapshot was reviewed.",
                        "facts": [],
                        "hypotheses": [],
                        "next_steps": ["Review the indexed source."],
                        "limitations": ["No source citation was needed."],
                    },
                ),
                input_tokens=8,
                output_tokens=5,
                usage_available=True,
            )
        ]
    )
    monkeypatch.setattr("patchwork.api.investigations.provider_for", lambda _settings: provider)
    created = api.post(
        "/api/investigations",
        json={
            "repository_id": repository["id"],
            "description": "Review the simple fixture.",
        },
    )
    assert created.status_code == 201
    identifier = created.json()["investigation"]["id"]
    for _ in range(50):
        record = api.get(f"/api/investigations/{identifier}").json()
        if record["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            break
        time.sleep(0.02)
    assert record["status"] == "COMPLETED"
    assert record["report"]["summary"] == "The source snapshot was reviewed."
    assert (
        api.get("/api/investigations", params={"repository_id": repository["id"]}).json()["items"][
            0
        ]["id"]
        == identifier
    )
    assert api.get(f"/api/investigations/{identifier}/steps").json()["total"] >= 1
