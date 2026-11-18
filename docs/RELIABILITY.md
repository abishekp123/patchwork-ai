# Local reliability and trusted environments

## Job ownership and recovery

Run one API process per SQLite database (`uvicorn ... --factory`, without multiple
workers). A nonblocking OS file lock beside the database rejects a second owner
with `runtime_already_running`. SIGKILL releases the lock automatically; the lock
file itself is retained to avoid inode replacement races. This implementation is
POSIX/local-filesystem oriented, not a distributed coordination protocol.

Startup atomically marks nonterminal investigations and verifications FAILED with
`interrupted`, completion timestamps, and an investigation recovery trace. Existing
facts, baseline summaries, logs, and terminal results are preserved. It never
replays model calls or code execution automatically. Retry by submitting the same
investigation or starting a new verification of the approved patch; new IDs keep
the failed attempt auditable. Concurrent identical repository/description
investigations and concurrent active verifications of one patch return 409.

Graceful shutdown cancels tasks and waits for bounded Docker cleanup before
marking undispatched jobs CANCELLED with `server_shutdown`. Repeated cancellation
is idempotent; late writes cannot replace terminal state. Verification cancellation
waits for the current bounded command/cleanup, so it may not return immediately.
If SQLite becomes unavailable, shutdown logs the persistence failure without
masking resource cleanup. Restore storage before restart; durable recovery cannot
recover a lost database.

New verification snapshots and runner resources live beneath a mode-0700 directory
in the OS temporary directory, keyed by the canonical database path hash. Containers
carry the corresponding `com.patchwork.owner` label. Startup removes only containers
for that owner, then removes its temporary children without following symlinks.
Docker unavailability with orphan resources fails startup with
`recovery_cleanup_pending`; start Docker and retry startup. Mounted resources are
retained until container removal succeeds. Imported repositories and unrelated
containers are never removed. Legacy unlabelled resources from older releases
require manual review; no global temporary-directory sweep is performed.

## Reviewed Python dependencies

Runtime containers cannot download or install packages. The optional trusted image
contains pytest and its locked pure-Python dependencies, including `packaging`.
The application never reads an imported `requirements.txt`, runs a repository
build hook, or accepts a caller-selected image.

From the project root, with Docker on PATH:

```sh
backend/.venv/bin/python scripts/build_verification_image.py
export PATCHWORK_VERIFICATION_IMAGE="$(docker image inspect patchwork-pytest:reviewed --format '{{.Id}}')"
```

The builder downloads only hash-checked binary wheels from the checked-in
`sandbox/pytest/requirements.lock` on the host, into a disposable build context.
Its base image is digest-pinned. `docker build --network=none` installs from those
wheels with `--no-index --require-hashes`; only trusted build inputs enter the
context. The build runs package installation as image-builder root, while runtime
verification always runs as UID 65532 with the existing isolation policy.

The administrator selects a local `sha256:<64 hex>` image ID or a registry image
pinned by digest. Mutable tags are rejected. The image must already exist locally;
verification still uses `--pull=never`. New verification records persist the exact
configured immutable identity in `environment_image` (legacy records have null).
Platform-specific image identities may differ; reproducibility here means pinned
base/dependency inputs, not a claim of bit-identical Docker build metadata.

For another controlled project, review and update this trusted lock/build context,
rebuild, and explicitly configure its immutable identity. There is no automatic
dependency inference or general package installer. Pytest plugin autoload and its
cache writer are disabled; intentionally required plugins would need a reviewed
allowlist change. Repository tests and conftest files still execute only inside
the approved sandbox. Summary counts are parsed from output, not tamper-proof
attestation.

## Browser validation

Playwright launches an isolated FastAPI fixture server plus the real Vite frontend.
The fixture server is outside the installed package, requires `PATCHWORK_E2E=1`,
and uses a temporary local Git repository, SQLite, deterministic model decisions,
and real Docker. Its reset/fixture routes do not exist in the production app.
No provider credentials or paid calls are used by browser tests.

```sh
# From frontend/, after building the trusted image and exporting the variable above:
npm ci
npx playwright install chromium webkit
npm run test:browser
```

Use `PATCHWORK_TEST_PYTHON=python` when the backend is installed in the active
Python environment rather than `backend/.venv`. The runner owns ports 8001/5174,
refuses existing servers, and shuts down its process groups. Linux may require
`npx playwright install --with-deps chromium webkit` (used in CI).

Four tests per browser cover empty/loading/error states, repository import,
keyboard-accessible file buttons, source search, investigation completion,
evidence-to-patch navigation, review/approval, real Docker results, browser refresh,
and investigation/verification cancellation. Browser route interception is used
only to inject loading/API-failure states. Screenshots and JSON reports are saved
in `frontend/test-results`; failed runs retain traces. README images are copied
from actual successful Chromium/WebKit runs, with the simulated model labeled.

See [Playwright server lifecycle](https://playwright.dev/docs/test-webserver) and
[browser installation](https://playwright.dev/docs/browsers).
