from __future__ import annotations

import ast
import importlib.util
import inspect
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r34_frozen_probability_risk_prospective.py"
WRAPPER = Path(__file__).parents[3] / "scripts/fast3/run_fast3_r34_frozen_probability_risk_prospective.ps1"
spec = importlib.util.spec_from_file_location("r34", RUNNER)
r34 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r34)


def prediction_rows(ids=("a", "b"), start="2026-08-10T10:00:00Z") -> pd.DataFrame:
    rows = []
    for index, candidate_id in enumerate(ids):
        row = {column: f"v_{column}" for column in r34.IMMUTABLE_PREDICTION_COLUMNS}
        row.update({
            "candidate_id": candidate_id,
            "decision_timestamp_utc": pd.Timestamp(start) + pd.Timedelta(minutes=index),
            "trading_date": "2026-08-10", "direction": "UP", "underlying": "QQQ",
            "candidate_contract_version": r34.CANDIDATE_CONTRACT_VERSION,
            "T1_raw": 0.1 + index, "P_WIN_CALIBRATED": 0.5, "T5_raw": 0.02,
            "L_LOSER_CALIBRATED": 0.03, "T6_raw": 0.01, "T6_DIAGNOSTIC_PERCENTILE": 0.5,
        })
        rows.append(row)
    return pd.DataFrame(rows)


def candidate_frame(features: list[str], timestamps: list[str]) -> pd.DataFrame:
    rows = []
    for index, raw_timestamp in enumerate(timestamps):
        timestamp = pd.Timestamp(raw_timestamp)
        row = {feature: 0.0 for feature in features}
        row.update({
            "candidate_id": f"c{index}", "decision_timestamp_utc": timestamp,
            "max_feature_timestamp_utc": timestamp, "trading_date": str(timestamp.date()),
            "direction": "UP", "underlying": "QQQ",
            "candidate_contract_version": r34.CANDIDATE_CONTRACT_VERSION,
        })
        rows.append(row)
    return pd.DataFrame(rows)


def test_r33_closeout_and_parent_stop_are_exact_and_immutable() -> None:
    closeout = r34.reconcile_r33_closeout()
    assert r34.sha256(r34.R33_CLOSEOUT) == "9763c4f775940eb5a1b51fc48b4f4e002d2740c8db06e369531a5ae6a31a078b"
    assert closeout["R33_RESEARCH_PHASE_STATUS"] == "CLOSED"
    assert closeout["AUTHORITATIVE_HEAD_SET"] == ["T1", "T5", "T6"]
    assert closeout["T7_STATUS"] == "REJECTED_REDUNDANT_WITH_T5"
    parent = r34.read_json(r34.PARENT_R34_SUMMARY)
    assert parent["FAST3_R34_STATUS"] == r34.PARENT_R34_STATUS
    assert parent["R34_PROSPECTIVE_START_UTC"] == "NOT_CREATED"


def test_r35_manifest_models_and_feature_hashes_are_exact() -> None:
    models, audit = r34.recover_frozen_inference_artifacts()
    assert r34.sha256(r34.R35_MANIFEST) == "f1b9a6f4cce2912bf816cf1949d82d99a556c4eebfebaf4387b719f72d282ffa"
    assert set(models) == {"T1", "T5", "T6"}
    assert all(models[head]["deployment_model_sha256"] == r34.EXPECTED_MODEL_SHA256[head] for head in models)
    assert all(audit[head]["model_hash_match"] for head in audit)
    assert all(audit[head]["feature_manifest_hash_match"] for head in audit)
    assert r34.sha256(r34.FEATURE_MANIFEST) == r34.FEATURE_MANIFEST_SHA256


def test_no_model_fit_or_r35_model_copy_and_t6_is_diagnostic_only() -> None:
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    fits = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "fit"]
    assert fits == []
    source = inspect.getsource(r34.score_candidates)
    assert "copyfile" not in RUNNER.read_text(encoding="utf-8").lower()
    assert "shutil" not in RUNNER.read_text(encoding="utf-8").lower()
    assert 'output["T6_DIAGNOSTIC_PERCENTILE"]' in source
    assert "T6_DECISION" not in source and "filter" not in source.lower()


def test_p_and_l_sources_methods_and_deciles_are_frozen() -> None:
    timestamps = pd.Series(pd.date_range("2025-01-01", periods=100, freq="h", tz="UTC"))
    scores = pd.Series(np.arange(100, dtype=float))
    targets = pd.Series(np.linspace(0.1, 0.9, 100))
    cutoff = pd.Timestamp("2026-08-10T10:00:00Z")
    for component in ("P", "L"):
        mapping = r34.build_empirical_decile_mapping(scores, targets, timestamps, cutoff, component)
        assert mapping["method"] == "R33I_FIXED_EMPIRICAL_DECILES"
        assert mapping["bucket_count"] == 10 and len(mapping["bucket_boundaries"]) == 9
        assert mapping["daily_update_allowed"] is False and mapping["search_count"] == 0
        assert np.isfinite(r34.apply_frozen_mapping(pd.Series([0.0, 99.0]), mapping)).all()
    prereg = r34.r34r_preregistration("2026-08-10T10:00:00Z")
    assert prereg["P_SOURCE"] == "T1" and prereg["L_SOURCE"] == "T5"
    assert prereg["T6_ROLE"] == "DIAGNOSTIC_ONLY"
    assert prereg["P_BUCKET_COUNT"] == prereg["L_BUCKET_COUNT"] == 10


