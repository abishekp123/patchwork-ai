# Session handoff

Date: 2026-11-18 (America/Toronto). Scope: enforce a $1 evaluation budget,
securely load the root `.env`, and attempt the existing five live fixtures.
Started from `134a50a`; fixtures, expected outcomes, and Docker isolation unchanged.

## Current result

**Live model evaluation blocked by OpenAI `insufficient_quota`.** Four HTTP requests
were rejected; a fifth was prevented by the dollar guard. No successful inference,
evidence report, patch, or live Docker comparison was produced. Repair rate and
semantic evidence accuracy are N/A, not 0%. The pinned image and Docker were ready.

Reported-usage API cost: **$0.00**. Invoice-confirmed expenditure: **unknown**.
Conservative upper bound: **$0.93060**, within the authorized **$1.00**. No retry
was made after the blocked suite. The key was never printed or committed.

[Measured per-fixture timings and raw artifacts](evaluation-results/live-quota-blocked.md).
The original JSON is preserved: its COMPLETED status meant the loop finished.
A subsequent offline-tested fix now stops account-wide failures immediately,
sets BLOCKED, and marks remaining fixtures NOT_RUN.

## Implementation

- `evaluations/cost.py`: locked, append-only, fsynced dollar ledger; integer
  nanodollars; full-context reservations before every HTTP attempt including retries.
  Valid usage releases unused capacity; ambiguous failures retain full reservations.
  Journals survive restarts; concurrent owners/corruption/write failures fail closed.
- Only reviewed `gpt-6-luna`, Standard service, reasoning none, and explicit cache
  mode without breakpoints. No hosted paid tools. Pricing reviewed from official
  documentation on this date. The guard is independent of token estimates.
- `--env-file` loads only OPENAI_API_KEY without interpolation or logging.
  `--max-cost-usd` is bounded to $1. `--cost-ledger` shares one authorization across
  fixtures and reruns. Defaults do not permit a more expensive model fallback.
- Per-fixture reports now include stage outcomes, investigation/proposal when
  available, source-location validation, latency, and usage/cost accounting.
  Usage is captured before structured response parsing, including invalid decisions.
- Existing recovery, trusted dependency environments, and browser workflows remain
  intact; see [RELIABILITY](RELIABILITY.md).

## Executed checks

| Command | Result |
| --- | --- |
| `pytest backend/tests/test_evaluation_cost.py backend/tests/test_live_evaluation.py backend/tests/test_provider.py -q` | **48 passed** |
| `PATCHWORK_RUN_DOCKER_INTEGRATION=1 PATCHWORK_TEST_IMAGE=<trusted image ID> pytest backend/tests -q` | **210 passed**, zero failures/skips, 39.47s; includes ten real Docker tests |
| Frontend `npm run check` | **31 passed**; lint, formatting, TypeScript and production build passed |
| `ruff check backend scripts` | Passed |
| `ruff format --check backend scripts` | Passed; 83 Python files |

Use `backend/.venv/bin/pytest` and `backend/.venv/bin/ruff` from the project root.
The real Docker regression suite uses the reviewed pytest image, not a live model.
No browser rerun was needed for these backend-only changes; prior Chromium/WebKit
coverage remains eight passing tests from the preceding stage, not a new result.

## Retry requirements

Restore OpenAI project billing/quota first. The current authorization ledger is
`/tmp/patchwork-authorized-dollar-ledger.jsonl`; a sanitized copy is committed with
the report. It retains four unresolved reservations and **cannot authorize another
full-capacity request**. Do not delete/reset it to regain budget. Reconcile billing
and obtain renewed authorization before a new run. Then use the documented CLI
in [EVALUATION](EVALUATION.md), a fresh results directory, and an appropriately
reviewed authorization ledger. No automatic paid retry is scheduled.

Remaining limitations: live AI quality unmeasured; invoice costs unavailable;
source-location validity is not semantic evidence truth; per-ledger limits cannot
control other users of the key; rates require review before a future authorization.
Previous limitations remain: single-process local operation, reviewed dependency
images only, and six development-toolchain audit entries recorded last stage.
