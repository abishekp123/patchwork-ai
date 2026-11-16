"""Minimal SQLite lifecycle; no domain schema until persistence is needed."""

import sqlite3
from contextlib import closing
from pathlib import Path


def initialize_database(path: Path) -> None:
    """Create the database on startup and fail fast if it cannot be opened."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=2)) as connection:
        connection.execute("PRAGMA schema_version").fetchone()


def check_database(path: Path) -> None:
    """Read the schema without silently recreating a missing database."""
    uri = f"{path.resolve().as_uri()}?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
        connection.execute("PRAGMA schema_version").fetchone()
