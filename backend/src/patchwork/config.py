"""Environment configuration, resolved once per application instance."""

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_path: Path = Path("data/patchwork.db")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.environ.get("PATCHWORK_DATABASE_PATH", "data/patchwork.db"))
        )
