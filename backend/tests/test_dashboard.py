from pathlib import Path

from fastapi.testclient import TestClient

from patchwork.config import Settings
from patchwork.database import connect_database
from patchwork.main import create_app


def test_dashboard_counts_and_recent_persisted_activity(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "patchwork.db",
        repository_dir=tmp_path / "snapshots",
    )
    with TestClient(create_app(settings)) as client:
        with connect_database(settings.database_path) as connection, connection:
            connection.execute(
                """INSERT INTO repositories (
                    id, normalized_url, commit_sha, status, created_at, updated_at,
                    indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    "r" * 64,
                    "https://github.com/example/project",
                    "c" * 40,
                    "ready",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                ),
            )
            connection.execute(
                """INSERT INTO investigations (
                    id, repository_id, commit_sha, description, status, created_at,
                    updated_at, expires
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "i" * 32,
                    "r" * 64,
                    "c" * 40,
                    "Investigate the indexed issue",
                    "COMPLETED",
                    "2026-01-01T00:00:01Z",
                    "2026-01-01T00:00:01Z",
                    0,
                ),
            )
            patches = (
                ("p" * 32, "pending_review", "Review this repair"),
                ("q" * 32, "approved", "Approved repair"),
            )
            for patch_id, status, title in patches:
                connection.execute(
                    """INSERT INTO patches (
                        id, repository_id, commit_sha, status, title, summary, diff,
                        evidence_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        patch_id,
                        "r" * 64,
                        "c" * 40,
                        status,
                        title,
                        "Summary",
                        "",
                        "[]",
                        "2026-01-01T00:00:02Z",
                        "2026-01-01T00:00:02Z",
                    ),
                )
            verification_rows = (
                ("v" * 32, "p" * 32, "RUNNING_BASELINE"),
                ("w" * 32, "q" * 32, "COMPLETED"),
            )
            for verification_id, patch_id, status in verification_rows:
                connection.execute(
                    """INSERT INTO verifications (
                        id, patch_id, repository_id, commit_sha, status,
                        sandbox_mode, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        verification_id,
                        patch_id,
                        "r" * 64,
                        "c" * 40,
                        status,
                        "docker",
                        "2026-01-01T00:00:03Z",
                        "2026-01-01T00:00:03Z",
                    ),
                )

        response = client.get("/api/dashboard")

    assert response.status_code == 200
    result = response.json()
    assert result == {
        "ready_repositories": 1,
        "investigations": 1,
        "pending_patches": 1,
        "approved_patches": 1,
        "active_verifications": 1,
        "completed_verifications": 1,
        "recent_activity": [
            {
                "kind": "verification",
                "id": "v" * 32,
                "repository_id": "r" * 64,
                "status": "RUNNING_BASELINE",
                "updated_at": "2026-01-01T00:00:03Z",
                "label": "Verification for patch " + "p" * 8,
            },
            {
                "kind": "verification",
                "id": "w" * 32,
                "repository_id": "r" * 64,
                "status": "COMPLETED",
                "updated_at": "2026-01-01T00:00:03Z",
                "label": "Verification for patch " + "q" * 8,
            },
            {
                "kind": "patch",
                "id": "p" * 32,
                "repository_id": "r" * 64,
                "status": "pending_review",
                "updated_at": "2026-01-01T00:00:02Z",
                "label": "Review this repair",
            },
            {
                "kind": "patch",
                "id": "q" * 32,
                "repository_id": "r" * 64,
                "status": "approved",
                "updated_at": "2026-01-01T00:00:02Z",
                "label": "Approved repair",
            },
            {
                "kind": "investigation",
                "id": "i" * 32,
                "repository_id": "r" * 64,
                "status": "COMPLETED",
                "updated_at": "2026-01-01T00:00:01Z",
                "label": "Investigate the indexed issue",
            },
        ],
    }
