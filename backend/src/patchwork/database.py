"""SQLite connections and ordered, atomic schema migration."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from patchwork.migrations import MIGRATIONS


@contextmanager
def connect_database(path: Path, *, create: bool = False) -> Iterator[sqlite3.Connection]:
    target = str(path) if create else f"{path.resolve().as_uri()}?mode=rw"
    with closing(sqlite3.connect(target, timeout=2, uri=not create)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection


def initialize_database(path: Path) -> None:
    """Create the database on startup and fail fast if it cannot be opened."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect_database(path, create=True) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise RuntimeError("Database schema is newer than this application")
        for statements in MIGRATIONS:
            for statement in statements:
                try:
                    connection.execute(statement)
                except sqlite3.OperationalError as error:
                    message = str(error).lower()
                    if (
                        "already exists" in message
                        or "duplicate column" in message
                        or "duplicate index" in message
                        or "index already exists" in message
                    ):
                        continue
                    raise
        connection.execute("PRAGMA user_version = 1")


def check_database(path: Path) -> None:
    """Read the schema without silently recreating a missing database."""
    uri = f"{path.resolve().as_uri()}?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
        connection.execute("PRAGMA schema_version").fetchone()
