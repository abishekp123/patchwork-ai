import asyncio
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from patchwork.config import Settings
from patchwork.database import connect_database
from patchwork.errors import PatchworkError
from patchwork.investigations.engine import run as run_investigation
from patchwork.investigations.models import TERMINAL, Investigation
from patchwork.investigations.provider import OpenAIProvider
from patchwork.investigations.store import Store
from patchwork.repositories.store import RepositoryStore
from patchwork.schemas.errors import ErrorResponse
from patchwork.schemas.investigations import (
    InvestigationRequest,
    InvestigationResponse,
    InvestigationStep,
    InvestigationStepPage,
    ProviderStatus,
)
from patchwork.schemas.repositories import Page

ERROR_RESPONSES = {
    code: {"model": ErrorResponse} for code in (404, 409, 413, 422, 500, 502, 503, 504)
}
router = APIRouter(prefix="/investigations", tags=["investigations"], responses=ERROR_RESPONSES)
Identifier = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


def settings_from_request(request: Request) -> Settings:
    return request.app.state.settings


Config = Annotated[Settings, Depends(settings_from_request)]


def provider_for(settings: Settings):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise PatchworkError(
            "provider_credentials_missing",
            "OPENAI_API_KEY is required to run an investigation.",
            503,
        )
    return OpenAIProvider(settings.investigation_model, settings.provider_timeout_seconds)


@router.post("", response_model=InvestigationResponse, status_code=201)
async def create_investigation(
    body: InvestigationRequest,
    settings: Config,
    request: Request,
) -> InvestigationResponse:
    repository = RepositoryStore(settings.database_path).get(body.repository_id)
    if repository.status != "ready":
        raise PatchworkError("index_not_ready", "Repository index is not ready.", 409)
    provider = provider_for(settings)
    store = Store(settings)
    record = store.create(repository, body.description)
    task = asyncio.create_task(run_investigation(settings, record, repository, provider))
    tasks: dict[str, asyncio.Task] = request.app.state.investigation_tasks
    tasks[record.id] = task
    task.add_done_callback(
        lambda completed: tasks.pop(record.id, None) if tasks.get(record.id) is completed else None
    )
    return InvestigationResponse(investigation=record)


@router.get("", response_model=Page[Investigation])
def list_investigations(
    settings: Config,
    repository_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[Investigation]:
    items, total = Store(settings).list(repository_id, limit, offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/provider-status", response_model=ProviderStatus)
def investigation_provider_status(settings: Config) -> ProviderStatus:
    available = bool(os.environ.get("OPENAI_API_KEY"))
    return ProviderStatus(
        available=available,
        provider="openai",
        model=settings.investigation_model,
        reason=None if available else "Configure OPENAI_API_KEY to run an investigation.",
    )


@router.get("/{identifier}", response_model=Investigation)
def get_investigation(identifier: Identifier, settings: Config) -> Investigation:
    return Store(settings).get(identifier)


@router.get("/{identifier}/steps", response_model=InvestigationStepPage)
def list_investigation_steps(
    identifier: Identifier,
    settings: Config,
    limit: Limit = 50,
    offset: Offset = 0,
) -> InvestigationStepPage:
    store = Store(settings)
    store.get(identifier)
    with connect_database(settings.database_path) as connection:
        total = connection.execute(
            "SELECT count(*) FROM investigation_steps WHERE investigation_id = ?",
            (identifier,),
        ).fetchone()[0]
    steps = store.steps(identifier, limit, offset)
    return InvestigationStepPage(
        items=[InvestigationStep.model_validate(item) for item in steps],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{identifier}/cancel", response_model=Investigation)
async def cancel_investigation(
    identifier: Identifier,
    settings: Config,
    request: Request,
) -> Investigation:
    store = Store(settings)
    record = store.get(identifier)
    if record.status in TERMINAL:
        return record
    store.transition(identifier, "CANCELLED", error="cancelled_by_user")
    task = request.app.state.investigation_tasks.get(identifier)
    if task is not None:
        task.cancel()
    return store.get(identifier)
