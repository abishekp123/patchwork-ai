from __future__ import annotations

import json
import uuid

from patchwork.database import connect_database
from patchwork.errors import PatchworkError
from patchwork.repositories.store import timestamp
from patchwork.verifications.models import (
    VerificationRecord,
    VerificationResult,
    VerificationSummary,
)

VALID_STATUSES = {
    "CREATED",
    "PREPARING",
    "RUNNING_BASELINE",
    "RUNNING_PATCHED",
    "COMPARING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
}
ACTIVE_STATUSES = {
    "CREATED",
    "PREPARING",
    "RUNNING_BASELINE",
    "RUNNING_PATCHED",
    "COMPARING",
}


class VerificationStore:
    def __init__(self, database_path):
        self.database_path = database_path

    def create(
        self,
        *,
        patch_id: str,
        repository_id: str,
        commit_sha: str,
        sandbox_mode: str,
    ) -> VerificationRecord:
        identifier = uuid.uuid4().hex
        now = timestamp()
        with connect_database(self.database_path) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                "SELECT id FROM verifications WHERE patch_id=? AND status IN ("
                + ",".join("?" for _ in ACTIVE_STATUSES)
                + ") LIMIT 1",
                (patch_id, *sorted(ACTIVE_STATUSES)),
            ).fetchone()
            if active is not None:
                raise PatchworkError(
                    "verification_in_progress",
                    "A verification is already active for this patch.",
                    409,
                )
            connection.execute(
                """
                INSERT INTO verifications (
                    id, patch_id, repository_id, commit_sha, status, sandbox_mode,
                    created_at, updated_at, started_at, completed_at,
                    baseline_summary, patched_summary, comparison_json,
                    error_code, execution_logs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, '[]')
                """,
                (
                    identifier,
                    patch_id,
                    repository_id,
                    commit_sha,
                    "CREATED",
                    sandbox_mode,
                    now,
                    now,
                ),
            )
        return self.get(identifier)

    def get(self, identifier: str) -> VerificationRecord:
        with connect_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM verifications WHERE id = ?",
                (identifier,),
            ).fetchone()
        if row is None:
            raise PatchworkError(
                "verification_not_found",
                "Verification record was not found.",
                404,
            )
        return self._decode(row)

    def list(self, *, limit: int = 20, offset: int = 0) -> tuple[list[VerificationRecord], int]:
        with connect_database(self.database_path) as connection:
            total = connection.execute("SELECT count(*) FROM verifications").fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM verifications ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._decode(row) for row in rows], total

    def list_for_patch(
        self,
        patch_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[VerificationRecord], int]:
        with connect_database(self.database_path) as connection:
            total = connection.execute(
                "SELECT count(*) FROM verifications WHERE patch_id = ?",
                (patch_id,),
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM verifications WHERE patch_id = ? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (patch_id, limit, offset),
            ).fetchall()
        return [self._decode(row) for row in rows], total

    def update(self, identifier: str, **payload) -> VerificationRecord:
        allowed = {
            "status",
            "updated_at",
            "started_at",
            "completed_at",
            "baseline_summary",
            "patched_summary",
            "comparison",
            "error_code",
            "execution_logs",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unsupported verification update fields: {sorted(unknown)}")
        with connect_database(self.database_path) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM verifications WHERE id = ?",
                (identifier,),
            ).fetchone()
            if current is None:
                raise PatchworkError(
                    "verification_not_found",
                    "Verification record was not found.",
                    404,
                )
            if current["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                return self._decode(current)
            new_status = payload.get("status", current["status"])
            if new_status not in VALID_STATUSES:
                raise ValueError("Unsupported verification status.")
            baseline = payload.get("baseline_summary")
            patched = payload.get("patched_summary")
            comparison = payload.get("comparison")
            execution_logs = payload.get(
                "execution_logs",
                json.loads(current["execution_logs_json"]),
            )
            connection.execute(
                """
                UPDATE verifications
                SET status = ?, updated_at = ?, started_at = ?, completed_at = ?,
                    baseline_summary = ?, patched_summary = ?, comparison_json = ?,
                    error_code = ?, execution_logs_json = ?
                WHERE id = ?
                """,
                (
                    new_status,
                    payload.get("updated_at", current["updated_at"]),
                    payload.get("started_at", current["started_at"]),
                    payload.get("completed_at", current["completed_at"]),
                    json.dumps(baseline.model_dump(), sort_keys=True)
                    if baseline is not None
                    else current["baseline_summary"],
                    json.dumps(patched.model_dump(), sort_keys=True)
                    if patched is not None
                    else current["patched_summary"],
                    json.dumps(comparison.model_dump(), sort_keys=True)
                    if comparison is not None
                    else current["comparison_json"],
                    payload.get("error_code", current["error_code"]),
                    json.dumps(execution_logs, sort_keys=True),
                    identifier,
                ),
            )
        return self.get(identifier)

    @staticmethod
    def _decode(row) -> VerificationRecord:
        payload = dict(row)
        payload["baseline_summary"] = (
            VerificationSummary.model_validate(json.loads(payload["baseline_summary"]))
            if payload.get("baseline_summary")
            else None
        )
        payload["patched_summary"] = (
            VerificationSummary.model_validate(json.loads(payload["patched_summary"]))
            if payload.get("patched_summary")
            else None
        )
        payload["comparison"] = (
            VerificationResult.model_validate(json.loads(payload["comparison_json"]))
            if payload.get("comparison_json")
            else None
        )
        payload["execution_logs"] = (
            json.loads(payload["execution_logs_json"]) if payload.get("execution_logs_json") else []
        )
        payload.pop("comparison_json", None)
        payload.pop("execution_logs_json", None)
        return VerificationRecord.model_validate(payload)
