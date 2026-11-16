# Working on Patchwork AI

- Implement only the explicitly requested milestone. Completed: foundation and repository indexing.
- Keep API routes, schemas, configuration, and persistence separate in `backend/`.
- Keep frontend API access separate from React presentation in `frontend/src/`.
- Prefer standard libraries and existing tooling; justify new dependencies.
- Use typed code, focused tests, and explicit error handling at system boundaries.
- Never execute imported repository code on the host; future execution needs isolation.
- Preserve immutable commit indexes, transactional publication, and offline core tests.
- Append SQLite migrations; never edit an already-shipped migration.
- Never commit secrets, local databases, build output, or dependencies.
- Run the checks in README for affected components. Report actual results only.
- Update API contracts with API changes and `docs/SESSION.md` at handoff.
- Use meaningful commits on `master`; never rewrite published history or force-push.
