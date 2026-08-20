from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r40_target_payoff_contract_independence_audit_r1.py"
SPEC = importlib.util.spec_from_file_location("r40", SCRIPT)
R = importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(R)


def test_preregistration_freezes_zero_model_zero_payoff_research():
    contract = R.preregistration("fixed")
    assert not contract["MODEL_TRAINING_ALLOWED"] and not contract["MODEL_PREDICTION_ALLOWED"]
    assert not contract["NEW_FEATURE_ALLOWED"] and not contract["NEW_PAYOFF_CONTRACT_ALLOWED"]
    assert not contract["COUNTERFACTUAL_SIMULATION_ALLOWED"] and not contract["PARAMETER_OPTIMIZATION_ALLOWED"]


def test_all_authoritative_hashes_are_exact():
    paths = {
        "PHASE2_DECISION": R.PHASE2_DECISION, "PHASE2_LINEAGE": R.PHASE2_LINEAGE,
        "R28G_LEDGER": R.R28G_LEDGER, "R28E_LEDGER": R.R28E_LEDGER,
        "R36_SUMMARY": R.R36_SUMMARY, "R39_SUMMARY": R.R39_SUMMARY,
        "UP_LEDGER": R.SCORE_ROOT / "R28_3_CROSS_ASSET_FLOW_UP_IMMUTABLE_VALIDATION_LEDGER.parquet",
        "DOWN_LEDGER": R.SCORE_ROOT / "R28_3_CROSS_ASSET_FLOW_DOWN_IMMUTABLE_VALIDATION_LEDGER.parquet",
        "TARGET_SOURCE": R.TARGET_SOURCE, "FIRST_TOUCH_SOURCE": R.FIRST_TOUCH_SOURCE,
        "CORRECTION_SOURCE": R.CORRECTION_SOURCE, "PAYOFF_SOURCE": R.PAYOFF_SOURCE,
    }
    assert {name: R.sha256(path) for name, path in paths.items()} == R.EXPECTED


def test_authoritative_definition_registry_is_complete_and_not_guessed():
    table = R.authoritative_definitions()
    assert len(table) == 10 and table.CONTRACT_ITEM.nunique() == 10
    assert table.SOURCE_FILE.map(Path.is_file).all()
    assert set(table.CONTRACT_ITEM) == {"TARGET_FIRST", "UP_DOWN_TARGET_EVENT", "FAVORABLE_PROFIT_BARRIER",
                                        "COMPETING_ADVERSE_BARRIER", "FIRST_TOUCH_EXIT_TIMESTAMP", "ENTRY_PRICE",
                                        "EXIT_PRICE", "GROSS_RETURN", "NET20", "CORPORATE_ACTION_NORMALIZED_PAYOFF"}


def test_dependency_matrix_has_only_fixed_rows_columns_and_labels():
    matrix = R.dependency_matrix()
    assert matrix.columns.tolist() == ["DEPENDENCY_SOURCE", "target_first", "exit_ts", "exit_price", "NET20"]
    assert matrix.DEPENDENCY_SOURCE.tolist() == ["decision-time features", "target_first", "first_touch contract", "profit barrier", "loss barrier"]
    assert set(matrix.iloc[:, 1:].stack()) <= {"NONE", "DIRECT", "INDIRECT", "SHARED_CONSTRUCTION"}


def test_mechanical_target_payoff_identities_and_classification():
    frame, _, r36, hashes = R.verify_inputs(); summary = R.audit(frame, r36, hashes)
    assert len(frame) == 1197
    assert summary["TARGET1_TOUCH_TS_EQUALS_EXIT_TS_COUNT"] == 613
    assert summary["TARGET1_TOUCH_TS_EQUALS_EXIT_TS_RATE"] == 1
    assert summary["TARGET0_COMPETING_TS_AVAILABLE_COUNT"] == 479
    assert summary["TARGET0_COMPETING_TS_EQUALS_EXIT_TS_COUNT"] == 0
    assert summary["FAST3_R40_CLASSIFICATION"] == "C_TARGET_PAYOFF_MECHANICALLY_COUPLED"
    assert summary["NET20_DEPENDS_ON_TARGET_FIRST_INDIRECTLY"] and not summary["NET20_DEPENDS_ON_TARGET_FIRST_DIRECTLY"]


def test_predictive_edge_is_preserved_but_r37_not_independent():
    frame, _, r36, hashes = R.verify_inputs(); summary = R.audit(frame, r36, hashes)
    assert summary["R28_PREDICTIVE_EDGE_VALID"]
    assert summary["PREDICTIVE_LEAKAGE_STATUS"] == "PASS"
    assert not summary["R37_TARGET_PAYOFF_COMPARISON_INDEPENDENT_VALIDATION"]
    assert summary["R37_ECONOMIC_ALIGNMENT_EVIDENCE_STATUS"] == "INVALID_AS_INDEPENDENT_EVIDENCE"
    assert summary["INDEPENDENT_ECONOMIC_EVALUATION_EXISTS"]
    assert summary["INDEPENDENT_ECONOMIC_EDGE_STATUS"] == "NOT_ESTABLISHED"


def test_no_model_prediction_search_final_or_new_payoff_contract():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (".fit(", ".predict(", "GridSearchCV", "RandomizedSearchCV", "counterfactual_return"):
        assert forbidden not in source
    assert '"MODEL_FIT_COUNT": 0' in source and '"MODEL_PREDICT_CALL_COUNT": 0' in source
    assert '"MAX_NEW_PAYOFF_CONTRACT_COUNT": 0' in source and '"FINAL_CONFIRMATION_DATA_USED": False' in source
    assert R.RESULTS == Path(r"D:\us-tech-quant-results")


def test_allowed_classification_enum_only():
    assert len(R.CLASSIFICATIONS) == 5
    assert "C_TARGET_PAYOFF_MECHANICALLY_COUPLED" in R.CLASSIFICATIONS
    assert "E_INVALID_CONTRACT_IDENTITY" in R.CLASSIFICATIONS
