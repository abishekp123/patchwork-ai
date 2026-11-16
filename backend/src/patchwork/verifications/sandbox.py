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
        if self.config.user == "0:0":
            raise PatchworkError("sandbox_policy", "The sandbox must run as a non-root user.", 422)
        if self.config.extra_args:
            rejected = [
                arg
                for arg in self.config.extra_args
                if arg.startswith("--privileged") or arg.startswith("--pid")
            ]
            if rejected:
                raise PatchworkError(
                    "sandbox_policy",
                    "Unsafe Docker flags are rejected before execution.",
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
        with tempfile.TemporaryDirectory(prefix="patchwork-verification-") as temp_dir:
            tmp = Path(temp_dir)
            script = tmp / "run.sh"
            script.write_text(f"#!/bin/sh\nset -eu\n{command}\n", encoding="utf-8")
            script.chmod(0o755)
            args = [
                "docker",
                "run",
                "--rm",
                "--read-only",
                "--network=none",
                "--user",
                self.config.user,
                "--memory",
                f"{self.config.memory_mb}m",
                "--cpus",
                str(self.config.cpus),
                "--workdir",
                self.config.workdir,
                "-v",
                f"{workspace}:{self.config.workdir}",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                "--security-opt",
                "no-new-privileges:true",
                self.config.image,
                "/bin/sh",
                "/workspace/run.sh",
            ]
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=workspace,
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
                VerificationSummary(exit_code=42, duration_ms=250, stdout_bytes=0, stderr_bytes=0),
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
