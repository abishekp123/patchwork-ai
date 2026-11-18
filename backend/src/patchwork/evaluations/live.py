"""Opt-in, bounded real-provider repair evaluation; never a fake-provider fallback."""

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from patchwork.config import Settings
from patchwork.database import initialize_database
from patchwork.errors import PatchworkError
from patchwork.evaluations.fixtures import FIXTURES, RepairFixture
from patchwork.ingestion.discovery import SourceFile
from patchwork.intelligence.python import parse_python
from patchwork.investigations.engine import run as investigate
from patchwork.investigations.provider import OpenAIProvider, Provider
from patchwork.investigations.store import Store
from patchwork.patches.engine import PatchGenerator, PatchValidator
from patchwork.patches.store import PatchStore
from patchwork.repositories.store import RepositoryStore, timestamp
from patchwork.verifications.engine import run_verification
from patchwork.verifications.models import SandboxConfig, VerificationRecord
from patchwork.verifications.sandbox import SandboxAdapter

COMMAND = "python -m unittest discover -v -p 'fixture_test_*.py'"
APPROVAL = "Explicit --approve-fixtures consent: isolated built-in evaluation fixtures only."


class Limits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    calls_per_case: int = Field(default=8, ge=2, le=15)
    total_calls: int = Field(default=40, ge=1, le=75)
    total_reserved_tokens: int = Field(default=600_000, ge=1, le=2_000_000)
    case_seconds: int = Field(default=180, ge=10, le=300)
    total_seconds: int = Field(default=900, ge=10, le=1500)
    sandbox_seconds: int = Field(default=20, ge=1, le=60)


class Budget:
    def __init__(self, limits: Limits):
        self.limits = limits
        self.started = time.monotonic()
        self.calls = self.reserved_tokens = self.input_tokens = self.output_tokens = 0
        self.usage_complete = True

    def reserve(self, context: str, tools: list[dict], output: int) -> None:
        # Byte-based upper reservation with instruction margin; 3 provider retry attempts.
        reservation = (len(context.encode()) + len(json.dumps(tools).encode()) + 4096 + output) * 3
        if (
            self.calls >= self.limits.total_calls
            or self.reserved_tokens + reservation > self.limits.total_reserved_tokens
            or time.monotonic() - self.started >= self.limits.total_seconds
        ):
            raise PatchworkError("evaluation_budget", "Global evaluation budget exhausted.", 422)
        self.calls += 1
        self.reserved_tokens += reservation

    def summary(self) -> dict:
        return {
            "logical_calls": self.calls,
            "http_attempt_limit": self.calls * 3,
            "reserved_tokens_estimate": self.reserved_tokens,
            "actual_input_tokens": self.input_tokens,
            "actual_output_tokens": self.output_tokens,
            "usage_complete": self.usage_complete,
        }


class MeteredProvider:
    def __init__(self, provider: Provider, budget: Budget):
        self.provider, self.budget, self.calls = provider, budget, 0

    async def decide(self, context: str, tools: list[dict], max_output: int):
        if self.calls >= self.budget.limits.calls_per_case:
            raise PatchworkError("evaluation_budget", "Fixture call budget exhausted.", 422)
        self.budget.reserve(context, tools, max_output)
        self.calls += 1
        try:
            decision = await self.provider.decide(context, tools, max_output)
        except BaseException:
            self.budget.usage_complete = False  # Failed requests may still be billed.
            raise
        self.budget.input_tokens += decision.input_tokens
        self.budget.output_tokens += decision.output_tokens
        self.budget.usage_complete &= decision.usage_available
        if decision.call.name not in {tool["name"] for tool in tools}:
            raise PatchworkError("provider_invalid_response", "Unexpected provider tool.", 502)
        return decision


def index_fixture(settings: Settings, fixture: RepairFixture):
    digest = hashlib.sha256(json.dumps(fixture.files, sort_keys=True).encode()).hexdigest()
    store = RepositoryStore(settings.database_path)
    repository, lease = store.claim(f"fixture://live-evaluation/{fixture.name}", digest[:40], 30)
    if lease is None:
        raise ValueError("Evaluation requires a fresh database.")
    files = [
        parse_python(
            SourceFile(
                path=path,
                source=source,
                encoding="utf-8",
                content_hash=hashlib.sha256(source.encode()).hexdigest(),
                size_bytes=len(source.encode()),
            ),
            deadline=time.monotonic() + 5,
            max_symbols=settings.max_symbols,
        )
        for path, source in sorted(fixture.files.items())
    ]
    return store.publish(repository.id, lease, files, {}, "fixture.git")


