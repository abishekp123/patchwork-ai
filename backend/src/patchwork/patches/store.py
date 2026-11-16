import json
import uuid

from patchwork.database import connect_database
from patchwork.errors import PatchworkError
from patchwork.patches.engine import PatchProposal, PatchRecord
from patchwork.repositories.store import timestamp


class PatchStore:
    def __init__(self, database_path):
        self.database_path = database_path

    def create(
        self,
        repository,
        proposal: PatchProposal,
        *,
        investigation_id: str | None = None,
        status: str = "pending_review",
    ) -> PatchRecord:
        identifier = uuid.uuid4().hex
        now = timestamp()
        diff = "\n\n".join(
            self._diff_for(change.path, change.before, change.after) for change in proposal.changes
        )
        with connect_database(self.database_path) as connection, connection:
            connection.execute(
                """
                INSERT INTO patches (
                    id, repository_id, commit_sha, investigation_id, status,
                    title, summary, diff, evidence_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    identifier,
                    repository.id,
                    repository.commit_sha,
                    investigation_id,
                    status,
                    proposal.title,
                    proposal.summary,
                    diff,
                    json.dumps(proposal.evidence_ids, sort_keys=True),
                    now,
                    now,
                ),
            )
        return self.get(identifier)

    def get(self, identifier: str) -> PatchRecord:
        with connect_database(self.database_path) as connection:
            row = connection.execute("SELECT * FROM patches WHERE id = ?", (identifier,)).fetchone()
        if row is None:
            raise PatchworkError("patch_not_found", "Patch was not found.", 404)
        payload = dict(row)
        payload["evidence_ids"] = (
            json.loads(payload["evidence_json"]) if payload["evidence_json"] else []
        )
        payload.pop("evidence_json", None)
        return PatchRecord.model_validate(payload)

    def list(self, *, limit: int = 20, offset: int = 0) -> tuple[list[PatchRecord], int]:
        with connect_database(self.database_path) as connection:
            total = connection.execute("SELECT count(*) FROM patches").fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM patches ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        records = []
        for row in rows:
            payload = dict(row)
            payload["evidence_ids"] = (
                json.loads(payload["evidence_json"]) if payload["evidence_json"] else []
            )
            payload.pop("evidence_json", None)
            records.append(PatchRecord.model_validate(payload))
        return records, total

    def transition(
        self,
        identifier: str,
        status: str,
        *,
        reviewer: str | None = None,
        reason: str | None = None,
        error_code: str | None = None,
    ) -> PatchRecord:
        allowed = {"pending_review", "approved", "rejected", "failed", "invalid", "draft"}
        if status not in allowed:
            raise ValueError("Unsupported patch status.")
        now = timestamp()
        with connect_database(self.database_path) as connection, connection:
            connection.execute(
                """
                UPDATE patches SET status = ?, updated_at = ?, reviewed_at = ?, reviewer = ?,
                decision_reason = ?, error_code = ? WHERE id = ?
                """,
                (
                    status,
                    now,
                    now if status in {"approved", "rejected", "failed", "invalid"} else None,
                    reviewer,
                    reason,
                    error_code,
                    identifier,
                ),
            )
        return self.get(identifier)

    @staticmethod
    def _diff_for(path: str, before: str, after: str) -> str:
        from patchwork.patches.engine import PatchGenerator

        return PatchGenerator._diff(path, before, after)
