from typing import Literal

from pydantic import BaseModel


class DashboardActivity(BaseModel):
    kind: Literal["investigation", "patch", "verification"]
    id: str
    repository_id: str
    status: str
    updated_at: str
    label: str


class DashboardSummary(BaseModel):
    ready_repositories: int
    investigations: int
    pending_patches: int
    approved_patches: int
    active_verifications: int
    completed_verifications: int
    recent_activity: list[DashboardActivity]
