import hashlib
import json
import time

from pydantic import ValidationError

from patchwork.database import connect_database
from patchwork.errors import PatchworkError
from patchwork.ingestion.validation import validate_path
from patchwork.intelligence import search
from patchwork.investigations.models import FileRange, Imports, ReportDraft, Search, Symbols
from patchwork.investigations.security import redact

SCHEMAS = {
    "search_code": Search,
    "find_symbols": Symbols,
    "inspect_file": FileRange,
    "inspect_imports": Imports,
    "finish_report": ReportDraft,
}


def definitions() -> list[dict]:
    return [
        {
            "type": "function",
            "name": name,
            "description": name.replace("_", " "),
            "strict": True,
            "parameters": schema.model_json_schema(),
        }
        for name, schema in SCHEMAS.items()
    ]


class Tools:
    def __init__(self, settings, repository) -> None:
        self.settings, self.repository = settings, repository
        self.evidence: dict[str, dict] = {}

    def execute(self, name: str, arguments: dict, deadline: float) -> dict:
        try:
            if time.monotonic() >= deadline:
                raise PatchworkError("tool_timeout", "Tool deadline exceeded.")
            if name not in SCHEMAS or name == "finish_report":
                raise PatchworkError("tool_not_allowed", "Unknown read-only tool.")
            args = SCHEMAS[name].model_validate(arguments)
            repo = self.repository
            if name == "search_code":
                result = search.search(self.settings, repo, args.query, 5).model_dump()
            elif name == "find_symbols":
                result = search.symbols(
                    self.settings, repo.id, args.name, args.exact, 5, 0
                ).model_dump()
            else:
                path = validate_path(args.path)
                with connect_database(self.settings.database_path) as connection:
                    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
                    row = connection.execute(
                        "SELECT id, source, line_count FROM files WHERE repository_id=? AND path=?",
                        (repo.id, path),
                    ).fetchone()
                    if row is None:
                        raise PatchworkError(
                            "file_not_indexed", "File is not indexed in this snapshot."
                        )
                    if name == "inspect_imports":
                        rows = connection.execute(
                            "SELECT data_json FROM imports WHERE file_id=? "
                            "ORDER BY start_byte LIMIT 20",
                            (row["id"],),
                        ).fetchall()
                        result = {"imports": [json.loads(item[0]) for item in rows]}
                    else:
                        if (
                            args.end_line < args.start_line
                            or args.end_line > row["line_count"]
                            or args.end_line - args.start_line >= 100
                        ):
                            raise PatchworkError(
                                "invalid_range", "Use a valid range of at most 100 lines."
                            )
                        excerpt = "\n".join(
                            row["source"].split("\n")[args.start_line - 1 : args.end_line]
                        )
                        if len(excerpt.encode()) > 6000:
                            raise PatchworkError("output_limit", "Request a smaller source range.")
                        ref = {
                            "repository_id": repo.id,
                            "commit_sha": repo.commit_sha,
                            "path": path,
                            "start_line": args.start_line,
                            "end_line": args.end_line,
                        }
                        evidence_id = hashlib.sha256(
                            json.dumps(ref, sort_keys=True).encode()
                        ).hexdigest()[:16]
                        result = {"evidence_id": evidence_id, **ref, "source": redact(excerpt)}
            serialized = redact(json.dumps(result, ensure_ascii=False))
            if time.monotonic() >= deadline:
                raise PatchworkError("tool_timeout", "Tool deadline exceeded.")
            if len(serialized.encode()) > 12000:
                raise PatchworkError("output_limit", "Narrow the tool query.")
            result = json.loads(serialized)
            if name == "inspect_file":
                self.evidence[result["evidence_id"]] = {
                    k: v for k, v in result.items() if k != "source"
                }
            return {"ok": True, "data": result}
        except (PatchworkError, ValidationError) as error:
            return {
                "ok": False,
                "error": error.code if isinstance(error, PatchworkError) else "invalid_arguments",
            }

    def review(self, arguments: dict) -> dict:
        draft = ReportDraft.model_validate(arguments)
        for fact in draft.facts:
            if not fact.evidence_ids:
                raise ValueError("Observed facts require evidence")
        refs = set()
        for finding in [*draft.facts, *draft.hypotheses]:
            for identifier in finding.evidence_ids:
                if identifier not in self.evidence:
                    raise ValueError("Unknown evidence reference")
                refs.add(identifier)
        # Recheck every issued reference against the current immutable index.
        for identifier in refs:
            ref = self.evidence[identifier]
            with connect_database(self.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT line_count FROM files WHERE repository_id=? AND path=?",
                    (self.repository.id, ref["path"]),
                ).fetchone()
            if row is None or not 1 <= ref["start_line"] <= ref["end_line"] <= row[0]:
                raise ValueError("Evidence no longer valid")
        return {
            **draft.model_dump(),
            "evidence": [self.evidence[key] for key in sorted(refs)],
            "outcome": "hypotheses" if refs and draft.hypotheses else "insufficient_evidence",
            "verification": "Source locations validated; model interpretations are unverified.",
        }
