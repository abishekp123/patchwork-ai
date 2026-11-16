import os
import sys
import time
from pathlib import Path

import pytest
from conftest import PUBLIC_URL, git
from pydantic import ValidationError

from patchwork.config import Settings
from patchwork.errors import PatchworkError
from patchwork.ingestion.discovery import discover
from patchwork.ingestion.git import GitClient
from patchwork.ingestion.validation import normalize_url, validate_path, validate_sha


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Owner/Project",
        "https://github.com/Owner/Project.git/",
    ],
)
def test_normalize_github_url(url: str) -> None:
    assert normalize_url(url) == "https://github.com/owner/project"


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "file:///tmp/repo",
        "/tmp/repo",
        "git@github.com:a/b",
        "https://github.com.evil.test/a/b",
        "https://user@github.com/a/b",
        "https://github.com:443/a/b",
        "https://github.com/a/../b",
        "https://github.com/a/%2e%2e",
        "https://github.com/a/b?x=1",
        "https://github.com/a/b#main",
        "https://github.com/a/b/tree/main",
        "https://github.com/-a/b",
        "https://github.com/a/..",
        " https://github.com/a/b",
        "https://github.com/a\\b/c",
        "https://github.com/a/b\n",
        "https://github.com/a/é",
    ],
)
def test_reject_unsupported_urls(url: str) -> None:
    with pytest.raises(PatchworkError, match="HTTPS"):
        normalize_url(url)


@pytest.mark.parametrize("revision", ["main", "abc123", "--upload-pack=evil", "a" * 39, "g" * 40])
def test_invalid_revisions(revision: str) -> None:
    with pytest.raises(PatchworkError, match="40-character"):
        validate_sha(revision)


@pytest.mark.parametrize(
    "path",
    ["../escape.py", "/escape.py", "a/../../b", "a//b", "a/./b", "C:/x", "a\\x", "a\x00b", "a\nb"],
)
def test_path_traversal_rejected(path: str) -> None:
    with pytest.raises(PatchworkError, match="unsafe"):
        validate_path(path)


def test_external_storage_required(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="outside"):
        Settings(repository_dir=Path(__file__).resolve().parent)
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValidationError, match="symlink"):
        Settings(repository_dir=link)


def test_fetch_arbitrary_pinned_commit(
    git_client: GitClient, local_repo: tuple[Path, str, str], settings: Settings
) -> None:
    _, old, current = local_repo
    assert git_client.resolve(PUBLIC_URL) == current
    git_client.fetch(PUBLIC_URL, old)
    files, skipped = discover(git_client, old, settings)
    assert [file.path for file in files] == ["main.py"]
    assert files[0].source == "def original():\n    return 1\n"
    assert len(files[0].content_hash) == 64
    assert skipped == {}
    assert not (git_client.git_dir / "main.py").exists()  # Never checked out.
    assert (git_client.git_dir / "shallow").read_text().strip() == old


def test_unavailable_revision(git_client: GitClient) -> None:
    with pytest.raises(PatchworkError) as failure:
        git_client.fetch(PUBLIC_URL, "0" * 40)
    assert failure.value.code == "invalid_revision"


def test_discovery_skips_untrusted_and_generated_content(
    git_client: GitClient, local_repo: tuple[Path, str, str], settings: Settings
) -> None:
    root = local_repo[0]
    (root / "escape.py").symlink_to("/etc/passwd")
    (root / "binary.py").write_bytes(b"\x00binary")
    (root / "invalid.py").write_bytes(b"\xff\xfe")
    (root / "large.py").write_bytes(b"x" * 1000)
    (root / "venv").mkdir()
    (root / "venv/ignored.py").write_text("ignored = True")
    (root / "unicode.py").write_text("café = '你好'\n", encoding="utf-8")
    (root / "latin.py").write_bytes(b"# coding: latin-1\ncaf\xe9 = 1\n")
    (root / "evil.py").write_text("raise RuntimeError('must never execute')\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "Untrusted files")
    commit = git(root, "rev-parse", "HEAD")
    git_client.fetch(PUBLIC_URL, commit)
    files, skipped = discover(
        git_client, commit, settings.model_copy(update={"max_file_bytes": 100})
    )
    assert [file.path for file in files] == ["evil.py", "latin.py", "main.py", "unicode.py"]
    assert "café" in files[1].source
    assert skipped == {
        "binary_file": 1,
        "ignored_directory": 1,
        "invalid_encoding": 1,
        "oversized_file": 1,
        "symlink_or_submodule": 1,
    }


@pytest.mark.parametrize("limit", [{"max_tree_entries": 1}, {"max_source_bytes": 1}])
def test_index_limits(
    git_client: GitClient,
    local_repo: tuple[Path, str, str],
    settings: Settings,
    limit: dict[str, int],
) -> None:
    root, _, commit = local_repo
    if "max_tree_entries" in limit:
        (root / "other.py").write_text("x = 1")
        git(root, "add", ".")
        git(root, "commit", "-m", "More files")
        commit = git(root, "rev-parse", "HEAD")
    git_client.fetch(PUBLIC_URL, commit)
    with pytest.raises(PatchworkError) as failure:
        discover(git_client, commit, settings.model_copy(update=limit))
    assert failure.value.status_code == 413


def test_git_timeout_kills_process(git_client: GitClient) -> None:
    executable = git_client.workspace / "slow-git"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(10)\n")
    executable.chmod(0o700)
    git_client.executable = str(executable)
    git_client.deadline = time.monotonic() + 0.05
    with pytest.raises(PatchworkError) as failure:
        git_client.run(["ignored"])
    assert failure.value.code == "ingestion_timeout"


def test_git_output_size_limit(git_client: GitClient) -> None:
    executable = git_client.workspace / "large-git"
    executable.write_text(f"#!{sys.executable}\nprint('x' * 10000)\n")
    executable.chmod(0o700)
    git_client.executable = str(executable)
    with pytest.raises(PatchworkError) as failure:
        git_client.run(["ignored"], max_output=100)
    assert failure.value.status_code == 413


def test_git_ignores_ambient_config(git_client: GitClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "alias.danger")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "!touch should-not-exist")
    result = git_client.run(["config", "--list"])
    assert b"danger" not in result
    assert b"protocol.allow=never" in result
    assert b"http.followredirects=false" in result
    assert not os.path.exists(git_client.workspace / "should-not-exist")
