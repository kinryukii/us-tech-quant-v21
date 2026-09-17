from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).with_name("a2_strategy_falsification_and_robustness_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_falsification_test_target", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def test_baseline_exact_replay_metrics_and_nav() -> None:
    daily = pd.read_parquet(MOD.BASE / "A2/portfolio_daily.parquet").sort_values("execution_date")
    manifest = json.loads(MOD.FREEZE_MANIFEST.read_text(encoding="utf-8"))
    result = MOD.metrics(daily.reconstructed_daily_return)
    exact = manifest["identity"]["headline_metrics_exact"]
    assert abs(result["cagr"] - exact["A2_CAGR"]) <= 1e-12
    assert abs(result["sharpe"] - exact["A2_SHARPE"]) <= 1e-12
    assert abs(result["max_drawdown"] - exact["A2_MDD"]) <= 1e-12
    np.testing.assert_allclose(
        np.cumprod(1 + daily.reconstructed_daily_return.to_numpy(float)),
        daily.reconstructed_nav.to_numpy(float), atol=1e-12, rtol=0,
    )


def test_historical_oof_hash_verifies_against_frozen_manifest() -> None:
    hashes = pd.read_csv(MOD.FREEZE_HASHES)
    row = hashes.loc[hashes.absolute_path.eq(str(MOD.BASE / "A2/oof_predictions.parquet"))]
    assert len(row) == 1
    actual = hashlib.sha256((MOD.BASE / "A2/oof_predictions.parquet").read_bytes()).hexdigest()
    assert actual == row.sha256.iloc[0]


def test_return_arithmetic() -> None:
    r = np.array([0.10, -0.05, 0.02])
    result = MOD.metrics(r)
    assert abs(result["cumulative_return"] - ((1.10 * 0.95 * 1.02) - 1)) < 1e-15


def test_contribution_subtraction_identity() -> None:
    daily = pd.read_parquet(MOD.BASE / "A2/portfolio_daily.parquet").sort_values("execution_date")
    pos = pd.read_parquet(MOD.BASE / "A2/position_ledger.parquet")
    actual = pos.groupby("date").portfolio_pnl_contribution.sum().reindex(daily.execution_date, fill_value=0).to_numpy(float)
    np.testing.assert_allclose(actual, daily.reconstructed_daily_return.to_numpy(float), atol=1e-12, rtol=0)


def test_benchmark_alignment_is_same_day_and_complete() -> None:
    daily = pd.read_parquet(MOD.BASE / "A2/portfolio_daily.parquet").sort_values("execution_date")
    benchmark, _ = MOD.benchmark_frame(daily.execution_date)
    assert benchmark.execution_date.tolist() == daily.execution_date.tolist()
    assert benchmark[["QQQ", "SOXX", "SPY"]].notna().all().all()


def test_no_future_date_join_and_2026_isolation() -> None:
    oof = pd.read_parquet(MOD.BASE / "A2/oof_predictions.parquet", columns=["signal_date", "split"])
    signal = pd.to_datetime(oof.signal_date)
    assert signal.max() <= pd.Timestamp("2025-12-31")
    daily = pd.read_parquet(MOD.BASE / "A2/portfolio_daily.parquet", columns=["execution_date"])
    execution = pd.to_datetime(daily.execution_date)
    assert execution.max() < pd.Timestamp("2026-01-01")
    assert execution.min() > signal.min()


def test_authoritative_oos_fold_labels_no_2022() -> None:
    oof = pd.read_parquet(MOD.BASE / "A2/oof_predictions.parquet", columns=["signal_date", "split"])
    oof["signal_date"] = pd.to_datetime(oof.signal_date)
    observed = oof.groupby(oof.signal_date.dt.year).split.unique().to_dict()
    assert set(observed) == {2023, 2024, 2025}
    assert set(observed[2023]) == {"DEVELOPMENT"}
    assert set(observed[2024]) == {"CONFIRMATION"}
    assert set(observed[2025]) == {"FINAL"}


def test_current_fit_is_distinct_from_historical_fold_generators() -> None:
    manifest = json.loads(MOD.FREEZE_MANIFEST.read_text(encoding="utf-8"))
    a2 = manifest["contracts"]["A2"]
    assert a2["supplemental_full_pre2026_model"]["used_for_frozen_oof_predictions"] is False
    assert len(a2["effective_model_vintages"]) == 3
    assert all(x["serialized_model_artifact_status"] == "SERIALIZED_STAGE_MODEL_NOT_PERSISTED_BY_FROZEN_RUN" for x in a2["effective_model_vintages"])


def test_source_hash_gap_is_separate_from_locked_path_components() -> None:
    hashes = pd.read_csv(MOD.FREEZE_HASHES)
    source = MOD.REPO / "scripts/v22/abcde_a2_nonlinear_alpha_baseline_r1.py"
    row = hashes.loc[hashes.absolute_path.eq(str(source))]
    assert len(row) == 1 and bool(row.immutable.iloc[0])
    assert row.sha256.iloc[0] == "75f332d09c76e4d4019a85e2a1afd514e2fb6649debfd9cd1ed9414c44c201bb"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == "056a46d191868a2a99e521671ba713c0b38fa948995749c975c56cdad9186d5f"
    for required in ["A2/oof_predictions.parquet", "A2/top20_selections.parquet", "A2/portfolio_daily.parquet", "A2/position_ledger.parquet"]:
        path = MOD.BASE / required
        frozen = hashes.loc[hashes.absolute_path.eq(str(path)), "sha256"].iloc[0]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == frozen


def test_moving_block_bootstrap_seed_is_deterministic() -> None:
    first = MOD.moving_block_indices(751, 10, np.random.default_rng(20260823))
    second = MOD.moving_block_indices(751, 10, np.random.default_rng(20260823))
    assert np.array_equal(first, second)
    assert len(first) == 751


def test_topn_sensitivity_does_not_mutate_authoritative_contract() -> None:
    oof = pd.DataFrame({
        "signal_date": pd.to_datetime(["2025-01-02"] * 30),
        "ticker": [f"T{i:02d}" for i in range(30)],
        "a2_prediction": np.arange(30, 0, -1, dtype=float),
        "a2_rank": np.arange(1, 31),
    })
    original = oof.copy(deep=True)
    maps = {n: MOD.target_map(oof, n) for n in [15, 20, 25]}
    pd.testing.assert_frame_equal(oof, original)
    assert [len(maps[n][pd.Timestamp("2025-01-02")]) for n in [15, 20, 25]] == [15, 20, 25]
    assert MOD.PREREGISTRATION["authoritative_top_n"] == 20


def test_final_artifact_contract_is_at_most_eight() -> None:
    assert len(MOD.FINAL_FILES) == 8
    assert len(set(MOD.FINAL_FILES)) == 8


def test_continuation_layering_and_one_x_cost_exact_replay() -> None:
    out = MOD.CONTINUATION_OUT
    identity = json.loads((out / "robustness_classification.json").read_text(encoding="utf-8"))
    assert identity["historical_path_authority"] == "PASS"
    assert identity["fold_model_binary_reproducibility"] == "UNRECOVERABLE"
    assert identity["current_deployment_fit_role"] == "FULL_HISTORY_OR_LATEST_DEPLOYMENT_FIT"
    assert identity["source_hash_mismatch_impact"] == "SPEC_PROVENANCE_PARTIAL"
    assert identity["falsification_executed"] is True
    assert identity["identity_layering"]["LAYER_2_A2_HISTORICAL_OOF_PATH"]["common_support_733"]["status"] == "NONAUTHORITATIVE_DIAGNOSTIC_MISMATCH_NOT_USED_AS_BASELINE"
    stress = pd.read_csv(out / "implementation_stress.csv")
    one = stress.loc[stress.test.eq("COST_STRESS") & stress.cost_multiplier.eq(1.0)].iloc[0]
    assert abs(one.sharpe - identity["baseline"]["sharpe"]) <= 1e-12
    assert abs(one.cumulative_return - identity["baseline"]["cumulative_return"]) <= 1e-12


def test_continuation_artifact_count_and_hash_manifest() -> None:
    out = MOD.CONTINUATION_OUT
    files = [p for p in out.iterdir() if p.is_file()]
    assert len(files) == 8
    manifest = json.loads((out / "hash_manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_count_including_manifest"] == 8
    for row in manifest["artifacts"]:
        path = out / row["name"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
