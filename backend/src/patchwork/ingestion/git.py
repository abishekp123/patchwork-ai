"""Bounded Git plumbing without checkout, credentials, hooks, or shell interpolation."""

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from patchwork.config import Settings
from patchwork.errors import PatchworkError
from patchwork.ingestion.validation import normalize_url, validate_sha


def directory_bytes(root: Path) -> int:
    total = 0
    for directory, _, files in os.walk(root, followlinks=False):
        for name in files:
            try:
                total += (Path(directory) / name).lstat().st_size
            except FileNotFoundError:
                continue  # Git atomically renames temporary pack files.
    return total


class GitClient:
    protocol_options = ["-c", "protocol.allow=never", "-c", "protocol.https.allow=always"]

    def __init__(self, settings: Settings, workspace: Path, deadline: float) -> None:
        self.settings = settings
        self.workspace = workspace
        self.git_dir = workspace / "repository.git"
        self.deadline = deadline
        self.executable = shutil.which("git")
        if not self.executable:
            raise PatchworkError("git_unavailable", "Git is not installed on the server.", 503)

    def remote(self, url: str) -> str:
        return normalize_url(url) + ".git"

    def run(self, arguments: list[str], *, max_output: int = 1_000_000) -> bytes:
        # Only host PATH and TLS certificate configuration are inherited. No Git config,
        # proxy credentials, SSH agents, credential helpers, or ambient GIT_* variables.
        env = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "SSL_CERT_FILE", "SSL_CERT_DIR")
            if key in os.environ
        }
        env.update(
            {
                "HOME": str(self.workspace),
                "XDG_CONFIG_HOME": str(self.workspace),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ASKPASS": "false",
                "LC_ALL": "C",
            }
        )
        command = [
            self.executable,
            "--no-optional-locks",
            *self.protocol_options,
            "-c",
            "credential.helper=",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "http.followRedirects=false",
            "-c",
            "fetch.fsckObjects=true",
            "-c",
            "gc.auto=0",
            *arguments,
        ]
        expires = min(self.deadline, time.monotonic() + self.settings.clone_timeout_seconds)
        output_path, error_path = self.workspace / "stdout", self.workspace / "stderr"
        with output_path.open("wb") as output, error_path.open("wb") as error:
            process = subprocess.Popen(
                command,
                cwd=self.workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=error,
                start_new_session=True,
            )
            try:
                while True:
                    if time.monotonic() >= expires:
                        raise PatchworkError(
                            "ingestion_timeout", "Repository operation timed out.", 504
                        )
                    if (
                        output_path.stat().st_size > max_output
                        or error_path.stat().st_size > 1_000_000
                        or directory_bytes(self.workspace) > self.settings.max_repository_bytes
                    ):
                        raise PatchworkError(
                            "repository_too_large", "Repository exceeds configured limits.", 413
                        )
                    if process.poll() is not None:
                        break
                    time.sleep(0.02)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        if process.returncode:
            detail = error_path.read_bytes().lower()
            if any(
                marker in detail
                for marker in (b"not our ref", b"couldn't find remote ref", b"unadvertised object")
            ):
                raise PatchworkError(
                    "invalid_revision", "The commit is unavailable in this repository."
                )
            raise PatchworkError(
                "upstream_unavailable", "Repository is unavailable or Git transport failed.", 502
            )
        return output_path.read_bytes()

    def resolve(self, url: str) -> str:
        result = self.run(["ls-remote", "--exit-code", self.remote(url), "HEAD"])
        try:
            return validate_sha(result.split()[0].decode("ascii"))
        except (IndexError, UnicodeError, PatchworkError):
            raise PatchworkError(
                "invalid_revision", "The repository has no resolvable default commit."
            ) from None

    def fetch(self, url: str, commit: str) -> None:
        commit = validate_sha(commit)
        self.run(["init", "--bare", "--template=", str(self.git_dir)])
        self.run(
            [
                "--git-dir",
                str(self.git_dir),
                "fetch",
                "--depth=1",
                "--no-tags",
                "--no-recurse-submodules",
                self.remote(url),
                commit,
            ]
        )
        actual = self.run(
            ["--git-dir", str(self.git_dir), "rev-parse", "--verify", "FETCH_HEAD^{commit}"]
        )
        if actual.decode("ascii").strip() != commit:
            raise PatchworkError(
                "invalid_revision", "Fetched revision does not match the requested commit."
            )

    def tree(self, commit: str) -> bytes:
        return self.run(
            [
                "--git-dir",
                str(self.git_dir),
                "ls-tree",
                "-rlz",
                validate_sha(commit),
            ],
            max_output=min(self.settings.max_repository_bytes, 16_000_000),
        )

    def blob(self, oid: str, size: int) -> bytes:
        return self.run(
            [
                "--git-dir",
                str(self.git_dir),
                "cat-file",
                "blob",
                validate_sha(oid),
            ],
            max_output=size,
        )
