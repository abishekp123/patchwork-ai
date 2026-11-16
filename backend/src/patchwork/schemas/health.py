from typing import Literal

from pydantic import BaseModel


class HealthChecks(BaseModel):
    database: Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: Literal["patchwork-ai"] = "patchwork-ai"
    version: str
    checks: HealthChecks
