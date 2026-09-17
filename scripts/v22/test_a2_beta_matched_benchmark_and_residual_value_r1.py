from __future__ import annotations

import hashlib
import importlib.util
import json

import numpy as np
import pandas as pd


SCRIPT = __file__.replace("test_a2_beta_matched_benchmark_and_residual_value_r1.py", "a2_beta_matched_benchmark_and_residual_value_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_beta_match_test_target", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
SHARED = MOD.import_file("a2_beta_match_test_shared", MOD.SHARED_SOURCE)


def authoritative_daily() -> pd.DataFrame:
    frame = pd.read_parquet(MOD.BASE / "A2/portfolio_daily.parquet").sort_values("execution_date").reset_index(drop=True)
    frame["execution_date"] = pd.to_datetime(frame.execution_date).dt.normalize()
    return frame


def test_a2_authoritative_path_reconciliation() -> None:
    daily = authoritative_daily()
    upstream = json.loads((MOD.UPSTREAM / "robustness_classification.json").read_text(encoding="utf-8"))
    result = SHARED.metrics(daily.reconstructed_daily_return)
    for key in ["cumulative_return", "cagr", "sharpe", "max_drawdown"]:
        assert abs(result[key] - upstream["baseline"][key]) <= 1e-12
    np.testing.assert_allclose(np.cumprod(1 + daily.reconstructed_daily_return), daily.reconstructed_nav, atol=1e-12, rtol=0)


def test_qqq_date_alignment_and_no_future_join() -> None:
    daily = authoritative_daily()
    benchmark, _ = SHARED.benchmark_frame(daily.execution_date)
    assert benchmark.execution_date.tolist() == daily.execution_date.tolist()
    assert benchmark.QQQ.notna().all()
    assert benchmark.execution_date.max() < pd.Timestamp("2026-01-01")


def test_beta_recomputation() -> None:
    daily = authoritative_daily()
    benchmark, _ = SHARED.benchmark_frame(daily.execution_date)
    observed = MOD.beta(daily.reconstructed_daily_return.to_numpy(float), benchmark.QQQ.to_numpy(float))
    assert abs(observed - 1.391504622347692) <= 1e-12


def test_risk_scaling_and_leveraged_return_arithmetic() -> None:
    qqq = np.array([.01, -.02, .03])
    scale = 1.4
    np.testing.assert_allclose(scale * qqq, [.014, -.028, .042], atol=0, rtol=1e-15)
    assert abs(np.prod(1 + scale * qqq) - ((1.014) * (.972) * (1.042))) < 1e-15


def test_active_return_identity() -> None:
    a2 = np.array([.02, -.01, .03])
    bm = np.array([.01, -.02, .04])
    active = a2 - bm
    np.testing.assert_allclose(active + bm, a2, atol=0, rtol=0)
    result = MOD.active_metrics(active)
    assert abs(result["active_cumulative_return"] - (np.prod(1 + active) - 1)) < 1e-15


def test_oos_fold_boundaries_and_2026_isolation() -> None:
    oof = pd.read_parquet(MOD.BASE / "A2/oof_predictions.parquet", columns=["signal_date", "split"])
    oof["signal_date"] = pd.to_datetime(oof.signal_date)
    expected = {2023: "DEVELOPMENT", 2024: "CONFIRMATION", 2025: "FINAL"}
    assert set(oof.signal_date.dt.year) == set(expected)
    assert all(set(oof.loc[oof.signal_date.dt.year.eq(year), "split"]) == {split} for year, split in expected.items())
    assert oof.signal_date.max() < pd.Timestamp("2026-01-01")


def test_hac_and_bootstrap_fixed_seed() -> None:
    active = np.linspace(-.01, .012, 251)
    first = MOD.bootstrap_active(SHARED, active)
    second = MOD.bootstrap_active(SHARED, active)
    assert first == second
    assert MOD.hac_mean(SHARED, active) == MOD.hac_mean(SHARED, active)


def test_leave_one_period_out_arithmetic() -> None:
    dates = pd.to_datetime(["2023-01-03", "2023-01-04", "2024-01-03", "2025-01-03"])
    active = np.array([.01, .02, -.01, .03])
    keep = dates.year != 2023
    expected = np.prod(1 + active[keep]) - 1
    assert abs(MOD.active_metrics(active[keep])["active_cumulative_return"] - expected) < 1e-15


def test_preregistration_hash_is_frozen() -> None:
    observed = hashlib.sha256(MOD.canonical_json(MOD.PREREGISTRATION).encode("utf-8")).hexdigest()
    assert observed == "1f65b5376fe2b2b2c9ccd10fdecad9e3f0fa860e687db7d2af8ca347030bb5af"


def test_final_artifact_count_and_hashes() -> None:
    files = sorted(p.name for p in MOD.OUT.iterdir() if p.is_file())
    assert files == sorted(MOD.FINAL_FILES)
    assert len(files) == 6
    manifest = json.loads((MOD.OUT / "hash_manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_count_including_manifest"] == 6
    for row in manifest["artifacts"]:
        path = MOD.OUT / row["name"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
