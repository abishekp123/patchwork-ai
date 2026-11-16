import json
import time
import uuid

from patchwork.database import connect_database
from patchwork.errors import PatchworkError
from patchwork.investigations.models import TERMINAL, Investigation
from patchwork.investigations.security import redact
from patchwork.repositories.store import timestamp

TRANSITIONS = {
    "CREATED": "CONTEXT_RETRIEVAL",
    "CONTEXT_RETRIEVAL": "INVESTIGATING",
    "INVESTIGATING": "EVIDENCE_REVIEW",
    "EVIDENCE_REVIEW": "COMPLETED",
}


class Store:
    def __init__(self, settings):
        self.settings = settings

    def create(self, repository, description):
        identifier, now = uuid.uuid4().hex, timestamp()
        with connect_database(self.settings.database_path) as db, db:
            db.execute(
                "INSERT INTO investigations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    repository.id,
                    repository.commit_sha,
                    redact(description),
                    "CREATED",
                    now,
                    now,
                    None,
                    time.time() + self.settings.investigation_seconds,
                    None,
                    None,
                ),
            )
        return self.get(identifier)

    def get(self, identifier):
        with connect_database(self.settings.database_path) as db, db:
            # A crashed process cannot retain a live claim past its deadline.
            db.execute(
                """UPDATE investigations SET status='FAILED', error_code='interrupted',
                       completed_at=?, updated_at=? WHERE expires < ?
                       AND status NOT IN ('COMPLETED','FAILED','CANCELLED','BUDGET_EXHAUSTED')""",
                (timestamp(), timestamp(), time.time()),
            )
            row = db.execute("SELECT * FROM investigations WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise PatchworkError("investigation_not_found", "Investigation not found.", 404)
        data = dict(row)
        data["report"] = json.loads(data["report"]) if data["report"] else None
        return Investigation.model_validate(data)

    def transition(self, identifier, status, report=None, error=None):
        with connect_database(self.settings.database_path) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT status FROM investigations WHERE id=?",
                (identifier,),
            ).fetchone()[0]
            if previous in TERMINAL:
                return
            if (
                status not in {"FAILED", "CANCELLED", "BUDGET_EXHAUSTED"}
                and TRANSITIONS.get(previous) != status
            ):
                raise ValueError("Invalid investigation transition")
            if status == "COMPLETED" and report is None:
                raise ValueError("Completion requires reviewed report")
            now = timestamp()
            db.execute(
                "UPDATE investigations SET status=?,updated_at=?,completed_at=?,"
                "report=?,error_code=? WHERE id=?",
                (
                    status,
                    now,
                    now if status in TERMINAL else None,
                    redact(json.dumps(report)) if report else None,
                    error,
                    identifier,
                ),
            )
            self._step(db, identifier, {"transition": status})

    def _step(self, db, identifier, data):
        encoded = redact(json.dumps(data))
        if len(encoded.encode()) > 20000:
            encoded = json.dumps({"error": "trace_output_limit"})
        db.execute(
            "INSERT INTO investigation_steps "
            "SELECT ?, coalesce(max(sequence),0)+1, ?, ? FROM investigation_steps "
            "WHERE investigation_id=?",
            (identifier, timestamp(), encoded, identifier),
        )

    def step(self, identifier, data):
        with connect_database(self.settings.database_path) as db, db:
            self._step(db, identifier, data)

    def steps(self, identifier, limit=50, offset=0):
        self.get(identifier)
        with connect_database(self.settings.database_path) as db:
            rows = db.execute(
                "SELECT sequence,created_at,data FROM investigation_steps "
                "WHERE investigation_id=? ORDER BY sequence LIMIT ? OFFSET ?",
                (identifier, limit, offset),
            ).fetchall()
        return [
            {"sequence": row[0], "created_at": row[1], "data": json.loads(row[2])} for row in rows
        ]
