from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SCRIPT = Path(r"D:\us-tech-quant\scripts\v22\a2_risk_os_r2.py")
OUTPUT = Path(r"D:\us-tech-quant-results\A2_RISK_OS_R2")
spec = importlib.util.spec_from_file_location("a2_risk_os_r2_tested", SCRIPT)
assert spec and spec.loader
R = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = R
spec.loader.exec_module(R)


def _json(name: str):
    return json.loads((OUTPUT / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def reconstructed():
    weights, positions, base_daily = R.base_inputs()
    targets = R.forward_targets(weights.signal_date.drop_duplicates(), base_daily)
    features, manifest, families = R.feature_table(weights, base_daily)
    panel = features.merge(targets, on="signal_date", validate="one_to_one")
    folds, _ = R.folds(panel)
    return weights, positions, base_daily, targets, features, manifest, families, panel, folds


def test_frozen_a2_r6_and_r1_identity():
    identity = R.frozen_identity()
    assert identity["r1_contract_sha256"] == R.R1_CONTRACT_SHA256
    assert identity["r6_oof_sha256"] == R.R1.R6_OOF_SHA256
    assert identity["r6_deploy_sha256"] == R.R1.R6_DEPLOY_SHA256
    assert identity["verified_a2_artifact_count"] == 46


def test_contract_is_frozen_and_contains_no_search():
    contract = _json("risk_os_r2_contract.json")
    assert R.sha256_file(OUTPUT / "risk_os_r2_contract.json") == "b486f6f194741b475fbedc7485639350eab9e31a36b48a15db034c836b044411"
    assert contract["primary_target"]["horizon_sessions"] == 20
    assert contract["parameter_search_count"] == 0
    assert contract["threshold_search_count"] == 0
    assert contract["primary_exposure_mapping"] == [[.60, 1.0], [.80, .90], [.95, .75], [1.01, .60]]


def test_no_2026_training_or_outcome_reads():
    audit = _json("risk_os_r2_audit.json")
    assert audit["2026_training_rows"] == 0
    assert audit["2026_outcome_read_count"] == 0
    assert audit["2026_R2_OUTCOME_READ_COUNT"] == 0
    assert audit["2026_parameter_search_count"] == 0
    assert audit["2026_threshold_search_count"] == 0


def test_target_is_future_only_and_exact_20_sessions(reconstructed):
    _, _, base_daily, targets, *_ = reconstructed
    returns = base_daily.set_index("date").daily_return.sort_index()
    for row in targets.iloc[::50].itertuples(index=False):
        future = returns.loc[returns.index > row.signal_date].iloc[:20]
        assert len(future) == 20
        assert future.index.min() > row.signal_date
        assert future.index[-1] == row.target_end_date
        expected = -float(((1 + future).cumprod() - 1).min())
        assert np.isclose(expected, row.Y_RISK_20, atol=0, rtol=0)
    assert targets.target_end_date.lt(pd.Timestamp("2026-01-01")).all()


def test_portfolio_date_unit_unique_and_features_pit_safe(reconstructed):
    *_, features, manifest, families, panel, _folds = reconstructed
    assert not panel.signal_date.duplicated().any()
    assert panel.information_date.lt(panel.signal_date).all()
    assert panel.signal_date.lt(pd.Timestamp("2026-01-01")).all()
    included = [row for row in manifest if row["included"]]
    assert all(row["pit_proof"] == "PASS_BACKWARD_LOOKING_ASOF_INFORMATION_DATE" for row in included)
    assert sum(len(value) for value in families.values()) == len(included)


def test_purge_embargo_and_fold_identity(reconstructed):
    *_, panel, folds = reconstructed
    assert len(folds) == 4
    for fold in folds:
        start = pd.Timestamp(fold["validation_start"])
        train = panel.loc[(panel.signal_date < start) & (panel.target_end_date < start)]
        valid = panel.loc[panel.signal_date.between(fold["validation_start"], fold["validation_end"])]
        assert train.target_end_date.max() < valid.signal_date.min()
        assert fold["overlap_leakage_count"] == 0


def test_train_only_preprocessing_percentile_and_reproducibility(reconstructed):
    *_, families, panel, folds = reconstructed
    features = sum(families.values(), [])
    candidate = next(item for item in R.candidates() if item.name == "RIDGE_FIXED")
    first, fits = R.run_candidate(panel, features, candidate, folds)
    second, _ = R.run_candidate(panel, features, candidate, folds)
    pd.testing.assert_frame_equal(first[["signal_date", "prediction", "risk_percentile"]], second[["signal_date", "prediction", "risk_percentile"]], check_exact=True)
    saved = pd.read_parquet(OUTPUT / "risk_os_r2_oof_predictions.parquet")
    pd.testing.assert_frame_equal(first[["signal_date", "prediction", "risk_percentile"]].reset_index(drop=True), saved[["signal_date", "prediction", "risk_percentile"]].reset_index(drop=True), check_exact=True)
    model, train, valid = fits[0]
    expected_medians = train[features].median().to_numpy(float)
    assert np.allclose(model.named_steps["impute"].statistics_, expected_medians, equal_nan=True)
    expected = R.empirical_percentile(model.predict(train[features]), model.predict(valid[features]))
    assert np.array_equal(expected, valid.risk_percentile.to_numpy())


def test_exposure_mapping_is_deterministic_and_never_levers():
    oof = pd.read_parquet(OUTPUT / "risk_os_r2_oof_predictions.parquet")
    first = R.mapping(oof.risk_percentile, R.PRIMARY_MAPPING)
    second = R.mapping(oof.risk_percentile, R.PRIMARY_MAPPING)
    assert np.array_equal(first, second)
    assert first.max() == 1.0
    assert set(first).issubset({1.0, .9, .75, .6})


def test_matched_exposure_is_exact_and_weights_nonnegative():
    audit = _json("risk_os_r2_audit.json")
    matched = pd.read_csv(OUTPUT / "risk_os_r2_matched_exposure.csv")
    assert audit["matched_exposure_error"] < 1e-12
    # The first target initializes the simulator and produces no evaluated
    # return.  Exposure matching is exact on the economically evaluated dates.
    evaluated = matched.iloc[1:]
    assert np.allclose(evaluated.dynamic.groupby(evaluated.fold).mean(), evaluated.matched.groupby(evaluated.fold).mean(), atol=1e-12)
    assert (matched[["base", "dynamic", "matched"]] >= 0).all().all()


def test_placebo_preserves_preregistered_timing_structure():
    placebo = pd.read_csv(OUTPUT / "risk_os_r2_placebo_summary.csv")
    assert len(placebo) == 300
    assert placebo.circular_shift.between(20, 505).all()
    assert placebo.permutation.nunique() == 300


def test_cost_accounting_and_sensitivity_cases_complete():
    economic = pd.read_csv(OUTPUT / "risk_os_r2_economic_metrics.csv")
    assert set(economic.cost_case) == {"BASELINE", "TWO_X", "ADVERSE"}
    assert set(economic.cost_rate) == {.001, .002, .003}
    assert len(economic) == 15
    assert np.allclose(economic.transaction_cost_proxy, economic.turnover * economic.cost_rate)


def test_source_fingerprints_and_frozen_artifacts_reproducible():
    run = _json("risk_os_r2_run_manifest.json")
    for path, expected in run["source_fingerprints"].items():
        assert R.sha256_file(Path(path)) == expected
    assert R.sha256_file(R.R1_CONTRACT) == R.R1_CONTRACT_SHA256


def test_final_gate_stops_before_2026():
    summary = _json("risk_os_r2_final_summary.json")
    audit = _json("risk_os_r2_audit.json")
    assert summary["A2_RISK_OS_R2_PRE2026_CLASSIFICATION"] == "D_NO_USEFUL_TIMING_SIGNAL"
    assert summary["A2_RISK_OS_R2_2026_AUTHORIZED"] is False
    assert summary["2026_R2_OUTCOME_READ_COUNT"] == 0
    assert audit["anti_bloat"]["new_r2_violation_count"] == 0
    assert summary["NEXT_AUTHORIZED_STEP"] == "PRESERVE_R2_RESEARCH_HISTORY_AND_STOP;DO_NOT_OPEN_2026"
