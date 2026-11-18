import asyncio
import json

import pytest

from patchwork.database import initialize_database
from patchwork.errors import PatchworkError
from patchwork.evaluations.fixtures import FIXTURES
from patchwork.evaluations.live import (
    Budget,
    Limits,
    MeteredProvider,
    evaluate_case,
    run_suite,
    successful_repair,
)
from patchwork.investigations.models import Call, Decision
from patchwork.investigations.provider import FakeProvider
from patchwork.verifications.models import VerificationRecord, VerificationSummary

# Expected implementations are test oracles, never sent to the live provider.
REPAIRS = {
    "arithmetic": "def repair(a, b):\n    return a + b\n",
    "off_by_one": "def repair(n):\n    return list(range(n + 1))\n",
    "boolean": "def repair(active, verified):\n    return active and verified\n",
    "dictionary": "def repair(mapping, key):\n    return mapping.get(key)\n",
    "conversion": (
        "def repair(value):\n    try:\n        return int(value)\n"
        "    except (TypeError, ValueError):\n        return None\n"
    ),
}


class FixtureProvider:
    def __init__(self, fixture, *, mutate_tests=False):
        self.fixture = fixture
        self.mutate_tests = mutate_tests
        self.calls = 0

    async def decide(self, context, tools, max_output):
        self.calls += 1
        if self.calls == 1:
            call = Call(
                name="inspect_file",
                arguments={
                    "path": "subject.py",
                    "start_line": 1,
                    "end_line": len(self.fixture.source.splitlines()),
                },
            )
        elif self.calls == 2:
            data = json.loads(context)
            ids = list(data["evidence_catalog"])
            call = Call(
                name="finish_report",
                arguments={
                    "summary": "Fixture bug",
                    "facts": [{"statement": "Observed bug", "evidence_ids": ids}],
                    "hypotheses": [],
                    "next_steps": ["Repair implementation"],
                    "limitations": ["Not executed"],
                },
            )
        else:
            data = json.loads(context)
            call = Call(
                name="generate_patch",
                arguments={
                    "title": "Repair fixture",
                    "summary": "Fix observed defect",
                    "changes": [
                        {
                            "path": "fixture_test_repair.py" if self.mutate_tests else "subject.py",
                            "before": self.fixture.source,
                            "after": REPAIRS[self.fixture.name],
                            "reason": "Match documented behavior",
                        }
                    ],
                    "evidence_ids": data["evidence_ids"],
                },
            )
        return Decision(call=call, input_tokens=100, output_tokens=100, usage_available=True)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture.name)
def test_each_fixture_reaches_validation_without_implicit_approval(settings, fixture, monkeypatch):
    initialize_database(settings.database_path)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Unapproved evaluation must not execute")

    monkeypatch.setattr("patchwork.evaluations.live.run_verification", forbidden)
    budget = Budget(Limits())
    row = asyncio.run(
        evaluate_case(settings, fixture, FixtureProvider(fixture), budget, approve=False)
    )
    assert row["outcome"] == "AWAITING_APPROVAL", row
    assert row["generated"] and row["validated"] and row["evidence"]
    assert not row["approved"] and not row["docker_tested"] and not row["successful_repair"]
    assert budget.input_tokens == budget.output_tokens == 300


def test_test_file_mutation_is_rejected(settings):
    initialize_database(settings.database_path)
    row = asyncio.run(
        evaluate_case(
            settings,
            FIXTURES[0],
            FixtureProvider(FIXTURES[0], mutate_tests=True),
            Budget(Limits()),
            approve=True,
        )
    )
    assert row["error_code"] == "evaluation_test_mutation"
    assert not row["approved"] and not row["validated"]


@pytest.mark.parametrize(
    "live, key, approve", [(False, True, True), (True, False, True), (True, True, False)]
)
def test_no_implicit_live_calls(tmp_path, monkeypatch, live, key, approve):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only" if key else "")
    result = asyncio.run(
        run_suite(tmp_path, live=live, approve=approve, limits=Limits(), model="test")
    )
    assert result["status"] == "NOT_RUN"
    assert result["usage"]["logical_calls"] == 0
    assert result["successful_repairs"] == 0
    assert all(
        row["outcome"] == "NOT_RUN"
        for row in json.loads((tmp_path / "results.json").read_text())["cases"]
    )
    assert "NOT_RUN" in (tmp_path / "results.md").read_text()


def test_global_budget_reserves_before_dispatch():
    provider = FakeProvider([])
    wrapper = MeteredProvider(provider, Budget(Limits(total_reserved_tokens=1)))
    with pytest.raises(PatchworkError, match="Global evaluation budget"):
        asyncio.run(wrapper.decide("context", [], 100))
    assert provider.contexts == []


def test_case_budget_and_usage():
    decision = Decision(
        call=Call(name="tool", arguments={}), input_tokens=5, output_tokens=7, usage_available=True
    )
    wrapper = MeteredProvider(
        FakeProvider([decision, decision, decision]), Budget(Limits(calls_per_case=2))
    )
    for _ in range(2):
        asyncio.run(wrapper.decide("context", [{"name": "tool"}], 100))
    with pytest.raises(PatchworkError, match="Fixture call budget"):
        asyncio.run(wrapper.decide("context", [{"name": "tool"}], 100))
    assert wrapper.budget.input_tokens == 10 and wrapper.budget.output_tokens == 14


def test_provider_failure_has_no_success(settings):
    initialize_database(settings.database_path)
    row = asyncio.run(
        evaluate_case(settings, FIXTURES[0], FakeProvider([]), Budget(Limits()), approve=True)
    )
    assert row["error_code"] == "provider_invalid_response"
    assert not any(
        row[key]
        for key in ("generated", "validated", "approved", "docker_tested", "successful_repair")
    )


def test_timeout_is_bounded_and_recorded(settings):
    initialize_database(settings.database_path)

    class TimeoutProvider:
        async def decide(self, *args):
            raise TimeoutError()

    row = asyncio.run(
        evaluate_case(settings, FIXTURES[0], TimeoutProvider(), Budget(Limits()), approve=True)
    )
    assert row["outcome"] == "FAILED"
    assert not row["successful_repair"]


def test_success_requires_docker_real_tests_and_baseline_failure():
    from patchwork.verifications.engine import _classify

    baseline = VerificationSummary(exit_code=1, tests_total=3, tests_failed=1, tests_passed=2)
    patched = VerificationSummary(exit_code=0, tests_total=3, tests_failed=0, tests_passed=3)
    record = VerificationRecord(
        id="id",
        patch_id="patch",
        repository_id="repo",
        commit_sha="a" * 40,
        status="COMPLETED",
        sandbox_mode="docker",
        created_at="now",
        updated_at="now",
        baseline_summary=baseline,
        patched_summary=patched,
        comparison=_classify(baseline, patched),
    )
    assert successful_repair(record, 3)
    assert not successful_repair(record.model_copy(update={"sandbox_mode": "fake"}), 3)
    assert not successful_repair(record, 4)
    assert not successful_repair(record.model_copy(update={"baseline_summary": patched}), 3)
    assert not successful_repair(
        record.model_copy(
            update={"patched_summary": patched.model_copy(update={"tests_skipped": 1})}
        ),
        3,
    )
