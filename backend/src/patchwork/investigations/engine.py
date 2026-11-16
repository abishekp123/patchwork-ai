import asyncio
import json
import time

from patchwork.errors import PatchworkError
from patchwork.investigations.models import TERMINAL
from patchwork.investigations.security import redact
from patchwork.investigations.store import Store
from patchwork.investigations.tools import Tools, definitions


async def run(settings, record, repository, provider):
    store, tools = Store(settings), Tools(settings, repository)
    deadline = time.monotonic() + settings.investigation_seconds
    history, seen = [], set()
    tokens = 0
    actual_input = actual_output = 0
    usage_complete = True
    report = None
    status, error = "BUDGET_EXHAUSTED", "step_limit"
    store.transition(record.id, "CONTEXT_RETRIEVAL")
    store.transition(record.id, "INVESTIGATING")
    try:
        for iteration in range(settings.investigation_steps):
            if store.get(record.id).status in TERMINAL:
                return store.get(record.id)
            if time.monotonic() >= deadline:
                error = "duration_limit"
                break
            context = redact(
                json.dumps(
                    {
                        "bug": record.description,
                        "repository": repository.id,
                        "commit": repository.commit_sha,
                        "evidence_catalog": tools.evidence,
                        "recent_observations": history[-4:],
                    }
                )
            )
            # Conservative UTF-8 byte reservation, not an exact tokenizer count.
            reserve = len(context.encode()) + len(json.dumps(definitions()).encode()) + 1000
            if (
                reserve > settings.investigation_context_bytes
                or tokens + reserve + 2000 > settings.investigation_tokens
            ):
                error = "token_budget"
                break
            if settings.investigation_cost_usd is not None:
                if settings.model_token_usd is None:
                    raise PatchworkError(
                        "cost_configuration",
                        "Set a conservative per-token USD rate.",
                        503,
                    )
                if (
                    (tokens + reserve + 2000) * settings.model_token_usd
                    > settings.investigation_cost_usd
                ):
                    error = "cost_budget"
                    break
            tokens += reserve + 2000  # Reserve before dispatch, including ambiguous failures.
            task = asyncio.create_task(provider.decide(context, definitions(), 2000))
            try:
                request_deadline = min(
                    deadline,
                    time.monotonic() + settings.provider_timeout_seconds,
                )
                while not task.done():
                    if store.get(record.id).status in TERMINAL:
                        task.cancel()
                        return store.get(record.id)
                    if time.monotonic() >= request_deadline:
                        raise PatchworkError("provider_timeout", "Provider deadline exceeded.", 504)
                    await asyncio.wait(
                        {task},
                        timeout=min(0.1, max(0, request_deadline - time.monotonic())),
                    )
                decision = task.result()
            finally:
                if not task.done():
                    task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            actual_input += decision.input_tokens
            actual_output += decision.output_tokens
            usage_complete &= decision.usage_available
            tokens = max(tokens, actual_input + actual_output)
            store.step(
                record.id,
                {
                    "iteration": iteration,
                    "usage": {
                        "input_tokens": decision.input_tokens,
                        "output_tokens": decision.output_tokens,
                        "available": decision.usage_available,
                    },
                    "reserved_tokens": tokens,
                    "context_bytes": len(context.encode()),
                },
            )
            if tokens > settings.investigation_tokens:
                error = "token_budget"
                break
            call = decision.call
            signature = json.dumps(call.model_dump(), sort_keys=True)
            if call.name == "finish_report":
                try:
                    report = tools.review(call.arguments)
                except ValueError:
                    history.append({"error": "invalid_report_or_evidence"})
                    store.step(record.id, history[-1])
                    continue
                store.transition(record.id, "EVIDENCE_REVIEW")
                status, error = "COMPLETED", None
                break
            start = time.monotonic()
            if signature in seen:
                result = {"ok": False, "error": "duplicate_call"}
            else:
                seen.add(signature)
                result = tools.execute(
                    call.name,
                    call.arguments,
                    min(deadline, start + settings.tool_timeout_seconds),
                )
            observation = {"call": call.model_dump(), "result": result}
            history.append(observation)
            store.step(
                record.id,
                {**observation, "duration_ms": round((time.monotonic() - start) * 1000, 3)},
            )
        if report is None:
            report = {
                "summary": record.description,
                "facts": [],
                "hypotheses": [],
                "evidence": list(tools.evidence.values()),
                "next_steps": ["Review the trace and continue debugging."],
                "limitations": ["Investigation ended before a reviewed conclusion."],
                "outcome": "insufficient_evidence",
            }
    except asyncio.CancelledError:
        store.transition(record.id, "CANCELLED", error="request_cancelled")
        raise
    except PatchworkError as failure:
        status, error = "FAILED", failure.code
    except Exception:
        status, error = "FAILED", "investigation_failed"
    report = report or {
        "outcome": "insufficient_evidence",
        "evidence": list(tools.evidence.values()),
    }
    report.update(
        {
            "repository_id": repository.id,
            "commit_sha": repository.commit_sha,
            "status": status,
            "usage": {
                "input_tokens": actual_input,
                "output_tokens": actual_output,
                "complete": usage_complete,
                "conservative_reserved_tokens": tokens,
            },
            "model": settings.investigation_model,
        }
    )
    store.transition(record.id, status, report, error)
    return store.get(record.id)