def test_calibration_lineage_population_is_frozen_and_final_free() -> None:
    frame = r34.load_calibration_population()
    assert len(frame) == 984_049 and not frame.candidate_id.duplicated().any()
    assert int(frame.raw_net20.lt(0).sum()) == 455_413
    assert r34.sha256(r34.R33I_CONTRACT) == r34.R33I_CONTRACT_SHA256
    assert r34.sha256(r34.R33I_OOF) == r34.R33I_OOF_SHA256
    assert frame.decision_timestamp_utc.max() < pd.Timestamp(datetime.now(timezone.utc))


def test_preregistration_precedes_calibration_and_start_is_created_last() -> None:
    source = inspect.getsource(r34.initialize_activation)
    fresh = source[source.index("started = datetime.now"):]
    assert fresh.index("write_json_once(prereg_path") < fresh.index("build_empirical_decile_mapping(")
    assert fresh.index("write_json_once(p_path") < fresh.index("prospective_start = datetime.now")
    assert fresh.index("write_json_once(l_path") < fresh.index("prospective_start = datetime.now")
    assert fresh.index("activation_scorer_sanity(") < fresh.index("prospective_start = datetime.now")
    assert fresh.index("prospective_start = datetime.now") < fresh.index("write_json_once(contract_path")
    pending = source[:source.index("started = datetime.now")]
    assert pending.index("read_json(p_path)") < pending.index("activation_scorer_sanity(")
    assert pending.index("activation_scorer_sanity(") < pending.index("prospective_start = datetime.now")
    assert pending.index("prospective_start = datetime.now") < pending.index("write_json_once(contract_path")
    start = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    assert start.endswith("Z") and "T" in start


def test_pre_start_rows_are_excluded_and_future_features_fail_closed() -> None:
    models, _ = r34.recover_frozen_inference_artifacts()
    features = models["T1"]["contract"]["feature_column_order"]
    frame = candidate_frame(features, ["2026-08-10T09:59:00Z", "2026-08-10T10:01:00Z"])
    legal, excluded, future = r34.validate_candidate_input(frame, features, pd.Timestamp("2026-08-10T10:00:00Z"))
    assert excluded == 1 and future == 0 and legal.candidate_id.tolist() == ["c1"]
    bad = frame.iloc[[1]].copy()
    bad["max_feature_timestamp_utc"] = pd.Timestamp("2026-08-10T10:02:00Z")
    with pytest.raises(r34.R34Stop, match="STOPPED_PIT_VIOLATION"):
        r34.validate_candidate_input(bad, features, pd.Timestamp("2026-08-10T10:00:00Z"))


def test_sanity_fixture_never_enters_ledger_and_scorer_feature_projection_hides_outcomes() -> None:
    frame = pd.DataFrame({"f1": [1.0], "f2": [2.0], "canonical_realized_payoff": [0.1], "future_price": [999.0]})
    first = r34.prepare_scorer_features(frame, ["f1", "f2"])
    frame.loc[:, ["canonical_realized_payoff", "future_price"]] = [-99.0, -99.0]
    second = r34.prepare_scorer_features(frame, ["f1", "f2"])
    assert first.equals(second) and not r34.SCORER_PROHIBITED_COLUMNS.intersection(first.columns)
    source = inspect.getsource(r34.activation_scorer_sanity)
    assert "append_only_predictions" not in source and "CANONICAL_LEDGER" not in source


def test_append_only_ledger_is_idempotent_duplicate_free_and_prediction_immutable() -> None:
    empty = pd.DataFrame(columns=r34.LEDGER_COLUMNS)
    first, added_first = r34.append_only_predictions(empty, prediction_rows())
    immutable = first[list(r34.IMMUTABLE_PREDICTION_COLUMNS)].copy(deep=True)
    second, added_second = r34.append_only_predictions(first, prediction_rows())
    assert added_first == 2 and added_second == 0
    assert immutable.equals(second[list(r34.IMMUTABLE_PREDICTION_COLUMNS)])
    assert second.candidate_id.duplicated().sum() == 0
    assert second.outcome_status.eq("PENDING").all()


