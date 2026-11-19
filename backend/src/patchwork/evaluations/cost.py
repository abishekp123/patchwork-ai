"""Durable, fail-closed API cost reservations for the reviewed evaluation model."""

import fcntl
import json
import os
from decimal import Decimal
from pathlib import Path

from patchwork.errors import PatchworkError

MODEL = "gpt-6-luna"
# Reviewed 2026-11-18: https://developers.openai.com/api/docs/models/gpt-6-luna
# Nanodollars per token. Explicit cache mode without breakpoints disables caching.
INPUT_RATE, OUTPUT_RATE = 100, 500
CONTEXT_LIMIT, OUTPUT_LIMIT = 1_050_000, 128_000
LONG_THRESHOLD = 272_000
NANO = 1_000_000_000


class CostLedger:
    """One locked append-only ledger across all fixtures, retries, and restarts.

    Reserve the FULL context capacity at long-context rates, plus bounded output,
    with 10% regional headroom. Never release an ambiguous attempt's reservation.
    Token estimates play no part in dollar enforcement. Not an account-wide cap.
    """

    def __init__(self, path: Path, maximum: Decimal):
        if not maximum.is_finite() or not Decimal(0) < maximum <= Decimal(1):
            raise ValueError("Evaluation budget must be greater than zero and at most $1.")
        self.limit = int(maximum * NANO)
        self.path, self.fixture = path, None
        self.attempts: list[dict] = []
        self.broken = False
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        self.file = os.fdopen(fd, "r+", encoding="utf-8")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if os.fstat(fd).st_size > 1_000_000:
                raise ValueError("Cost ledger exceeds limit.")
            events = [json.loads(line) for line in self.file]
            if events and (
                events[0].get("kind") != "policy"
                or any(item.get("kind") == "policy" for item in events[1:])
            ):
                raise ValueError("Cost ledger policy missing or duplicated.")
            for event in events:
                self._apply(event)
            if not events:
                self._append({"kind": "policy", "model": MODEL, "limit": self.limit, "version": 1})
            if self.charged > self.limit:
                raise ValueError("Cost ledger exceeds authorized budget.")
        except BaseException:
            self.file.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.file.close()

    @property
    def charged(self) -> int:
        return sum(item.get("cost_bound_nano", item["reserved_nano"]) for item in self.attempts)

    def _apply(self, event: dict) -> None:
        kind = event["kind"]
        if kind == "policy":
            if event != {"kind": kind, "model": MODEL, "limit": self.limit, "version": 1}:
                raise ValueError("Cost ledger policy mismatch.")
        elif kind == "reserve":
            if event["id"] != len(self.attempts) or event["reserved_nano"] <= 0:
                raise ValueError("Invalid cost reservation.")
            self.attempts.append(event)
        elif kind == "usage":
            item = self.attempts[event["id"]]
            if (
                "cost_bound_nano" in item
                or not 0 <= event["cost_bound_nano"] <= item["reserved_nano"]
            ):
                raise ValueError("Invalid cost settlement.")
            item.update(event)
        else:
            raise ValueError("Invalid cost ledger event.")

    def _append(self, event: dict) -> None:
        if self.broken:
            raise OSError("Cost ledger is unavailable; no further requests allowed.")
        try:
            self.file.seek(0, os.SEEK_END)
            self.file.write(json.dumps(event, sort_keys=True) + "\n")
            self.file.flush()
            os.fsync(self.file.fileno())  # Durable reservation must precede dispatch.
            self._apply(event)
        except BaseException:
            self.broken = True
            raise

    def reserve(self, model: str, output: int) -> int:
        if model != MODEL or type(output) is not int or not 1 <= output <= OUTPUT_LIMIT:
            raise PatchworkError("cost_configuration", "Unreviewed model or output bound.", 422)
        reservation = (CONTEXT_LIMIT * INPUT_RATE * 2 + output * OUTPUT_RATE * 3 // 2) * 11 // 10
        if self.charged + reservation > self.limit:
            raise PatchworkError("evaluation_cost_budget", "USD evaluation budget exhausted.", 422)
        identifier = len(self.attempts)
        self._append(
            {
                "kind": "reserve",
                "id": identifier,
                "fixture": self.fixture,
                "max_output": output,
                "reserved_nano": reservation,
            }
        )
        return identifier

    def observe(self, identifier: int, raw: bytes) -> None:
        """Account for usage even when the structured decision is invalid/incomplete."""
        try:
            data = json.loads(raw)
            usage = data["usage"]
            inp, out = usage["input_tokens"], usage["output_tokens"]
            if (
                type(inp) is not int
                or type(out) is not int
                or not 0 <= inp <= CONTEXT_LIMIT
                or not 0 <= out <= self.attempts[identifier]["max_output"]
                or data.get("service_tier") != "default"
                or not data.get("model", "").startswith(MODEL)
            ):
                return
            # Explicit cache mode: cache activity is unexpected; retain full reserve.
            details = usage.get("input_tokens_details", {})
            if any(value for key, value in details.items() if "cache" in key):
                return
            cost = inp * INPUT_RATE + out * OUTPUT_RATE
            if inp > LONG_THRESHOLD:
                cost = inp * INPUT_RATE * 2 + out * OUTPUT_RATE * 3 // 2
        except (ValueError, KeyError, TypeError, AttributeError):
            return
        self._append(
            {
                "kind": "usage",
                "id": identifier,
                "input_tokens": inp,
                "output_tokens": out,
                "cost_nano": cost,
                "cost_bound_nano": (cost * 11 + 9) // 10,
            }
        )

    def summary(self, start: int = 0) -> dict:
        rows = self.attempts[start:]
        return {
            "model": MODEL,
            "maximum_usd": self.limit / NANO,
            "http_attempts": len(rows),
            "usage_complete": all("cost_nano" in row for row in rows),
            "input_tokens": sum(row.get("input_tokens", 0) for row in rows),
            "output_tokens": sum(row.get("output_tokens", 0) for row in rows),
            "usage_cost_usd": sum(row.get("cost_nano", 0) for row in rows) / NANO,
            "cost_upper_bound_usd": sum(
                row.get("cost_bound_nano", row["reserved_nano"]) for row in rows
            )
            / NANO,
            "unsettled_attempts": sum("cost_nano" not in row for row in rows),
        }
