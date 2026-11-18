from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path, PurePosixPath

from patchwork.config import Settings
from patchwork.database import connect_database
from patchwork.errors import PatchworkError
from patchwork.ingestion.validation import validate_path
from patchwork.patches.store import PatchStore
from patchwork.repositories.store import timestamp
from patchwork.verifications.models import (
    SandboxConfig,
    VerificationRecord,
    VerificationResult,
    VerificationSummary,
)
from patchwork.verifications.sandbox import SandboxAdapter, SandboxFactory
from patchwork.verifications.store import VerificationStore


def _populate_snapshot(database_path: Path, repository_id: str, destination: Path) -> None:
    destination.mkdir(exist_ok=True)
    destination.chmod(0o755)  # Mounted child; its private host parent remains 0700.
    with connect_database(database_path) as connection:
        rows = connection.execute(
            "SELECT path, source FROM files WHERE repository_id = ? ORDER BY path",
            (repository_id,),
        ).fetchall()
    for row in rows:
        relative = Path(validate_path(row["path"]))
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        parent = target.parent
        while parent != destination:
            parent.chmod(0o755)
            parent = parent.parent
        target.write_text(row["source"], encoding="utf-8")
        target.chmod(0o644)


def _apply_unified_diff_to_file(file_path: Path, diff_text: str) -> None:
    original_lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    diff_lines = diff_text.splitlines(keepends=True)
    output: list[str] = []
    old_index = 0
    index = 0
    found_hunk = False

    while index < len(diff_lines):
        header = re.match(
            r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",
            diff_lines[index],
        )
        if header is None:
            index += 1
            continue
        found_hunk = True
        old_start = int(header.group(1))
        old_count = int(header.group(2) or 1)
        new_count = int(header.group(4) or 1)
        target_index = max(old_start - 1, 0)
        if target_index < old_index or target_index > len(original_lines):
            raise PatchworkError(
                "verification_patch_invalid", "Patch hunks overlap or exceed the source.", 409
            )
        output.extend(original_lines[old_index:target_index])
        old_index = target_index
        consumed_old = 0
        produced_new = 0
        index += 1

        while index < len(diff_lines) and not diff_lines[index].startswith("@@ "):
            current = diff_lines[index]
            if current in {"\n", "\r\n"}:
                index += 1
                continue
            if current.startswith("\\"):
                if output and output[-1].endswith("\n"):
                    output[-1] = output[-1][:-1]
                index += 1
                continue
            if not current or current[0] not in " +-":
                break
            marker, content = current[0], current[1:]
            if marker in " -":
                if old_index >= len(original_lines):
                    raise PatchworkError(
                        "verification_patch_invalid",
                        "Patch removes or references content beyond the source.",
                        409,
                    )
                original_line = original_lines[old_index]
                if original_line.rstrip("\r\n") != content.rstrip("\r\n"):
                    raise PatchworkError(
                        "verification_patch_stale",
                        "Patch context does not match the indexed source.",
                        409,
                    )
                old_index += 1
                consumed_old += 1
            if marker in " +":
                output.append(original_lines[old_index - 1] if marker == " " else content)
                produced_new += 1
            index += 1

        if consumed_old != old_count or produced_new != new_count:
            raise PatchworkError(
                "verification_patch_invalid",
                "Patch hunk line counts do not match its contents.",
                409,
            )

    if not found_hunk:
        raise PatchworkError("verification_patch_invalid", "Patch contains no valid hunks.", 409)
    output.extend(original_lines[old_index:])
    file_path.write_text("".join(output), encoding="utf-8")


