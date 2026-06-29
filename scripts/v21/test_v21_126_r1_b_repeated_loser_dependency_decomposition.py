from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_126_r1_b_repeated_loser_dependency_decomposition.py"
OUT = ROOT / "outputs/v21/V21.126_R1_B_REPEATED_LOSER_DEPENDENCY_DECOMPOSITION"


def test_v21_126_r1_b_repeated_loser_dependency_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((OUT / "V21.126_R1_manifest.json").read_text(encoding="utf-8"))
    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["model_parameters_changed"] is False
    assert manifest["rankings_recomputed"] is False
    assert manifest["official_new_strategy_variants_created"] is False
    assert manifest["diagnostic_subsets_created"] is True

    for name in [
        "b_repeated_loser_overlap.csv",
        "b_repeated_loser_contribution_decomposition.csv",
        "b_clean_subset_forward_diagnostic.csv",
        "b_dependency_classification.csv",
        "b_risk_review.csv",
        "V21.126_R1_B_repeated_loser_dependency_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    overlap = pd.read_csv(OUT / "b_repeated_loser_overlap.csv")
    assert set(overlap["topN"]) == {20, 50}
    assert "repeated_loser_overlap_count" in overlap.columns

    clean = pd.read_csv(OUT / "b_clean_subset_forward_diagnostic.csv")
    assert not clean.empty
    assert clean["diagnostic_only"].astype(str).str.upper().eq("TRUE").all()
    assert clean["official_variant"].astype(str).str.upper().eq("FALSE").all()

    classification = pd.read_csv(OUT / "b_dependency_classification.csv")
    assert "dependency_classification" in classification.columns

    risk = pd.read_csv(OUT / "b_risk_review.csv")
    assert "metadata_warning" in risk.columns

    report = (OUT / "V21.126_R1_B_repeated_loser_dependency_report.txt").read_text(encoding="utf-8")
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report
