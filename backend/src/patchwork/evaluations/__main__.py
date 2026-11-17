import json
import tempfile
from pathlib import Path

from patchwork.evaluations.runner import run_evaluation


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="patchwork-eval-") as directory:
        result = run_evaluation(Path(directory) / "evaluation.db")
    print(json.dumps(result.model_dump(), sort_keys=True, indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
