# Engineering decisions

1. **Preserve the small monorepo.** Independent Python/npm projects, FastAPI's app
   factory, injected settings, the health contract, and the frontend remain intact.
2. **Bare Git plumbing, not checkout.** HTTPS GitHub URLs and full commit SHA-1s
   bound transport. Fetching the exact commit with depth one handles historical
   pins without cloning history. Reading blobs avoids hooks, smudge filters,
   executable working trees, and filesystem symlinks. No GitHub token is required.
3. **Immutable snapshot identity.** A URL/commit pair has a stable identifier.
   Ready imports are reused; a new commit produces a new snapshot. Failed attempts
   can retry, and failed default-resolution attempts retain a nullable commit.
   Parser/index semantics are versioned with `index_version`; rebuild/version
   migration for future parser changes is a later feature.
4. **Standard-library SQLite and explicit migrations.** Append ordered SQL in
   `migrations.py`; apply transactionally using `user_version`. Constraints and
   indexes protect uniqueness and ownership. No ORM, PostgreSQL, or Redis needed.
5. **Claim then publish.** A short transaction claims an import, external work runs
   outside the transaction, and one transaction publishes the entire index. Leases
   prevent duplicate workers and permit recovery after crashes. Tokens reject stale
   publication. Disk and SQLite cannot commit atomically; orphan cleanup after
   abrupt termination is an operational limitation, not a partial-index exposure.
6. **Tree-sitter's Python grammar only.** These two packages are the only added
   runtime dependencies. Syntax recovery, Unicode, and lexical scopes are useful
   without importing code. Import targets, calls, inheritance, and package layouts
   are not guessed. Malformed files remain searchable with explicit error flags.
7. **Persist decoded source alongside metadata.** Original-byte hashes identify
   content; SQLite source enables reproducible retrieval without filesystem access.
   This intentionally duplicates bounded source data in exchange for a simpler,
   safer search boundary. Skipped files are summarized by reason, not individually.
8. **Bounded lexical search instead of another service.** Indexed exact symbol
   lookups plus bounded scans satisfy this milestone without ripgrep subprocesses,
   embeddings, FTS tokenization changes, or a vector database. Ranking is documented
   in CONTRACTS; no latency/throughput claims have been made.
9. **POSIX local operation and explicit limits.** Process-group termination,
   read-only snapshots, private storage, and configurable per-import budgets are
   sufficient for local development. They do not replace an OS sandbox, global
   quotas, authentication, or production abuse controls.
10. **Offline-first tests and real timestamps.** Core tests use temporary local
    Git repositories through a test-only adapter. A separate public GitHub smoke
    test verifies production transport. CI covers Python 3.12/3.14 and Node 24.
    Existing history is preserved; new commits use their actual implementation time.

References: [Git fetch](https://git-scm.com/docs/git-fetch),
[Git transport configuration](https://git-scm.com/docs/git-config), and
[Tree-sitter Python bindings](https://tree-sitter.github.io/py-tree-sitter/).
