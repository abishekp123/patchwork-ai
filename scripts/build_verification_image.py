"""Build the reviewed pytest environment offline; print its immutable local image ID.

Only the host download step has network access. No imported repository or its
requirements/build hooks enter this build context. Run from the project root.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "python@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="patchwork-image-build-") as directory:
        context = Path(directory)
        for name in ("Dockerfile", "requirements.lock"):
            shutil.copyfile(ROOT / "sandbox/pytest" / name, context / name)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--only-binary=:all:",
                "--require-hashes",
                "--dest",
                str(context / "wheels"),
                "-r",
                str(context / "requirements.lock"),
            ],
            check=True,
            timeout=180,
        )
        subprocess.run(["docker", "pull", BASE], check=True, timeout=180)
        iid = context / "image-id"
        subprocess.run(
            [
                "docker",
                "build",
                "--network=none",
                "--pull=false",
                "--iidfile",
                str(iid),
                "-t",
                "patchwork-pytest:reviewed",
                str(context),
            ],
            check=True,
            timeout=180,
        )
        print(iid.read_text().strip())


if __name__ == "__main__":
    main()
