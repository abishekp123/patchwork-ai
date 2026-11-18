# Session handoff

Date: 2026-11-18 (America/Toronto). Scope: final local validation, job recovery,
and controlled Python dependency environments. Started from verified `cfe5ff6`;
existing history and Docker isolation were preserved.

## Implemented

- Single API owner per canonical SQLite database path via OS lock (including symlink aliases). Startup atomically fails
  interrupted investigations/verifications, preserves partial evidence/results,
  and cleans only database-owned containers and temporary children. Docker must
  be restored before orphan cleanup can proceed. No automatic paid/execution
  replay; explicit retry produces a new attempt.
- Idempotent cancellation and immutable terminal records, duplicate investigation
  prevention, graceful shutdown handling, and clear UI interruption/retry text.
  Tests kill real owner processes, verify lock recovery, and remove real orphan
  containers. SQLite loss during shutdown is logged without masking cleanup.
- Trusted pytest image built from a digest-pinned Python base and reviewed,
  hash-locked wheels. Installation happens during an offline image build;
  runtime networking/install remain disabled. Configured image identities must
  be immutable and are persisted on verification records (migration 3).
- Playwright Chromium/WebKit tests use an explicitly enabled test-only server,
  local Git fixtures, deterministic model responses, real services, and real
  Docker. Production has no testing routes or model substitution. Fixed file
  button accessibility semantics and the hidden active-verification cancel button.
- Actual browser screenshots are in `docs/screenshots`. The simulated model is
  labeled in the UI and README; these are not live AI performance evidence.

## Exact verification evidence

| Check | Result |
| --- | --- |
| Full backend, Docker enabled | **183 passed, 0 failed, 0 skipped** (33.06s) |
| Focused Docker + verification tests | **30 passed** (includes 10 real Docker tests) |
| Fault/recovery + health/API focused run | **27 passed** |
| Frontend `npm run check` | **31 passed**, Oxlint/Prettier/TypeScript/build passed |
| Playwright Chromium + WebKit | **8 passed**, four per browser; no retries/skips |
| Ruff lint and format | Passed; 81 Python files formatted |
| `pip check` | No broken requirements |
| Live five-fixture AI evaluation | **NOT_RUN**; no credentials in environment or `.env`; zero provider calls |
| npm dependency audit | Six high-severity entries from dev-toolchain `picomatch` ReDoS chain; unresolved |
| CI | All four jobs passed for `90c7a14`: [run 44415888482](https://github.com/abishekp123/patchwork-ai/actions/runs/44415888482) |

Backend command from root (Docker CLI must be on PATH):

```sh
PATCHWORK_RUN_DOCKER_INTEGRATION=1 \
PATCHWORK_TEST_IMAGE="$PATCHWORK_VERIFICATION_IMAGE" \
  backend/.venv/bin/pytest backend/tests -q
```

The ordinary CI backend jobs intentionally skip the ten Docker tests. The Docker
job builds the reviewed image, executes all ten without skips, then runs both
browser projects sequentially. Do not overlap browser and Docker suites: existing
container-cleanup assertions observe all labelled test containers.

From `frontend/`, run `npm run check` and `npm run test:browser`. Browser evidence
covers import, keyboard file navigation, search, investigation states, evidence
and patch review, explicit approval, real Docker improvement, empty/loading/API
failure states, refresh persistence, and cancellation before results exist.
The workflow fixture fails one of two tests before repair and passes both afterward.
No imported Python executes on the host.

## Live evaluation command

The existing harness calls `OpenAIProvider.decide`, which sends strict function
calls to `https://api.openai.com/v1/responses` with bounded retries/timeouts and
usage metadata. Neither model investigations nor patch proposals were measured
against a real provider this session. Repair rate, failure rate, model latency,
and inference cost are **N/A**, not zero-percent results.

After securely exporting `OPENAI_API_KEY`, from `backend/`, with Docker/base image
ready, use a fresh output directory:

```sh
.venv/bin/python -m patchwork.evaluations.live --live --approve-fixtures \
  --output-dir /tmp/patchwork-live-20261118-new \
  --max-calls 40 --max-reserved-tokens 600000 --max-seconds 900
```

Recorded NOT_RUN reports are in `docs/evaluation-results`. See
[EVALUATION](EVALUATION.md) for consent and bounds, and
[RELIABILITY](RELIABILITY.md) for dependency-image setup and recovery semantics.

## Verdict and remaining work

**Ready as a software engineering portfolio demonstration of a local application**:
real browser/API/Docker integration and process-failure recovery are demonstrated.
It is not deployment-ready and its AI repair quality remains unmeasured.

- Run the real five-fixture evaluation with credentials before claiming model
  success rates. Browser tests intentionally use a deterministic provider.
- Resolve the reported development-toolchain advisory through a reviewed update;
  npm suggested major downgrades, which were not applied blindly. Development
  servers remain loopback-bound. No production-security readiness claim is made.
- One process/local database only; no multi-user authentication, global quotas,
  distributed execution, or durable resumption. Interrupted jobs require retry.
- Dependency support is the reviewed image/lock, not arbitrary projects or dynamic
  installs. Docker shares a kernel; output-based test summaries are not attestation.
- Recovery covers newly labelled resources. Legacy unowned temporary paths require
  manual review. Database corruption requires restoring usable storage.

Do not introduce broader deployment infrastructure without a new request.
