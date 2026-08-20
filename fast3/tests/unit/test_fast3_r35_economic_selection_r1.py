from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r35_economic_selection_r1.py"
SPEC = importlib.util.spec_from_file_location("r35eco", SCRIPT)
R = importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(R)


def tiny_frame(n: int = 100) -> pd.DataFrame:
    time = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"candidate_id": [f"c{i:03}" for i in range(n)], "decision_timestamp_utc": time,
                         "fold": np.where(np.arange(n) < n // 2, "F1", "F2"), "head": np.where(np.arange(n) % 2, "UP", "DOWN"),
                         "raw_net20": np.linspace(-.1, .1, n), "pred": np.linspace(1, 0, n),
                         **{name: np.linspace(0, 1, n) for name in R.FEATURES}})


def test_frozen_inputs_features_targets_and_model_budget():
    assert len(R.BASE_FEATURES) == 14 and len(R.DERIVED_FEATURES) == 4
    assert R.FILTER_EXCLUSIONS == (5, 10, 20)
    assert R.MODEL_PARAMS == {"learning_rate": .05, "max_iter": 100, "max_leaf_nodes": 7,
                              "min_samples_leaf": 20, "l2_regularization": 1.0, "random_state": 1729}


def test_target_and_four_derived_feature_formulas():
    target = pd.DataFrame({"candidate_id": ["a"], "decision_timestamp_utc": pd.to_datetime(["2020-01-01"], utc=True),
                           "raw_net20": [-.03], "head": ["UP"], "label_information_end_utc": pd.to_datetime(["2020-01-02"], utc=True)})
    features = pd.DataFrame({"candidate_id": ["a"], "decision_timestamp_utc": target.decision_timestamp_utc,
        "realized_vol_15m": [.02], "realized_vol_60m": [.01], "return_15m": [-.04], "peer_return_15m": [.01],
        "relative_return_15m": [-.05], "underlying_symbol": ["QQQ"],
        **{name: [0.] for name in R.BASE_FEATURES if name not in {"realized_vol_15m", "realized_vol_60m", "return_15m", "peer_return_15m", "relative_return_15m"}}})
    x = R.add_targets_and_features(target, features)
    assert x.LARGE_LOSS_2PCT.iloc[0] == x.LARGE_LOSS_3PCT.iloc[0] == 1
    assert x.LOSS_SEVERITY.iloc[0] == .03
    assert x.realized_vol_ratio_15m_60m.iloc[0] == 2 and x.abs_return_15m.iloc[0] == .04
    assert x.cross_asset_disagreement_15m.iloc[0] == .05 and x.abs_relative_dislocation_15m.iloc[0] == .05


def test_future_outcome_mutation_cannot_change_feature_identity():
    frame = tiny_frame(); before = R.feature_mutation_hash(frame)
    future = frame.raw_net20.copy(); future.iloc[50:] *= -10
    assert R.feature_mutation_hash(frame, future) == before


def test_fold_local_risk_percentiles_are_deterministic_and_no_outcome_input():
    frame = tiny_frame(); first = R.assign_fold_risk_percentile(frame, "pred"); second = R.assign_fold_risk_percentile(frame, "pred")
    pd.testing.assert_series_equal(first, second)
    assert first.groupby(frame.fold).max().eq(1).all()


def test_filter_rules_are_oof_score_only_and_fixed():
    frame = tiny_frame(); frame["risk_percentile"] = R.assign_fold_risk_percentile(frame, "pred")
    for exclusion in R.FILTER_EXCLUSIONS:
        kept = frame.loc[frame.risk_percentile <= 1 - exclusion / 100]
        assert len(kept) <= len(frame) and "raw_net20" not in R.assign_fold_risk_percentile.__code__.co_names


def test_corporate_action_and_frozen_ledger_hashes():
    assert R.sha256(R.R28_3G_LEDGER) == R.EXPECTED["R28_3G_LEDGER"]
    identity = R.read_json(R.R30A_DATA_IDENTITY)
    assert identity["TARGET_ROW_COUNT"] == 1197 and identity["FINAL_CONFIRMATION_DATA_USED"] is False
    assert R.sha256(Path(identity["TARGET_LEDGER_PATH"])) == R.EXPECTED["R30A_TARGET_LEDGER"]
    assert R.sha256(Path(identity["FEATURE_LEDGER_SOURCE"])) == R.EXPECTED["R30A_FEATURE_LEDGER"]


def test_preregistration_is_no_search_no_final_and_fixed_chronological_folds():
    r30a = R.import_module(R.R30A_RUNNER, "test_r35eco_r30a")
    identity = R.read_json(R.R30A_DATA_IDENTITY); contract = R.preregistration("fixed", identity, r30a)
    assert contract["HYPERPARAMETER_SEARCH_ALLOWED"] is contract["FEATURE_SEARCH_ALLOWED"] is False
    assert contract["FINAL_CONFIRMATION_DATA_ALLOWED"] is False
    assert contract["FOLDS"] == [list(row) for row in r30a.ECONOMIC_FOLDS]
    assert all(int(fold[0].split("_")[1][:4]) >= 2021 for fold in contract["FOLDS"])


def test_pit_chronology_and_classification_enum_guards_are_present():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'feature_time <= decision' in source and 'label_information_end_utc' in source
    assert R.CLASSIFICATIONS == {"A_LOSS_SEVERITY_FILTER_CONFIRMED_POSITIVE_ECONOMIC_EDGE",
        "B_LOSS_SEVERITY_SIGNAL_EXISTS_BUT_ECONOMIC_EDGE_NOT_CONFIRMED",
        "C_NO_USEFUL_LOSS_SEVERITY_SIGNAL", "D_INVALID_RESEARCH_INTEGRITY_FAILURE"}
    assert "GridSearchCV" not in source and "RandomizedSearchCV" not in source and "FINAL_CONFIRMATION_DATA_USED\": False" in source


def test_storage_external_and_no_r28_refit_or_threshold_change():
    assert R.RESULTS_ROOT == Path(r"D:\us-tech-quant-results") and R.SOURCE_ROOT == Path(r"D:\us-tech-quant")
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"R28_REFIT_COUNT": 0' in source and '"R28_THRESHOLD_CHANGE_COUNT": 0' in source
    assert not (R.SOURCE_ROOT / "results").exists()
