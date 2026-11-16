"""Synchronous orchestration; transport, extraction, and atomic publication are separate."""

import logging
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from patchwork.config import Settings
from patchwork.errors import PatchworkError
from patchwork.ingestion.discovery import discover
from patchwork.ingestion.git import GitClient
from patchwork.ingestion.validation import normalize_url, validate_sha
from patchwork.intelligence.models import ParsedFile
from patchwork.intelligence.python import parse_python
from patchwork.repositories.models import Repository
from patchwork.repositories.store import RepositoryStore

logger = logging.getLogger(__name__)


def freeze_snapshot(root: Path) -> None:
    for directory, dirs, files in os.walk(root, topdown=False, followlinks=False):
        for name in [*dirs, *files]:
            child = Path(directory) / name
            if child.is_symlink():
                raise PatchworkError("unsafe_storage", "Snapshot storage contains a symlink.", 503)
            child.chmod(0o555 if child.is_dir() else 0o444)
    root.chmod(0o555)


def remove_snapshot(root: Path) -> None:
    # Only called for a newly-created private snapshot owned by this ingestion.
    for directory, _, _ in os.walk(root, followlinks=False):
        Path(directory).chmod(0o700)
    shutil.rmtree(root)


def ingest_repository(
    settings: Settings,
    url: str,
    commit_sha: str | None = None,
    *,
    client_type: type[GitClient] = GitClient,
) -> tuple[Repository, bool]:
    url = normalize_url(url)
    commit = validate_sha(commit_sha) if commit_sha is not None else None
    store = RepositoryStore(settings.database_path)
    deadline = time.monotonic() + settings.ingestion_timeout_seconds
    repository: Repository | None = None
    token: str | None = None
    snapshot: Path | None = None
    if commit is not None:
        repository, token = store.claim(url, commit, settings.ingestion_timeout_seconds)
        if token is None:
            return repository, True
    try:
        root = settings.repository_dir
        if root.is_symlink():
            raise PatchworkError("unsafe_storage", "Repository storage must not be a symlink.", 503)
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if root.stat().st_mode & 0o077:
            raise PatchworkError(
                "unsafe_storage", "Repository storage must be private (mode 0700).", 503
            )
        with tempfile.TemporaryDirectory(prefix="ingest-", dir=root) as temporary:
            client = client_type(settings, Path(temporary), deadline)
            if commit is None:
                commit = client.resolve(url)
                repository, token = store.claim(url, commit, settings.ingestion_timeout_seconds)
                if token is None:
                    return repository, True
            assert repository is not None and token is not None
            client.fetch(url, commit)
            sources, skipped = discover(client, commit, settings)
            parsed: list[ParsedFile] = []
            count = 0
            for source in sources:
                item = parse_python(
                    source, deadline=deadline, max_symbols=settings.max_symbols - count
                )
                count += len(item.symbols) + len(item.imports)
                parsed.append(item)
            if time.monotonic() >= deadline:
                raise PatchworkError("ingestion_timeout", "Repository indexing timed out.", 504)
            snapshot = root / f"{repository.id}-{token}.git"
            client.git_dir.rename(snapshot)
            freeze_snapshot(snapshot)
            result = store.publish(
                repository.id, token, parsed, skipped, snapshot.name, deadline=deadline
            )
            return result, False
    except Exception as cause:
        if isinstance(cause, PatchworkError):
            error = cause
        elif isinstance(cause, sqlite3.OperationalError) and time.monotonic() >= deadline:
            error = PatchworkError("ingestion_timeout", "Index publication timed out.", 504)
        elif isinstance(cause, (OSError, sqlite3.Error)):
            logger.exception("Repository storage failed")
            error = PatchworkError("storage_unavailable", "Repository storage is unavailable.", 503)
        else:
            logger.exception("Repository indexing failed")
            error = PatchworkError("indexing_failed", "Repository indexing failed.", 500)
        if snapshot is not None and snapshot.exists():
            remove_snapshot(snapshot)
        if error.code not in {"ingestion_in_progress", "ingestion_conflict"}:
            if repository is None:
                repository, token = store.claim(url, commit, settings.ingestion_timeout_seconds)
            if token is not None:
                store.fail(repository.id, token, error)
            error.repository_id = repository.id
        if error is cause:
            raise
        raise error from cause
