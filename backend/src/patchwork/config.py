"""Environment configuration, resolved once per application instance."""

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, validate_default=True)

    database_path: Path = Path("data/patchwork.db")
    repository_dir: Path = Path.home() / ".local/share/patchwork-ai/repositories"
    clone_timeout_seconds: float = Field(default=60, gt=0, le=600)
    ingestion_timeout_seconds: float = Field(default=120, gt=0, le=1800)
    max_repository_bytes: int = Field(default=50_000_000, gt=0, le=1_000_000_000)
    max_file_bytes: int = Field(default=512_000, gt=0, le=2_000_000)
    max_source_bytes: int = Field(default=10_000_000, gt=0, le=100_000_000)
    max_tree_entries: int = Field(default=20_000, gt=0, le=100_000)
    max_python_files: int = Field(default=2_000, gt=0, le=10_000)
    max_symbols: int = Field(default=50_000, gt=0, le=200_000)
    max_results: int = Field(default=100, gt=0, le=500)
    max_snippet_chars: int = Field(default=300, ge=40, le=2000)

    @field_validator("repository_dir")
    @classmethod
    def external_storage(cls, value: Path) -> Path:
        if value.is_symlink():
            raise ValueError("Repository storage must not be a symlink")
        resolved = value.expanduser().resolve()
        source_root = Path(__file__).resolve().parents[3]
        if resolved == source_root or resolved.is_relative_to(source_root):
            raise ValueError("Repository storage must be outside the application source tree")
        return resolved

    @classmethod
    def from_env(cls) -> "Settings":
        values = {
            name: os.environ[f"PATCHWORK_{name.upper()}"]
            for name in cls.model_fields
            if f"PATCHWORK_{name.upper()}" in os.environ
        }
        return cls.model_validate(values)
