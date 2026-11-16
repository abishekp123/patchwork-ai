import subprocess
import time
from pathlib import Path

import pytest

from patchwork.config import Settings
from patchwork.ingestion.git import GitClient
from patchwork.ingestion.validation import normalize_url

PUBLIC_URL = "https://github.com/example/python-project"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args],
        cwd=root,
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


@pytest.fixture
def local_repo(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "origin"
    root.mkdir()
    git(root, "init", "-b", "master")
    (root / "main.py").write_text("def original():\n    return 1\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "Initial fixture")
    first = git(root, "rev-parse", "HEAD")
    (root / "main.py").write_text("def updated():\n    return 2\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "Update fixture")
    return root, first, git(root, "rev-parse", "HEAD")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(database_path=tmp_path / "state.db", repository_dir=tmp_path / "snapshots")


@pytest.fixture
def client_type(local_repo: tuple[Path, str, str]) -> type[GitClient]:
    # Only this test adapter permits local transport; no public input/config enables it.
    root = local_repo[0]

    class LocalGitClient(GitClient):
        protocol_options = [*GitClient.protocol_options, "-c", "protocol.file.allow=always"]

        def remote(self, url: str) -> str:
            normalize_url(url)
            return root.as_uri()

    return LocalGitClient


@pytest.fixture
def git_client(settings: Settings, tmp_path: Path, client_type: type[GitClient]) -> GitClient:
    workspace = tmp_path / "fetch"
    workspace.mkdir()
    return client_type(settings, workspace, time.monotonic() + 30)
