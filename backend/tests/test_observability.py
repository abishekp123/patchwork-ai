import logging
import re
from pathlib import Path

from fastapi.testclient import TestClient

from patchwork.config import Settings
from patchwork.main import create_app


def test_request_correlation_is_returned_and_error_body_matches(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "patchwork.db",
        repository_dir=tmp_path / "snapshots",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/health", headers={"X-Request-ID": "workbench.42"})
        assert response.headers["X-Request-ID"] == "workbench.42"

        invalid_id = client.get("/health", headers={"X-Request-ID": "not a safe id"})
        assert re.fullmatch(r"[0-9a-f]{32}", invalid_id.headers["X-Request-ID"])

        error = client.get("/api/not-a-route", headers={"X-Request-ID": "trace-404"})
        assert error.status_code == 404
        assert error.json()["error"]["request_id"] == "trace-404"


def test_request_logs_exclude_query_secrets(caplog, tmp_path: Path):
    caplog.set_level(logging.INFO, logger="patchwork.request")
    settings = Settings(
        database_path=tmp_path / "patchwork.db",
        repository_dir=tmp_path / "snapshots",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/health?access_token=must-not-be-logged")
    assert response.status_code == 200
    assert "must-not-be-logged" not in caplog.text
    assert "request.completed" in caplog.text
