import sqlite3
from pathlib import Path

import pytest
from conftest import PUBLIC_URL
from test_python_index import parse

from patchwork.config import Settings
from patchwork.database import connect_database, initialize_database
from patchwork.errors import PatchworkError
from patchwork.ingestion.git import GitClient
from patchwork.repositories.service import ingest_repository
from patchwork.repositories.store import RepositoryStore, repository_id


def test_migration_is_repeatable_and_preserves_existing_database(settings: Settings) -> None:
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("CREATE TABLE prior_data (value TEXT)")
        connection.execute("INSERT INTO prior_data VALUES ('preserved')")
    initialize_database(settings.database_path)
    initialize_database(settings.database_path)
    with connect_database(settings.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT value FROM prior_data").fetchone()[0] == "preserved"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migration_rollback(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "patchwork.database.MIGRATIONS", (("CREATE TABLE transient (id INTEGER)", "INVALID SQL"),)
    )
    with pytest.raises(sqlite3.OperationalError):
        initialize_database(settings.database_path)
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE name = 'transient'").fetchone()
            is None
        )


def test_atomic_publication_and_constraints(settings: Settings) -> None:
    initialize_database(settings.database_path)
    store = RepositoryStore(settings.database_path)
    record, token = store.claim(PUBLIC_URL, "a" * 40, 10)
    assert token
    item = parse("import os\ndef run(): pass\n")
    with pytest.raises(sqlite3.IntegrityError):
        store.publish(record.id, token, [item, item], {}, "test.git")
    with connect_database(settings.database_path) as connection:
        for table in ("files", "symbols", "imports"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert store.get(record.id).status == "indexing"
    ready = store.publish(record.id, token, [item], {}, "test.git")
    assert (ready.file_count, ready.symbol_count, ready.import_count) == (1, 2, 1)
    with pytest.raises(PatchworkError, match="lease"):
        store.publish(record.id, token, [], {}, "other.git")
    assert store.get(record.id) == ready


def test_duplicate_claim_and_expired_lease(settings: Settings) -> None:
    initialize_database(settings.database_path)
    store = RepositoryStore(settings.database_path)
    record, old_token = store.claim(PUBLIC_URL, "a" * 40, 10)
    with pytest.raises(PatchworkError) as failure:
        store.claim(PUBLIC_URL, "a" * 40, 10)
    assert failure.value.status_code == 409
    with connect_database(settings.database_path) as connection, connection:
        connection.execute("UPDATE repositories SET lease_expires = 0")
    _, new_token = store.claim(PUBLIC_URL, "a" * 40, 10)
    assert new_token and new_token != old_token
    assert old_token
    store.fail(record.id, old_token, PatchworkError("old", "old"))
    assert store.get(record.id).status == "indexing"
    with pytest.raises(PatchworkError):
        store.publish(record.id, old_token, [], {}, "old.git")
    store.publish(record.id, new_token, [], {}, "new.git")


def test_complete_import_repeat_and_revision_isolation(
    settings: Settings, local_repo: tuple[Path, str, str], client_type: type[GitClient]
) -> None:
    initialize_database(settings.database_path)
    _, old, current = local_repo
    first, reused = ingest_repository(settings, PUBLIC_URL, old, client_type=client_type)
    assert not reused and first.status == "ready"
    assert first.commit_sha == old and first.file_count == 1
    again, reused = ingest_repository(settings, PUBLIC_URL, old, client_type=client_type)
    assert reused and again == first
    latest, reused = ingest_repository(settings, PUBLIC_URL, client_type=client_type)
    assert not reused and latest.commit_sha == current and latest.id != first.id
    assert len(list(settings.repository_dir.glob("*.git"))) == 2
    assert not list(settings.repository_dir.glob("ingest-*"))
    for snapshot in settings.repository_dir.glob("*.git"):
        assert snapshot.stat().st_mode & 0o222 == 0
        assert (snapshot / "HEAD").stat().st_mode & 0o222 == 0
    with connect_database(settings.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM files").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM symbols").fetchone()[0] == 4
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failed_import_is_persisted_and_retryable(
    settings: Settings, local_repo: tuple[Path, str, str], client_type: type[GitClient]
) -> None:
    initialize_database(settings.database_path)
    commit = local_repo[2]
    tiny = settings.model_copy(update={"max_source_bytes": 1})
    with pytest.raises(PatchworkError) as failure:
        ingest_repository(tiny, PUBLIC_URL, commit, client_type=client_type)
    identifier = failure.value.repository_id
    assert identifier
    record = RepositoryStore(settings.database_path).get(identifier)
    assert record.status == "failed" and record.error_code == "index_too_large"
    assert record.file_count == 0 and record.indexed_at is None
    assert list(settings.repository_dir.iterdir()) == []
    ready, _ = ingest_repository(settings, PUBLIC_URL, commit, client_type=client_type)
    assert ready.id == identifier and ready.error_code is None


def test_resolution_failure_is_recorded(settings: Settings) -> None:
    class Unavailable(GitClient):
        def resolve(self, url: str) -> str:
            raise PatchworkError("upstream_unavailable", "Unavailable", 502)

    initialize_database(settings.database_path)
    with pytest.raises(PatchworkError):
        ingest_repository(settings, PUBLIC_URL, client_type=Unavailable)
    record = RepositoryStore(settings.database_path).get(repository_id(PUBLIC_URL, None))
    assert record.commit_sha is None and record.status == "failed"


def test_concurrent_claims_have_one_owner(settings: Settings) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    initialize_database(settings.database_path)
    barrier = Barrier(2)

    def claim() -> str:
        barrier.wait(timeout=5)
        try:
            _, token = RepositoryStore(settings.database_path).claim(PUBLIC_URL, "a" * 40, 10)
            assert token
            return "claimed"
        except PatchworkError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _i: claim(), range(2)))
    assert sorted(outcomes) == ["claimed", "ingestion_in_progress"]


