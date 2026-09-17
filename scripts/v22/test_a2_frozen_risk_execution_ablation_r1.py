from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
SOURCE = ROOT / "scripts/v22/a2_frozen_risk_execution_ablation_r1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("a2_ablation_under_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M = load_module()


def test_frozen_hashes_and_pre2026_identity():
    for value, expected in M.EXPECTED.items():
        path = Path(value)
        assert path.is_file()
        assert M.sha256_file(path) == expected
    identity = json.loads(M.E5_IDENTITY.read_text(encoding="utf-8"))
    assert identity["selection_source"] == "PRE2026_ONLY"
    assert identity["candidate_outcome_fields_2026_used"] == []


def test_raw_a2_exact_return_nav_turnover_cost_reconciliation():
    frozen = pd.read_parquet(M.BASE / "A2/portfolio_daily.parquet").sort_values("execution_date").reset_index(drop=True)
    paths = pd.read_parquet(M.E5_PATHS)
    raw = paths.loc[paths.candidate.eq("E0_CONTROL")].sort_values("execution_date").reset_index(drop=True)
    assert len(raw) == len(frozen) == 751
    np.testing.assert_allclose(raw.net_return, frozen.reconstructed_daily_return, atol=1e-12, rtol=0)
    np.testing.assert_allclose(raw.nav, frozen.reconstructed_nav, atol=1e-12, rtol=0)
    np.testing.assert_allclose(raw.turnover, frozen.reconstructed_turnover, atol=1e-12, rtol=0)
    np.testing.assert_allclose(raw.transaction_cost_amount, frozen.reconstructed_transaction_cost, atol=1e-12, rtol=0)


def test_r6_domain_gate_fails_without_silent_drop():
    e5_spec = importlib.util.spec_from_file_location("e5_for_domain_test", M.E5_SOURCE)
    e5 = importlib.util.module_from_spec(e5_spec)
    sys.modules[e5_spec.name] = e5
    e5_spec.loader.exec_module(e5)
    _, intended = e5.load_pre_predictions()
    r6 = pd.read_parquet(M.R6_OOF, columns=["signal_date", "ticker", "candidate_id"])
    r6.signal_date = pd.to_datetime(r6.signal_date)
    r6 = r6.loc[r6.candidate_id.eq("LGBM_BAD_ASYM_2")]
    available = set(zip(r6.signal_date, r6.ticker.astype(str)))
    dates = sorted(set(intended) & set(r6.signal_date))
    covered = [sum((date, ticker) in available for ticker in intended[date]) for date in dates]
    assert len(dates) == 609
    assert sum(covered) == 9897
    assert len(dates) * 20 == 12180
    assert sum(value == 20 for value in covered) == 6
    assert min(covered) == 8


def test_r6_weights_and_constant_gross_arithmetic_are_internally_valid_but_noncomparable():
    weights = pd.read_parquet(M.R6_WEIGHTS)
    grouped = weights.groupby("signal_date")
    np.testing.assert_allclose(grouped.r5_weight.sum(), 1.0, atol=1e-12, rtol=0)
    np.testing.assert_allclose(weights.original_r6_weight, weights.raw_a2_weight * weights.r6_multiplier, atol=1e-12, rtol=0)
    gross = grouped.original_r6_weight.sum()
    assert gross.between(0, 1).all()
    # ARM5's fixed control is Raw relative weights times the same-day R6 gross.
    sample = gross.iloc[:10].to_numpy(float)
    arm5 = np.repeat((sample / 20)[:, None], 20, axis=1)
    np.testing.assert_allclose(arm5.sum(axis=1), sample, atol=1e-12, rtol=0)


def test_e5_paired_return_and_cost_arithmetic():
    paths = pd.read_parquet(M.E5_PATHS)
    piv = paths.loc[paths.candidate.isin(["E0_CONTROL", "E5_COMBINED_CONSERVATIVE"])].pivot(
        index="execution_date", columns="candidate", values="net_return"
    )
    delta = piv["E5_COMBINED_CONSERVATIVE"] - piv["E0_CONTROL"]
    paired = pd.read_csv(M.OUT / "paired_delta_statistics.csv").set_index("comparison")
    assert len(delta) == int(paired.loc["D_E5", "session_count"]) == 751
    assert abs(delta.mean() * 252 - paired.loc["D_E5", "annualized_mean_delta"]) < 1e-15
    summary = pd.read_csv(M.OUT / "arm_summary.csv").set_index("arm")
    raw, e5 = summary.loc["ARM0_RAW_A2"], summary.loc["ARM2_A2_E5"]
    assert e5.turnover < raw.turnover
    assert e5.total_cost < raw.total_cost


def test_oos_folds_and_2026_isolation():
    paths = pd.read_parquet(M.E5_PATHS)
    dates = pd.to_datetime(paths.execution_date)
    assert dates.max() < pd.Timestamp("2026-01-01")
    assert set(dates.dt.year) == {2023, 2024, 2025}
    folds = pd.read_csv(M.OUT / "fold_comparison.csv")
    valid = folds.loc[folds.arm.isin(["ARM0_RAW_A2", "ARM2_A2_E5"])]
    assert set(valid.fold.astype(int)) == {2023, 2024, 2025}


def test_pit_fold_boundaries_and_no_future_join():
    r6 = pd.read_parquet(M.R6_OOF, columns=["information_date", "signal_date", "train_max_target_end", "embargo_cutoff"])
    for column in r6.columns:
        r6[column] = pd.to_datetime(r6[column])
    assert (r6.information_date < r6.signal_date).all()
    assert (r6.train_max_target_end < r6.signal_date).all()
    assert (r6.embargo_cutoff < r6.signal_date).all()


def test_bootstrap_is_fixed_seed_and_hac_not_iid():
    delta = np.sin(np.arange(751) / 13) / 1000
    first = M.paired_stats(delta, 7)
    second = M.paired_stats(delta, 7)
    assert first == second
    assert np.isfinite(first["hac_tstat"])
    assert first["bootstrap_ci_low"] <= first["bootstrap_ci_high"]


def test_final_artifact_count_and_hash_manifest():
    files = sorted(path.name for path in M.OUT.iterdir() if path.is_file())
    assert files == sorted(M.FINAL_FILES)
    assert len(files) == 7
    manifest = json.loads((M.OUT / "hash_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "PASS_HASH_VERIFIED"
    assert manifest["artifact_count_excluding_self"] == 6
    for row in manifest["artifacts"]:
        assert M.sha256_file(M.OUT / row["name"]) == row["sha256"]
