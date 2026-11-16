import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from patchwork.database import connect_database
from patchwork.errors import PatchworkError
from patchwork.intelligence.models import ParsedFile
from patchwork.repositories.models import Repository


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def repository_id(url: str, commit: str | None) -> str:
    return hashlib.sha256(f"{url}\0{commit or 'unresolved'}".encode()).hexdigest()


def as_repository(row: dict[str, object]) -> Repository:
    return Repository.model_validate({**row, "skipped": json.loads(str(row["skipped_json"]))})


class RepositoryStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def get(self, identifier: str) -> Repository:
        with connect_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM repositories WHERE id = ?", (identifier,)
            ).fetchone()
        if row is None:
            raise PatchworkError("repository_not_found", "Repository snapshot was not found.", 404)
        return as_repository(dict(row))

    def list(self, limit: int, offset: int) -> tuple[list[Repository], int]:
        with connect_database(self.database_path) as connection:
            total = connection.execute("SELECT count(*) FROM repositories").fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM repositories ORDER BY created_at, id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [as_repository(dict(row)) for row in rows], total

    def claim(self, url: str, commit: str | None, duration: float) -> tuple[Repository, str | None]:
        identifier, now, token = repository_id(url, commit), timestamp(), uuid.uuid4().hex
        with connect_database(self.database_path) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM repositories WHERE id = ?", (identifier,)
            ).fetchone()
            if row is not None:
                if row["status"] == "ready":
                    return as_repository(dict(row)), None
                if row["status"] == "indexing" and row["lease_expires"] > time.time():
                    error = PatchworkError(
                        "ingestion_in_progress", "This snapshot is already being indexed.", 409
                    )
                    error.repository_id = identifier
                    raise error
                connection.execute(
                    """UPDATE repositories SET status = 'indexing', updated_at = ?,
                    error_code = NULL,
                    error_message = NULL, lease_token = ?, lease_expires = ? WHERE id = ?""",
                    (now, token, time.time() + duration + 30, identifier),
                )
            else:
                connection.execute(
                    """INSERT INTO repositories
                    (id, normalized_url, commit_sha, status, created_at, updated_at,
                    lease_token, lease_expires)
                    VALUES (?, ?, ?, 'indexing', ?, ?, ?, ?)""",
                    (identifier, url, commit, now, now, token, time.time() + duration + 30),
                )
        return self.get(identifier), token

    def fail(self, identifier: str, token: str, error: PatchworkError) -> None:
        with connect_database(self.database_path) as connection, connection:
            connection.execute(
                """UPDATE repositories SET status = 'failed', updated_at = ?, error_code = ?,
                error_message = ?, lease_token = NULL, lease_expires = NULL
                WHERE id = ? AND lease_token = ? AND status = 'indexing'""",
                (timestamp(), error.code, error.message, identifier, token),
            )

    def publish(
        self,
        identifier: str,
        token: str,
        files: list[ParsedFile],
        skipped: dict[str, int],
        snapshot_name: str,
    ) -> Repository:
        now = timestamp()
        with connect_database(self.database_path) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT lease_token, status FROM repositories WHERE id = ?", (identifier,)
            ).fetchone()
            if row is None or row["lease_token"] != token or row["status"] != "indexing":
                raise PatchworkError(
                    "ingestion_conflict", "The ingestion lease is no longer owned.", 409
                )
            connection.execute("DELETE FROM files WHERE repository_id = ?", (identifier,))
            for parsed in files:
                file = parsed.file
                cursor = connection.execute(
                    """INSERT INTO files (repository_id, path, path_key, content_hash, size_bytes,
                    encoding, source, line_count, has_errors) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        identifier,
                        file.path,
                        file.path.casefold(),
                        file.content_hash,
                        file.size_bytes,
                        file.encoding,
                        file.source,
                        max(1, file.source.count("\n") + (not file.source.endswith("\n"))),
                        parsed.has_errors,
                    ),
                )
                file_id = cursor.lastrowid
                connection.executemany(
                    """INSERT INTO symbols (repository_id, file_id, name, qualified_name, name_key,
                    qualified_key, kind, start_line, end_line, start_byte, data_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            identifier,
                            file_id,
                            symbol.name,
                            symbol.qualified_name,
                            symbol.name.casefold(),
                            symbol.qualified_name.casefold(),
                            symbol.kind,
                            symbol.start_line,
                            symbol.end_line,
                            symbol.start_byte,
                            symbol.model_dump_json(),
                        )
                        for symbol in parsed.symbols
                    ],
                )
                connection.executemany(
                    """INSERT INTO imports
                    (repository_id, file_id, module_name, start_byte, data_json)
                    VALUES (?, ?, ?, ?, ?)""",
                    [
                        (
                            identifier,
                            file_id,
                            item.module_name,
                            item.start_byte,
                            item.model_dump_json(),
                        )
                        for item in parsed.imports
                    ],
                )
            connection.execute(
                """UPDATE repositories SET status = 'ready', updated_at = ?, indexed_at = ?,
                snapshot_name = ?, file_count = ?, symbol_count = ?, import_count = ?,
                skipped_json = ?,
                lease_token = NULL, lease_expires = NULL, error_code = NULL, error_message = NULL
                WHERE id = ?""",
                (
                    now,
                    now,
                    snapshot_name,
                    len(files),
                    sum(len(file.symbols) for file in files),
                    sum(len(file.imports) for file in files),
                    json.dumps(skipped, sort_keys=True),
                    identifier,
                ),
            )
        return self.get(identifier)
