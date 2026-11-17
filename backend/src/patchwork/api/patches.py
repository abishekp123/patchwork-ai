import os
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from patchwork.config import Settings
from patchwork.errors import PatchworkError
from patchwork.patches.engine import PatchGenerator, PatchValidator
from patchwork.patches.store import PatchStore
from patchwork.repositories.store import RepositoryStore
from patchwork.schemas.errors import ErrorResponse
from patchwork.schemas.patches import PatchDecision, PatchPage, PatchRequest, PatchResponse

ERROR_RESPONSES = {
    code: {"model": ErrorResponse} for code in (404, 409, 413, 422, 500, 502, 503, 504)
}
router = APIRouter(prefix="/patches", tags=["patches"], responses=ERROR_RESPONSES)
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
            "OPENAI_API_KEY is required to generate a patch.",
            503,
        )
    from patchwork.investigations.provider import OpenAIProvider

    return OpenAIProvider(settings.investigation_model, settings.provider_timeout_seconds)


@router.post("", response_model=PatchResponse, status_code=201)
async def create_patch(
    body: PatchRequest,
    settings: Config,
) -> PatchResponse:
    repository = RepositoryStore(settings.database_path).get(body.repository_id)
    if repository.status != "ready":
        raise PatchworkError("index_not_ready", "Repository index is not ready.", 409)
    evidence_refs = []
    if body.investigation_id is not None:
        from patchwork.investigations.store import Store as InvestigationStore

        investigation = InvestigationStore(settings).get(body.investigation_id)
        if (
            investigation.repository_id != repository.id
            or investigation.commit_sha != repository.commit_sha
        ):
            raise PatchworkError(
                "investigation_snapshot_mismatch",
                "Investigation evidence must belong to this repository snapshot.",
                409,
            )
        if investigation.status != "COMPLETED" or not investigation.report:
            raise PatchworkError(
                "investigation_not_complete",
                "A completed investigation is required to generate an evidence-backed patch.",
                409,
            )
        cited_ids = {
            evidence_id
            for finding in [
                *investigation.report.get("facts", []),
                *investigation.report.get("hypotheses", []),
            ]
            for evidence_id in finding.get("evidence_ids", [])
        }
        refs_by_id = {
            item.get("evidence_id"): item
            for item in investigation.report.get("evidence", [])
            if isinstance(item, dict) and isinstance(item.get("evidence_id"), str)
        }
        requested = set(body.evidence_ids)
        if not requested or not requested.issubset(cited_ids & refs_by_id.keys()):
            raise PatchworkError(
                "invalid_investigation_evidence",
                "Select evidence cited by the completed investigation.",
                422,
            )
        evidence_refs = [refs_by_id[item] for item in body.evidence_ids]
    provider = provider_for(settings)
    generator = PatchGenerator(settings, repository, provider)
    proposal = await generator.generate(
        body.description,
        evidence_ids=body.evidence_ids,
        evidence_refs=evidence_refs,
    )
    try:
        PatchValidator(settings, repository).validate(proposal)
    except ValueError:
        raise PatchworkError(
            "patch_validation_failed",
            "The proposed patch failed deterministic snapshot validation.",
            422,
        ) from None
    store = PatchStore(settings.database_path)
    record = store.create(repository, proposal, investigation_id=body.investigation_id)
    return PatchResponse(patch=record)


@router.get("", response_model=PatchPage)
def list_patches(
    settings: Config,
    limit: Limit = 20,
    offset: Offset = 0,
) -> PatchPage:
    items, total = PatchStore(settings.database_path).list(limit=limit, offset=offset)
    return PatchPage(items=list(items), total=total, limit=limit, offset=offset)


@router.get("/{identifier}", response_model=PatchResponse)
def get_patch(identifier: Identifier, settings: Config) -> PatchResponse:
    patch = PatchStore(settings.database_path).get(identifier)
    return PatchResponse(patch=patch)


@router.post("/{identifier}/approve", response_model=PatchResponse)
def approve_patch(
    identifier: Identifier,
    body: PatchDecision,
    settings: Config,
) -> PatchResponse:
    if body.decision != "approve":
        raise PatchworkError("invalid_decision", "Only approval decisions are accepted here.", 422)
    record = PatchStore(settings.database_path).transition(
        identifier,
        "approved",
        reviewer=body.reviewer,
        reason=body.reason,
    )
    return PatchResponse(patch=record)


@router.post("/{identifier}/reject", response_model=PatchResponse)
def reject_patch(
    identifier: Identifier,
    body: PatchDecision,
    settings: Config,
) -> PatchResponse:
    if body.decision != "reject":
        raise PatchworkError("invalid_decision", "Only rejection decisions are accepted here.", 422)
    record = PatchStore(settings.database_path).transition(
        identifier,
        "rejected",
        reviewer=body.reviewer,
        reason=body.reason,
    )
    return PatchResponse(patch=record)
