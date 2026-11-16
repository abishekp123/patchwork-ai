"""Discover Python blobs from a pinned Git tree; never follow filesystem links."""

import hashlib
import io
import time
import tokenize
from collections import Counter
from dataclasses import dataclass

from patchwork.config import Settings
from patchwork.errors import PatchworkError
from patchwork.ingestion.git import GitClient
from patchwork.ingestion.validation import validate_path

IGNORED = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        "node_modules",
        "dist",
        "build",
        "vendor",
        "site-packages",
        ".eggs",
        "htmlcov",
        "generated",
        ".cache",
    }
)


@dataclass(frozen=True)
class SourceFile:
    path: str
    content_hash: str
    size_bytes: int
    encoding: str
    source: str


def discover(
    client: GitClient, commit: str, settings: Settings
) -> tuple[list[SourceFile], dict[str, int]]:
    entries = client.tree(commit).split(b"\0")
    if len(entries) - 1 > settings.max_tree_entries:
        raise PatchworkError("too_many_files", "Repository tree exceeds the entry limit.", 413)
    files: list[SourceFile] = []
    skipped: Counter[str] = Counter()
    expanded_size = source_size = 0
    for entry in sorted(filter(None, entries), key=lambda entry: entry.split(b"\t", 1)[-1]):
        if time.monotonic() >= client.deadline:
            raise PatchworkError("ingestion_timeout", "Repository operation timed out.", 504)
        header, raw_path = entry.split(b"\t", 1)
        mode, kind, oid, raw_size = header.split()
        if kind == b"blob":
            expanded_size += int(raw_size)
            if expanded_size > settings.max_repository_bytes:
                raise PatchworkError(
                    "repository_too_large", "Expanded repository exceeds the size limit.", 413
                )
        try:
            path = validate_path(raw_path.decode("utf-8"))
        except UnicodeError:
            skipped["invalid_path_encoding"] += 1
            continue
        parts = path.split("/")
        if any(part in IGNORED or part.endswith(".egg-info") for part in parts[:-1]):
            skipped["ignored_directory"] += 1
            continue
        if mode not in {b"100644", b"100755"} or kind != b"blob":
            skipped["symlink_or_submodule"] += 1
            continue
        if not path.endswith(".py"):
            skipped["not_python"] += 1
            continue
        size = int(raw_size)
        if size > settings.max_file_bytes:
            skipped["oversized_file"] += 1
            continue
        if (
            len(files) >= settings.max_python_files
            or source_size + size > settings.max_source_bytes
        ):
            raise PatchworkError(
                "index_too_large", "Python sources exceed the indexing limit.", 413
            )
        raw = client.blob(oid.decode("ascii"), size)
        if b"\x00" in raw:
            skipped["binary_file"] += 1
            continue
        try:
            encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
            source = raw.decode(encoding)
        except (UnicodeError, SyntaxError, LookupError):
            skipped["invalid_encoding"] += 1
            continue
        source_size += max(size, len(source.encode("utf-8")))
        if source_size > settings.max_source_bytes:
            raise PatchworkError(
                "index_too_large", "Decoded sources exceed the indexing limit.", 413
            )
        files.append(SourceFile(path, hashlib.sha256(raw).hexdigest(), size, encoding, source))
    return files, dict(sorted(skipped.items()))
