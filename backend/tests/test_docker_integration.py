import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from patchwork.config import Settings
from patchwork.database import connect_database, initialize_database
from patchwork.ingestion.discovery import SourceFile
from patchwork.intelligence.python import parse_python
from patchwork.patches.engine import PatchChange, PatchProposal
from patchwork.patches.store import PatchStore
from patchwork.repositories.store import RepositoryStore
from patchwork.verifications.engine import run_verification
from patchwork.verifications.models import SandboxConfig
from patchwork.verifications.sandbox import SandboxAdapter

pytestmark = pytest.mark.docker_integration

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "docker_verification"
DOCKER_IMAGE = "python@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c"


@pytest.fixture(autouse=True)
def require_real_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.environ.get("PATCHWORK_RUN_DOCKER_INTEGRATION") != "1":
        pytest.skip("Set PATCHWORK_RUN_DOCKER_INTEGRATION=1 to run real Docker tests.")
    bundled_cli = Path("/Applications/Docker.app/Contents/Resources/bin")
    current_path = os.environ.get("PATH", "")
    if bundled_cli.is_dir() and str(bundled_cli) not in current_path.split(os.pathsep):
        monkeypatch.setenv("PATH", f"{bundled_cli}{os.pathsep}{current_path}")
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail("Docker CLI is required when integration tests are explicitly enabled.")
    engine = subprocess.run(
        [docker, "info", "--format", "{{.OSType}}/{{.Architecture}}"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if engine.returncode != 0:
        pytest.fail("Docker Engine is required when integration tests are explicitly enabled.")
    platform = engine.stdout.strip().replace("aarch64", "arm64").replace("x86_64", "amd64")
    assert platform in {"linux/amd64", "linux/arm64"}
    image = subprocess.run(
        [docker, "image", "inspect", DOCKER_IMAGE, "--format", "{{.Os}}/{{.Architecture}}"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert image.returncode == 0, (
        "Pull the pinned fixture image outside the sandbox first: "
        f"docker pull --platform {platform} {DOCKER_IMAGE}"
    )
    assert image.stdout.strip() == platform


def _manifest() -> dict[str, object]:
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    allowed_files = manifest["files"]
    assert isinstance(allowed_files, dict)
    declared_paths = set(allowed_files)
    actual_paths = {
        path.relative_to(FIXTURE_ROOT).as_posix()
        for path in FIXTURE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    assert actual_paths == declared_paths
    for relative, expected_hash in allowed_files.items():
        candidate = FIXTURE_ROOT / relative
        assert not candidate.is_symlink()
        assert candidate.resolve().is_relative_to(FIXTURE_ROOT.resolve())
        assert hashlib.sha256(candidate.read_bytes()).hexdigest() == expected_hash
    assert manifest["image"] == DOCKER_IMAGE
    assert manifest["platforms"] == ["linux/amd64", "linux/arm64"]
    return manifest


def _tracked_containers() -> set[str]:
    result = subprocess.run(
        ["docker", "ps", "--all", "--quiet", "--filter", "label=com.patchwork.verification=true"],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    return set(result.stdout.split())


def _approved_fixture_patch(settings: Settings, manifest: dict[str, object]):
    initialize_database(settings.database_path)
    store = RepositoryStore(settings.database_path)
    repository, token = store.claim(
        "fixture://patchwork-ai/docker-verification",
        "a" * 40,
        60,
    )
    assert token is not None
    parsed_files = []
    for relative in manifest["snapshot_files"]:
        source_bytes = (FIXTURE_ROOT / relative).read_bytes()
        source = source_bytes.decode("utf-8")
        file = SourceFile(
            path=relative,
            content_hash=hashlib.sha256(source_bytes).hexdigest(),
            size_bytes=len(source_bytes),
            encoding="utf-8",
            source=source,
        )
        parsed_files.append(parse_python(file, deadline=time.monotonic() + 10, max_symbols=1000))
    repository = store.publish(
        repository.id,
        token,
        parsed_files,
        {},
        "locally-authored-docker-fixture",
    )
    source = next(item.file.source for item in parsed_files if item.file.path == "calculator.py")
    proposal = PatchProposal(
        title="Repair the fixture addition function",
        summary="Return the arithmetic sum expected by the fixture test.",
        changes=[
            PatchChange(
                path="calculator.py",
                before=source,
                after="def add(left: int, right: int) -> int:\n    return left + right\n",
                reason="The fixture currently subtracts instead of adding.",
            )
        ],
        evidence_ids=[],
    )
    patches = PatchStore(settings.database_path)
    draft = patches.create(repository, proposal)
    approved = patches.transition(
        draft.id,
        "approved",
        reviewer="docker-integration-test",
        reason="Controlled local fixture only.",
    )
    return repository, approved


def test_real_docker_approved_patch_baseline_and_repair_workflow(tmp_path: Path) -> None:
    manifest = _manifest()
    before_containers = _tracked_containers()
    fixture_hashes = {
        relative: hashlib.sha256((FIXTURE_ROOT / relative).read_bytes()).hexdigest()
        for relative in manifest["files"]
    }
    settings = Settings(
        database_path=tmp_path / "patchwork.sqlite3",
        repository_dir=tmp_path / "repository-storage",
        verification_timeout_seconds=45,
        verification_output_limit_bytes=8192,
    )
    repository, patch = _approved_fixture_patch(settings, manifest)
    with connect_database(settings.database_path) as connection:
        original_index = [
            tuple(row)
            for row in connection.execute(
                "SELECT path, content_hash, source FROM files "
                "WHERE repository_id = ? ORDER BY path",
                (repository.id,),
            ).fetchall()
        ]

    record = asyncio.run(
        run_verification(
            settings,
            patch.id,
            repository_id=repository.id,
            commit_sha=repository.commit_sha,
            baseline_command=manifest["baseline_command"],
            patched_command=manifest["baseline_command"],
            sandbox_mode="docker",
        )
    )

    assert record.status == "COMPLETED"
    assert record.baseline_summary is not None
    assert record.patched_summary is not None
    assert record.comparison is not None
    assert record.baseline_summary.exit_code != 0
    assert record.patched_summary.exit_code == 0, record.execution_logs[3]
    assert record.comparison.status == "IMPROVED"
    assert "test_add_returns_sum" in record.execution_logs[1]
    assert "test_add_returns_sum" in record.execution_logs[3]
    assert (
        record.baseline_summary.tests_total,
        record.baseline_summary.tests_passed,
        record.baseline_summary.tests_failed,
    ) == (7, 6, 1)
    assert (
        record.patched_summary.tests_total,
        record.patched_summary.tests_passed,
        record.patched_summary.tests_failed,
    ) == (7, 7, 0)
    assert record.baseline_summary.stdout_truncated
    assert record.patched_summary.stdout_truncated
    assert (
        len(record.execution_logs[0].encode("utf-8"))
        + len(record.execution_logs[1].encode("utf-8"))
        <= settings.verification_output_limit_bytes
    )

    with connect_database(settings.database_path) as connection:
        unchanged_index = [
            tuple(row)
            for row in connection.execute(
                "SELECT path, content_hash, source FROM files "
                "WHERE repository_id = ? ORDER BY path",
                (repository.id,),
            ).fetchall()
        ]
    assert unchanged_index == original_index
    assert fixture_hashes == {
        relative: hashlib.sha256((FIXTURE_ROOT / relative).read_bytes()).hexdigest()
        for relative in manifest["files"]
    }
    assert _tracked_containers() == before_containers


def test_real_docker_timeout_is_bounded_and_container_is_removed(tmp_path: Path) -> None:
    manifest = _manifest()
    workspace = tmp_path / "timeout-workspace"
    workspace.mkdir()
    shutil.copyfile(
        FIXTURE_ROOT / "timeout_fixture" / "timeout_fixture.py",
        workspace / "timeout_fixture.py",
    )
    adapter = SandboxAdapter(
        SandboxConfig(
            mode="docker",
            image=DOCKER_IMAGE,
            trusted_roots=[str(tmp_path)],
            timeout_seconds=2,
            output_limit_bytes=4096,
        )
    )
    before_containers = _tracked_containers()
    started = time.monotonic()
    summary, _stdout, stderr = adapter.run(
        command=manifest["timeout_command"],
        workspace=workspace,
        timeout_seconds=2,
    )
    elapsed = time.monotonic() - started

    assert summary.exit_code is None
    assert summary.error_code == "sandbox_timeout"
    assert elapsed < 20
    assert "Timeout" in stderr or "timeout" in stderr.lower()
    assert _tracked_containers() == before_containers
