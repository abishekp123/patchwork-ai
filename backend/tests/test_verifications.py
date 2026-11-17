import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from patchwork.config import Settings
from patchwork.database import initialize_database
from patchwork.errors import PatchworkError
from patchwork.ingestion.discovery import SourceFile
from patchwork.intelligence.models import Import, ParsedFile, Symbol
from patchwork.patches.engine import PatchChange, PatchGenerator, PatchProposal
from patchwork.patches.store import PatchStore
from patchwork.repositories.store import RepositoryStore
from patchwork.verifications.engine import _apply_patch_to_snapshot, run_verification
from patchwork.verifications.models import SandboxConfig
from patchwork.verifications.sandbox import FakeSandboxAdapter, SandboxAdapter, SandboxFactory
from patchwork.verifications.store import VerificationStore


def _ready_repository(settings: Settings):
    initialize_database(settings.database_path)
    store = RepositoryStore(settings.database_path)
    repository, token = store.claim("https://github.com/example/python-project", "a" * 40, 10)
    assert token is not None
    parsed = ParsedFile(
        file=SourceFile(
            path="example.py",
            content_hash="abc123",
            size_bytes=20,
            encoding="utf-8",
            source="def bug():\n    return 1\n",
        ),
        has_errors=False,
        symbols=(
            Symbol(
                path="example.py",
                name="bug",
                qualified_name="bug",
                kind="function",
                parent=None,
                start_line=1,
                end_line=2,
                start_byte=0,
                end_byte=12,
            ),
        ),
        imports=(
            Import(
                path="example.py",
                module_name="os",
                imported_name="path",
                alias=None,
                relative_level=0,
                scope=None,
                start_line=1,
                end_line=1,
                start_byte=0,
                statement="import os",
            ),
        ),
    )
    return store.publish(repository.id, token, [parsed], {}, "fixture.git")


def test_fake_sandbox_returns_test_summary():
    adapter = FakeSandboxAdapter()
    summary, stdout, stderr = adapter.run(
        command="python -m pytest -q",
        workspace=Path("/tmp"),
        timeout_seconds=30,
    )
    assert summary.exit_code == 0
    assert summary.tests_total == 1
    assert summary.tests_passed == 1
    assert stdout == "[100%] success\n"
    assert stderr == ""


def test_sandbox_factory_dispatches_modes():
    assert isinstance(SandboxFactory.create("fake"), FakeSandboxAdapter)
    assert isinstance(SandboxFactory.create("docker"), SandboxAdapter)


def test_sandbox_policy_rejects_unsafe_configuration(tmp_path: Path):
    config = SandboxConfig(
        mode="docker",
        network_disabled=False,
        read_only_root=True,
        no_new_privileges=True,
    )
    with pytest.raises(PatchworkError, match="Network must be disabled"):
        SandboxAdapter(config).validate_policy()

    unsafe = SandboxConfig(
        mode="docker",
        read_only_root=True,
        no_new_privileges=True,
        extra_args=["--privileged=true"],
    )
    with pytest.raises(PatchworkError, match="Unsafe Docker flags"):
        SandboxAdapter(unsafe).validate_policy()

    root_user = SandboxConfig(mode="docker", user="0:0")
    with pytest.raises(PatchworkError, match="non-root"):
        SandboxAdapter(root_user).validate_policy()

    unpinned_image = SandboxConfig(
        mode="docker",
        image="python:3.12-slim",
        trusted_roots=["/tmp"],
    )
    with pytest.raises(PatchworkError, match="pinned by SHA-256"):
        SandboxAdapter(unpinned_image).validate_policy()

    unsafe_workdir = SandboxConfig(
        mode="docker",
        workdir="/workspace,ro",
        trusted_roots=[str(tmp_path)],
    )
    with pytest.raises(PatchworkError, match="fixed /workspace"):
        SandboxAdapter(unsafe_workdir).validate_policy()

    comma_workspace = tmp_path / "workspace,ro=true"
    comma_workspace.mkdir()
    trusted_adapter = SandboxAdapter(SandboxConfig(mode="docker", trusted_roots=[str(tmp_path)]))
    with pytest.raises(PatchworkError, match="mount separators"):
        trusted_adapter._trusted_workspace(comma_workspace)


