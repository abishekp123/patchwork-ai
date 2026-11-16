# Session handoff

Date: 2026-11-16 (America/Toronto). Implemented scope: Milestone 2 only.

## Current state

- Public HTTPS GitHub imports resolve or accept full pinned commit SHAs, use
  bounded bare fetches, and securely discover Python blobs without execution.
- Tree-sitter extracts modules, nested classes/functions/methods, async flags,
  decorators, signatures, locations, and literal imports. Malformed files retain
  recoverable symbols and explicit syntax-error flags.
- SQLite migration 1 persists snapshot status/errors, files/hashes/source, symbols,
  and imports. Claims, leases, constraints, and atomic publication prevent duplicate
  or partially visible indexes. Ready pinned imports reuse the existing index.
- Typed repository/files/symbols/imports/search APIs, bounded lexical ranking,
  consistent errors, and proxy-compatible aliases are implemented.
- Existing frontend and health contract are unchanged. No LLM key, AI agent,
  authentication, queue, vector store, patch generation, or code execution added.

## Verification executed

Local environment: macOS arm64, Python 3.14.3, Node 26.13.1, npm 11.20.0.

| Check | Result |
| --- | --- |
| Backend full pytest suite | 91 passed, including all 6 Milestone 1 tests |
| Ruff lint and formatting | Passed |
| Python dependency consistency (`pip check`) | Passed |
| Frontend Vitest | 12 passed |
| Frontend Oxlint, Prettier, TypeScript, production build | Passed |
| Real public GitHub import | 201; pinned MarkupSafe revision below |
| Repeat pinned public import | 200, reused index |
| Public exact `Markup` lookup / `escape` search | 1 exact symbol / 5 bounded hits |
| Uvicorn + Vite startup, direct health and proxied health | Passed; HTTP 200 |
| Repository search through existing Vite proxy | Passed; HTTP 200, 2 bounded hits |
| `git diff --check` | Passed |

Public smoke source: `https://github.com/pallets/markupsafe` at
`4e111271b1494995708a9e878a10829b5e10c7ba`: 12 indexed files, 128 symbols, 53 imports.
This separate smoke run used temporary external storage. Core tests are offline,
using local Git fixtures. Test servers were stopped after verification. No browser
visual result or performance measurement is claimed.

Tests cover URL/revision validation, pinned historical commits, repeat imports,
Unicode/encodings, malformed/nested/async syntax, imports, literal search ranking,
limits, missing symbols, traversal/symlinks/submodules, virtual environments,
timeouts, migration rollback, atomic publication, concurrent/stale claims, failed
attempt cleanup/retry, API contracts, and health/frontend compatibility.

CI targets Linux Python 3.12/3.14 and Node 24. The initial Milestone 2 CI run caught
a class method named `list` shadowing the annotation builtin on Python 3.12; it was
renamed. A focused test also caught Tree-sitter raising `ValueError` on cancellation;
this now returns the structured timeout error. Final remote checks are attached to
`master` in [GitHub Actions](https://github.com/abishekp123/patchwork-ai/actions/workflows/ci.yml).

## History and boundaries

Private repository: https://github.com/abishekp123/patchwork-ai. Work remains on
`master`, preserving Milestone 1 history and real author/committer timestamps.
Milestone 2 groups: `f3532ce` transport/discovery; `f464a61` parsing/persistence;
`c87aeb0` search/API; final hardening/tests/documentation commit.

Known limitations: synchronous POSIX operation; Python-only indexing; literal
imports without static resolution; bounded source scans rather than semantic
search; no global storage quota or automatic orphan cleanup. Polling disk limits
can briefly overshoot and are not an OS sandbox. Failed default-branch resolution
records have no commit. Skipped files have aggregate reasons, not per-file records.
Parser-version rebuilds and public/multi-tenant deployment are deferred.

## Next milestone (requires authorization)

Milestone 3 can build bug-report/investigation sessions and evidence-backed tools
on the immutable index and retrieval contracts. Add structured traces and bounded
orchestration; continue to keep imported code inert. Do not begin repair generation
or execution before their explicitly authorized milestones.
