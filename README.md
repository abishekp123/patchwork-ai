# Patchwork AI

A platform for AI-assisted code investigation and verified repair.
Milestones 1–5 and the integrated developer workspace are implemented: browse
immutable repository snapshots, search indexed source, investigate with cited
evidence, propose and review patches, and compare approved patches using isolated
verification. A persisted dashboard summarizes workspace activity; an offline
evaluation command exercises the investigation-to-approval flow without an API
key. Imported repository code is never executed on the host.

The backend owns indexing, investigation orchestration, deterministic patch
validation, review state, verification, and persistence. Live investigation and
patch generation require `OPENAI_API_KEY`; missing credentials are surfaced
explicitly and never replaced with fake provider output. Fake providers and fake
sandbox execution are test-only paths. Runtime verification requires the
configured Docker sandbox and fails closed if it is unavailable.

## Requirements

- Python 3.12+ (CI targets 3.12 and 3.14)
- Node.js 24 or 26 and npm (CI targets Node 24)
- Git 2.30+ on PATH; the backend targets macOS/Linux (POSIX process control)

## Install

From the repository root:

```sh
cp .env.example .env
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
cd ../frontend
npm ci
cd ..
```

The Python lock includes development tools; `pyproject.toml` declares direct
runtime and development dependencies. The frontend uses `package-lock.json`.
To intentionally refresh Python dependencies, use a fresh virtual environment,
install `-e '.[dev]'`, then regenerate the lock with
`python -m pip list --format=freeze --exclude patchwork-ai-backend --exclude pip`.
Review dependency changes and run checks before committing either lock.

## Run locally

Terminal 1, from the repository root:

```sh
cd backend
.venv/bin/uvicorn patchwork.main:create_app --factory --reload --host 127.0.0.1 --port 8000 --env-file ../.env
```

Terminal 2, from the repository root:

```sh
cd frontend
npm run dev
```

Open **http://127.0.0.1:5173** to browse repositories, investigate indexed
source, propose patches, review them, and view persisted activity and
verification results. Vite proxies `/api/*` to the backend. API docs are at
http://127.0.0.1:8000/docs. Stop either server with Ctrl+C.

```sh
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:5173/api/health
```

Both return:

```json
{"status":"ok","service":"patchwork-ai","version":"0.1.0","checks":{"database":"ok"}}
```

Configuration lives in the ignored root `.env`. `PATCHWORK_DATABASE_PATH`
defaults to `data/patchwork.db`, relative to the backend working directory.
Startup creates its parent directory and applies transactional SQLite migrations.
Existing Milestone 1 databases upgrade automatically; back up persistent data
before upgrades. `PATCHWORK_API_PROXY_TARGET` defaults to
`http://127.0.0.1:8000`. Restart Vite after changing it. Do not put secrets in
`VITE_*` variables: Vite exposes those to the browser. Set `OPENAI_API_KEY` in
the root `.env` to enable live model-backed investigation and patch generation.
There is no automatic offline/fake fallback when the key is missing.

To enable the review UI's runtime verification action, configure
`PATCHWORK_SANDBOX_MODE=docker`, ensure Docker is available, and pre-pull the
pinned sandbox image described in the Docker integration section. Requests
default to Docker execution; the API does not silently substitute fake results.
Fake mode is rejected by HTTP requests and environment configuration. Test code
can inject a fake adapter directly; historical simulated results are labeled in the UI.

If the dashboard cannot connect, check the backend terminal and direct health
URL, then the proxy target. An invalid database prevents startup; a database
that becomes unavailable after startup returns HTTP 503. Ports are fixed so a
conflict fails visibly instead of silently selecting another port.

## Import and search a repository

With the backend running:

```sh
curl --fail-with-body http://127.0.0.1:8000/api/repositories \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://github.com/pallets/markupsafe","commit_sha":"4e111271b1494995708a9e878a10829b5e10c7ba"}'
```

Omit `commit_sha` to resolve the default branch. The response includes the immutable
commit and repository snapshot `id`. Use that ID in `/docs` to try the files,
imports, symbols, and search endpoints, or replace `SNAPSHOT_ID` below:

```sh
curl --fail 'http://127.0.0.1:8000/api/repositories/SNAPSHOT_ID/symbols?name=Markup'
curl --fail 'http://127.0.0.1:8000/api/repositories/SNAPSHOT_ID/search?q=escape&limit=10'
```

Imports run synchronously. Repeating a ready URL/SHA returns the existing index.
Only public HTTPS GitHub URLs are supported; imported code is never checked out
or executed. Read-only bare snapshots default to
`~/.local/share/patchwork-ai/repositories`, outside the application tree. An
existing override directory must be private (mode 0700). `.env.example` documents
all limits: by default 60 seconds per Git command, 120 seconds per ingestion,
50 MB fetched/expanded repository, 512 KB per Python file, 10 MB indexed source,
2000 Python files, 20000 tree entries, 50000 symbols/imports, 100 results, and
300-character snippets. Limits use bytes, not MiB. Oversized individual Python
files are skipped; aggregate-limit violations fail the import. See
[contracts](docs/CONTRACTS.md) for skipped-content, error, and ranking semantics.

