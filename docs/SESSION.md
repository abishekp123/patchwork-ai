# Session handoff

Date: 2026-11-16 (America/Toronto). Scope: final Milestone 5 Docker integration
verification; no Milestone 6 work started.

## Current state

- Repository indexing remains immutable and inert. Investigations and patches use
  pinned indexed source; patch approval is required before verification.
- Verification builds independent baseline and patched temporary snapshots, applies
  a strict unified diff only to the patched copy, then runs the same allowlisted
  command in separate Docker containers.
- The Docker adapter requires a SHA-256-pinned image, numeric non-root UID,
  disabled networking, read-only root filesystem, dropped capabilities,
  no-new-privileges, CPU/memory/PID limits, strict timeouts, and bounded output.
  It does not mount the repository root or Docker socket. Timeout cleanup removes
  and checks the named container.
- Docker integration tests are opt-in and use only a local fixture whose Python
  files are SHA-256 allowlisted in
  `backend/tests/fixtures/docker_verification/manifest.json`. The fixture proves
  an arithmetic bug fails before its approved repair and passes afterward, and
  checks runtime isolation, resource limits, output truncation, cleanup, and
  source/index immutability.
- Fake-adapter tests are deterministic unit tests only; their results are not
  counted as real Docker execution.

## Verification run

Environment: macOS Apple Silicon (`arm64`), Docker Desktop Engine 29.9.3
(`desktop-linux`), Python 3.14.3, Node 26.13.1, npm 11.20.0.

Pinned image: `python@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c`
(Python 3.12.12 slim Bookworm multi-architecture index; pulled with its ARM64
variant before the sandbox tests).

| Check | Result |
| --- | --- |
| Default backend pytest suite | 124 passed, 2 opt-in Docker tests skipped |
| Real Docker integration suite | 2 passed, 0 failed, 0 skipped |
| Baseline fixture container | 7 tests: 6 passed, 1 expected failure |
| Patched fixture container | 7 tests: 7 passed |
| Docker fixture timeout | Timed out at 2 seconds; container cleanup verified |
| Ruff lint and format | Passed |
| Frontend Oxlint, Prettier, Vitest | Passed; 16 tests across 3 files |
| Frontend TypeScript check and production build | Passed |

Real-container checks confirmed non-root UID 65532, zero effective/bounding
capabilities, `NoNewPrivs=1`, no IPv4 default route or outbound IPv4/IPv6
connectivity, read-only root, CPU quota, 512 MiB memory limit, PID limit 64,
bounded output, workspace-only fixture/runner mounts, no Docker socket mount, and
no residual labeled containers after success or timeout. The original fixture
hashes and SQLite indexed source rows were unchanged.

Run the real suite explicitly from `backend/`:

```sh
PATCHWORK_RUN_DOCKER_INTEGRATION=1 \
  .venv/bin/python -m pytest -m docker_integration -q tests/test_docker_integration.py
```

The default test run intentionally skips these tests. Docker must be running and
the pinned image must be pre-pulled; no package installation or download occurs
inside execution containers.

## Known limitations

- Docker containers share the daemon and host kernel; this is not VM isolation
  against Docker/kernel vulnerabilities or a compromised Docker Desktop setup.
- Real container verification has only been exercised on Docker Desktop ARM64.
  The pinned image index supports multiple architectures, but other runtime/
  architecture combinations were not tested here.
- Fake adapter results do not execute Python and do not establish sandbox safety.
- Live OpenAI inference, auth/authorization, durable external workers, global
  quotas, automatic orphan-snapshot collection, and production deployment remain
  outside this scope.

## History and boundary

Work remains on `master`, preserving existing history. This checkpoint completes
the requested real-Docker verification tests for the existing Milestone 5
workflow only. Do not start the next milestone without authorization.
