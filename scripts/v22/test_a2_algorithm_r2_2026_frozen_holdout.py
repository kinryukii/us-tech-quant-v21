from __future__ import annotations

import ast
import json
from pathlib import Path


SCRIPT = Path(__file__).with_name("a2_algorithm_r2_2026_frozen_holdout.py")
RESULT = Path(r"D:\us-tech-quant-results\A2_ALGORITHM_R2_2026_FROZEN_HOLDOUT")


def test_fail_closed_runner_never_opens_2026_scientific_data() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    forbidden = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"fit", "predict", "read_parquet", "read_csv"}:
                forbidden.append(node.func.attr)
    assert forbidden == []


def test_contract_truthfully_records_prior_exposure_and_no_evaluation() -> None:
    contract = json.loads((RESULT / "2026_holdout_contract.json").read_text(encoding="utf-8"))
    status = json.loads((RESULT / "status.json").read_text(encoding="utf-8"))
    audit = json.loads((RESULT / "preflight_contamination_audit.json").read_text(encoding="utf-8"))
    assert contract["HOLDOUT_CONTRACT_FROZEN_BEFORE_OUTCOME_READ"] is False
    assert contract["evaluation_authorized_after_this_record"] is False
    assert status["2026_EVALUATION_ROWS"] == 0
    assert audit["prior_outcome_content_read_count"] == 0
    assert audit["current_run_2026_target_read_count"] == 0
    assert audit["current_run_2026_pnl_read_count"] == 0


def test_no_deployment_or_post_holdout_change_is_authorized() -> None:
    status = json.loads((RESULT / "status.json").read_text(encoding="utf-8"))
    assert status["DEPLOYMENT_STATUS"] == "NOT_AUTHORIZED_BY_THIS_RUN"
    for key in (
        "POST_HOLDOUT_PARAMETER_CHANGE_COUNT",
        "POST_HOLDOUT_BLEND_CHANGE_COUNT",
        "POST_HOLDOUT_FEATURE_CHANGE_COUNT",
        "POST_HOLDOUT_REGIME_RULE_CHANGE_COUNT",
    ):
        assert status[key] == 0
