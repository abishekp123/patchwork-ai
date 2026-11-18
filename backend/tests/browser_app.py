"""Playwright-only server: local Git + deterministic model; real services and Docker.

Never installed with the application. Explicit PATCHWORK_E2E=1 is required.
"""

import asyncio
import atexit
import os
import subprocess
import tempfile
from pathlib import Path

from test_live_evaluation import FixtureProvider

from patchwork.api import investigations, patches
from patchwork.api.repositories import git_client_type
from patchwork.config import Settings
from patchwork.database import connect_database
from patchwork.evaluations.fixtures import FIXTURES, RepairFixture
from patchwork.evaluations.live import index_fixture
from patchwork.ingestion.git import GitClient
from patchwork.ingestion.validation import normalize_url
from patchwork.main import create_app
from patchwork.patches.engine import PatchChange, PatchProposal
from patchwork.patches.store import PatchStore


def create_browser_app():
    if os.environ.get("PATCHWORK_E2E") != "1":
        raise RuntimeError("Browser fixture server requires explicit opt-in")
    os.environ["OPENAI_API_KEY"] = "browser-fixture-not-a-provider-key"
    temporary = tempfile.TemporaryDirectory(prefix="patchwork-browser-")
    atexit.register(temporary.cleanup)
    root = Path(temporary.name)
    origin = root / "origin"
    origin.mkdir()
    fixture = FIXTURES[0]
    (origin / "subject.py").write_text(fixture.source)
    (origin / "test_subject.py").write_text(
        "from packaging.version import Version\nfrom subject import repair\n\n"
        "def test_sum():\n    assert repair(2, 3) == 5\n\n"
        "def test_dependency():\n    assert Version('1.10') > Version('1.2')\n"
    )
    for args in (("init", "-b", "master"), ("add", "."), ("commit", "-m", "Browser fixture")):
        subprocess.run(
            ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args],
            cwd=origin,
            capture_output=True,
            check=True,
        )

    class LocalGit(GitClient):
        protocol_options = [*GitClient.protocol_options, "-c", "protocol.file.allow=always"]

        def remote(self, url):
            normalize_url(url)
            return origin.as_uri()

    class BrowserProvider(FixtureProvider):
        async def decide(self, context, tools, max_output):
            await asyncio.sleep(20 if "wait for cancellation" in context else 0.3)
            return await super().decide(context, tools, max_output)

    class BrowserPatchProvider:
        async def generate_patch(self, payload, repository):
            return {
                "title": "Browser fixture repair (simulated model)",
                "summary": "Deterministic browser fixture; no paid inference.",
                "changes": [
                    {
                        "path": "subject.py",
                        "before": fixture.source,
                        "after": fixture.source.replace("a - b", "a + b"),
                        "reason": "Known fixture correction",
                    }
                ],
                "evidence_ids": payload["evidence_ids"],
            }

    investigations.provider_for = lambda settings: BrowserProvider(fixture)
    patches.provider_for = lambda settings: BrowserPatchProvider()
    settings = Settings(
        database_path=root / "browser.db",
        repository_dir=root / "snapshots",
        verification_image=os.environ["PATCHWORK_VERIFICATION_IMAGE"],
        investigation_model="browser-fixture-no-inference",
        verification_timeout_seconds=20,
    )
    app = create_app(settings)
    app.dependency_overrides[git_client_type] = lambda: LocalGit

    @app.post("/api/__test/slow-patch")
    async def slow_patch():
        fixture = RepairFixture(
            "slow-browser-fixture",
            "Controlled cancellation test",
            FIXTURES[0].source,
            ("__import__('time').sleep(3); self.assertEqual(repair(2, 3), 5)",),
        )
        repository = index_fixture(settings, fixture)
        patch = PatchStore(settings.database_path).create(
            repository,
            PatchProposal(
                title="Slow browser fixture",
                summary="Real Docker cancellation check",
                changes=[
                    PatchChange(
                        path="subject.py",
                        before=fixture.source,
                        after=fixture.source.replace("a - b", "a + b"),
                        reason="Known repair",
                    )
                ],
            ),
        )
        return {"patch_id": patch.id}

    @app.post("/api/__test/reset")
    async def reset():
        tasks = [*app.state.investigation_tasks.values(), *app.state.verification_tasks.values()]
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with connect_database(settings.database_path) as db, db:
            for table in (
                "verifications",
                "patches",
                "investigation_steps",
                "investigations",
                "imports",
                "symbols",
                "files",
                "repositories",
            ):
                db.execute(f"DELETE FROM {table}")
        return {"reset": True}

    return app
