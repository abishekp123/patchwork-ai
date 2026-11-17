# Architecture

## Implemented through Milestone 5 verification

```text
HTTP request → repository service → bounded Git plumbing → Python blob discovery
                               → Tree-sitter → transactional SQLite publication
HTTP retrieval → SQLite metadata / exact symbols / bounded lexical source search
Approved patch → immutable index → independent snapshots → restricted Docker
React review UI → verification lifecycle API → SQLite
```

- `api/` and `schemas/`: HTTP validation, response contracts, and consistent error
  envelopes. `/api/repositories` is canonical; unprefixed aliases support Vite's
  existing prefix-removing proxy. The frontend and `/health` contract are unchanged.
- `ingestion/`: accepts only public HTTPS GitHub URLs and full SHA-1 commits;
  resolves HEAD when omitted. Fetches depth-one bare snapshots, checks the fetched
  commit, and reads tree/blob objects without checkout. No imported Python is run.
- `intelligence/python.py`: deterministic syntax extraction into typed models.
  Records lexical nesting, declaration ranges, async flags, decorators, signatures,
  and literal imports. Recoverable syntax errors are visible on files/symbols.
- `repositories/service.py`: synchronous orchestration with explicit settings,
  deadlines, cleanup, and an injectable transport for offline tests. It can later
  be called by a worker without moving business logic into HTTP handlers.
- `repositories/store.py`: SQLite claims/leases, status, and atomic index publication.
  Snapshot identity is SHA-256 of normalized URL and pinned commit; each revision
  has its own record. Ready snapshots are immutable and reused without reindexing.
- `intelligence/search.py`: indexed exact symbol lookup, deterministic lexical
  ranking, and bounded source scanning. Retrieval reads persisted source, so it
  never opens user-supplied paths or runs tools inside a repository.
- `patches/` and `investigations/`: evidence-backed repair proposals are checked
  against a pinned SQLite snapshot and require human approval before verification.
  Unified diffs are applied only to a disposable patched snapshot; the published
  source index remains unchanged.
- `verifications/`: persist the run lifecycle and baseline/patched summaries.
  Docker mode runs the same allowlisted command in separate containers over
  independent temporary snapshots. Fake mode is for deterministic unit tests
  only and is not a Docker execution substitute.
- `api/verifications.py` and `frontend/src/api/verifications.ts`: typed routes and
  clients expose creation, status/results, cancellation, and sandbox availability.
  The patch review UI polls persisted status and renders backend-reported outcomes.

## Storage and consistency

`migrations.py` contains ordered SQL migrations applied under `BEGIN IMMEDIATE`;
`PRAGMA user_version` tracks the schema. Migration 1 adds repositories, files,
symbols, imports, foreign keys, uniqueness constraints, and lookup indexes.
Future schema changes append migrations. Back up the database before upgrading;
downgrades are rejected rather than silently modifying newer schemas.

Claims commit before network work. A short exclusive transaction then publishes
all file/symbol/import rows and the ready status together. Failures retain a
sanitized error record and expose no partial index. Competing claims return 409;
a crashed claim can be reclaimed after its lease expires (ingestion budget plus
30 seconds). Tokens prevent an expired worker from overwriting a new attempt.

Bare snapshots live outside the application tree in a private directory. Completed
files are mode 0444 and directories 0555; ingestion only reads published snapshots.
SQLite stores indexed source and original-byte SHA-256 hashes. Failed attempts
clean their own temporary/snapshot directories. Abrupt process termination may
leave unreferenced directories; automatic garbage collection is deferred.

## Security and resource boundaries

Git uses argument lists, a sanitized environment, disabled credential helpers and
hooks, no redirects, HTTPS-only production transport, no templates, no checkout,
and no submodule recursion. Symlinks/submodules are never materialized. Paths are
validated as relative POSIX paths; ignored/generated/virtual-environment content,
binary blobs, invalid encodings, and oversized Python files are skipped with counts.

Deadlines, monitored disk/output sizes, expanded-tree sizes, file/source/symbol
counts, and response/snippet limits bound each operation. Disk checks poll every
20 ms and can briefly overshoot; these are application limits, not OS isolation
or a global disk quota. This service targets local POSIX development. Git must
remain patched; public hosting and adversarial multi-tenant isolation are deferred.

Docker verification uses a SHA-256-pinned, multi-architecture Python slim image,
non-root numeric UID, `--network=none`, a read-only container root, dropped
capabilities, `no-new-privileges`, CPU/memory/PID limits, strict execution
timeouts, and bounded captured output. Only a disposable indexed snapshot and a
temporary runner script are mounted; the repository root and Docker socket are
not mounted. Timed-out containers are explicitly removed and cleanup is checked.
The host process prepares and deletes snapshot directories but does not execute
their Python code. The optional real-Docker test suite runs only hash-allowlisted,
locally authored fixtures and is excluded from normal CI.

Containers still share the Docker daemon and host kernel; this is not a VM-level
security boundary against kernel/daemon vulnerabilities or a defense for a
compromised Docker Desktop installation. The adapter depends on a trusted daemon
and its default seccomp profile. Docker execution fails closed when the daemon,
pinned image, or required policy is unavailable.

## Future boundaries (not implemented)

Import names are not resolved into dependency or call graphs. Authentication,
authorization, durable external workers/queues, global storage quotas, automatic
snapshot garbage collection, and production observability/deployment remain
future work. Model-based patch/investigation quality also needs a versioned
evaluation corpus; current workflow tests use deterministic fake providers.