def _apply_patch_to_snapshot(root: Path, diff_text: str) -> None:
    lines = diff_text.splitlines(keepends=True)
    blocks: list[list[str]] = []
    index = 0
    while index < len(lines):
        if (
            lines[index].startswith("--- ")
            and index + 1 < len(lines)
            and lines[index + 1].startswith("+++ ")
        ):
            start = index
            index += 2
            while index < len(lines) and not (
                lines[index].startswith("--- ")
                and index + 1 < len(lines)
                and lines[index + 1].startswith("+++ ")
            ):
                index += 1
            blocks.append(lines[start:index])
        else:
            index += 1

    if not blocks:
        raise PatchworkError("verification_patch_invalid", "Patch contains no file changes.", 409)

    root_resolved = root.resolve()
    for block in blocks:
        old_name = block[0][4:].strip()
        new_name = block[1][4:].strip()
        if old_name != new_name or old_name in {"/dev/null", ""}:
            raise PatchworkError(
                "verification_patch_invalid",
                "Only modifications to existing files are supported.",
                409,
            )
        try:
            relative = validate_path(old_name)
        except PatchworkError as error:
            raise PatchworkError(
                "verification_patch_invalid",
                "Patch contains an unsafe file path.",
                409,
            ) from error
        if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
            raise PatchworkError(
                "verification_patch_invalid", "Patch contains an unsafe file path.", 409
            )
        target = root / relative
        if (
            target.is_symlink()
            or not target.is_file()
            or not target.resolve().is_relative_to(root_resolved)
        ):
            raise PatchworkError(
                "verification_patch_invalid",
                "Patch target is missing or escapes the snapshot.",
                409,
            )
        _apply_unified_diff_to_file(target, "".join(block[2:]))


def _classify(baseline: VerificationSummary, patched: VerificationSummary) -> VerificationResult:
    if baseline.error_code or patched.error_code or None in (baseline.exit_code, patched.exit_code):
        status = "INCONCLUSIVE"
        reason = "An infrastructure failure or timeout prevents a reliable comparison."
    elif baseline.exit_code == 0 and patched.exit_code == 0:
        status = "UNCHANGED"
        reason = "Both baseline and patched runs succeeded with the same outcome."
    elif baseline.exit_code != 0 and patched.exit_code == 0:
        status = "IMPROVED"
        reason = "The patch resolved a previously failing command."
    elif baseline.exit_code == 0 and patched.exit_code != 0:
        status = "REGRESSED"
        reason = "The patched run failed where the baseline passed."
    else:
        status = "FAILED"
        reason = "Both runs failed or verification infrastructure could not compare them reliably."
    return VerificationResult(
        status=status,
        classification=status,
        reason=reason,
        baseline=baseline,
        patched=patched,
        diff_summary={
            "tests_total": patched.tests_total - baseline.tests_total,
            "tests_passed": patched.tests_passed - baseline.tests_passed,
            "tests_failed": patched.tests_failed - baseline.tests_failed,
            "tests_skipped": patched.tests_skipped - baseline.tests_skipped,
        },
        logs=[],
    )


def _validate_command(command: str) -> str:
    cleaned = command.strip()
    if not cleaned:
        raise PatchworkError("sandbox_policy", "Verification commands cannot be empty.", 422)
    if re.fullmatch(
        r"(?:python(?:3)?\s+-m\s+pytest(?:\s+-q)?|pytest(?:\s+-q)?|"
        r"python(?:3)?\s+-m\s+unittest\s+discover\s+-v\s+-p\s+"
        r"'(?:fixture_test_\*\.py|timeout_fixture\.py)')",
        cleaned,
    ):
        return cleaned
    raise PatchworkError(
        "sandbox_policy",
        "Only allowlisted pytest and trusted-fixture unittest commands are permitted.",
        422,
    )


