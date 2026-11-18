import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_verifications import _ready_repository

from patchwork.errors import PatchworkError
from patchwork.investigations.store import Store
from patchwork.main import create_app
from patchwork.patches.engine import PatchChange, PatchProposal
from patchwork.patches.store import PatchStore
from patchwork.runtime import application_owner, cleanup_orphans, owner_id, resource_root
from patchwork.verifications.models import VerificationSummary
from patchwork.verifications.store import VerificationStore


def verification(settings, repository):
    patch = PatchStore(settings.database_path).create(
        repository,
        PatchProposal(
            title="Recovery fixture",
            summary="Known repair",
            changes=[
                PatchChange(
                    path="example.py",
                    before="def bug():\n    return 1\n",
                    after="def bug():\n    return 2\n",
                    reason="Fixture",
                )
            ],
        ),
    )
    return VerificationStore(settings.database_path).create(
        patch_id=patch.id,
        repository_id=repository.id,
        commit_sha=repository.commit_sha,
        sandbox_mode="docker",
    )


def test_startup_reconciles_interrupted_preserving_evidence(settings):
    repository = _ready_repository(settings)
    investigation = Store(settings).create(repository, "Investigate crash")
    record = verification(settings, repository)
    store = VerificationStore(settings.database_path)
    summary = VerificationSummary(exit_code=1, tests_failed=1, tests_total=1)
    store.update(record.id, status="RUNNING_PATCHED", baseline_summary=summary)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert Store(settings).get(investigation.id).error_code == "interrupted"
        recovered = store.get(record.id)
        assert recovered.status == "FAILED" and recovered.error_code == "interrupted"
        assert recovered.baseline_summary == summary
    with TestClient(create_app(settings)):
        assert store.get(record.id) == recovered
    assert Store(settings).steps(investigation.id)[0]["data"] == {"recovery": "interrupted"}


def test_terminal_updates_and_cancellation_are_idempotent(settings):
    repository = _ready_repository(settings)
    with TestClient(create_app(settings)) as client:
        record = verification(settings, repository)
        store = VerificationStore(settings.database_path)
        store.update(record.id, baseline_summary=VerificationSummary(exit_code=1))
        url = f"/api/verifications/{record.id}/cancel"
        first = client.post(url).json()
        assert client.post(url).json() == first
        cancelled = store.get(record.id)
        assert cancelled.status == "CANCELLED" and cancelled.baseline_summary.exit_code == 1
        assert store.update(record.id, status="COMPLETED") == cancelled
        investigation = Store(settings).create(repository, "Cancellation")
        url = f"/api/investigations/{investigation.id}/cancel"
        first = client.post(url).json()
        assert client.post(url).json() == first
        Store(settings).transition(investigation.id, "FAILED", error="late_failure")
        assert Store(settings).get(investigation.id).status == "CANCELLED"


def test_shutdown_cancels_jobs_that_have_not_started(settings):
    repository = _ready_repository(settings)
    with TestClient(create_app(settings)):
        investigation = Store(settings).create(repository, "Not dispatched yet")
        record = verification(settings, repository)
    assert Store(settings).get(investigation.id).status == "CANCELLED"
    assert VerificationStore(settings.database_path).get(record.id).error_code == "server_shutdown"


def test_duplicate_investigations_are_serialized_and_retry_is_explicit(settings):
    repository = _ready_repository(settings)

    def submit():
        try:
            return Store(settings).create(repository, "Same bug")
        except PatchworkError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert results.count("investigation_in_progress") == 1
    record = next(item for item in results if not isinstance(item, str))
    Store(settings).transition(record.id, "FAILED", error="interrupted")
    assert Store(settings).create(repository, "Same bug").id != record.id


def test_owner_lock_rejects_second_server(settings):
    with (
        application_owner(settings.database_path),
        pytest.raises(PatchworkError, match="one worker"),
    ):
        with TestClient(create_app(settings)):
            pass


def test_sigkill_releases_owner_and_next_start_fails_interrupted_jobs(settings):
    repository = _ready_repository(settings)
    code = """
import sys,time
from pathlib import Path
from patchwork.config import Settings
from patchwork.runtime import application_owner
from patchwork.repositories.store import RepositoryStore
from patchwork.investigations.store import Store
settings=Settings(database_path=Path(sys.argv[1]),repository_dir=Path(sys.argv[2]))
with application_owner(settings.database_path):
    repo=RepositoryStore(settings.database_path).get(sys.argv[3])
    record=Store(settings).create(repo,'Crash test')
    print(record.id,flush=True)
    time.sleep(60)
"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            code,
            str(settings.database_path),
            str(settings.repository_dir),
            repository.id,
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        identifier = process.stdout.readline().strip()
        assert len(identifier) == 32
        process.kill()
        process.wait(timeout=5)
        with TestClient(create_app(settings)):
            assert Store(settings).get(identifier).error_code == "interrupted"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_orphan_cleanup_scopes_containers_and_never_follows_symlinks(
    settings, tmp_path, monkeypatch
):
    root = resource_root(settings.database_path)
    external = tmp_path / "keep"
    external.mkdir()
    (external / "important").write_text("keep")
    (root / "link").symlink_to(external)
    (root / "job-old").mkdir()
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert (root / "job-old").exists()  # Mounts are cleaned before directories.
        return subprocess.CompletedProcess(args, 0, "a" * 12 if "ps" in args else "", "")

    monkeypatch.setattr("patchwork.runtime.subprocess.run", run)
    cleanup_orphans(settings.database_path)
    assert f"label=com.patchwork.owner={owner_id(settings.database_path)}" in calls[0]
    assert calls[1] == ["docker", "rm", "-f", "a" * 12]
    assert not list(root.iterdir()) and (external / "important").read_text() == "keep"


def test_unavailable_docker_keeps_orphan_mounts(settings, monkeypatch):
    root = resource_root(settings.database_path)
    marker = root / "job-old"
    marker.mkdir()

    def unavailable(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr("patchwork.runtime.subprocess.run", unavailable)
    with pytest.raises(PatchworkError, match="Start Docker"):
        cleanup_orphans(settings.database_path)
    assert marker.exists()
    marker.rmdir()


def test_database_alias_cannot_acquire_a_second_owner(settings, tmp_path):
    _ready_repository(settings)
    alias = tmp_path / "alias.db"
    alias.symlink_to(settings.database_path)
    with application_owner(settings.database_path):
        with pytest.raises(PatchworkError, match="one worker"), application_owner(alias):
            pass
