# API contracts

## Health (unchanged)

`GET /health` returns HTTP 200:

```json
{"status":"ok","service":"patchwork-ai","version":"0.1.0","checks":{"database":"ok"}}
```

SQLite failure after startup returns HTTP 503 with `status: "degraded"` and
`checks.database: "error"`. Responses are JSON with `Cache-Control: no-store`.
Startup validates/migrates SQLite before serving requests. The check reads schema
metadata, not full integrity/write capacity. Vite forwards `/api/health` here.

## Repository snapshots

Canonical backend routes follow `/api/repositories`. Identical `/repositories`
aliases support the existing Vite proxy and are omitted from OpenAPI. Generated
schemas/examples are available at `/openapi.json` and `/docs`.

| Method and route | Behavior |
| --- | --- |
| `POST /api/repositories` | Synchronous import/index; 201 newly indexed, 200 reused |
| `GET /api/repositories` | Paginated snapshots, including pending/failed attempts |
| `GET /api/repositories/{id}` | Status, pinned revision, counts, timestamps, errors |
| `GET /api/repositories/{id}/files` | Paginated indexed file metadata and hashes |
| `GET /api/repositories/{id}/symbols` | Paginated symbols, optional exact name lookup |
| `GET /api/repositories/{id}/imports` | Paginated literal import records |
| `GET /api/repositories/{id}/search` | Ranked, bounded lexical search |

Import request (extra fields rejected):

```json
{"url":"https://github.com/pallets/markupsafe","commit_sha":"4e111271b1494995708a9e878a10829b5e10c7ba"}
```

Omit `commit_sha` to resolve the current default HEAD. Only full 40-hex-character
SHA-1 values are accepted; branches, tags, abbreviated hashes, and revision
expressions are not. Owner/name and SHA are normalized to lowercase; optional
`.git` and a trailing slash are accepted. Credentials, ports, non-GitHub hosts,
query strings, local paths, SSH, and other schemes are rejected.

Response: `{ "repository": Repository, "reused": boolean }`. `Repository` has:
`id` (64 hex characters), `normalized_url`, `commit_sha`, `status`
(`indexing|ready|failed`), UTC `created_at`, `updated_at`, `indexed_at`,
`index_version`, `file_count`, `symbol_count`, `import_count`, `skipped` reason
counts, and nullable `error_code`/`error_message`. Commit is nullable only for
failures before default HEAD could be resolved. Timestamps and surrogate row IDs
are bookkeeping, not deterministic extraction output. No storage paths or lease
secrets are exposed. Repeating a ready pinned import is network-free and preserves
its timestamps/rows. An unpinned repeat must resolve HEAD again.

Files/symbols/imports/list pages use `limit` (default 20, 1–500) and `offset`
(default 0, 0–100000), returning `{items,total,limit,offset}`. The effective limit
is additionally clamped to `PATCHWORK_MAX_RESULTS`. Indexed retrieval requires a
ready snapshot (otherwise 409). Optional `commit_sha` on indexed retrieval must
match the snapshot (otherwise 404); repository IDs already isolate revisions.

Symbols accept `name` and `exact` (default true). Exact matching is case-sensitive
on simple or qualified names; false uses casefolded substrings. No match returns
an empty 200 page. Entries include IDs, relative POSIX paths, names/kinds,
qualified lexical names/parent labels, async flags, inclusive one-based line
ranges, UTF-8 byte ranges (end exclusive), signatures, decorators, and syntax
error flags. Modules use their file path as qualified name, without guessing the
runtime package layout. Decorated declarations start on `def`/`class`, not `@`.
Byte offsets refer to decoded source re-encoded as UTF-8; hashes cover original
blob bytes. Imports retain module text, relative-dot count, imported name/alias,
lexical scope, statement text, and locations; they do not assert resolution edges.
Signatures/decorators are bounded to 512 characters; import statements to 2000.

## Search ranking

`GET .../search?q=escape&limit=20` accepts a nonblank query up to 200 characters.
Matching is literal Unicode casefolded substring matching, with no regex or SQL
wildcard semantics. Results rank in this order (lower rank is better):

0. Exact simple or qualified symbol name.
1. Symbol-name or qualified-name prefix.
2. Other symbol-name/qualified-name substring.
3. Exact file path.
4. File-path prefix.
5. Other file-path substring.
6. Source-line substring.

Ties use path, declaration byte/line order, then row ID. The same source location
may appear in different categories. Source scan covers only indexed Python files,
bounded at ingestion; it stops once enough results establish truncation. Response:
`{repository_id,commit_sha,query,results,limit,truncated}`. Hits include `kind`,
`path`, one-based `start_line`/`end_line`, bounded `snippet`, `rank`, and nullable
symbol ID/name/qualified name. Source/path hits cover one line; symbol ranges span
the declaration but their snippet shows the declaration's first line. Snippets
are capped by `PATCHWORK_MAX_SNIPPET_CHARS`; long lines are cropped around a match
when present. This is lexical retrieval, not semantic relevance scoring.

