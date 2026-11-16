from typing import Literal

from pydantic import BaseModel, ConfigDict

from patchwork.ingestion.discovery import SourceFile


class Symbol(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    name: str
    qualified_name: str
    kind: Literal["module", "function", "class", "method"]
    parent: str | None = None
    is_async: bool = False
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    signature: str = ""
    decorators: tuple[str, ...] = ()
    has_errors: bool = False


class Import(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    module_name: str
    imported_name: str | None = None
    alias: str | None = None
    relative_level: int = 0
    scope: str | None = None
    start_line: int
    end_line: int
    start_byte: int
    statement: str


class ParsedFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: SourceFile
    has_errors: bool
    symbols: tuple[Symbol, ...]
    imports: tuple[Import, ...]
