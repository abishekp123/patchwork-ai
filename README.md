# Patchwork AI

A platform for AI-assisted code investigation and verified repair.
**Milestone 1 implements the foundation only:** a FastAPI API, local SQLite
connectivity, and a React dashboard showing real service health. Repository
import, AI agents, and isolated execution are not implemented yet.

## Requirements

- Python 3.12+ (CI targets 3.12 and 3.14)
- Node.js 24 or 26 and npm (CI targets Node 24)
- Git; the commands below use a macOS/Linux shell

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

Open **http://127.0.0.1:5173**. The page fetches `/api/health`; Vite proxies it
to the backend's `/health`. Use **Refresh status** to check again. API docs are at
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
Startup creates its parent directory and an empty SQLite database; no domain
tables exist yet. `PATCHWORK_API_PROXY_TARGET` defaults to
`http://127.0.0.1:8000`. Restart Vite after changing it. Do not put secrets in
`VITE_*` variables: Vite exposes those to the browser.

If the dashboard cannot connect, check the backend terminal and direct health
URL, then the proxy target. An invalid database prevents startup; a database
that becomes unavailable after startup returns HTTP 503. Ports are fixed so a
conflict fails visibly instead of silently selecting another port.

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

To inspect the built frontend, run `npm run preview` in `frontend/` and open
http://127.0.0.1:4173 with the backend still running. Preview includes the local
API proxy. A future production server must serve the static build and route
`/api/*` to the API; Vite's development/preview servers are not production hosting.

## Layout and documentation

- `backend/src/patchwork/`: application assembly, configuration, routes, schemas, SQLite
- `frontend/src/`: API client, health feature, React presentation
- [Architecture](docs/ARCHITECTURE.md) · [API contracts](docs/CONTRACTS.md)
- [Decisions](docs/DECISIONS.md) · [Roadmap](docs/ROADMAP.md)
- [Session handoff](docs/SESSION.md) · [Agent instructions](AGENTS.md)
