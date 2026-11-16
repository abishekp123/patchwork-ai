# API contracts

## `GET /health`

No request body or authentication. `Content-Type: application/json` and
`Cache-Control: no-store`. This checks the running API and basic access to the
configured SQLite schema. It does not run a write test or full integrity scan.

HTTP **200**:

```json
{
  "status": "ok",
  "service": "patchwork-ai",
  "version": "0.1.0",
  "checks": { "database": "ok" }
}
```

HTTP **503**, if SQLite fails after startup:

```json
{
  "status": "degraded",
  "service": "patchwork-ai",
  "version": "0.1.0",
  "checks": { "database": "error" }
}
```

`service` is constant; `version` is a nonempty application version string.
Database errors are logged server-side without exposing paths or exceptions in
the response. Startup failure prevents the server from accepting requests.
Missing database files are not recreated by health requests.

The frontend requests `/api/health`; the local proxy removes `/api`. It accepts
only the documented status/body combinations, tolerates extra JSON fields,
aborts requests after five seconds, and allows manual retry. There is no polling.
An HTTP 503 with a valid body shows a degraded service; connection failures,
timeouts, invalid bodies, and other HTTP statuses show an unavailable API.

FastAPI serves generated OpenAPI at `/openapi.json` and interactive docs at
`/docs`. Update the Pydantic models, frontend validator, and tests together when
changing this contract. No repository or investigation endpoints exist yet.
