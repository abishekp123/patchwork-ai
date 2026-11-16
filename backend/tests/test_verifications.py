from pathlib import Path

import pytest

from patchwork.errors import PatchworkError
from patchwork.verifications.models import SandboxConfig
from patchwork.verifications.sandbox import FakeSandboxAdapter, SandboxAdapter, SandboxFactory


def test_fake_sandbox_returns_test_summary():
    adapter = FakeSandboxAdapter()
    summary, stdout, stderr = adapter.run(
        command="python -m pytest -q",
        workspace=Path("/tmp"),
        timeout_seconds=30,
    )
    assert summary.exit_code == 0
    assert summary.tests_total == 1
    assert summary.tests_passed == 1
    assert stdout == "[100%] success\n"
    assert stderr == ""


def test_sandbox_factory_dispatches_modes():
    assert isinstance(SandboxFactory.create("fake"), FakeSandboxAdapter)
    assert isinstance(SandboxFactory.create("docker"), SandboxAdapter)


def test_sandbox_policy_rejects_unsafe_configuration():
    config = SandboxConfig(
        mode="docker",
        network_disabled=False,
        read_only_root=True,
        no_new_privileges=True,
    )
    with pytest.raises(PatchworkError, match="Network must be disabled"):
        SandboxAdapter(config).validate_policy()

    unsafe = SandboxConfig(
        mode="docker",
        read_only_root=True,
        no_new_privileges=True,
        extra_args=["--privileged=true"],
    )
    with pytest.raises(PatchworkError, match="Unsafe Docker flags"):
        SandboxAdapter(unsafe).validate_policy()

    root_user = SandboxConfig(mode="docker", user="0:0")
    with pytest.raises(PatchworkError, match="non-root"):
        SandboxAdapter(root_user).validate_policy()


def test_docker_adapter_reports_unavailable_when_not_installed(monkeypatch):
    monkeypatch.setattr("patchwork.verifications.sandbox.shutil.which", lambda _: None)
    adapter = SandboxAdapter(SandboxConfig(mode="docker"))
    assert adapter.available() is False