def successful_repair(record: VerificationRecord, expected_tests: int) -> bool:
    base, patched = record.baseline_summary, record.patched_summary
    return bool(
        record.sandbox_mode == "docker"
        and record.status == "COMPLETED"
        and record.comparison
        and record.comparison.status == "IMPROVED"
        and base
        and patched
        and not base.error_code
        and not patched.error_code
        and base.exit_code == 1
        and base.tests_failed > 0
        and patched.exit_code == 0
        and patched.tests_failed == 0
        and base.tests_total == patched.tests_total == expected_tests
        and base.tests_skipped == patched.tests_skipped == 0
        and patched.tests_passed == expected_tests
    )


async def evaluate_case(
    settings: Settings,
    fixture: RepairFixture,
    provider: Provider,
    budget: Budget,
    *,
    approve: bool,
) -> dict:
    """Provider injection is for harness tests; the CLI always constructs OpenAIProvider."""
    started = time.monotonic()
    row = {
        "fixture": fixture.name,
        "outcome": "FAILED",
        "generated": False,
        "validated": False,
        "approved": False,
        "docker_tested": False,
        "successful_repair": False,
        "error_code": None,
    }
    metered = MeteredProvider(provider, budget)
    try:
        remaining = budget.limits.total_seconds - (started - budget.started)
        if remaining <= 0:
            raise PatchworkError("evaluation_budget", "Duration budget exhausted.", 422)
        async with asyncio.timeout(min(budget.limits.case_seconds, remaining)):
            repository = index_fixture(settings, fixture)
            row.update(repository_id=repository.id, commit_sha=repository.commit_sha)
            investigation = Store(settings).create(repository, fixture.description)
            row["investigation_id"] = investigation.id
            completed = await investigate(settings, investigation, repository, metered)
            if completed.status != "COMPLETED" or not completed.report:
                raise PatchworkError(
                    completed.error_code or "investigation_incomplete",
                    "Investigation did not complete.",
                    422,
                )
            refs = completed.report["evidence"]
            cited = sorted(
                {ref for fact in completed.report["facts"] for ref in fact["evidence_ids"]}
            )
            if not refs or not cited:
                raise PatchworkError("insufficient_evidence", "No observed source evidence.", 422)
            row["evidence"] = refs
            proposal = await PatchGenerator(settings, repository, metered).generate(
                fixture.description,
                evidence_ids=cited,
                evidence_refs=refs,
            )
            row["generated"] = True
            # Protect the oracle: a model may edit only the implementation, never tests.
            if {change.path for change in proposal.changes} != {"subject.py"}:
                raise PatchworkError("evaluation_test_mutation", "Tests cannot be patched.", 422)
            if not proposal.evidence_ids or not set(proposal.evidence_ids).issubset(cited):
                raise PatchworkError(
                    "insufficient_evidence", "Patch must cite observed evidence.", 422
                )
            PatchValidator(settings, repository).validate(proposal)
            row["validated"] = True
            patches = PatchStore(settings.database_path)
            patch = patches.create(repository, proposal, investigation_id=completed.id)
            row["patch_id"] = patch.id
            if not approve:
                row["outcome"] = "AWAITING_APPROVAL"
                return row
            patches.transition(
                patch.id, "approved", reviewer="opt-in-fixture-evaluator", reason=APPROVAL
            )
            row["approved"] = True
            record = await run_verification(
                settings,
                patch.id,
                repository_id=repository.id,
                commit_sha=repository.commit_sha,
                baseline_command=COMMAND,
                patched_command=COMMAND,
            )
            row["verification_id"] = record.id
            row["docker_tested"] = record.sandbox_mode == "docker" and bool(
                record.baseline_summary and record.patched_summary
            )
            row["verification"] = {
                "status": record.status,
                "baseline": record.baseline_summary.model_dump()
                if record.baseline_summary
                else None,
                "patched": record.patched_summary.model_dump() if record.patched_summary else None,
                "comparison": record.comparison.status if record.comparison else None,
            }
            row["successful_repair"] = successful_repair(record, len(fixture.assertions))
            row["outcome"] = "SUCCESSFUL_REPAIR" if row["successful_repair"] else "NOT_REPAIRED"
    except TimeoutError:
        row["error_code"] = "evaluation_timeout"
    except PatchworkError as error:
        row["error_code"] = error.code
    except ValueError:
        row["error_code"] = "patch_validation"
    except Exception:
        row["error_code"] = "evaluation_failed"  # Never persist arbitrary exception/provider text.
    finally:
        row["duration_seconds"] = round(time.monotonic() - started, 3)
        row["logical_calls"] = metered.calls
    return row


