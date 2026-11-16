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
{"error":{"code":"invalid_revision","message":"The commit is unavailable in this repository.","repository_id":null,"details":[]}}
```

A persisted failure includes its repository ID. Request validation returns
`validation_error` with location/message/type details, without echoing input.
Status codes: 404 missing snapshot/revision; 409 busy/not-ready/lost claim;
413 resource limit; 422 invalid input/revision/query; 502 upstream unavailable;
503 storage/Git unavailable; 504 deadline; 500 unexpected indexing failure.
Upstream stderr and local paths stay server-side. HTTP errors use the same envelope.
No authentication or public deployment is provided in this milestone.
