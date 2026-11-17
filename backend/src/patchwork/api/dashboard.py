from typing import Annotated

from fastapi import APIRouter, Depends, Request

from patchwork.config import Settings
from patchwork.database import connect_database
from patchwork.schemas.dashboard import DashboardActivity, DashboardSummary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def settings_from_request(request: Request) -> Settings:
    return request.app.state.settings


Config = Annotated[Settings, Depends(settings_from_request)]


@router.get("", response_model=DashboardSummary)
def get_dashboard(settings: Config) -> DashboardSummary:
    with connect_database(settings.database_path) as connection:
        ready_repositories = connection.execute(
            "SELECT count(*) FROM repositories WHERE status='ready'"
        ).fetchone()[0]
        investigations = connection.execute("SELECT count(*) FROM investigations").fetchone()[0]
        pending_patches = connection.execute(
            "SELECT count(*) FROM patches WHERE status='pending_review'"
        ).fetchone()[0]
        approved_patches = connection.execute(
            "SELECT count(*) FROM patches WHERE status='approved'"
        ).fetchone()[0]
        active_verifications = connection.execute(
            """SELECT count(*) FROM verifications
            WHERE status IN (
                'CREATED', 'PREPARING', 'RUNNING_BASELINE',
                'RUNNING_PATCHED', 'COMPARING'
            )"""
        ).fetchone()[0]
        completed_verifications = connection.execute(
            "SELECT count(*) FROM verifications WHERE status='COMPLETED'"
        ).fetchone()[0]
        rows = connection.execute(
            """SELECT kind, id, repository_id, status, updated_at, label FROM (
                SELECT 'investigation' AS kind, id, repository_id, status, updated_at,
                    substr(description, 1, 120) AS label FROM investigations
                UNION ALL
                SELECT 'patch', id, repository_id, status, updated_at, title FROM patches
                UNION ALL
                SELECT 'verification', id, repository_id, status, updated_at,
                    'Verification for patch ' || substr(patch_id, 1, 8) FROM verifications
            ) ORDER BY updated_at DESC, kind, id LIMIT 12"""
        ).fetchall()
    return DashboardSummary(
        ready_repositories=ready_repositories,
        investigations=investigations,
        pending_patches=pending_patches,
        approved_patches=approved_patches,
        active_verifications=active_verifications,
        completed_verifications=completed_verifications,
        recent_activity=[DashboardActivity.model_validate(dict(row)) for row in rows],
    )
