from pathlib import Path

from scripts.v22.fast3_agent import package_final_artifacts as package


def test_package_frozen_results_contract(tmp_path: Path):
    summary = package.build(tmp_path)
    expected = {
        "FAST3_AUTORESEARCH_FINAL_REPORT.md",
        "FAST3_AUTORESEARCH_FINAL_SUMMARY.json",
        "FAST3_AUTORESEARCH_EXPERIMENT_REGISTRY.parquet",
        "FAST3_AUTORESEARCH_CHAMPION_CONFIG.json",
        "FAST3_AUTORESEARCH_LEAKAGE_AUDIT.json",
        "FAST3_AUTORESEARCH_RANDOM_WINDOW_METRICS.parquet",
        "FAST3_AUTORESEARCH_RESUME_COMMAND.txt",
    }
    assert expected <= {path.name for path in tmp_path.iterdir()}
    assert summary["research_status"] == "FAIL_NO_ROBUST_EDGE"
    assert summary["confirmation_read_count"] == 0
    assert summary["prospective_shadow_allowed"] is False