def test_repeat_pinned_import_does_not_contact_remote(
    settings: Settings, client_type: type[GitClient], local_repo: tuple[Path, str, str]
) -> None:
    initialize_database(settings.database_path)
    first, _ = ingest_repository(settings, PUBLIC_URL, local_repo[1], client_type=client_type)

    class NoNetwork(GitClient):
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("Repeat pinned import must not create a transport")

    repeated, reused = ingest_repository(settings, PUBLIC_URL, local_repo[1], client_type=NoNetwork)
    assert reused and repeated == first


def test_publication_failure_cleans_snapshot_and_records_failure(
    settings: Settings,
    client_type: type[GitClient],
    local_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize_database(settings.database_path)

    def fail_publish(*args: object, **kwargs: object) -> None:
        raise PatchworkError("publication_failed", "Test publication failure", 503)

    monkeypatch.setattr(RepositoryStore, "publish", fail_publish)
    with pytest.raises(PatchworkError) as failure:
        ingest_repository(settings, PUBLIC_URL, local_repo[1], client_type=client_type)
    assert failure.value.repository_id
    record = RepositoryStore(settings.database_path).get(failure.value.repository_id)
    assert record.status == "failed" and record.file_count == 0
    assert list(settings.repository_dir.iterdir()) == []


def test_publication_deadline_rolls_back(settings: Settings) -> None:
    initialize_database(settings.database_path)
    store = RepositoryStore(settings.database_path)
    record, token = store.claim(PUBLIC_URL, "a" * 40, 10)
    assert token
    with pytest.raises(PatchworkError) as failure:
        store.publish(record.id, token, [parse("def run(): pass\n")], {}, "test.git", deadline=0)
    assert failure.value.code == "ingestion_timeout"
    with connect_database(settings.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM files").fetchone()[0] == 0


def test_foreign_keys_reject_cross_repository_symbols(settings: Settings) -> None:
    initialize_database(settings.database_path)
    store = RepositoryStore(settings.database_path)
    first, token = store.claim(PUBLIC_URL, "a" * 40, 10)
    assert token
    store.publish(first.id, token, [parse("def run(): pass\n")], {}, "first.git")
    second, _ = store.claim(PUBLIC_URL, "b" * 40, 10)
    with connect_database(settings.database_path) as connection, connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE symbols SET repository_id = ?", (second.id,))


def test_newer_schema_is_rejected(settings: Settings) -> None:
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError, match="newer"):
        initialize_database(settings.database_path)
