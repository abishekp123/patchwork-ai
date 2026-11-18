# Repair evaluation

Three separate checks answer different questions:

| Command (from `backend/`) | Provider | Execution | Meaning |
| --- | --- | --- | --- |
| `python -m patchwork.evaluations` | Deterministic fake | None | Workflow plumbing |
| `PATCHWORK_RUN_DOCKER_INTEGRATION=1 pytest tests/test_docker_integration.py` | None; known repairs | Real Docker | Sandbox and fixture correctness |
| `python -m patchwork.evaluations.live --live --approve-fixtures --output-dir /tmp/new-run` | Real OpenAI Responses API | Real Docker | Measured AI repair outcomes |

Use `.venv/bin/python` / `.venv/bin/pytest` in the local environment. The live
command requires an exported `OPENAI_API_KEY`, Docker, and the pinned image from
README. It never loads keys from a file or substitutes a fake provider. Missing
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
is recorded separately; failed/ambiguous requests mark usage incomplete. No cost
estimate is fabricated. Existing provider retries are bounded to appropriate
transient responses; there are no harness-level repair retries.

CLI options `--model`, `--max-calls`, `--max-reserved-tokens`, and `--max-seconds`
configure global limits. Call/token reservations occur before dispatch. Provider
and investigation deadlines apply within each case. Cancellation waits for the
current bounded Docker worker to clean up before removing snapshots; elapsed time
can exceed the investigation deadline by that command's remaining timeout and
bounded cleanup grace. No additional command starts after cancellation.

Use a fresh output directory for every execution. `results.json` and `results.md`
checkpoint per case. `evaluation.db` retains investigations, evidence, approved
patches, and verification records for audit. Reports contain stage flags,
identifiers, evidence references, test summaries, errors, duration, model, usage,
and limits; arbitrary provider exception payloads/credentials are not included.
Exit code 0 requires all five cases to be successful repairs; a completed suite
with failures still exits 1. Do not commit local databases or credentials.

## Recorded result and limits

The [recorded live run](evaluation-results/live-not-run.md) is **NOT_RUN**:
credentials were unavailable. All five known-repair oracles passed real Docker
checks locally; this validates the dataset, not AI repair quality.

Fixture success is not general correctness. Test counts come from bounded process
output, not tamper-proof attestation; adversarial code can spoof output. Docker
shares a kernel and is not a hostile multi-tenant isolation guarantee. The pinned
standard-library image has no pytest or third-party project dependencies. Broader
repositories, dependency provisioning, model-quality measurements, authentication,
durable workers, and crash recovery for active verification remain future work.
