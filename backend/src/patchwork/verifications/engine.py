from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path

from patchwork.config import Settings
from patchwork.database import connect_database
from patchwork.errors import PatchworkError
from patchwork.patches.store import PatchStore
from patchwork.repositories.store import timestamp
from patchwork.verifications.models import (
    SandboxConfig,
    VerificationRecord,
    VerificationResult,
    VerificationSummary,
)
from patchwork.verifications.sandbox import SandboxFactory
from patchwork.verifications.store import VerificationStore


def _populate_snapshot(database_path: Path, repository_id: str, destination: Path) -> None:
    with connect_database(database_path) as connection:
        rows = connection.execute(
            "SELECT path, source FROM files WHERE repository_id = ? ORDER BY path",
            (repository_id,),
        ).fetchall()
    for row in rows:
        relative = Path(row["path"])
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(row["source"], encoding="utf-8")


def _apply_unified_diff_to_file(file_path: Path, diff_text: str) -> None:
    if not diff_text.strip():
        return
    original = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
    original_lines = original.splitlines(keepends=True)
    output: list[str] = []
    line_index = 0
    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].startswith("--- "):
            i += 1
            continue
        if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
            break
        file_marker = lines[i][4:].strip()
        if file_marker not in {"/dev/null", ""}:
            pass
        i += 2
        while i < len(lines) and not lines[i].startswith("--- "):
            if not lines[i].startswith("@@ "):
                i += 1
                continue
            match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", lines[i])
            if match is None:
                i += 1
                continue
            start = max(0, int(match.group(1)) - 1)
            while line_index < start:
                output.append(original_lines[line_index])
                line_index += 1
            i += 1
            while (
                i < len(lines)
                and not lines[i].startswith("@@ ")
                and not lines[i].startswith("--- ")
            ):
                current = lines[i]
                if current.startswith(" "):
                    output.append(current[1:] + ("\n" if not current.endswith("\n") else ""))
                    line_index += 1
                elif current.startswith("-"):
                    line_index += 1
                elif current.startswith("+"):
                    output.append(current[1:] + ("\n" if not current.endswith("\n") else ""))
                i += 1
    while line_index < len(original_lines):
        output.append(original_lines[line_index])
        line_index += 1
    file_path.write_text("".join(output), encoding="utf-8")


def _apply_patch_to_snapshot(root: Path, diff_text: str) -> None:
    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].startswith("--- "):
            i += 1
            continue
        if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
            break
        target_name = lines[i][4:].strip()
        if target_name in {"/dev/null", ""}:
            i += 2
            continue
        target_file = root / target_name
        if target_file.exists():
            _apply_unified_diff_to_file(target_file, "\n".join(lines[i : i + 2]))
        i += 2
        while i < len(lines) and not lines[i].startswith("--- "):
            if lines[i].startswith("@@ "):
                start = i
                i += 1
                while (
                    i < len(lines)
                    and not lines[i].startswith("@@ ")
                    and not lines[i].startswith("--- ")
                ):
                    i += 1
                _apply_unified_diff_to_file(
                    target_file,
                    "\n".join(lines[start:i]),
                )
                continue
            i += 1


def _classify(baseline: VerificationSummary, patched: VerificationSummary) -> VerificationResult:
    if baseline.exit_code == 0 and patched.exit_code == 0:
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
    if re.fullmatch(r"(?:python(?:3)?\s+-m\s+pytest(?:\s+-q)?|pytest(?:\s+-q)?)", cleaned):
        return cleaned
    raise PatchworkError(
        "sandbox_policy",
        "Only allowlisted pytest commands are permitted for verification.",
        422,
    )


async def run_verification(
    settings: Settings,
    patch_id: str,
    *,
    repository_id: str,
    commit_sha: str,
    baseline_command: str,
    patched_command: str,
    sandbox_mode: str = "fake",
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

    baseline_command = _validate_command(baseline_command)
    patched_command = _validate_command(patched_command)

    store = VerificationStore(settings.database_path)
    record = (
        store.get(verification_id)
        if verification_id is not None
        else store.create(
            patch_id=patch_id,
            repository_id=repository_id,
            commit_sha=commit_sha,
            sandbox_mode=sandbox_mode,
        )
    )
    baseline_dir = Path(tempfile.mkdtemp(prefix="patchwork-verify-base-"))
    patched_dir = Path(tempfile.mkdtemp(prefix="patchwork-verify-patched-"))
    try:
        _populate_snapshot(settings.database_path, repository_id, baseline_dir)
        _populate_snapshot(settings.database_path, repository_id, patched_dir)
        _apply_patch_to_snapshot(patched_dir, patch.diff)

        sandbox = SandboxFactory.create(
            sandbox_mode,
            config=(
                None
                if sandbox_mode == "fake"
                else SandboxConfig(
                    mode="docker",
                    trusted_roots=list(
                        dict.fromkeys(
                            [
                                str(settings.repository_dir),
                                str(baseline_dir.parent),
                                *settings.verification_trusted_roots,
                            ]
                        )
                    ),
                    timeout_seconds=int(settings.verification_timeout_seconds),
                )
            ),
        )
        store.update(
            record.id,
            status="RUNNING_BASELINE",
            updated_at=timestamp(),
            started_at=timestamp(),
        )
        try:
            baseline_summary, baseline_stdout, baseline_stderr = sandbox.run(
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
            patched_summary, patched_stdout, patched_stderr = sandbox.run(
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
