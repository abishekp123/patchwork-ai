from pathlib import Path

from patchwork.evaluations.runner import run_evaluation


def test_offline_evaluation_covers_investigation_to_approval(tmp_path: Path):
    result = run_evaluation(tmp_path / "evaluation.db")

    assert result.passed
    assert all(result.checks.values())
    assert set(result.checks) == {
        "investigation_completed",
        "source_evidence_cited",
        "patch_matches_expected_source",
        "validated_unified_diff_created",
        "patch_persisted_with_investigation",
        "human_approval_persisted",
        "indexed_snapshot_unchanged",
    }