def write_reports(output: Path, result: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Live repair evaluation",
        "",
        f"Status: {result['status']}",
        f"Model: {result['model']}",
        f"Reason: {result.get('reason') or 'See case outcomes.'}",
        "",
        "| Fixture | Outcome | Generated | Validated | Approved | Docker tested | Repair |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["cases"]:
        values = [
            row["fixture"],
            row["outcome"],
            *[
                str(row[name])
                for name in (
                    "generated",
                    "validated",
                    "approved",
                    "docker_tested",
                    "successful_repair",
                )
            ],
        ]
        lines.append("| " + " | ".join(values) + " |")
    lines += [
        "",
        "A successful repair means the fixed fixture tests passed in Docker; it is not",
        "a general correctness proof. No source is executed on the host.",
        "",
    ]
    (output / "results.md").write_text("\n".join(lines))


async def run_suite(output: Path, *, live: bool, approve: bool, limits: Limits, model: str) -> dict:
    result = {
        "suite": "real-ai-repair-v1",
        "created_at": timestamp(),
        "model": model,
        "provider": "OpenAI Responses API",
        "status": "NOT_RUN",
        "cases": [],
        "limits": limits.model_dump(),
        "approval_policy": APPROVAL,
        "reason": None,
    }
    budget = Budget(limits)
    if not live:
        result["reason"] = "Explicit --live opt-in required."
    elif not os.environ.get("OPENAI_API_KEY"):
        result["reason"] = (
            "OPENAI_API_KEY unavailable; no inference or Docker evaluation performed."
        )
    elif not approve:
        result["reason"] = "Explicit --approve-fixtures consent required for this evaluation suite."
    elif not SandboxAdapter(SandboxConfig(trusted_roots=[tempfile.gettempdir()])).available():
        result["reason"] = "Docker daemon or pinned image unavailable."
    else:
        output.mkdir(parents=True, exist_ok=True)
        # Keep traces but never mix successive evaluations or production data.
        with tempfile.TemporaryDirectory(prefix="patchwork-live-snapshots-") as snapshots:
            settings = Settings(
                database_path=output / "evaluation.db",
                repository_dir=Path(snapshots),
                investigation_model=model,
                investigation_steps=limits.calls_per_case - 1,
                investigation_tokens=limits.total_reserved_tokens,
                investigation_seconds=min(limits.case_seconds, 120),
                verification_timeout_seconds=limits.sandbox_seconds,
                verification_output_limit_bytes=8192,
            )
            if settings.database_path.exists():
                raise ValueError("Choose a fresh output directory; evaluation.db already exists.")
            initialize_database(settings.database_path)
            provider = OpenAIProvider(model, settings.provider_timeout_seconds)
            for fixture in FIXTURES:
                row = await evaluate_case(settings, fixture, provider, budget, approve=approve)
                result["cases"].append(row)
                result["status"] = "RUNNING"
                result["usage"] = budget.summary()
                write_reports(output, result)  # Checkpoint after every case.
            result["status"] = "COMPLETED"
    if result["status"] == "NOT_RUN":
        result["cases"] = [
            {
                "fixture": fixture.name,
                "outcome": "NOT_RUN",
                "generated": False,
                "validated": False,
                "approved": False,
                "docker_tested": False,
                "successful_repair": False,
                "error_code": "prerequisite_unavailable",
            }
            for fixture in FIXTURES
        ]
    result["usage"] = budget.summary()
    result["successful_repairs"] = sum(row["successful_repair"] for row in result["cases"])
    write_reports(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--approve-fixtures", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--max-reserved-tokens", type=int, default=600_000)
    parser.add_argument("--max-seconds", type=int, default=900)
    args = parser.parse_args()
    limits = Limits(
        total_calls=args.max_calls,
        total_reserved_tokens=args.max_reserved_tokens,
        total_seconds=args.max_seconds,
    )
    result = asyncio.run(
        run_suite(
            args.output_dir,
            live=args.live,
            approve=args.approve_fixtures,
            limits=limits,
            model=args.model,
        )
    )
    print(json.dumps({name: result[name] for name in ("status", "successful_repairs", "reason")}))
    return (
        0
        if result["status"] == "COMPLETED" and result["successful_repairs"] == len(FIXTURES)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