## Errors

```json
{"error":{"code":"invalid_revision","message":"The commit is unavailable in this repository.","repository_id":null,"request_id":"trace-42","details":[]}}
```

A persisted failure includes its repository ID. Request validation returns
`validation_error` with location/message/type details, without echoing input.
Status codes: 404 missing snapshot/revision; 409 busy/not-ready/lost claim;
413 resource limit; 422 invalid input/revision/query; 502 upstream unavailable;
503 storage/Git unavailable; 504 deadline; 500 unexpected indexing failure.
Upstream stderr and local paths stay server-side. HTTP errors use the same envelope.
No authentication or public deployment is provided in this milestone.

Every response includes `X-Request-ID`. A caller-provided ID is accepted only if it
matches `[A-Za-z0-9._-]{1,64}`; otherwise the server generates one. Error envelopes
include the same value as `error.request_id`. Request logs use route templates and
omit query strings.

## Workspace, investigations, and patches

| Method and route | Behavior |
| --- | --- |
| `GET /api/dashboard` | Persisted workspace counts and up to 12 recent investigation, patch, and verification records |
| `GET /api/investigations/provider-status` | Reports whether the configured OpenAI provider is available |
| `POST /api/investigations` | Creates a persisted investigation and returns immediately while a local background task runs |
| `GET /api/investigations` | Paginated history; optional `repository_id` filter |
| `GET /api/investigations/{id}` | Persisted investigation state and reviewed report |
| `GET /api/investigations/{id}/steps` | Paginated orchestration trace |
| `POST /api/investigations/{id}/cancel` | Requests cancellation of a running investigation |
| `POST /api/patches` | Generates a source- and evidence-validated patch proposal |
| `GET /api/patches` and `GET /api/patches/{id}` | List and retrieve persisted patches |
| `POST /api/patches/{id}/approve` | Human approval; only pending patches can transition |
| `POST /api/patches/{id}/reject` | Human rejection; only pending patches can transition |

Investigation and patch generation require `OPENAI_API_KEY`; missing credentials
return an explicit provider error. Patch creation from an investigation requires
a completed report and evidence IDs cited by that report from the same immutable
repository snapshot. Patch validation rejects unsafe, stale, unsupported, or
no-op changes before persistence. Approval/rejection conflicts return 409.
Investigation tasks are process-local: persisted records survive restarts, but
there is no durable task queue or automatic resume.

## Verification

| Method and route | Behavior |
| --- | --- |
| `POST /api/patches/{id}/verifications` | Starts asynchronous verification of an approved patch; request mode defaults to `docker` |
| `GET /api/patches/{id}/verifications` | Paginated verification history for a patch |
| `GET /api/verifications/{id}` | Persisted lifecycle and summaries |
| `GET /api/verifications/{id}/results` | Persisted deterministic comparison result |
| `POST /api/verifications/{id}/cancel` | Cancels a running verification where possible |
| `GET /api/verification/sandbox-status` | Reports configured sandbox availability and policy failures |

Only approved patches tied to the same ready repository snapshot can be run.
Baseline and patched versions use independent snapshots and the same allowlisted
command. Docker is the runtime default and fails closed on unavailable or unsafe
configuration. `sandbox_mode` accepts only `"docker"`; `"fake"` returns 422.
The application setting also accepts only Docker. Fake adapters require explicit
in-process test injection and cannot be enabled by API callers. Readiness checks
the daemon and pinned image; unavailable runtime verification returns 503 before
creating a run. Unsupported or unequal commands return 422 before creating a run.
Concurrent active verification requests for one patch return 409. Results are
classified as `IMPROVED`, `REGRESSED`, `UNCHANGED`, `FAILED`, or `INCONCLUSIVE` according to
backend summaries. Timeouts/infrastructure errors are INCONCLUSIVE, never an
improvement. UNCHANGED means both commands passed, not that a repair was proved.
`SANDBOX_UNAVAILABLE` remains a response enum for compatibility. The frontend displays
persisted backend responses rather than synthesizing progress or test outcomes.

The offline command `.venv/bin/python -m patchwork.evaluations` exercises the
investigation-to-approval path with deterministic fake responses and temporary
storage. It does not call an external provider, execute indexed code, or perform
Docker verification.


Verification cancellation and graceful shutdown wait for bounded Docker worker
cleanup; they do not abandon a mounted snapshot. Cancellation can therefore take
up to the current command timeout plus Docker cleanup grace. Historical fake-mode
records remain readable and are explicitly labeled simulated by the review UI.
The opt-in live evaluation is a CLI, not a new public API; its consent, budgets,
and report schema are documented in [EVALUATION](EVALUATION.md).
