from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Repository(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    normalized_url: str
    commit_sha: str | None
    status: Literal["indexing", "ready", "failed"]
    created_at: str
    updated_at: str
    indexed_at: str | None
    error_code: str | None
    error_message: str | None
    index_version: int
    file_count: int
    symbol_count: int
    import_count: int
    skipped: dict[str, int] = Field(default_factory=dict)