async def _run_sandbox(sandbox: SandboxAdapter, **kwargs):
    # Keep the API responsive. On cancellation, the bounded worker must finish Docker
    # cleanup before its mounted directories are removed; never abandon the thread.
    worker = asyncio.create_task(asyncio.to_thread(sandbox.run, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(worker)
        except Exception:
            pass
        raise


async def run_verification(
    settings: Settings,
    patch_id: str,
    *,
    repository_id: str,
    commit_sha: str,
    baseline_command: str,
    patched_command: str,
    sandbox_mode: str = "docker",
    sandbox: SandboxAdapter | None = None,
    verification_id: str | None = None,
) -> VerificationRecord:
    patch = PatchStore(settings.database_path).get(patch_id)
    if patch.repository_id != repository_id or patch.commit_sha != commit_sha:
        raise PatchworkError(
            "verification_mismatch",
            "Patch and repository snapshot do not match.",
            409,
        )
    if patch.status != "approved":
        raise PatchworkError(
            "patch_not_approved",
            "Only approved patches can be verified.",
            409,
        )

    if sandbox_mode != "docker":
        raise PatchworkError("sandbox_unavailable", "Runtime verification requires Docker.", 422)

    baseline_command = _validate_command(baseline_command)
    patched_command = _validate_command(patched_command)

    if baseline_command != patched_command:
        raise PatchworkError("sandbox_policy", "Both snapshots must use the same command.", 422)

    store = VerificationStore(settings.database_path)
    record = (
        store.get(verification_id)
        if verification_id is not None
        else store.create(
            patch_id=patch_id,
            repository_id=repository_id,
            commit_sha=commit_sha,
            sandbox_mode=sandbox.config.mode if sandbox is not None else sandbox_mode,
        )
    )
    private_root = Path(tempfile.mkdtemp(prefix="patchwork-verify-"))
    baseline_dir = private_root / "baseline"
    patched_dir = private_root / "patched"
    try:
        _populate_snapshot(settings.database_path, repository_id, baseline_dir)
        _populate_snapshot(settings.database_path, repository_id, patched_dir)
        _apply_patch_to_snapshot(patched_dir, patch.diff)

        sandbox = sandbox or SandboxFactory.create(
            sandbox_mode,
            config=SandboxConfig(
                trusted_roots=[str(baseline_dir.parent)],
                timeout_seconds=int(settings.verification_timeout_seconds),
                output_limit_bytes=settings.verification_output_limit_bytes,
            ),
        )
        store.update(
            record.id,
            status="RUNNING_BASELINE",
            updated_at=timestamp(),
            started_at=timestamp(),
        )
        baseline_summary, baseline_stdout, baseline_stderr = await _run_sandbox(
            sandbox,
            command=baseline_command,
            workspace=baseline_dir,
            timeout_seconds=int(settings.verification_timeout_seconds),
        )
        store.update(
            record.id,
            status="RUNNING_PATCHED",
            updated_at=timestamp(),
            baseline_summary=baseline_summary,
            execution_logs=[baseline_stdout, baseline_stderr],
        )
        patched_summary, patched_stdout, patched_stderr = await _run_sandbox(
            sandbox,
            command=patched_command,
            workspace=patched_dir,
            timeout_seconds=int(settings.verification_timeout_seconds),
        )
        comparison = _classify(baseline_summary, patched_summary)
        comparison.logs = [patched_stdout, patched_stderr]
        store.update(
            record.id,
            status="COMPLETED",
            updated_at=timestamp(),
            completed_at=timestamp(),
            baseline_summary=baseline_summary,
            patched_summary=patched_summary,
            comparison=comparison,
            execution_logs=[baseline_stdout, baseline_stderr, patched_stdout, patched_stderr],
        )
        return store.get(record.id)
    except asyncio.CancelledError:
        store.update(
            record.id,
            status="CANCELLED",
            updated_at=timestamp(),
            completed_at=timestamp(),
            error_code="cancelled_by_user",
        )
        raise
    except PatchworkError as error:
        store.update(
            record.id,
            status="FAILED",
            updated_at=timestamp(),
            completed_at=timestamp(),
            error_code=error.code,
        )
        raise
    except Exception as error:  # pragma: no cover - defensive storage
        store.update(
            record.id,
            status="FAILED",
            updated_at=timestamp(),
            completed_at=timestamp(),
            error_code="verification_failed",
        )
        raise PatchworkError(
            "verification_failed",
            f"Verification failed: {error}",
            500,
        ) from error
    finally:
        for directory in (baseline_dir, patched_dir):
            if directory.exists():
                for child in sorted(directory.rglob("*"), reverse=True):
                    if child.is_file() or child.is_symlink():
                        child.unlink()
                    elif child.is_dir():
                        child.rmdir()
                directory.rmdir()
        private_root.rmdir()
