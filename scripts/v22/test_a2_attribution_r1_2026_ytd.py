import ast
import json
from pathlib import Path


SOURCE = Path(__file__).with_name("a2_attribution_r1_2026_ytd.py")
OUT = Path(r"D:\us-tech-quant-results\A2_ATTRIBUTION_R1_2026_YTD")


def test_runner_contains_no_model_fit_or_search_surface():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    fit_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "fit"
    ]
    assert fit_calls == []
    text = SOURCE.read_text(encoding="utf-8")
    assert "GridSearchCV" not in text
    assert "RandomizedSearchCV" not in text
    assert 'MODEL = "M0_A2_HGB"' in text
    assert 'NEXT_AUTHORIZED_STEP": "STOP_AND_REVIEW_ATTRIBUTION_R1"' in text


def test_materialized_status_is_forensic_only_and_identity_passes():
    status = json.loads((OUT / "status.json").read_text(encoding="utf-8"))
    assert status["A2_ATTRIBUTION_R1_2026_YTD_STATUS"] == "PASS_FORENSIC_ATTRIBUTION_COMPLETE"
    assert status["A2_ECONOMIC_PATH_IDENTITY_STATUS"].startswith("PASS_EXACT_DETERMINISTIC_REPLAY")
    assert status["2026_YTD_EVIDENCE_STATUS"] == "RETROSPECTIVE_WITH_PRIOR_OUTCOME_EXPOSURE"
    for key in (
        "2026_TRAINING_ROWS", "MODEL_FIT_COUNT", "PARAMETER_SEARCH_COUNT", "RISK_RULE_SEARCH_COUNT",
        "ELIGIBILITY_MASK_CHANGE_COUNT", "FUTURE_INFORMATION_VIOLATION_COUNT", "PIT_13F_TEMPORAL_VIOLATION_COUNT",
    ):
        assert status[key] == 0
    assert status["SHARED_SOURCE_CHANGE_REQUIRED"] is False
    assert status["NEXT_AUTHORIZED_STEP"] == "STOP_AND_REVIEW_ATTRIBUTION_R1"
    assert status["NEXT_RESEARCH_HYPOTHESIS_COUNT"] <= 3


def test_identity_audit_and_manifest_hash_every_material_artifact():
    identity = json.loads((OUT / "a2_identity_audit.json").read_text(encoding="utf-8"))
    assert identity["return_identity_max_abs_error"] <= 5e-12
    assert identity["pit_13f_temporal_violation_count"] == 0
    assert identity["eligibility_mask_change_count"] == 0
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["self_hash_excluded_because_recursive"] is True
    assert manifest["artifact_count_excluding_self"] == len(manifest["artifacts"])
    assert all(len(row["sha256"]) == 64 and (OUT / row["artifact"]).is_file() for row in manifest["artifacts"])


def test_required_outputs_and_sector_fail_closed_surface():
    contract = json.loads((OUT / "attribution_contract.json").read_text(encoding="utf-8"))
    assert contract["sector_attribution_status"] == "SKIPPED_INSUFFICIENT_AUTHORITATIVE_SECTOR_LINEAGE"
    required = {
        "security_pnl_attribution.csv", "date_level_attribution.csv", "sector_attribution.csv",
        "13f_vintage_attribution.csv", "winner_loser_attribution.csv", "execution_cost_attribution.csv",
        "concentration_diagnostics.csv", "max_drawdown_security_contribution.csv",
        "max_drawdown_date_contribution.csv", "max_drawdown_sector_contribution.csv",
        "max_drawdown_forensic.md", "risk_source_taxonomy.csv", "attribution_report.md",
    }
    assert all((OUT / name).is_file() for name in required)
