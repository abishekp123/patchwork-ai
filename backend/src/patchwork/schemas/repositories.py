from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from patchwork.errors import PatchworkError
from patchwork.ingestion.validation import normalize_url, validate_sha
from patchwork.intelligence.models import Import, Symbol
from patchwork.repositories.models import Repository


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=250, examples=["https://github.com/pallets/markupsafe"])
    commit_sha: str | None = Field(default=None, min_length=40, max_length=40)

    @field_validator("url")
    @classmethod
    def normalized(cls, value: str) -> str:
        try:
            return normalize_url(value)
        except PatchworkError as error:
            raise ValueError(error.message) from None

    @field_validator("commit_sha")
    @classmethod
    def pinned(cls, value: str | None) -> str | None:
        try:
            return validate_sha(value) if value is not None else None
        except PatchworkError as error:
            raise ValueError(error.message) from None


class ImportResponse(BaseModel):
    repository: Repository
    reused: bool


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class FileMetadata(BaseModel):
    path: str
    content_hash: str
    size_bytes: int
    encoding: str
    line_count: int
    has_errors: bool


class IndexedSymbol(Symbol):
    id: int


class IndexedImport(Import):
    id: int


class SearchHit(BaseModel):
    kind: Literal["symbol", "path", "text"]
    path: str
    start_line: int
    end_line: int
    snippet: str
    rank: int
    name: str | None = None
    qualified_name: str | None = None
    symbol_id: int | None = None


class SearchResponse(BaseModel):
    repository_id: str
    commit_sha: str
    query: str
    results: list[SearchHit]
    limit: int
    truncated: bool
