"""Single-process ownership and restart reconciliation for the local application."""

import fcntl
import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from patchwork.database import connect_database
from patchwork.errors import PatchworkError
from patchwork.repositories.store import timestamp


def owner_id(database: Path) -> str:
    return hashlib.sha256(str(database.resolve()).encode()).hexdigest()


def resource_root(database: Path) -> Path:
    root = Path(tempfile.gettempdir()) / f"patchwork-runtime-{owner_id(database)}"
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PatchworkError(
            "runtime_storage", "Runtime storage must be a private owned directory.", 503
        )
    return root


def reconcile(database: Path, *, cancelled: bool = False) -> None:
    """Owner lock must be held. Never replay inference or execution automatically."""
    status, error = ("CANCELLED", "server_shutdown") if cancelled else ("FAILED", "interrupted")
    now = timestamp()
    with connect_database(database) as db, db:
        db.execute("BEGIN IMMEDIATE")
        ids = db.execute(
            "SELECT id FROM investigations WHERE status NOT IN "
            "('COMPLETED','FAILED','CANCELLED','BUDGET_EXHAUSTED')"
        ).fetchall()
        for row in ids:
            db.execute(
                "INSERT INTO investigation_steps SELECT ?,coalesce(max(sequence),0)+1,?,? "
                "FROM investigation_steps WHERE investigation_id=?",
                (row[0], now, '{"recovery":"' + error + '"}', row[0]),
            )
        db.execute(
            "UPDATE investigations SET status=?,error_code=?,updated_at=?,completed_at=? "
            "WHERE status NOT IN ('COMPLETED','FAILED','CANCELLED','BUDGET_EXHAUSTED')",
            (status, error, now, now),
        )
        db.execute(
            "UPDATE verifications SET status=?,error_code=?,updated_at=?,completed_at=? "
            "WHERE status NOT IN ('COMPLETED','FAILED','CANCELLED')",
            (status, error, now, now),
        )


def cleanup_orphans(database: Path) -> None:
    root = resource_root(database)
    children = list(root.iterdir())
    if not children:
        return
    # An old worker may still own mounts. Remove only containers for this DB owner
    # before touching any files. If Docker is unavailable retain everything and fail closed.
    try:
        result = subprocess.run(
            ["docker", "ps", "-aq", "--filter", f"label=com.patchwork.owner={owner_id(database)}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        identifiers = result.stdout.split()
        if len(identifiers) > 100 or any(
            not re.fullmatch(r"[0-9a-f]{12,64}", value) for value in identifiers
        ):
            raise ValueError("Invalid container listing")
        for identifier in identifiers:
            subprocess.run(
                ["docker", "rm", "-f", identifier], capture_output=True, timeout=10, check=True
            )
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise PatchworkError(
            "recovery_cleanup_pending",
            "Interrupted jobs were failed. Start Docker and restart Patchwork "
            "to clean owned resources.",
            503,
        ) from error
    for child in children:
        if child.is_symlink() or not child.is_dir():
            child.unlink()
        else:
            shutil.rmtree(child)


@contextmanager
def application_owner(database: Path):
    database = database.resolve()  # Symlink/relative aliases must share the same lock inode.
    database.parent.mkdir(parents=True, exist_ok=True)
    lock = database.with_name(database.name + ".runtime.lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PatchworkError(
                "runtime_already_running",
                "Another Patchwork process owns this database. Use one worker.",
                503,
            ) from None
        yield
    finally:
        os.close(fd)  # OS releases this lock even after SIGKILL; do not unlink a live lock inode.
