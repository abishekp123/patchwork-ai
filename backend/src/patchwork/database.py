"""SQLite connections and ordered, atomic schema migration."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from patchwork.migrations import MIGRATIONS


@contextmanager
def connect_database(path: Path) -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(path, timeout=2)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection


def initialize_database(path: Path) -> None:
    """Create the database on startup and fail fast if it cannot be opened."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect_database(path) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise RuntimeError("Database schema is newer than this application")
        for number, statements in enumerate(MIGRATIONS[version:], start=version + 1):
            for statement in statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {number}")


def check_database(path: Path) -> None:
    """Read the schema without silently recreating a missing database."""
    uri = f"{path.resolve().as_uri()}?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
        connection.execute("PRAGMA schema_version").fetchone()
