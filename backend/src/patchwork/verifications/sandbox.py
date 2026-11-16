from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from patchwork.errors import PatchworkError
from patchwork.verifications.models import SandboxConfig, VerificationSummary


class SandboxAdapter:
    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig()

    def available(self) -> bool:
        if self.config.mode != "docker":
            return False
        return shutil.which("docker") is not None

    def _trusted_workspace(self, workspace: Path) -> Path:
        if not workspace.exists():
            raise PatchworkError("sandbox_policy", "Workspace does not exist.", 422)
        if workspace.is_symlink():
            raise PatchworkError("sandbox_policy", "Workspace must not be a symlink.", 422)
        resolved = workspace.resolve()
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
            rejected = []
            for arg in self.config.extra_args:
                normalized = arg.lower()
                if normalized.startswith("--privileged") or "--pid" in normalized:
                    rejected.append(arg)
                elif normalized.startswith("--cap-add") or normalized.startswith("--cap-drop"):
                    if "all" not in normalized and "NET_ADMIN" in normalized.upper():
                        rejected.append(arg)
            if rejected:
                raise PatchworkError(
                    "sandbox_policy",
                    "Unsafe Docker flags are rejected before execution.",
                    422,
                )
        user_id = self.config.user.split(":", 1)[0]
        if user_id == "0":
            raise PatchworkError("sandbox_policy", "The sandbox must run as a non-root user.", 422)
        if self.config.trusted_roots == []:
            raise PatchworkError(
                "sandbox_policy",
                "Docker verification requires at least one trusted workspace root.",
                422,
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
        with tempfile.TemporaryDirectory(prefix="patchwork-verification-") as temp_dir:
            tmp = Path(temp_dir)
            script_path = tmp / "entrypoint.sh"
            script_path.write_text(script, encoding="utf-8")
            script_path.chmod(0o755)
            args = [
                "docker",
                "run",
                "--rm",
                "--read-only",
                "--network=none",
                "--cap-drop=ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--pids-limit=64",
                "--memory",
                f"{self.config.memory_mb}m",
                "--cpus",
                str(self.config.cpus),
                "--user",
                self.config.user,
                "--workdir",
                self.config.workdir,
                "--mount",
                f"type=bind,src={resolved_workspace},dst={self.config.workdir},ro=false",
                "--mount",
                f"type=bind,src={tmp},dst=/tmp/patchwork-runtime,ro=false",
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
            try:
                proc = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    cwd=str(resolved_workspace),
                )
            except subprocess.TimeoutExpired as error:
                stdout = error.stdout or ""
                stderr = error.stderr or "Timeout expired while running the sandboxed command."
                return (
                    VerificationSummary(
                        exit_code=None,
                        duration_ms=timeout_seconds * 1000,
                        stdout_bytes=len(stdout.encode("utf-8")),
                        stderr_bytes=len(stderr.encode("utf-8")),
                        error_code="sandbox_timeout",
                    ),
                    stdout,
                    stderr,
                )
            summary = VerificationSummary(
                exit_code=proc.returncode,
                duration_ms=0,
                stdout_bytes=len(proc.stdout.encode("utf-8")),
                stderr_bytes=len(proc.stderr.encode("utf-8")),
            )
            return summary, proc.stdout, proc.stderr


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
        if mode == "fake":
            return FakeSandboxAdapter(config or SandboxConfig(mode="fake"))
        raise PatchworkError("sandbox_unavailable", f"Unsupported sandbox mode: {mode}", 422)


__all__ = ["SandboxAdapter", "FakeSandboxAdapter", "SandboxFactory"]
