import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patchwork.config import Settings
from patchwork.main import create_app


def test_health_initializes_sqlite_and_returns_contract(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "patchwork.db"
    with TestClient(create_app(Settings(database_path=database_path))) as client:
        response = client.get("/health")

    assert database_path.is_file()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "status": "ok",
        "service": "patchwork-ai",
        "version": "0.1.0",
        "checks": {"database": "ok"},
    }


@pytest.mark.parametrize("failure", ["missing", "corrupt"])
def test_health_returns_503_when_database_becomes_unavailable(tmp_path: Path, failure: str) -> None:
    database_path = tmp_path / "patchwork.db"
    with TestClient(create_app(Settings(database_path=database_path))) as client:
        if failure == "missing":
            database_path.unlink()
        else:
            database_path.write_bytes(b"not a sqlite database" * 100)
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "service": "patchwork-ai",
        "version": "0.1.0",
        "checks": {"database": "error"},
    }
    assert str(tmp_path) not in response.text
    if failure == "missing":
        assert not database_path.exists()


def test_app_uses_environment_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "configured.db"
    monkeypatch.setenv("PATCHWORK_DATABASE_PATH", str(database_path))
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
    assert database_path.is_file()


def test_startup_fails_for_invalid_database(tmp_path: Path) -> None:
    database_path = tmp_path / "invalid.db"
    database_path.write_bytes(b"invalid database" * 100)
    with (
        pytest.raises(sqlite3.DatabaseError),
        TestClient(create_app(Settings(database_path=database_path))),
    ):
        pass


def test_openapi_documents_success_and_unavailable_responses(tmp_path: Path) -> None:
    app = create_app(Settings(database_path=tmp_path / "patchwork.db"))
    responses = app.openapi()["paths"]["/health"]["get"]["responses"]
    for code in ("200", "503"):
        assert responses[code]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/HealthResponse"
        }
