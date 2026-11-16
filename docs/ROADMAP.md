# Roadmap

1. **Foundation — implemented.** Modular API/UI, SQLite, health checks, CI, docs.
2. **Repository ingestion and code intelligence — implemented.** Public GitHub
   snapshots pinned to commits, secure Python discovery, Tree-sitter extraction,
   transactional indexes, and typed lexical/symbol retrieval APIs.
3. **Evidence-based investigation.** Bug-report/session persistence, structured
   investigator tools over this index, bounded orchestration, and reviewable
   evidence/traces. Define measurable evaluation cases before expanding autonomy.
4. **Proposed repair and isolated verification.** Reviewable patches and restricted
   disposable Docker execution with time/resource/network policies. No host execution
   of imported code and no automatic merge.
5. **Durability and evaluation.** Persisted run state, cancellation/retries,
   replayable traces, and measured investigation/repair quality on versioned cases.
6. **Production hardening.** Authentication/authorization, observability, deployment,
   quotas, snapshot garbage collection, and scaling based on measured need.

The user revised Milestone 2 to include code intelligence. Bug reports and an
investigation UI remain future scope. Every later milestone requires explicit
approval; no Milestone 3 implementation is included here.