Storage limits apply per import, not globally. Failed requests clean up their own
files; process crashes can leave orphan directories for manual cleanup while the
API is stopped. No automatic deletion/garbage collection or public hosting is
provided. Completed snapshots and database data persist across restarts.

## Checks

From `backend/`:

```sh
.venv/bin/python -m pip check
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

From `frontend/`:

```sh
npm run check
```

The frontend check runs Oxlint, Prettier, Vitest, TypeScript, and a Vite
production build. Use `npm run test:watch` during development. Format with
`.venv/bin/ruff format .` in `backend/` and `npm run format` in `frontend/`.
GitHub Actions runs the same checks on pushes to `master` and pull requests.
Backend integration tests create small temporary Git repositories; core tests
never depend on GitHub network access or an LLM key.

### Offline workflow evaluation

Run the deterministic evaluation from `backend/`:

```sh
.venv/bin/python -m patchwork.evaluations
```

It uses a fake provider and a temporary SQLite database to check investigation
completion, evidence citation, source-validated patch generation, persistence,
human approval, and indexed-snapshot immutability. It needs no API key or Docker
daemon, does not execute repository code, and does not represent live model
quality or real sandbox execution.

### Opt-in Docker sandbox integration tests

The normal backend suite does not start Docker. To run the separate real-container
checks, first ensure Docker Desktop/Engine is running and pull the pinned,
multi-architecture image outside the sandbox (native amd64 on Linux CI, arm64
on Apple Silicon):

```sh
docker pull \
  python@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
cd backend
PATCHWORK_RUN_DOCKER_INTEGRATION=1 \
  .venv/bin/python -m pytest -m docker_integration -q tests/test_docker_integration.py
```

If Docker Desktop's bundled CLI is not on `PATH`, prepend
`/Applications/Docker.app/Contents/Resources/bin` before the `docker pull`
command. The fixture tests add that path automatically on macOS. Their host-side
runner uses pytest; the container fixture uses only Python's standard-library
`unittest`, so it installs no dependencies.

The test manifest pins every locally authored fixture by SHA-256. The tests
exercise a deliberately failing arithmetic test and its approved repair, runtime
isolation (non-root, no network, read-only root, dropped capabilities,
no-new-privileges, CPU/memory/PID limits), bounded output, timeout, cleanup, and
snapshot immutability. They do not download packages or run public repositories.
Fake-adapter unit tests remain separate and do not count as Docker integration
coverage. Explicitly enabling the suite makes missing Docker/image prerequisites
a failure, not a skip. The dedicated Linux amd64 CI job requires at least eight
executed tests and zero skips. The suite also checks five repair fixture oracles
and the HTTP approval/verification/restart flow. It never substitutes fake execution.

### Opt-in real AI repair evaluation

This is separate from the offline evaluation and Docker oracle tests. With
`OPENAI_API_KEY` exported and Docker/image ready, from `backend/`:

```sh
.venv/bin/python -m patchwork.evaluations.live --live --approve-fixtures \
  --output-dir /tmp/patchwork-live-run
```

Use a fresh output directory. The approval flag authorizes only the five built-in
fixtures after deterministic patch/evidence validation. JSON, Markdown, and SQLite
traces distinguish generated, validated, approved, Docker-tested, and successful
repairs. No key means **NOT_RUN**, never fake success. The CLI does not load `.env`;
credentials must be in the process environment. See [evaluation policy and
limits](docs/EVALUATION.md). Live model quality has not yet been measured.

The pinned image contains Python's standard library, not pytest or third-party
project dependencies. The allowlisted fixture `unittest` command is validated;
generic pytest verification requires a separately reviewed dependency-image
strategy. The sandbox never installs packages or enables networking automatically.

To inspect the built frontend, run `npm run preview` in `frontend/` and open
http://127.0.0.1:4173 with the backend still running. Preview includes the local
API proxy. A future production server must serve the static build and route
`/api/*` to the API; Vite's development/preview servers are not production hosting.

## Layout and documentation

- `backend/src/patchwork/`: typed API/schemas, ingestion, indexed retrieval,
  investigation and patch workflows, isolated verification, evaluation, and storage
- `frontend/src/`: API client and React workspace, patch-review, and verification UI
- [Architecture](docs/ARCHITECTURE.md) · [API contracts](docs/CONTRACTS.md)
- [Decisions](docs/DECISIONS.md) · [Roadmap](docs/ROADMAP.md)
- [Session handoff](docs/SESSION.md) · [Agent instructions](AGENTS.md)
