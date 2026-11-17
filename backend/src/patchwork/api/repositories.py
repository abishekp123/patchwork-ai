from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from patchwork.config import Settings
from patchwork.errors import PatchworkError
from patchwork.ingestion.git import GitClient
from patchwork.intelligence import search as retrieval
from patchwork.repositories.models import Repository
from patchwork.repositories.service import ingest_repository
from patchwork.repositories.store import RepositoryStore
from patchwork.schemas.errors import ErrorResponse
from patchwork.schemas.repositories import (
    FileContent,
    FileMetadata,
    ImportRequest,
    ImportResponse,
    IndexedImport,
    IndexedSymbol,
    Page,
    SearchResponse,
)

ERROR_RESPONSES = {
    code: {"model": ErrorResponse} for code in (404, 409, 413, 422, 500, 502, 503, 504)
}
router = APIRouter(prefix="/repositories", tags=["repositories"], responses=ERROR_RESPONSES)
Identifier = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0, le=100_000)]
Commit = Annotated[str | None, Query(pattern=r"^[0-9a-fA-F]{40}$")]


def settings_from_request(request: Request) -> Settings:
    return request.app.state.settings


def git_client_type() -> type[GitClient]:
    """Dependency injection is for server composition/tests, never user-controlled transport."""
    return GitClient


Config = Annotated[Settings, Depends(settings_from_request)]


def ready_repository(identifier: str, settings: Settings, commit_sha: str | None) -> Repository:
    repository = RepositoryStore(settings.database_path).get(identifier)
    if commit_sha is not None and repository.commit_sha != commit_sha.lower():
        raise PatchworkError(
            "revision_not_found", "This repository ID does not index that commit.", 404
        )
    if repository.status != "ready":
        raise PatchworkError("index_not_ready", "Repository index is not ready.", 409)
    return repository


@router.post(
    "", response_model=ImportResponse, status_code=201, responses={200: {"model": ImportResponse}}
)
def import_repository(
    body: ImportRequest,
    response: Response,
    settings: Config,
    client_type: Annotated[type[GitClient], Depends(git_client_type)],
) -> ImportResponse:
    """Fetch and index synchronously. A full commit SHA makes repeat imports network-free."""
    repository, reused = ingest_repository(
        settings, body.url, body.commit_sha, client_type=client_type
    )
    response.status_code = 200 if reused else 201
    return ImportResponse(repository=repository, reused=reused)


@router.get("", response_model=Page[Repository])
def list_repositories(settings: Config, limit: Limit = 20, offset: Offset = 0) -> Page[Repository]:
    limit = min(limit, settings.max_results)
    items, total = RepositoryStore(settings.database_path).list_repositories(limit, offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{identifier}", response_model=Repository)
def get_repository(identifier: Identifier, settings: Config) -> Repository:
    return RepositoryStore(settings.database_path).get(identifier)


@router.get("/{identifier}/symbols", response_model=Page[IndexedSymbol])
def find_symbols(
    identifier: Identifier,
    settings: Config,
    name: Annotated[str | None, Query(min_length=1, max_length=4096)] = None,
    exact: bool = True,
    commit_sha: Commit = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[IndexedSymbol]:
    """Case-sensitive exact simple/qualified name lookup; exact=false uses casefolded substrings."""
    ready_repository(identifier, settings, commit_sha)
    return retrieval.symbols(
        settings, identifier, name, exact, min(limit, settings.max_results), offset
    )


@router.get("/{identifier}/files", response_model=Page[FileMetadata])
def list_files(
    identifier: Identifier,
    settings: Config,
    commit_sha: Commit = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[FileMetadata]:
    ready_repository(identifier, settings, commit_sha)
    return retrieval.files(settings, identifier, min(limit, settings.max_results), offset)


@router.get("/{identifier}/files/{path:path}/content", response_model=FileContent)
def get_file_content(
    identifier: Identifier,
    path: Annotated[str, Path(min_length=1, max_length=4096)],
    settings: Config,
    commit_sha: Commit = None,
    start_line: Annotated[int, Query(ge=1)] = 1,
    end_line: Annotated[int | None, Query(ge=1)] = None,
) -> FileContent:
    repository = ready_repository(identifier, settings, commit_sha)
    return retrieval.file_content(settings, repository, path, start_line, end_line)


@router.get("/{identifier}/imports", response_model=Page[IndexedImport])
def list_imports(
    identifier: Identifier,
    settings: Config,
    commit_sha: Commit = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[IndexedImport]:
    ready_repository(identifier, settings, commit_sha)
    return retrieval.imports(settings, identifier, min(limit, settings.max_results), offset)


@router.get("/{identifier}/search", response_model=SearchResponse)
def search_code(
    identifier: Identifier,
    settings: Config,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    commit_sha: Commit = None,
    limit: Limit = 20,
) -> SearchResponse:
    """Literal search ranked by symbol exact/prefix/substring, path matches, then source lines."""
    repository = ready_repository(identifier, settings, commit_sha)
    return retrieval.search(settings, repository, q, min(limit, settings.max_results))
