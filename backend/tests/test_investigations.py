import asyncio
import hashlib
import json
import time

import pytest

from patchwork.config import Settings
from patchwork.database import initialize_database
from patchwork.ingestion.discovery import SourceFile
from patchwork.intelligence.models import Import, ParsedFile, Symbol
from patchwork.investigations.engine import run as run_investigation
from patchwork.investigations.models import Call, Decision
from patchwork.investigations.provider import FakeProvider
from patchwork.investigations.store import Store
from patchwork.investigations.tools import Tools
from patchwork.repositories.store import RepositoryStore


def _ready_repository(settings: Settings):
    initialize_database(settings.database_path)
    store = RepositoryStore(settings.database_path)
    repository, token = store.claim("https://github.com/example/python-project", "a" * 40, 10)
    assert token is not None
    parsed = ParsedFile(
        file=SourceFile(
            path="example.py",
            content_hash="abc123",
            size_bytes=20,
            encoding="utf-8",
            source="def bug():\n    return 1\n",
        ),
        has_errors=False,
        symbols=(
            Symbol(
                path="example.py",
                name="bug",
                qualified_name="bug",
                kind="function",
                parent=None,
                start_line=1,
                end_line=2,
                start_byte=0,
                end_byte=12,
            ),
        ),
        imports=(
            Import(
                path="example.py",
                module_name="os",
                imported_name="path",
                alias=None,
                relative_level=0,
                scope=None,
                start_line=1,
                end_line=1,
                start_byte=0,
                statement="import os",
            ),
        ),
    )
    ready = store.publish(repository.id, token, [parsed], {}, "fixture.git")
    return ready


def test_fake_provider_completes_a_reviewed_investigation(settings: Settings):
    repository = _ready_repository(settings)
    store = Store(settings)
    record = store.create(repository, "Find the root cause in the bug report.")
    evidence_ref = {
        "repository_id": repository.id,
        "commit_sha": repository.commit_sha,
        "path": "example.py",
        "start_line": 1,
        "end_line": 2,
    }
    evidence_id = hashlib.sha256(json.dumps(evidence_ref, sort_keys=True).encode()).hexdigest()[:16]

    class Provider(FakeProvider):
        def __init__(self):
            super().__init__(
                [
                    Decision(
                        call=Call(
                            name="inspect_file",
                            arguments={"path": "example.py", "start_line": 1, "end_line": 2},
                        ),
                        input_tokens=11,
                        output_tokens=6,
                        usage_available=True,
                    ),
                    Decision(
                        call=Call(
                            name="finish_report",
                            arguments={
                                "summary": "The issue is localized.",
                                "facts": [
                                    {
                                        "statement": "The bug site is in example.py.",
                                        "evidence_ids": [evidence_id],
                                    }
                                ],
                                "hypotheses": [
                                    {
                                        "statement": "The function returns an incorrect value.",
                                        "evidence_ids": [evidence_id],
                                    }
                                ],
                                "next_steps": ["Review the function output."],
                                "limitations": ["No runtime verification was performed."],
                            },
                        ),
                        input_tokens=9,
                        output_tokens=7,
                        usage_available=True,
                    ),
                ]
            )

    provider = Provider()
    result = asyncio.run(run_investigation(settings, record, repository, provider))

    assert result.status == "COMPLETED"
    assert provider.contexts
    assert result.report["outcome"] == "hypotheses"
    assert result.report["evidence"][0]["path"] == "example.py"


def test_tools_validate_citations_and_reject_invalid_ranges(settings: Settings):
    repository = _ready_repository(settings)
    tools = Tools(settings, repository)

    result = tools.execute(
        "inspect_file",
        {"path": "example.py", "start_line": 1, "end_line": 2},
        time.monotonic() + 5,
    )
    assert result["ok"] is True
    evidence_id = result["data"]["evidence_id"]
    reviewed = tools.review(
        {
            "summary": "Root cause identified.",
            "facts": [
                {
                    "statement": "The function definition is visible.",
                    "evidence_ids": [evidence_id],
                }
            ],
            "hypotheses": [],
            "next_steps": ["Continue validation"],
            "limitations": ["This is only static evidence."],
        }
    )
    assert reviewed["evidence"][0]["path"] == "example.py"

    with pytest.raises(ValueError):
        tools.review(
            {
                "summary": "Will fail.",
                "facts": [{"statement": "Unknown evidence", "evidence_ids": ["missing"]}],
                "hypotheses": [],
                "next_steps": ["Continue"],
                "limitations": ["No cite"],
            }
        )

    invalid = tools.execute(
        "inspect_file",
        {"path": "../example.py", "start_line": 1, "end_line": 2},
        time.monotonic() + 5,
    )
    assert invalid["ok"] is False
    assert invalid["error"] == "unsafe_path"


def test_store_transitions_and_budget_exhaustion(settings: Settings):
    repository = _ready_repository(settings)
    store = Store(settings)
    record = store.create(repository, "Check state transitions.")

    with pytest.raises(ValueError):
        store.transition(record.id, "COMPLETED", report={"summary": "not valid"})

    store.transition(record.id, "CANCELLED", error="cancelled_by_user")
    assert store.get(record.id).status == "CANCELLED"

    next_record = store.create(repository, "Verify cancellation and budget exhaustion.")
    budget_settings = settings.model_copy(
        update={
            "investigation_context_bytes": 1,
            "investigation_tokens": 1,
            "investigation_steps": 1,
        }
    )
    provider = FakeProvider(
        [
            Decision(
                call=Call(name="search_code", arguments={"query": "bug"}),
                input_tokens=1,
                output_tokens=1,
                usage_available=True,
            )
        ]
    )

    result = asyncio.run(run_investigation(budget_settings, next_record, repository, provider))
    assert result.status == "BUDGET_EXHAUSTED"
    assert result.error_code in {"token_budget", "cost_budget", "step_limit"}
