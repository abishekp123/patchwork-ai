import asyncio
import hashlib
import json
import time
from pathlib import Path

from pydantic import BaseModel

from patchwork.config import Settings
from patchwork.database import connect_database, initialize_database
from patchwork.ingestion.discovery import SourceFile
from patchwork.intelligence.python import parse_python
from patchwork.investigations.engine import run as run_investigation
from patchwork.investigations.models import Call, Decision
from patchwork.investigations.provider import FakeProvider
from patchwork.investigations.store import Store as InvestigationStore
from patchwork.patches.engine import PatchChange, PatchGenerator, PatchProposal, PatchValidator
from patchwork.patches.store import PatchStore
from patchwork.repositories.store import RepositoryStore

SOURCE = "def add_one(value: int) -> int:\n    return value + 2\n"
EXPECTED_SOURCE = "def add_one(value: int) -> int:\n    return value + 1\n"
REPOSITORY_URL = "https://github.com/patchwork-ai/deterministic-evaluation"
COMMIT = "e" * 40


class EvaluationResult(BaseModel):
    suite: str
    version: int
    passed: bool
    checks: dict[str, bool]
    details: dict[str, str]


class RepairPatchProvider:
    async def generate_patch(self, payload: dict, _repository) -> dict:
        source_file = next(
            item for item in payload["source_files"] if item["path"] == "src/math.py"
        )
        return PatchProposal(
            title="Correct add_one",
            summary="Return the input plus one.",
            changes=[
                PatchChange(
                    path="src/math.py",
                    before=source_file["source"],
                    after=EXPECTED_SOURCE,
                    reason="The implementation adds two instead of one.",
                )
            ],
            evidence_ids=payload["evidence_ids"],
        ).model_dump()


def _evidence_id(repository_id: str, commit_sha: str, path: str) -> str:
    reference = {
        "repository_id": repository_id,
        "commit_sha": commit_sha,
        "path": path,
        "start_line": 1,
        "end_line": 2,
    }
    return hashlib.sha256(json.dumps(reference, sort_keys=True).encode()).hexdigest()[:16]


def run_evaluation(database_path: Path) -> EvaluationResult:
    settings = Settings(
        database_path=database_path,
        repository_dir=database_path.parent / "snapshots",
    )
    initialize_database(settings.database_path)
    repositories = RepositoryStore(settings.database_path)
    repository, lease = repositories.claim(REPOSITORY_URL, COMMIT, 30)
    if lease is None:
        raise RuntimeError("The evaluation repository unexpectedly already exists.")

    source_file = SourceFile(
        path="src/math.py",
        content_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
        size_bytes=len(SOURCE.encode()),
        encoding="utf-8",
        source=SOURCE,
    )
    parsed = parse_python(
        source_file,
        deadline=time.monotonic() + 5,
        max_symbols=settings.max_symbols,
    )
    repository = repositories.publish(
        repository.id,
        lease,
        [parsed],
        {},
        "fixture.git",
    )

    evidence_id = _evidence_id(repository.id, repository.commit_sha, source_file.path)
    provider = FakeProvider(
        [
            Decision(
                call=Call(
                    name="inspect_file",
                    arguments={"path": source_file.path, "start_line": 1, "end_line": 2},
                )
            ),
            Decision(
                call=Call(
                    name="finish_report",
                    arguments={
                        "summary": "add_one increments by two instead of one.",
                        "facts": [
                            {
                                "statement": "The implementation adds two.",
                                "evidence_ids": [evidence_id],
                            }
                        ],
                        "hypotheses": [
                            {
                                "statement": "The constant is the likely defect.",
                                "evidence_ids": [evidence_id],
                            }
                        ],
                        "next_steps": ["Review the one-line correction."],
                        "limitations": ["The model did not execute the source."],
                    },
                )
            ),
        ]
    )
    investigation_store = InvestigationStore(settings)
    investigation = investigation_store.create(repository, "add_one returns the wrong value")
    completed = asyncio.run(run_investigation(settings, investigation, repository, provider))
    if completed.status != "COMPLETED" or completed.report is None:
        raise RuntimeError("The deterministic investigation did not complete.")

    evidence_refs = completed.report["evidence"]
    cited_ids = completed.report["facts"][0]["evidence_ids"]
    proposal = asyncio.run(
        PatchGenerator(settings, repository, RepairPatchProvider()).generate(
            completed.report["summary"],
            evidence_ids=cited_ids,
            evidence_refs=evidence_refs,
        )
    )
    diff = PatchValidator(settings, repository).validate(proposal)
    patches = PatchStore(settings.database_path)
    patch = patches.create(
        repository,
        proposal,
        investigation_id=completed.id,
    )
    approved = patches.transition(
        patch.id,
        "approved",
        reviewer="deterministic-evaluator",
        reason="All evidence and snapshot checks passed.",
    )
    with connect_database(settings.database_path) as connection:
        original_source = connection.execute(
            "SELECT source FROM files WHERE repository_id=? AND path=?",
            (repository.id, source_file.path),
        ).fetchone()[0]

    checks = {
        "investigation_completed": completed.status == "COMPLETED",
        "source_evidence_cited": evidence_id in cited_ids,
        "patch_matches_expected_source": proposal.changes[0].after == EXPECTED_SOURCE,
        "validated_unified_diff_created": bool(diff and "--- " in diff and "+++ " in diff),
        "patch_persisted_with_investigation": (
            patch.investigation_id == completed.id
            and patch.evidence_ids == [evidence_id]
            and patches.get(patch.id).diff == diff
        ),
        "human_approval_persisted": approved.status == "approved",
        "indexed_snapshot_unchanged": original_source == SOURCE,
    }
    return EvaluationResult(
        suite="offline-repair-workflow",
        version=1,
        passed=all(checks.values()),
        checks=checks,
        details={
            "repository": REPOSITORY_URL,
            "commit": COMMIT,
            "path": source_file.path,
            "execution": "No repository code was executed.",
            "provider": "Deterministic fake provider; no API key required.",
        },
    )
