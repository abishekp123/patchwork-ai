# Session handoff

Date: 2026-11-16 (America/Toronto). Implemented scope: Milestone 3 investigation orchestration and verification.

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
- Investigation sessions now create persisted records with explicit lifecycle
  states, bounded tool execution, provider integration, and evidence-backed report
  validation. The engine supports created/context retrieval/investigating/evidence
  review/completed/failed/cancelled/budget exhausted transitions and rejects
  invalid or stale citations before accepting a report.
- The OpenAI Responses API adapter is implemented behind a provider abstraction,
  uses environment credentials, retries transient network errors, and records
  usage metadata when available. Automated tests exercise mocked provider
  responses instead of requiring a live API key.
- The backend exposes investigation APIs for create, fetch, steps, and cancel.
  No repair generation, execution, or host code execution were added.

## Verification executed

Local environment: macOS arm64, Python 3.14.3, Node 26.13.1, npm 11.20.0.

| Check | Result |
| --- | --- |
| Backend full pytest suite | 105 passed |
| Ruff lint and formatting | Passed |
| Python dependency consistency (`pip check`) | Passed |
| Frontend Vitest | 12 passed |
| Frontend Oxlint, Prettier, TypeScript, production build | Passed |
| Real public GitHub import | 201; pinned MarkupSafe revision below |
| Repeat pinned public import | 200, reused index |
| Public exact `Markup` lookup / `escape` search | 1 exact symbol / 5 bounded hits |
| Fake-provider investigation run | Completed successfully with evidence-backed final report |
| Investigation engine tests | Passed: state transitions, cancellation, budget exhaustion, valid citations, invalid evidence |
| Uvicorn + Vite startup, direct health and proxied health | Passed; HTTP 200 |
| Repository search through existing Vite proxy | Passed; HTTP 200, 2 bounded hits |
| `git diff --check` | Passed |

This run keeps the core workflow offline and deterministic: public smoke checks use
an immutable GitHub snapshot, while the investigation engine is validated with a
fake provider in the test suite. Live OpenAI inference remains unverified because
no `OPENAI_API_KEY` is configured in this workspace. The checks and the provider
contract intentionally avoid requiring credentials in unit tests.

## History and boundaries

Private repository: https://github.com/abishekp123/patchwork-ai. Work remains on
`master`, preserving Milestone 1 history and real author/committer timestamps.
Milestone 3 extends the existing provider and read-only tool contracts with an
explicit investigation lifecycle and evidence validation. The project continues
to keep imported code inert and does not begin repair generation or execution.

Known limitations: live provider verification requires a configured API key and a
separate smoke run; investigation traces do not yet implement external queueing or
multi-agent scheduling; patch generation and isolated execution remain future work.
No global storage quota or automatic orphan cleanup is introduced.

## Next milestone (requires authorization)

Milestone 4 would begin repair synthesis and isolated verification workflows,
using the same evidence-backed investigation model while keeping model execution
sandboxed and separate from the repository indexer.