def test_generated_unified_diff_is_applied_to_snapshot(tmp_path: Path):
    source = "def add(left, right):\n    return left - right\n"
    repaired = "def add(left, right):\n    return left + right\n"
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    target = snapshot / "calculator.py"
    target.write_text(source, encoding="utf-8")
    diff = PatchGenerator.build_diff("calculator.py", source, repaired)

    _apply_patch_to_snapshot(snapshot, diff)

    assert target.read_text(encoding="utf-8") == repaired


def test_generated_unified_diff_rejects_stale_snapshot(tmp_path: Path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    target = snapshot / "calculator.py"
    target.write_text("def add(left, right):\n    return left * right\n", encoding="utf-8")
    diff = PatchGenerator.build_diff(
        "calculator.py",
        "def add(left, right):\n    return left - right\n",
        "def add(left, right):\n    return left + right\n",
    )

    with pytest.raises(PatchworkError, match="does not match the indexed source"):
        _apply_patch_to_snapshot(snapshot, diff)
    assert target.read_text(encoding="utf-8") == "def add(left, right):\n    return left * right\n"


def test_docker_adapter_reports_unavailable_when_not_installed(monkeypatch):
    monkeypatch.setattr("patchwork.verifications.sandbox.shutil.which", lambda _: None)
    adapter = SandboxAdapter(SandboxConfig(mode="docker"))
    assert adapter.available() is False


def test_verification_engine_runs_for_approved_patch(settings: Settings):
    repository = _ready_repository(settings)
    proposal = PatchProposal(
        title="Guard the bug path",
        summary="This patch keeps the reviewed repair traceable.",
        changes=[
            PatchChange(
                path="example.py",
                before="def bug():\n    return 1\n",
                after="def bug():\n    return 1\n# verified patch\n",
                reason="Keep the change explicit for review.",
            )
        ],
        evidence_ids=[],
    )
    patch = PatchStore(settings.database_path).create(repository, proposal)
    approved = PatchStore(settings.database_path).transition(
        patch.id,
        "approved",
        reviewer="human",
        reason="Ready for runtime verification.",
    )
    assert approved.status == "approved"

    record = asyncio.run(
        run_verification(
            settings,
            approved.id,
            repository_id=repository.id,
            commit_sha=repository.commit_sha,
            baseline_command="python -m pytest -q",
            patched_command="python -m pytest -q",
            sandbox_mode="fake",
        )
    )
    assert record.status == "COMPLETED"
    assert record.comparison is not None
    assert record.comparison.status == "UNCHANGED"
    assert record.baseline_summary is not None
    assert record.patched_summary is not None


def test_verification_store_rejects_invalid_status_updates(settings: Settings):
    repository = _ready_repository(settings)
    proposal = PatchProposal(
        title="Status check",
        summary="Validate store transitions.",
        changes=[
            PatchChange(
                path="example.py",
                before="def bug():\n    return 1\n",
                after="def bug():\n    return 2\n",
                reason="Exercise the verification lifecycle.",
            )
        ],
        evidence_ids=[],
    )
    patch = PatchStore(settings.database_path).create(repository, proposal)
    record = VerificationStore(settings.database_path).create(
        patch_id=patch.id,
        repository_id=repository.id,
        commit_sha=repository.commit_sha,
        sandbox_mode="fake",
    )
    with pytest.raises(ValueError, match="Unsupported verification status"):
        VerificationStore(settings.database_path).update(record.id, status="NOT_REAL")


def test_concurrent_verification_creation_allows_only_one_active_run(settings: Settings):
    repository = _ready_repository(settings)
    patch = PatchStore(settings.database_path).create(
        repository,
        PatchProposal(
            title="Concurrent review",
            summary="Run only one active verification per approved patch.",
            changes=[
                PatchChange(
                    path="example.py",
                    before="def bug():\n    return 1\n",
                    after="def bug():\n    return 2\n",
                    reason="Exercise verification serialization.",
                )
            ],
        ),
    )
    PatchStore(settings.database_path).transition(
        patch.id,
        "approved",
        reviewer="human",
        reason="Approved for the concurrency test.",
    )
    store = VerificationStore(settings.database_path)

    def create():
        try:
            return store.create(
                patch_id=patch.id,
                repository_id=repository.id,
                commit_sha=repository.commit_sha,
                sandbox_mode="fake",
            )
        except PatchworkError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: create(), range(2)))
    assert sum(not isinstance(result, str) for result in results) == 1
    assert results.count("verification_in_progress") == 1
