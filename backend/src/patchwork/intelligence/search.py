"""Bounded lexical search over immutable indexed source, with deterministic ranking."""

import json
import sqlite3

from patchwork.config import Settings
from patchwork.database import connect_database
from patchwork.errors import PatchworkError
from patchwork.ingestion.validation import validate_path
from patchwork.repositories.models import Repository
from patchwork.schemas.repositories import (
    FileContent,
    FileMetadata,
    IndexedImport,
    IndexedSymbol,
    Page,
    SearchHit,
    SearchResponse,
)


def snippet(line: str, query: str, limit: int) -> str:
    line = line.rstrip("\r")
    if len(line) <= limit:
        return line
    folded_offset = line.casefold().find(query.casefold())
    original_offset = 0
    if folded_offset > 0:
        length = 0
        for index, character in enumerate(line):
            length += len(character.casefold())
            if length > folded_offset:
                original_offset = index
                break
    start = max(0, original_offset - limit // 3)
    return line[start : start + limit]


def symbols(
    settings: Settings, identifier: str, name: str | None, exact: bool, limit: int, offset: int
) -> Page[IndexedSymbol]:
    clauses, parameters = ["s.repository_id = ?"], [identifier]
    if name is not None:
        if exact:
            clauses.append("(s.name = ? OR s.qualified_name = ?)")
            parameters.extend([name, name])
        else:
            clauses.append("(instr(s.name_key, ?) > 0 OR instr(s.qualified_key, ?) > 0)")
            parameters.extend([name.casefold(), name.casefold()])
    where = " AND ".join(clauses)
    with connect_database(settings.database_path) as connection:
        total = connection.execute(
            f"SELECT count(*) FROM symbols s WHERE {where}", parameters
        ).fetchone()[0]
        rows = connection.execute(
            f"""SELECT s.id, s.data_json FROM symbols s JOIN files f ON f.id = s.file_id
            WHERE {where} ORDER BY f.path, s.start_byte, s.kind, s.id LIMIT ? OFFSET ?""",
            [*parameters, limit, offset],
        ).fetchall()
    return Page(
        items=[IndexedSymbol(id=row["id"], **json.loads(row["data_json"])) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def files(settings: Settings, identifier: str, limit: int, offset: int) -> Page[FileMetadata]:
    with connect_database(settings.database_path) as connection:
        total = connection.execute(
            "SELECT count(*) FROM files WHERE repository_id = ?", (identifier,)
        ).fetchone()[0]
        rows = connection.execute(
            """SELECT path, content_hash, size_bytes, encoding, line_count, has_errors
            FROM files WHERE repository_id = ? ORDER BY path LIMIT ? OFFSET ?""",
            (identifier, limit, offset),
        ).fetchall()
    return Page(
        items=[FileMetadata.model_validate(dict(row)) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def file_content(
    settings: Settings,
    repository: Repository,
    path: str,
    start_line: int,
    end_line: int | None,
) -> FileContent:
    safe_path = validate_path(path)
    with connect_database(settings.database_path) as connection:
        row = connection.execute(
            """SELECT content_hash, source, line_count FROM files
            WHERE repository_id = ? AND path = ?""",
            (repository.id, safe_path),
        ).fetchone()
    if row is None:
        raise PatchworkError("file_not_found", "File is not present in this snapshot.", 404)
    if end_line is None:
        end_line = min(row["line_count"], start_line + 199)
    if start_line > row["line_count"] or end_line < start_line or end_line - start_line >= 200:
        raise PatchworkError("invalid_range", "Request a valid source range of at most 200 lines.")
    lines = row["source"].split("\n")
    content = "\n".join(lines[start_line - 1 : end_line])
    assert repository.commit_sha is not None
    return FileContent(
        repository_id=repository.id,
        commit_sha=repository.commit_sha,
        path=safe_path,
        content_hash=row["content_hash"],
        start_line=start_line,
        end_line=end_line,
        total_lines=row["line_count"],
        content=content,
    )


def imports(settings: Settings, identifier: str, limit: int, offset: int) -> Page[IndexedImport]:
    with connect_database(settings.database_path) as connection:
        total = connection.execute(
            "SELECT count(*) FROM imports WHERE repository_id = ?", (identifier,)
        ).fetchone()[0]
        rows = connection.execute(
            """SELECT i.id, i.data_json FROM imports i JOIN files f ON f.id = i.file_id
            WHERE i.repository_id = ? ORDER BY f.path, i.start_byte, i.id LIMIT ? OFFSET ?""",
            (identifier, limit, offset),
        ).fetchall()
    return Page(
        items=[IndexedImport(id=row["id"], **json.loads(row["data_json"])) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def search(settings: Settings, repository: Repository, query: str, limit: int) -> SearchResponse:
    limit = max(1, min(limit, settings.max_results))
    query = query.strip()
    if not query:
        raise PatchworkError(
            "invalid_query", "Search query must contain non-whitespace characters."
        )
    needle = query.casefold()
    identifier = repository.id
    hits: list[SearchHit] = []
    cache: dict[int, list[str]] = {}

    def line_at(connection: sqlite3.Connection, file_id: int, number: int) -> str:
        if file_id not in cache:
            source = connection.execute(
                "SELECT source FROM files WHERE id = ?", (file_id,)
            ).fetchone()[0]
            cache[file_id] = source.split("\n")
        lines = cache[file_id]
        return lines[number - 1] if number <= len(lines) else ""

    with connect_database(settings.database_path) as connection:
        rows = connection.execute(
            """SELECT s.id, s.file_id, s.name, s.qualified_name, s.start_line, s.end_line, f.path,
            CASE WHEN s.name_key = :q OR s.qualified_key = :q THEN 0
            WHEN substr(s.name_key, 1, length(:q)) = :q
              OR substr(s.qualified_key, 1, length(:q)) = :q THEN 1 ELSE 2 END AS rank
            FROM symbols s JOIN files f ON f.id = s.file_id
            WHERE s.repository_id = :id
              AND (instr(s.name_key, :q) > 0 OR instr(s.qualified_key, :q) > 0)
            ORDER BY rank, f.path, s.start_byte, s.id LIMIT :limit""",
            {"q": needle, "id": identifier, "limit": limit + 1},
        )
        for row in rows:
            hits.append(
                SearchHit(
                    kind="symbol",
                    path=row["path"],
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                    snippet=snippet(
                        line_at(connection, row["file_id"], row["start_line"]),
                        query,
                        settings.max_snippet_chars,
                    ),
                    rank=row["rank"],
                    name=row["name"],
                    qualified_name=row["qualified_name"],
                    symbol_id=row["id"],
                )
            )
        if len(hits) <= limit:
            rows = connection.execute(
                """SELECT id, path, CASE WHEN path_key = :q THEN 3
                WHEN substr(path_key, 1, length(:q)) = :q THEN 4 ELSE 5 END AS rank
                FROM files WHERE repository_id = :id AND instr(path_key, :q) > 0
                ORDER BY rank, path LIMIT :limit""",
                {"q": needle, "id": identifier, "limit": limit + 1 - len(hits)},
            )
            for row in rows:
                hits.append(
                    SearchHit(
                        kind="path",
                        path=row["path"],
                        start_line=1,
                        end_line=1,
                        rank=row["rank"],
                        snippet=snippet(
                            line_at(connection, row["id"], 1), query, settings.max_snippet_chars
                        ),
                    )
                )
        if len(hits) <= limit:
            # At most max_source_bytes per snapshot. Literal matching, never a regex or subprocess.
            for row in connection.execute(
                "SELECT path, source FROM files WHERE repository_id = ? ORDER BY path",
                (identifier,),
            ):
                for number, line in enumerate(row["source"].split("\n"), start=1):
                    if needle in line.casefold():
                        hits.append(
                            SearchHit(
                                kind="text",
                                path=row["path"],
                                start_line=number,
                                end_line=number,
                                snippet=snippet(line, query, settings.max_snippet_chars),
                                rank=6,
                            )
                        )
                        if len(hits) > limit:
                            break
                if len(hits) > limit:
                    break
    assert repository.commit_sha is not None
    return SearchResponse(
        repository_id=identifier,
        commit_sha=repository.commit_sha,
        query=query,
        results=hits[:limit],
        limit=limit,
        truncated=len(hits) > limit,
    )
