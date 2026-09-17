import ast
import json
from pathlib import Path


SOURCE = Path(__file__).with_name("a2_algorithm_r2a_2026_retrospective_and_forward_shadow_anchor.py")
OUT = Path(r"D:\us-tech-quant-results\A2_ALGORITHM_R2A_2026_RETROSPECTIVE_AND_FORWARD_SHADOW_ANCHOR")


def test_runner_contains_no_fit_call_and_only_three_models():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    fit_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "fit"]
    assert fit_calls == []
    text = SOURCE.read_text(encoding="utf-8")
    assert 'MODELS = ("M0_A2_HGB", "M1_XGB_REG", "M2_W50")' in text
    assert "W25" not in text and "W40" not in text and "W60" not in text and "W75" not in text


def test_materialized_status_and_forward_anchor_contract():
    status = json.loads((OUT / "status.json").read_text(encoding="utf-8"))
    assert status["2026_YTD_EVIDENCE_STATUS"] == "RETROSPECTIVE_WITH_PRIOR_OUTCOME_EXPOSURE"
    assert status["2026_TRAINING_ROWS"] == 0
    assert status["2026_PARAMETER_SEARCH_COUNT"] == 0
    assert status["2026_BLEND_SEARCH_COUNT"] == 0
    assert status["PIT_13F_TEMPORAL_VIOLATION_COUNT"] == 0
    assert status["MODEL_UNIVERSE_MISMATCH_COUNT"] == 0
    assert status["DEPLOYMENT_STATUS"] == "NOT_AUTHORIZED"
    forward = json.loads((OUT / "forward_shadow_contract.json").read_text(encoding="utf-8"))
    assert forward["prospective_eligibility"].endswith("STRICTLY_GREATER_THAN_FREEZE_TIMESTAMP")
    assert forward["FIRST_FUTURE_PROSPECTIVE_ELIGIBLE_PREDICTION_DATE"] == "NOT_YET_AVAILABLE_WAIT_FOR_NEXT_ELIGIBLE_PREDICTION"


def test_manifest_hashes_every_material_artifact():
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["self_hash_excluded_because_recursive"] is True
    assert manifest["artifact_count_excluding_self"] == len(manifest["artifacts"])
    assert all(len(row["sha256"]) == 64 and (OUT / row["artifact"]).is_file() for row in manifest["artifacts"])
