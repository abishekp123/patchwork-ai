# Architecture

## Implemented in Milestone 1

```text
React dashboard
  → typed fetch client: GET /api/health
  → Vite development/preview proxy (removes /api)
  → FastAPI: GET /health
  → short-lived SQLite connection: PRAGMA schema_version
```

- **Frontend:** React components render loading, healthy, degraded, and failure
  states. The health hook owns request cancellation and refresh; the API module
  owns HTTP handling, a five-second timeout, and runtime response validation.
- **API:** `main.py` assembles the application and startup lifecycle. `api/`
  owns HTTP behavior; `schemas/` owns public Pydantic models. OpenAPI exposes
  success and unavailable responses.
- **Configuration:** immutable settings are resolved once per app instance.
  Tests inject temporary paths; no global app or database opens during import.
- **Persistence:** standard-library SQLite, initialized at startup. Each health
  request opens and closes its own connection in FastAPI's synchronous worker
  thread. No domain tables or migration framework yet. The health check reads
  schema metadata; it does not prove write access, full integrity, or capacity.
- **Development boundary:** the browser uses same-origin `/api` URLs. Vite alone
  knows the backend target; no CORS middleware or browser-side server URL needed.

## Future boundaries (not implemented)

Repository intake will pin immutable source revisions and store repository and
bug-report metadata in SQLite. Code intelligence will combine ripgrep with
Tree-sitter syntax trees. Investigation orchestration will consume those tools
through explicit typed inputs/outputs and record evidence, steps, and proposals.

Verification will run untrusted code only in restricted disposable Docker
environments with resource/time limits, controlled network access, and no host
secrets. The API process must never execute imported code itself. Durable runs
and replayable traces come after the first synchronous workflow; queues and
alternate databases require demonstrated need. The dashboard will review
evidence, diffs, and verification results without owning orchestration logic.

Production hosting, authentication, authorization, rate limits, and deployment
operations are deferred. The current application binds to loopback for local use.
