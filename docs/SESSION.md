# Session handoff

Date: 2026-11-17 (America/Toronto). Scope: verification hardening, real Docker CI,
and opt-in AI repair evaluation. Existing `master` history preserved; no new
repository or speculative milestone work.

## Implemented

- Public verification requests and environment settings accept only Docker.
  Fake adapters require direct test injection. Missing daemon/image returns 503;
  invalid/unequal commands return 422; unapproved patches remain blocked with 409.
- Docker preflight checks CLI, daemon, and pinned image. Infrastructure failures
  are INCONCLUSIVE. Worker threads keep the event loop responsive; cancellation
  and graceful shutdown wait for bounded container cleanup.
- Native Linux revealed a host-mount permission defect hidden by Docker Desktop.
  Disposable readable mount children now sit under private mode-0700 parents;
  the runner is mounted read-only and daemon bookkeeping is not exposed.
  Non-root UID 65532, no networking/capabilities, read-only root, resource limits,
  timeouts, bounded output, and container cleanup remain enforced.
- Dedicated Ubuntu amd64 Docker CI pulls the existing multi-platform digest and
  requires at least eight executed tests with zero skips. Includes confinement,
  timeout, five known-repair fixture oracles, and HTTP approval/restart coverage.
- Separate live evaluation CLI uses real investigation and patch providers, source
  evidence validation, explicit fixture approval, and actual Docker comparison.
  Five fixtures, one patch attempt each, shared call/token/time budgets, and
  checkpointed JSON/Markdown reports. See [EVALUATION](EVALUATION.md).
- Fixed Vite routing: `/api/health` maps to `/health`; other API prefixes remain.
  Historical fake verification records are visibly labeled simulated.

## Executed validation

Local: macOS Apple Silicon, Python 3.14, Docker Desktop arm64; frontend Node 26.
Commands below are from project root unless specified otherwise.

| Command/check | Actual result |
| --- | --- |
| `PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH" PATCHWORK_RUN_DOCKER_INTEGRATION=1 backend/.venv/bin/pytest backend/tests -q` | 168 passed, 0 failed, 0 skipped |
| Explicit Docker suite alone | 8 passed, 0 failed, 0 skipped |
| `backend/.venv/bin/ruff check backend` | Passed |
| `backend/.venv/bin/ruff format --check backend` | 77 files formatted |
| `backend/.venv/bin/python -m pip check` | No broken requirements |
| `npm run check` in `frontend/` | 31 tests passed; lint, formatting, TypeScript, build passed |
| `backend/.venv/bin/python -m patchwork.evaluations` | Seven offline checks true; fake provider, no execution |
| Live evaluation with explicit consent | NOT_RUN, zero provider calls: no API key in environment or local `.env` |
| GitHub Actions | [Implementation dc907e5: all four jobs passed](https://github.com/abishekp123/patchwork-ai/actions/runs/44227188964), including real Docker amd64 |

The ordinary backend CI jobs intentionally skip eight opt-in Docker cases; the
separate Docker job executes them. Known-repair oracle successes are **not** live
AI successes. The recorded [live JSON](evaluation-results/live-not-run.json) and
[Markdown](evaluation-results/live-not-run.md) contain all five NOT_RUN cases.

## Actual local application checks

Started Uvicorn and Vite using an isolated temporary database and a test-only
local Git transport dependency. Through the actual Vite HTTP proxy:

- Frontend HTML and health returned 200; dashboard, provider/sandbox status routes
  also returned 200. Controlled local Git import returned 201/ready; indexed
  `repair` source search returned precise symbols and snippets.
- Missing provider credentials returned 503 without creating a fake investigation.
  Offline tests cover state-machine and provider-response behavior.
- A clearly labeled known fixture patch was blocked before approval (409), then
  explicitly approved through HTTP. Docker baseline: 0/3 passed; patched: 3/3
  passed; persisted result IMPROVED. This was not an AI-generated repair.
- Dashboard API showed one approved patch and one completed verification. A real
  backend process restart preserved the result and activity. Docker integration
  tests independently exercise approval and app-instance restart persistence.
- Browser automation was attempted but failed with an internal `timeoutMs`
  connection error. HTML delivery and React tests passed; no visual browser or
  interactive user-flow pass is claimed. No live-model test occurred.

## Remaining limitations and next work

Verdict: **core working prototype**, with locally validated Docker/API workflow.
It is not deployment-ready or a measured real-world AI repair system.

1. Supply credentials and run the opt-in live suite in a fresh output directory;
   review generated diffs and failures before making model-quality claims.
2. Complete an interactive browser review when automation works. UI default
   pytest execution needs a reviewed dependency-image strategy: the current
   pinned image contains standard-library Python, not pytest/project packages.
3. Before deployment: authentication/authorization, durable workers, crash/orphan
   recovery for active verification, global quotas, and stronger hostile-code
   isolation. Completed records persist, but active work is not durably resumed.
4. Container output is not tamper-proof test attestation. These small fixtures do
   not prove general patch correctness; Docker shares the daemon/kernel.

Do not begin broader production infrastructure without authorization. Local
validation data and databases remain outside the repository and are not committed.