def test_outcomes_reconcile_only_after_maturity_without_prediction_rewrite() -> None:
    ledger, _ = r34.append_only_predictions(pd.DataFrame(columns=r34.LEDGER_COLUMNS), prediction_rows(("a",)))
    outcomes = pd.DataFrame({
        "candidate_id": ["a"], "outcome_maturity_timestamp": [pd.Timestamp("2026-08-11T10:00:00Z")],
        "canonical_realized_payoff": [0.02], "winner_indicator": [True],
        "winner_gain_magnitude": [0.02], "loser_loss_magnitude": [np.nan],
    })
    before = ledger[list(r34.IMMUTABLE_PREDICTION_COLUMNS)].copy(deep=True)
    early, early_count = r34.reconcile_mature_outcomes(ledger, outcomes, pd.Timestamp("2026-08-10T10:00:00Z"))
    late, late_count = r34.reconcile_mature_outcomes(ledger, outcomes, pd.Timestamp("2026-08-12T10:00:00Z"))
    assert early_count == 0 and early.outcome_status.iloc[0] == "PENDING"
    assert late_count == 1 and late.outcome_status.iloc[0] == "MATURED"
    assert before.equals(late[list(r34.IMMUTABLE_PREDICTION_COLUMNS)])


def test_no_ev_relative_score_weight_threshold_selection_trading_broker_or_final() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    required_zero = (
        '"MODEL_FIT_COUNT": 0', '"GAIN_CALIBRATION_RETRY_COUNT": 0',
        '"T6_ECONOMIC_LEVEL_MAPPING_COUNT": 0', '"T6_DECISION_USE_COUNT": 0',
        '"ABSOLUTE_EV_CONSTRUCTION_COUNT": 0', '"RELATIVE_SCORE_CONSTRUCTION_COUNT": 0',
        '"EV_SCORE_CONSTRUCTION_COUNT": 0', '"EV_COMBINATION_SEARCH_COUNT": 0',
        '"WEIGHT_SEARCH_COUNT": 0', '"THRESHOLD_SEARCH_COUNT": 0',
        '"SIGNAL_SELECTION_COUNT": 0', '"TRADING_SIMULATION_COUNT": 0',
        '"EXECUTION_SIMULATION_COUNT": 0', '"POSITION_SIZING_SEARCH_COUNT": 0',
    )
    assert all(value in source for value in required_zero)
    assert '"BROKER_ACTION_ALLOWED": False' in source
    assert '"TRADE_SELECTION_ALLOWED": False' in source
    assert '"FINAL_CONFIRMATION_DATA_LOADED": False' in source
    assert '"FINAL_HOLDOUT_INSPECTED": False' in source


def test_prospective_contract_freezes_roles_hashes_and_prohibitions() -> None:
    contract = r34.prospective_contract(
        "2026-08-10T10:00:00.000000Z", Path("p.json"), "p" * 64,
        Path("l.json"), "l" * 64, {"reference_values": [0.0], "decision_use_allowed": False},
    )
    assert contract["T1_role"] == "CALIBRATED_WIN_PROBABILITY_SOURCE"
    assert contract["T5_role"] == "CALIBRATED_CONDITIONAL_LOSS_SOURCE"
    assert contract["T6_role"] == "DIAGNOSTIC_ONLY" and contract["T6_decision_use_allowed"] is False
    assert contract["absolute_ev_allowed"] is False and contract["relative_score_allowed"] is False
    assert contract["calibration_update_allowed"] is False and contract["final_data_prohibited"] is True


def test_single_daily_launcher_source_anti_bloat_and_external_storage() -> None:
    r34.validate_storage_contract()
    wrapper = WRAPPER.read_text(encoding="utf-8")
    assert "-Execute" in wrapper and "--execute" in wrapper
    repo = Path(__file__).parents[3]
    launchers = [path for path in (repo / "scripts/fast3").glob("*r34*.ps1") if path.is_file()]
    assert launchers == [WRAPPER]
    r34_sources = [
        path.resolve() for path in repo.rglob("*r34*frozen_probability_risk_prospective*.py") if path.is_file()
    ]
    assert set(r34_sources) == {RUNNER.resolve(), Path(__file__).resolve()}
    assert r34.RESULTS_ROOT == Path(r"D:\us-tech-quant-results")
    assert r34.R35_ROOT.is_relative_to(r34.RESULTS_ROOT)


def test_allowed_r34r_status_enum_is_closed() -> None:
    assert r34.ALLOWED_R34R_STATUSES == {
        "PASS", "STOPPED_R33_CLOSEOUT_HASH_MISMATCH",
        "STOPPED_R35_DEPLOYMENT_MANIFEST_HASH_MISMATCH", "STOPPED_DEPLOYMENT_MODEL_HASH_MISMATCH",
        "STOPPED_FEATURE_MANIFEST_HASH_MISMATCH", "STOPPED_CALIBRATION_LINEAGE_NOT_RECOVERABLE",
        "STOPPED_DATA_OR_LINEAGE_INTEGRITY", "STOPPED_PIT_VIOLATION",
        "STOPPED_STORAGE_CONTRACT_VIOLATION", "STOPPED_PREREGISTRATION_ORDER_VIOLATION",
        "STOPPED_ANTI_BLOAT_VIOLATION",
    }
    assert "PARTIAL_READY" not in r34.ALLOWED_R34R_STATUSES
