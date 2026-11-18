from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from patchwork.errors import PatchworkError
from patchwork.verifications.models import SandboxConfig, VerificationSummary


class _OutputCapture:
    def __init__(self, limit: int):
        self.limit = limit
        self.lock = threading.Lock()
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.stdout_bytes = 0
        self.stderr_bytes = 0
        self.stdout_truncated = False
        self.stderr_truncated = False

    def drain(self, stream, destination: bytearray, name: str) -> None:
        while chunk := stream.read(4096):
            with self.lock:
                total_name = f"{name}_bytes"
                truncated_name = f"{name}_truncated"
                setattr(self, total_name, getattr(self, total_name) + len(chunk))
                stream_limit = self.limit // 2 if name == "stdout" else self.limit - self.limit // 2
                available = max(0, stream_limit - len(destination))
                kept = chunk[:available]
                destination.extend(kept)
                if len(kept) != len(chunk):
                    setattr(self, truncated_name, True)


class SandboxAdapter:
    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig()

    def available(self) -> bool:
        if self.config.mode != "docker":
            return False
        if shutil.which("docker") is None:
            return False
        try:
            for args in (["info"], ["image", "inspect", self.config.image]):
                result = subprocess.run(
                    ["docker", *args],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
                if result.returncode != 0:
                    return False
        except (OSError, subprocess.TimeoutExpired):
            return False
        return True

    def _trusted_workspace(self, workspace: Path) -> Path:
        if not workspace.exists():
            raise PatchworkError("sandbox_policy", "Workspace does not exist.", 422)
        if workspace.is_symlink():
            raise PatchworkError("sandbox_policy", "Workspace must not be a symlink.", 422)
        resolved = workspace.resolve()
        if "," in str(resolved):
            raise PatchworkError(
                "sandbox_policy",
                "Workspace paths cannot contain Docker mount separators.",
                422,
            )
        if self.config.trusted_roots:
            allowed = [Path(root).expanduser().resolve() for root in self.config.trusted_roots]
            if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
                raise PatchworkError(
                    "sandbox_policy",
                    "Workspace is outside the configured trusted sandbox roots.",
                    422,
                )
        return resolved

    def validate_policy(self) -> None:
        if self.config.mode != "docker":
            raise PatchworkError(
                "sandbox_unavailable",
                "Only the Docker sandbox is supported for runtime verification.",
                503,
            )
        if self.config.network_disabled is not True:
            raise PatchworkError(
                "sandbox_policy",
                "Network must be disabled in the sandbox.",
                422,
            )
        if self.config.read_only_root is not True:
            raise PatchworkError(
                "sandbox_policy",
                "The sandbox root filesystem must be read-only.",
                422,
            )
        if self.config.no_new_privileges is not True:
            raise PatchworkError(
                "sandbox_policy",
                "No-new-privileges must remain enabled.",
                422,
            )
        if self.config.extra_args:
            raise PatchworkError(
                "sandbox_policy",
                "Unsafe Docker flags are rejected before execution.",
                422,
            )
        if re.fullmatch(r"[1-9]\d{0,9}(?::\d{1,10})?", self.config.user) is None:
            raise PatchworkError("sandbox_policy", "The sandbox must run as a non-root user.", 422)
        if not re.fullmatch(r"[a-z0-9./:_-]+@sha256:[0-9a-f]{64}", self.config.image):
            raise PatchworkError(
                "sandbox_policy",
                "Docker verification requires an image pinned by SHA-256 digest.",
                422,
            )
        if self.config.trusted_roots == []:
            raise PatchworkError(
                "sandbox_policy",
                "Docker verification requires at least one trusted workspace root.",
                422,
            )
        if self.config.workdir != "/workspace":
            raise PatchworkError(
                "sandbox_policy",
                "Docker verification uses the fixed /workspace mount point.",
                422,
            )

    @staticmethod
    def _container_exists(container_id: str) -> bool:
        result = subprocess.run(
            ["docker", "inspect", "--type", "container", container_id],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return True
        if (
            "No such object" in result.stderr
            or "no such container" in result.stderr.lower()
            or "not found" in result.stderr.lower()
        ):
            return False
        raise PatchworkError(
            "sandbox_cleanup",
            "Unable to verify Docker container cleanup.",
            503,
        )

    @classmethod
    def _cleanup_container(cls, container_name: str, cidfile: Path, *, wait: bool) -> None:
        container_ref = container_name
        if cidfile.exists():
            container_id = cidfile.read_text(encoding="ascii").strip()
            if container_id and not re.fullmatch(r"[0-9a-f]{64}", container_id):
                raise PatchworkError(
                    "sandbox_cleanup",
                    "Docker returned an invalid container identifier.",
                    503,
                )
            if container_id:
                container_ref = container_id
        attempts = 20 if wait else 1
        for attempt in range(attempts):
            if cls._container_exists(container_ref):
                break
            if attempt + 1 < attempts:
                if wait and attempt % 5 == 0:
                    subprocess.run(
                        ["docker", "rm", "--force", container_name],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                time.sleep(0.1)
        else:
            return
        if cls._container_exists(container_ref):
            subprocess.run(
                ["docker", "rm", "--force", container_ref],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if cls._container_exists(container_ref):
                raise PatchworkError(
                    "sandbox_cleanup",
                    "Docker container remained after cleanup.",
                    503,
                )

    @staticmethod
    def _with_unittest_counts(
        summary: VerificationSummary,
        command: str,
        stdout: str,
        stderr: str,
    ) -> VerificationSummary:
        if "unittest" not in command:
            return summary
        output = f"{stdout}\n{stderr}"
        ran = re.search(r"Ran (\d+) tests?\b", output)
        if ran is None:
            return summary
        failed = re.search(r"FAILED \(([^)]*)\)", output)
        succeeded = re.search(r"OK(?: \(([^)]*)\))?", output)
        counts = ""
        if failed is not None:
            counts = failed.group(1)
        elif succeeded is not None and succeeded.group(1):
            counts = succeeded.group(1)
        failures = re.search(r"failures=(\d+)", counts)
        errors = re.search(r"errors=(\d+)", counts)
        skipped = re.search(r"skipped=(\d+)", counts)
        total = int(ran.group(1))
        failed_count = (int(failures.group(1)) if failures else 0) + (
            int(errors.group(1)) if errors else 0
        )
        skipped_count = int(skipped.group(1)) if skipped else 0
        return summary.model_copy(
            update={
                "tests_total": total,
                "tests_passed": max(0, total - failed_count - skipped_count),
                "tests_failed": failed_count,
                "tests_skipped": skipped_count,
            }
        )

    def run(
        self,
        *,
        command: str,
        workspace: Path,
        timeout_seconds: int,
    ) -> tuple[VerificationSummary, str, str]:
        self.validate_policy()
        if not self.available():
            raise PatchworkError(
                "sandbox_unavailable",
                "Docker sandbox is unavailable on this runner.",
                503,
            )
        resolved_workspace = self._trusted_workspace(workspace)
        script = "#!/bin/sh\nset -eu\n" + command + "\n"
        with tempfile.TemporaryDirectory(
            prefix="runner-", dir=self.config.runtime_root
        ) as temp_dir:
            tmp = Path(temp_dir)
            if "," in str(tmp.resolve()):
                raise PatchworkError(
                    "sandbox_policy",
                    "Runner paths cannot contain Docker mount separators.",
                    422,
                )
            # Keep daemon bookkeeping private on the host. Only the readable
            # runner child is mounted, so UID 65532 works on native Linux too.
            runner = tmp / "runner"
            runner.mkdir(mode=0o755)
            runner.chmod(0o755)
            script_path = runner / "entrypoint.sh"
            cidfile = tmp / "container-id"
            container_name = f"patchwork-verify-{uuid.uuid4().hex}"
            script_path.write_text(script, encoding="utf-8")
            script_path.chmod(0o644)
            capture = _OutputCapture(self.config.output_limit_bytes)
            args = [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--cidfile",
                str(cidfile),
                "--name",
                container_name,
                "--label",
                "com.patchwork.verification=true",
                *(
                    ["--label", f"com.patchwork.owner={self.config.owner_id}"]
                    if self.config.owner_id
                    else []
                ),
                "--read-only",
                "--network=none",
                "--cap-drop=ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--pids-limit",
                str(self.config.pids_limit),
                "--memory",
                f"{self.config.memory_mb}m",
                "--cpus",
                str(self.config.cpus),
                "--user",
                self.config.user,
                "--env",
                "PYTHONDONTWRITEBYTECODE=1",
                "--workdir",
                self.config.workdir,
                "--mount",
                f"type=bind,src={resolved_workspace},dst={self.config.workdir},ro=false",
                "--mount",
                f"type=bind,src={runner},dst=/tmp/patchwork-runtime,ro=true",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                "--tmpfs",
                "/var/tmp:rw,noexec,nosuid,size=64m",
                "--tmpfs",
                "/run:rw,noexec,nosuid,size=32m",
                "--ulimit",
                "nofile=128:128",
                self.config.image,
                "/bin/sh",
                "/tmp/patchwork-runtime/entrypoint.sh",
            ]
            started_at = time.monotonic()
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                cwd=str(resolved_workspace),
            )
            assert process.stdout is not None
            assert process.stderr is not None
            stdout_reader = threading.Thread(
                target=capture.drain,
                args=(process.stdout, capture.stdout, "stdout"),
                daemon=True,
            )
            stderr_reader = threading.Thread(
                target=capture.drain,
                args=(process.stderr, capture.stderr, "stderr"),
                daemon=True,
            )
            stdout_reader.start()
            stderr_reader.start()
            timed_out = False
            try:
                try:
                    process.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    process.kill()
                    process.wait(timeout=10)
                stdout_reader.join(timeout=10)
                stderr_reader.join(timeout=10)
                if stdout_reader.is_alive() or stderr_reader.is_alive():
                    raise PatchworkError(
                        "sandbox_output",
                        "Docker output streams did not close after execution.",
                        503,
                    )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                self._cleanup_container(container_name, cidfile, wait=timed_out)
            stdout = capture.stdout.decode("utf-8", errors="replace")
            stderr = capture.stderr.decode("utf-8", errors="replace")
            summary = VerificationSummary(
                exit_code=None if timed_out else process.returncode,
                duration_ms=int((time.monotonic() - started_at) * 1000),
                stdout_truncated=capture.stdout_truncated,
                stderr_truncated=capture.stderr_truncated,
                stdout_bytes=capture.stdout_bytes,
                stderr_bytes=capture.stderr_bytes,
                error_code="sandbox_timeout" if timed_out else None,
            )
            if timed_out and not stderr:
                stderr = "Timeout expired while running the sandboxed command."
            summary = self._with_unittest_counts(summary, command, stdout, stderr)
            return summary, stdout, stderr


class FakeSandboxAdapter(SandboxAdapter):
    def __init__(self, config: SandboxConfig | None = None):
        super().__init__(config or SandboxConfig(mode="fake"))

    def available(self) -> bool:
        return True

    def validate_policy(self) -> None:
        return None

    def run(
        self,
        *,
        command: str,
        workspace: Path,
        timeout_seconds: int,
    ) -> tuple[VerificationSummary, str, str]:
        if "exit 42" in command:
            return (
                VerificationSummary(
                    exit_code=42,
                    duration_ms=250,
                    stdout_bytes=0,
                    stderr_bytes=0,
                    error_code="sandbox_command_failed",
                ),
                "",
                "sandbox command failed",
            )
        expected = "pytest" in command or "python -m pytest" in command
        stdout = "[100%] success\n" if expected else "ok\n"
        stderr = "" if expected else "warning\n"
        return (
            VerificationSummary(
                exit_code=0,
                duration_ms=120,
                stdout_bytes=len(stdout.encode("utf-8")),
                stderr_bytes=len(stderr.encode("utf-8")),
                tests_total=1 if expected else 0,
                tests_passed=1 if expected else 0,
                tests_failed=0,
                tests_skipped=0,
            ),
            stdout,
            stderr,
        )


class SandboxFactory:
    @staticmethod
    def create(mode: str, *, config: SandboxConfig | None = None) -> SandboxAdapter:
        if mode == "docker":
            return SandboxAdapter(config or SandboxConfig(mode="docker"))
        raise PatchworkError("sandbox_unavailable", f"Unsupported sandbox mode: {mode}", 422)


__all__ = ["SandboxAdapter", "FakeSandboxAdapter", "SandboxFactory"]
