import asyncio
import json
from decimal import Decimal

import httpx
import pytest

from patchwork.errors import PatchworkError
from patchwork.evaluations.cost import MODEL, CostLedger
from patchwork.evaluations.live import Limits
from patchwork.investigations.provider import OpenAIProvider
from patchwork.investigations.tools import definitions


def response(**changes):
    return {
        "model": MODEL,
        "service_tier": "default",
        "status": "completed",
        "output": [
            {"type": "function_call", "name": "search_code", "arguments": '{"query":"bug"}'}
        ],
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 100,
            "input_tokens_details": {"cached_tokens": 0},
        },
        **changes,
    }


def test_reservation_restart_and_exclusive_owner(tmp_path):
    path = tmp_path / "ledger.jsonl"
    with CostLedger(path, Decimal("1")) as ledger:
        for _ in range(4):
            ledger.reserve(MODEL, 2000)
        assert ledger.summary()["cost_upper_bound_usd"] == 0.9306
        with pytest.raises((BlockingIOError, OSError)):
            CostLedger(path, Decimal("1"))
    with CostLedger(path, Decimal("1")) as ledger:
        with pytest.raises(PatchworkError, match="USD evaluation budget"):
            ledger.reserve(MODEL, 2000)
        assert ledger.summary()["unsettled_attempts"] == 4
    with pytest.raises(ValueError, match="policy mismatch"):
        CostLedger(path, Decimal("0.5"))


def test_actual_usage_releases_only_unused_capacity(tmp_path):
    with CostLedger(tmp_path / "ledger", Decimal("1")) as ledger:
        identifier = ledger.reserve(MODEL, 2000)
        ledger.observe(identifier, json.dumps(response()).encode())
        assert ledger.summary()["usage_cost_usd"] == 0.00015
        assert ledger.summary()["cost_upper_bound_usd"] == 0.000165
        assert ledger.summary()["usage_complete"]


@pytest.mark.parametrize(
    "data",
    [
        b"bad-json",
        b"{}",
        json.dumps(response(usage=None)).encode(),
        json.dumps(response(service_tier="priority")).encode(),
        json.dumps(response(usage={"input_tokens": -1, "output_tokens": 1})).encode(),
        json.dumps(response(usage={"input_tokens": 1, "output_tokens": 999999})).encode(),
        json.dumps(
            response(
                usage={
                    "input_tokens": 100,
                    "output_tokens": 1,
                    "input_tokens_details": {"cached_tokens": 20},
                }
            )
        ).encode(),
    ],
)
def test_missing_or_invalid_usage_retains_full_reservation(tmp_path, data):
    with CostLedger(tmp_path / "ledger", Decimal("1")) as ledger:
        identifier = ledger.reserve(MODEL, 2000)
        before = ledger.charged
        ledger.observe(identifier, data)
        assert ledger.charged == before
        assert not ledger.summary()["usage_complete"]


def test_retries_reserve_before_every_http_attempt(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    calls = []
    with CostLedger(tmp_path / "ledger", Decimal("0.3")) as ledger:

        def handler(request):
            calls.append(request)
            assert ledger.charged > 0
            body = json.loads(request.content)
            assert body["service_tier"] == "default"
            assert body["prompt_cache_options"] == {"mode": "explicit"}
            return httpx.Response(503, json={})

        provider = OpenAIProvider(MODEL, 1, httpx.MockTransport(handler), accounting=ledger)
        with pytest.raises(PatchworkError, match="USD evaluation budget"):
            asyncio.run(provider.decide("{}", definitions(), 2000))
        assert len(calls) == ledger.summary()["http_attempts"] == 1


def test_invalid_decision_still_records_billable_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    with CostLedger(tmp_path / "ledger", Decimal("1")) as ledger:
        provider = OpenAIProvider(
            MODEL,
            1,
            httpx.MockTransport(lambda r: httpx.Response(200, json=response(output=[]))),
            accounting=ledger,
        )
        with pytest.raises(PatchworkError, match="Invalid provider response"):
            asyncio.run(provider.decide("{}", definitions(), 2000))
        assert ledger.summary()["usage_cost_usd"] == 0.00015


def test_transport_ambiguity_retains_reserve(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")

    def fail(request):
        raise httpx.ReadTimeout("timeout")

    with CostLedger(tmp_path / "ledger", Decimal("1")) as ledger:
        provider = OpenAIProvider(MODEL, 1, httpx.MockTransport(fail), accounting=ledger)
        with pytest.raises(PatchworkError, match="transport failed"):
            asyncio.run(provider.decide("{}", definitions(), 2000))
        assert ledger.summary()["unsettled_attempts"] == 1


def test_failed_durable_write_prevents_network(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    with CostLedger(tmp_path / "ledger", Decimal("1")) as ledger:

        def fail(fd):
            raise OSError("disk unavailable")

        monkeypatch.setattr("patchwork.evaluations.cost.os.fsync", fail)

        def forbidden(request):
            pytest.fail("No request may precede durable reservation")

        with pytest.raises(OSError):
            asyncio.run(
                OpenAIProvider(MODEL, 1, httpx.MockTransport(forbidden), accounting=ledger).decide(
                    "{}", definitions(), 2000
                )
            )


@pytest.mark.parametrize("value", ["0", "1.01", "NaN", "Infinity"])
def test_invalid_dollar_limits(tmp_path, value):
    with pytest.raises(ValueError):
        CostLedger(tmp_path / "ledger", Decimal(value))
    with pytest.raises(ValueError):
        Limits(maximum_usd=Decimal(value))


def test_unreviewed_model_fails_before_dispatch(tmp_path):
    with CostLedger(tmp_path / "ledger", Decimal("1")) as ledger:
        with pytest.raises(PatchworkError, match="Unreviewed model"):
            ledger.reserve("unknown", 2000)
        assert not ledger.attempts


def test_long_context_usage_and_partial_case_summary(tmp_path):
    with CostLedger(tmp_path / "ledger", Decimal("1")) as ledger:
        ledger.reserve(MODEL, 2000)
        index = ledger.reserve(MODEL, 2000)
        ledger.observe(
            index,
            json.dumps(response(usage={"input_tokens": 300000, "output_tokens": 100})).encode(),
        )
        assert ledger.summary(1)["usage_cost_usd"] == 0.060075
        assert ledger.summary()["unsettled_attempts"] == 1


@pytest.mark.parametrize(
    "content", ['{"kind":"reserve","id":0,"reserved_nano":1}\n', '{"kind":', "{}\n"]
)
def test_corrupt_ledger_fails_closed(tmp_path, content):
    path = tmp_path / "ledger"
    path.write_text(content)
    with pytest.raises(ValueError):
        CostLedger(path, Decimal("1"))


def test_paid_builtin_tools_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    with CostLedger(tmp_path / "ledger", Decimal("1")) as ledger:

        def forbidden(request):
            pytest.fail("Paid builtin tools cannot be dispatched")

        with pytest.raises(PatchworkError, match="Only local function tools"):
            asyncio.run(
                OpenAIProvider(MODEL, 1, httpx.MockTransport(forbidden), accounting=ledger).decide(
                    "{}", [{"type": "web_search"}], 2000
                )
            )
        assert not ledger.attempts
