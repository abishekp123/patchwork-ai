import asyncio
import json

import httpx
import pytest

from patchwork.errors import PatchworkError
from patchwork.investigations.provider import OpenAIProvider
from patchwork.investigations.tools import definitions


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "provider_authentication"),
        (400, "provider_request_rejected"),
        (429, "provider_rate_limit"),
        (503, "provider_outage"),
    ],
)
def test_provider_errors(monkeypatch, status, code):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={})

    with pytest.raises(PatchworkError) as error:
        asyncio.run(
            OpenAIProvider("test", 1, httpx.MockTransport(handler)).decide("{}", definitions(), 100)
        )
    assert error.value.code == code
    assert len(calls) == (3 if status in (429, 503) else 1)


def test_provider_contract(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")

    def handler(request):
        body = json.loads(request.content)
        assert body["store"] is False and body["parallel_tool_calls"] is False
        assert all(tool["strict"] for tool in body["tools"])
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "function_call", "name": "search_code", "arguments": '{"query":"bug"}'}
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    decision = asyncio.run(
        OpenAIProvider("test", 1, httpx.MockTransport(handler)).decide("{}", definitions(), 100)
    )
    assert decision.call.name == "search_code" and decision.input_tokens == 10


def test_invalid_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    provider = OpenAIProvider(
        "test", 1, httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    with pytest.raises(PatchworkError, match="Invalid provider"):
        asyncio.run(provider.decide("{}", definitions(), 100))
