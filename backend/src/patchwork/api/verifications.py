import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from patchwork.config import Settings
from patchwork.errors import PatchworkError
from patchwork.patches.store import PatchStore
from patchwork.repositories.store import RepositoryStore, timestamp
from patchwork.schemas.errors import ErrorResponse
from patchwork.schemas.verifications import (
    SandboxStatusResponse,
    VerificationPage,
    VerificationRequest,
    VerificationResponse,
    VerificationResultResponse,
)
from patchwork.verifications.engine import run_verification
from patchwork.verifications.sandbox import SandboxFactory
from patchwork.verifications.store import VerificationStore

ERROR_RESPONSES = {
    code: {"model": ErrorResponse} for code in (404, 409, 413, 422, 500, 502, 503, 504)
}
router = APIRouter(tags=["verifications"], responses=ERROR_RESPONSES)
Identifier = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


def settings_from_request(request: Request) -> Settings:
    return request.app.state.settings


Config = Annotated[Settings, Depends(settings_from_request)]


@router.post(
    "/patches/{identifier}/verifications",
    response_model=VerificationResponse,
    status_code=201,
)
async def create_verification_for_patch(
    identifier: Identifier,
    request: Request,
    settings: Config,
    body: VerificationRequest | None = None,
) -> VerificationResponse:
    patch = PatchStore(settings.database_path).get(identifier)
    if patch.status != "approved":
        raise PatchworkError(
            "patch_not_approved",
            "Only approved patches can be verified.",
            409,
        )
    repository = RepositoryStore(settings.database_path).get(patch.repository_id)
    if repository.status != "ready":
        raise PatchworkError("index_not_ready", "Repository index is not ready.", 409)
    if repository.commit_sha != patch.commit_sha:
        raise PatchworkError(
            "verification_mismatch",
            "Patch and repository snapshot do not match.",
            409,
        )

    payload = body or VerificationRequest()
    store = VerificationStore(settings.database_path)
    record = store.create(
        patch_id=patch.id,
        repository_id=repository.id,
        commit_sha=repository.commit_sha,
        sandbox_mode=payload.sandbox_mode,
    )

    tasks = getattr(request.app.state, "verification_tasks", {})
    task = asyncio.create_task(
        run_verification(
            settings,
            patch.id,
            repository_id=repository.id,
            commit_sha=repository.commit_sha,
            baseline_command=payload.baseline_command or "python -m pytest -q",
            patched_command=payload.patched_command or "python -m pytest -q",
            sandbox_mode=payload.sandbox_mode,
            verification_id=record.id,
        )
    )
    tasks[record.id] = task
    request.app.state.verification_tasks = tasks

    def _cleanup(_finished_task: asyncio.Task[object]) -> None:
        remaining = getattr(request.app.state, "verification_tasks", {})
        remaining.pop(record.id, None)
        request.app.state.verification_tasks = remaining

    task.add_done_callback(_cleanup)
    return VerificationResponse(verification=store.get(record.id))


@router.get("/patches/{identifier}/verifications", response_model=VerificationPage)
def list_patch_verifications(
    identifier: Identifier,
    settings: Config,
    limit: Limit = 20,
    offset: Offset = 0,
) -> VerificationPage:
    PatchStore(settings.database_path).get(identifier)
    items, total = VerificationStore(settings.database_path).list_for_patch(
        identifier,
        limit=limit,
        offset=offset,
    )
    return VerificationPage(items=list(items), total=total, limit=limit, offset=offset)


@router.get("/verifications/{identifier}", response_model=VerificationResponse)
def get_verification(identifier: Identifier, settings: Config) -> VerificationResponse:
    record = VerificationStore(settings.database_path).get(identifier)
    return VerificationResponse(verification=record)


@router.get("/verifications/{identifier}/results", response_model=VerificationResultResponse)
def get_verification_results(
    identifier: Identifier,
    settings: Config,
) -> VerificationResultResponse:
    record = VerificationStore(settings.database_path).get(identifier)
    return VerificationResultResponse(verification_id=record.id, result=record.comparison)


@router.post("/verifications/{identifier}/cancel", response_model=VerificationResponse)
async def cancel_verification(
    identifier: Identifier,
    settings: Config,
    request: Request,
) -> VerificationResponse:
    store = VerificationStore(settings.database_path)
    record = store.get(identifier)
    if record.status in {"COMPLETED", "FAILED", "CANCELLED"}:
        return VerificationResponse(verification=record)
    tasks = getattr(request.app.state, "verification_tasks", {})
    task = tasks.get(identifier)
    if task is not None and not task.done():
        task.cancel()
    request.app.state.verification_tasks = tasks
    store.update(
        identifier,
        status="CANCELLED",
        updated_at=timestamp(),
        completed_at=timestamp(),
        error_code="cancelled_by_user",
    )
    return VerificationResponse(verification=store.get(identifier))


@router.get("/verification/sandbox-status", response_model=SandboxStatusResponse)
def sandbox_status(settings: Config) -> SandboxStatusResponse:
    mode = settings.sandbox_mode
    adapter = SandboxFactory.create(mode)
    if mode == "fake":
        return SandboxStatusResponse(
            available=adapter.available(),
            mode=mode,
            reason="Fake sandbox for deterministic tests.",
        )
    try:
        adapter.validate_policy()
        return SandboxStatusResponse(available=adapter.available(), mode=mode)
    except PatchworkError as error:
        return SandboxStatusResponse(available=False, mode=mode, reason=error.message)
