import os
import socket
import unittest
from pathlib import Path


class SandboxPolicyTests(unittest.TestCase):
    def test_container_is_non_root_and_has_no_capabilities(self) -> None:
        self.assertNotEqual(os.geteuid(), 0)
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        values = dict(line.split(":\t", 1) for line in status.splitlines() if ":\t" in line)
        self.assertEqual(values["NoNewPrivs"], "1")
        self.assertEqual(values["CapEff"], "0000000000000000")
        self.assertEqual(values["CapBnd"], "0000000000000000")

    def test_network_namespace_has_no_external_route(self) -> None:
        routes = Path("/proc/net/route").read_text(encoding="utf-8").splitlines()[1:]
        self.assertFalse(any(row.split()[1] == "00000000" for row in routes if row.split()))
        with self.assertRaises(OSError):
            socket.create_connection(("1.1.1.1", 53), timeout=1)
        with self.assertRaises(OSError):
            socket.create_connection(("2606:4700:4700::1111", 53), timeout=1)

    def test_container_root_filesystem_is_read_only(self) -> None:
        root_mount = next(
            line.split()
            for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
            if line.split()[4] == "/"
        )
        self.assertIn("ro", root_mount[5].split(","))

    def test_only_snapshot_and_runner_mounts_are_present(self) -> None:
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        mountpoints = {line.split()[4] for line in mountinfo.splitlines()}
        self.assertIn("/workspace", mountpoints)
        self.assertIn("/tmp/patchwork-runtime", mountpoints)
        self.assertNotIn("/var/run/docker.sock", mountpoints)
        self.assertNotIn("patchwork-ai", mountinfo)

    def test_cpu_memory_and_process_limits_are_applied(self) -> None:
        cgroup = Path("/sys/fs/cgroup")
        quota, period = (int(value) for value in (cgroup / "cpu.max").read_text().split())
        self.assertGreater(quota, 0)
        self.assertGreater(period, 0)
        self.assertLessEqual(quota, period)

        memory_limit = int((cgroup / "memory.max").read_text())
        self.assertGreater(memory_limit, 0)
        self.assertLessEqual(memory_limit, 512 * 1024 * 1024)

        process_limit = int((cgroup / "pids.max").read_text())
        self.assertGreater(process_limit, 0)
        self.assertLessEqual(process_limit, 64)
