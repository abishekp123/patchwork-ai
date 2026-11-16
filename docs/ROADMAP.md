# Roadmap

1. **Foundation — implemented.** Modular API and UI, SQLite connectivity,
   health contract, checks, CI, and project documentation.
2. **Repository intake and bug reports.** Import a selected GitHub repository at
   an immutable commit, validate inputs and paths, persist metadata with initial
   migrations, and add a small dashboard flow. Never run imported code on the host.
3. **Code intelligence.** File inventory, ripgrep retrieval, Tree-sitter symbols
   and references, and evidence links pinned to source revisions.
4. **Investigation and proposed repair.** Typed tools and structured agent steps,
   bounded model calls, reviewable traces, and proposed diffs. No automatic merge.
5. **Isolated verification.** Restricted disposable Docker execution, explicit
   resource/network policies, test output capture, and verification status.
6. **Durability and evaluation.** Persisted run state, cancellation/retry semantics,
   replayable traces, and a versioned bug dataset with measured repair quality.
7. **Production hardening.** Authentication/authorization, observability,
   deployment, abuse limits, and storage/execution scaling based on measured need.

Each milestone requires explicit authorization. Only Milestone 1 is in scope
for the initial implementation.
