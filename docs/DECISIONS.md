# Engineering decisions

1. **Small monorepo.** Independent Python and npm projects keep ownership clear
   without introducing workspace/build orchestration for two small components.
2. **Application factory and typed boundaries.** FastAPI/Pydantic define the
   contract; injected settings isolate tests. Strict TypeScript plus runtime
   validation prevents malformed server responses from appearing healthy.
3. **SQLite through the standard library.** Enough for initial persistence,
   with no ORM, migration tool, or artificial domain schema. Introduce versioned
   migrations with the first real tables. Connections are short-lived and closed.
4. **A meaningful health check.** Startup validates the database; `/health`
   checks schema access and returns 503 on failure. This is deliberately a basic
   dependency check, not a guarantee of full database health.
5. **Same-origin frontend requests.** Vite proxies `/api` locally. Production
   routing will follow the same URL contract, avoiding unnecessary CORS setup.
6. **Existing tooling.** Vite's React/TypeScript scaffold, Tailwind's Vite plugin,
   Oxlint/Prettier, Ruff, pytest, and Vitest. No component library is needed for
   the single status panel. Starlette's current TestClient uses `httpx2` in tests.
7. **Repeatable installs.** Commit npm's lock and a fully pinned Python development
   dependency snapshot. Direct dependencies remain declared in `pyproject.toml`.
   Refresh locks intentionally in clean environments and verify in CI.
8. **Scope and history.** Private repository, `master`, real implementation
   timestamps, and incremental commits. AI orchestration, authentication,
   queues, containers, and indexing remain future work.

Implementation references: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/),
[Vite guide](https://vite.dev/guide/), and
[Tailwind's Vite integration](https://tailwindcss.com/docs/installation/using-vite).
