# Repair evaluation

Three separate checks answer different questions:

| Command (from `backend/`) | Provider | Execution | Meaning |
| --- | --- | --- | --- |
| `python -m patchwork.evaluations` | Deterministic fake | None | Workflow plumbing |
| `PATCHWORK_RUN_DOCKER_INTEGRATION=1 pytest tests/test_docker_integration.py` | None; known repairs | Real Docker | Sandbox and fixture correctness |
| `python -m patchwork.evaluations.live --live --approve-fixtures --output-dir /tmp/new-run` | Real OpenAI Responses API | Real Docker | Measured AI repair outcomes |

Use `.venv/bin/python` / `.venv/bin/pytest` in the local environment. The live
command requires `OPENAI_API_KEY` (exported or explicitly loaded using
`--env-file ../.env`), Docker, and the pinned image from README. Only the key is
loaded, without interpolation or logging; no fake provider is substituted. Missing
prerequisites produce JSON/Markdown **NOT_RUN** reports and exit code 1. The
standard tests require neither credentials nor paid calls.

## Fixtures and approval policy

`evaluations/fixtures.py` contains five deterministic, locally authored Python
source/test pairs: arithmetic, inclusive range, boolean conjunction, dictionary
fallback, and conversion exception handling. Tests use only `unittest`. The index
uses a synthetic content-derived revision and isolated SQLite database; it does
not claim these fixtures were fetched from GitHub. Source strings are parsed and
validated on the host, never executed there.

Each case runs the real investigation loop, requires validated source evidence,
generates one patch, and passes existing path/hash/syntax/evidence validation.
Only `subject.py` may change; test edits, fabricated evidence, and no-ops fail.
There is no hidden expected repair in the live provider context. Known repairs
exist only in the deterministic tests.

`--approve-fixtures` is explicit consent to approve generated changes **only for
these built-in disposable fixtures**, after validation. Approval is persisted
with reviewer `opt-in-fixture-evaluator` and the policy text. This is evaluation
consent, not human review of each diff, and does not change the application's
production approval requirement. Without it the live suite does not start.

Verification uses the same allowlisted command on both snapshots:
`python -m unittest discover -v -p 'fixture_test_*.py'`. All Docker security
controls remain enabled. A successful repair requires Docker COMPLETED/IMPROVED,
a nonzero baseline with observed test failures, a zero patched exit, exactly the
expected test count (3, 3, 4, 3, 3), no skipped tests, and no infrastructure errors.
Generated, validated, approved, and Docker-tested are distinct report flags;
none alone is a successful repair.

## Bounds and artifacts

Defaults: five cases; one patch attempt each; eight logical model calls per case,
40 total; 600,000 reserved tokens; 180 seconds per case and 900 seconds globally;
20 seconds per Docker command; 8 KiB combined bounded command output. Each model
call reserves UTF-8 context/tool bytes, an instruction margin, and output capacity
for all three maximum provider HTTP attempts. These reservations are conservative
estimates, **not exact token counts**. Actual provider-reported input/output usage
is recorded separately; failed/ambiguous requests mark usage incomplete. A separate dollar ledger enforces the monetary limit described below. Existing provider retries are bounded to appropriate
transient responses; there are no harness-level repair retries.

CLI options `--model`, `--max-calls`, `--max-reserved-tokens`, and `--max-seconds`
configure execution limits. `--max-cost-usd` accepts values greater than zero and
no greater than $1; `--cost-ledger` selects the shared durable authorization ledger. Call/token reservations occur before dispatch. Provider
and investigation deadlines apply within each case. Cancellation waits for the
current bounded Docker worker to clean up before removing snapshots; elapsed time
can exceed the investigation deadline by that command's remaining timeout and
bounded cleanup grace. No additional command starts after cancellation.

Use a fresh output directory for every execution. `results.json` and `results.md`
checkpoint per case. `evaluation.db` retains investigations, evidence, approved
patches, and verification records for audit. Reports contain stage flags,
identifiers, evidence references, test summaries, errors, duration, model, usage,
and limits; arbitrary provider exception payloads/credentials are not included.
Account-wide quota/authentication failures stop remaining cases as NOT_RUN and
set the suite to BLOCKED. Dollar exhaustion and ledger failures also stop the suite.
Exit code 0 requires all five cases to be successful repairs; a completed suite
with failures still exits 1. Do not commit local databases or credentials.

## Recorded result and limits

The [latest actual attempt](evaluation-results/live-quota-blocked.md) was blocked
by provider quota, with four rejected HTTP requests and no successful inference.
The $1 guard prevented a fifth request. Reported-usage cost is $0; actual billed
expenditure is unknown, bounded conservatively by $0.93060. All model-quality
metrics are N/A. The older [NOT_RUN record](evaluation-results/live-not-run.md)
predates key configuration. Known-repair Docker oracles validate execution and
fixtures, not AI quality.

Fixture success is not general correctness. Test counts come from bounded process
output, not tamper-proof attestation; adversarial code can spoof output. Docker
shares a kernel and is not a hostile multi-tenant isolation guarantee. The pinned
standard-library image has no pytest or third-party project dependencies. Broader
repositories, model-quality measurements, authentication, and durable external
workers remain future work. A reviewed pytest dependency image and local startup
reconciliation are now available; see [RELIABILITY](RELIABILITY.md).

## Dollar enforcement and pricing assumptions

The reviewed model is `gpt-6-luna`, Standard service, reasoning disabled, and
explicit cache mode without breakpoints (no cache writes or reads). Only local
function tools are permitted; hosted paid tools are rejected before dispatch.
Prices and capacities were checked on 2026-11-18 against the official
[model page](https://developers.openai.com/api/docs/models/gpt-6-luna) and
[cache policy](https://developers.openai.com/api/docs/guides/prompt-caching).
Rates are $0.10/M input and $0.50/M output; long-context rates double input
and multiply output by 1.5 above 272K input tokens. Recheck prices before any
new authorization; unknown models are rejected, never silently substituted.

Before each HTTP attempt, including retries, `CostLedger` reserves the entire
1,050,000-token context capacity at the long-context input rate plus the requested
maximum output at the long-context output rate, with 10% regional headroom.
For the existing 2,000-output-token calls this is $0.23265. This uses documented
capacity rather than a guessed token count. Integer nanodollars avoid float drift.
The append-only journal is locked and fsynced before dispatch. A failed journal
write prevents further requests. Truncated/corrupt journals fail closed.

Valid response usage settles the reservation to the rate-calculated amount plus
headroom. Usage is recorded before structured-response validation, so malformed
or incomplete model decisions can still be accounted for. Missing/invalid usage,
timeouts, and ambiguous errors retain the full reservation across process restarts.
Unexpected cache activity or service tiers also retain the reservation.

The cap applies to this ledger's evaluation requests under the reviewed published
pricing, not other applications sharing the key, taxes, or an invoice guarantee.
A fresh results directory is required, but **reuse the same ledger for every retry
under the same authorization**. Do not delete it to regain budget. Only a new,
explicit authorization permits a new ledger. The current ledger has $0.93060
reserved and cannot authorize another full-capacity request.

Per-fixture JSON includes investigation completion, verified source-location
status, the report and validated proposal when available, provider usage/cost,
end-to-end elapsed time, and baseline/patched Docker summaries. Verified source
locations do not prove the truth of model interpretations; semantic evidence
accuracy requires a separately identified review. No such review is possible
when inference is blocked. API costs are derived from returned token usage and
published rates, not retrieved invoice totals.
