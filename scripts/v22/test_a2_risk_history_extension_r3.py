from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import a2_risk_history_extension_r3 as subject


A = Path(r"D:\us-tech-quant-results\A2_RISK_HISTORY_EXTENSION_R1")
B = Path(r"D:\us-tech-quant-results\A2_RISK_CONTROL_R3_NON_PREDICTIVE_RISK_BUDGETING")


def test_frozen_contract_identities() -> None:
    assert subject.sha256_file(subject.R1_CONTRACT) == subject.R1_HASH
    assert subject.sha256_file(subject.R2_CONTRACT) == subject.R2_HASH
    assert subject.sha256_file(subject.R6_OOF) == subject.R6_HASH


def test_historical_oof_is_pre2026_complete_top20() -> None:
    frame = pd.read_parquet(A / "r6_historical_oof_predictions.parquet")
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    assert frame.signal_date.max() < pd.Timestamp("2026-01-01")
    assert frame.groupby("signal_date").size().eq(20).all()
    assert not frame.duplicated(["signal_date", "ticker"]).any()


def test_reconstructed_oof_is_past_trained_and_not_deploy_backcast() -> None:
    frame = pd.read_parquet(A / "r6_historical_oof_predictions.parquet")
    rebuilt = frame[frame.fold.astype(str).str.startswith("HISTORICAL_EXPANDING")]
    assert len(rebuilt) > 0
    assert (pd.to_datetime(rebuilt.train_max_target_end) < pd.to_datetime(rebuilt.embargo_cutoff)).all()
    audit = json.loads((A / "a2_risk_history_extension_summary.json").read_text())
    assert audit["deployment_model_backcast_count"] == 0


def test_geometry_coverage_and_pit_window() -> None:
    summary = json.loads((A / "a2_risk_history_extension_summary.json").read_text())
    geometry = pd.read_parquet(A / "portfolio_geometry_extended.parquet")
    assert summary["PORTFOLIO_GEOMETRY_COVERAGE"] >= .95
    assert geometry.complete_sessions.eq(60).all()
    assert (pd.to_datetime(geometry.information_date) < pd.to_datetime(geometry.signal_date)).all()


def test_phase_a_has_no_synthetic_or_lookahead_rows() -> None:
    summary = json.loads((A / "a2_risk_history_extension_summary.json").read_text())
    assert summary["SYNTHETIC_HISTORY_COUNT"] == 0
    assert summary["PIT_VIOLATION_COUNT"] == 0
    assert summary["LOOKAHEAD_VIOLATION_COUNT"] == 0


def test_r3_contract_is_nonpredictive_and_bounded() -> None:
    contract = json.loads((B / "A2_RISK_CONTROL_R3_CONTRACT.json").read_text())
    assert contract["primary"]["method"] == "VOLATILITY_TARGETING"
    assert contract["primary"]["min_exposure"] == .50
    assert contract["primary"]["max_exposure"] == 1.0
    assert contract["primary"]["max_daily_change"] == .05


def test_causal_reference_excludes_current_value() -> None:
    dates = pd.date_range("2020-01-01", periods=62, freq="B")
    frame = pd.DataFrame({"signal_date": dates, "exante_portfolio_vol": np.arange(1, 63), "combined_stress_loss": np.arange(101, 163)})
    result = subject.causal_budgets(frame)
    assert result.iloc[0].vol_reference == np.median(np.arange(1, 61))
    assert result.iloc[0].stress_reference == np.median(np.arange(101, 161))


def test_smoothing_and_no_leverage() -> None:
    values = subject.smooth_budget(pd.Series([.5, 1.0, .5, 1.0]))
    assert values.between(.5, 1.0).all()
    assert values.diff().dropna().abs().le(.0500000001).all()


def test_matched_exposure_exact_and_2026_unread() -> None:
    audit = json.loads((B / "r3_audit.json").read_text())
    summary = json.loads((B / "r3_final_summary.json").read_text())
    assert audit["matched_exposure_error"] <= 1e-12
    assert audit["2026_R3_OUTCOME_READ_COUNT"] == 0
    assert summary["2026_R3_OUTCOME_READ_COUNT"] == 0
    assert not summary["R3_2026_AUTHORIZED"]


def test_weight_mapping_is_nonnegative_and_capped() -> None:
    frame = pd.read_parquet(B / "r3_weight_attribution.parquet")
    columns = ["base_r6_weight", "vol_weight", "stress_weight", "combined_weight"]
    assert frame[columns].ge(0).all().all()
    assert frame.vol_weight.le(frame.base_r6_weight + 1e-15).all()
    assert frame.combined_weight.le(frame.base_r6_weight + 1e-15).all()


def test_contract_and_output_hashes_reproducible() -> None:
    summary = json.loads((B / "r3_final_summary.json").read_text())
    assert subject.sha256_file(B / "A2_RISK_CONTROL_R3_CONTRACT.json") == summary["A2_RISK_CONTROL_R3_CONTRACT_SHA256"]
    manifest = json.loads((B / "artifact_hashes.json").read_text())
    for name, digest in manifest["files"].items():
        assert subject.sha256_file(B / name) == digest
