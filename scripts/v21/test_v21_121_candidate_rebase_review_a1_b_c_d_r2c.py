from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_121_candidate_rebase_review_a1_b_c_d_r2c.py"
OUT = ROOT / "outputs/v21/V21.121_CANDIDATE_REBASE_REVIEW_A1_B_C_D_R2C"


def test_v21_121_candidate_rebase_review_outputs() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr

    manifest_path = OUT / "V21.121_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["protected_outputs_modified"] is False
    assert manifest["official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
    assert manifest["no_parameter_optimization_performed"] is True
    assert manifest["new_variant_generated"] is False
    assert manifest["historical_rankings_recomputed"] is False
    assert manifest["prior_stage_outputs_read_as_frozen_evidence"] is True

    for name in [
        "evidence_ledger_v21_117_to_v21_120.csv",
        "candidate_scorecard_a1_b_c_d_d_r2c.csv",
        "d_and_d_r2c_downgrade_review.csv",
        "a1_b_c_primary_candidate_review.csv",
        "candidate_decision_matrix.csv",
        "V21.121_candidate_rebase_review_report.txt",
    ]:
        assert (OUT / name).is_file(), name

    scorecard = pd.read_csv(OUT / "candidate_scorecard_a1_b_c_d_d_r2c.csv")
    assert set(scorecard["candidate"]) == {
        "A1_BASELINE_CONTROL",
        "B_STATIC_MOMENTUM_BLEND",
        "C_DYNAMIC_MOMENTUM_BLEND",
        "D_WEIGHT_OPTIMIZED_R1",
        "D_R2C_BC_CONFIRMATION_OVERLAY",
    }
    d2c = scorecard[scorecard["candidate"].eq("D_R2C_BC_CONFIRMATION_OVERLAY")].iloc[0]
    assert bool(d2c["concentration_warning"]) is True
    assert bool(d2c["overfit_warning"]) is True

    downgrade = pd.read_csv(OUT / "d_and_d_r2c_downgrade_review.csv").iloc[0]
    assert bool(downgrade["repeated_loser_issue_unresolved"]) is True
    assert bool(downgrade["concentrated_SOXX_alpha_blocks_adoption"]) is True

    ledger = pd.read_csv(OUT / "evidence_ledger_v21_117_to_v21_120.csv")
    assert {"IN_SAMPLE_OR_DESIGN_WINDOW", "NEWLY_MATURED_AFTER_REFRESH", "ATTRIBUTION_ONLY_NEW_MATURITY"}.issubset(set(ledger["evidence_type"]))

    matrix = pd.read_csv(OUT / "candidate_decision_matrix.csv")
    assert "candidate_decision" in matrix.columns
    assert manifest["evidence_favors"] == "A1"

    report = (OUT / "V21.121_candidate_rebase_review_report.txt").read_text(encoding="utf-8")
    assert "official_adoption_allowed=false" in report
    assert "next recommended stage=" in report
