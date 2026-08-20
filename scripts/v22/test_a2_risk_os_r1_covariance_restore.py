from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(r"D:\us-tech-quant\scripts\v22\a2_risk_os_r1.py")
RESTORE = Path(r"D:\us-tech-quant-results\A2_RISK_OS_R1\COVARIANCE_RESTORE_R1")
CONTRACT_SHA256 = "058dbbed6d5880da8f0bb0e0fbb921f669d62465ced64711cacd80eb939d997e"
PANEL_SHA256 = "96ec9533439d7adaa6e30cb6f0519e048ef770c901e48d3efe896a9c502a944d"

spec = importlib.util.spec_from_file_location("a2_risk_os_r1_covariance_tested", SCRIPT)
assert spec and spec.loader
R = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = R
spec.loader.exec_module(R)


def _json(name: str):
    return json.loads((RESTORE / name).read_text(encoding="utf-8"))


def test_frozen_contract_a2_and_r6_identity_unchanged():
    identity = R.frozen_identity()
    assert R.sha256_file(R.CONTRACT_PATH) == CONTRACT_SHA256
    assert identity["r6_oof_sha256"] == R.R6_OOF_SHA256
    assert identity["r6_deploy_sha256"] == R.R6_DEPLOY_SHA256
    assert identity["verified_a2_artifact_count"] == 46


def test_covariance_panel_is_authoritative_pre2026_and_unique():
    panel = pd.read_parquet(R.COVARIANCE_PANEL)
    manifest = json.loads(R.COVARIANCE_MANIFEST.read_text(encoding="utf-8"))
    assert R.sha256_file(R.COVARIANCE_PANEL) == PANEL_SHA256 == manifest["panel_sha256"]
    assert panel.trade_date.max() < pd.Timestamp("2026-01-01")
    assert not panel.duplicated(["canonical_ticker", "trade_date"]).any()
    assert set(panel.source) == {"MOOMOO_OPEND_RAW_PLUS_REHAB"}
    assert set(panel.autype) == {"PIT_FORWARD_REHAB_INDEX"}
    assert manifest["moomoo_api_request_count"] == 0
    assert manifest["training_or_2026_outcome_rows"] == 0


def test_ticker_mapping_and_corporate_action_lineage_are_deterministic():
    panel = pd.read_parquet(R.COVARIANCE_PANEL)
    manifest = json.loads(R.COVARIANCE_MANIFEST.read_text(encoding="utf-8"))
    assert panel.canonical_ticker.nunique() == 322
    assert panel.groupby("canonical_ticker").moomoo_transport_code.nunique().max() == 1
    assert panel.groupby("canonical_ticker").cusip.nunique().max() == 1
    assert manifest["ticker_mapping_sha256"] == R.sha256_file(Path(manifest["ticker_mapping_source"]))
    assert manifest["rehab_factors_sha256"] == R.sha256_file(Path(manifest["rehab_factors_path"]))
    assert manifest["corporate_action_event_count"] == 1433


def test_every_covariance_window_is_pit_correct_and_complete():
    panel = pd.read_parquet(R.COVARIANCE_PANEL)
    panel["trade_date"] = pd.to_datetime(panel.trade_date)
    pivot = panel.pivot(index="trade_date", columns="canonical_ticker", values="return").sort_index()
    oof = pd.read_parquet(
        R.R6_OOF,
        columns=["candidate_id", "signal_date", "information_date", "ticker"],
    )
    oof = oof.loc[oof.candidate_id.eq(R.R6_REFERENCE_MODEL)].copy()
    oof["signal_date"] = pd.to_datetime(oof.signal_date)
    oof["information_date"] = pd.to_datetime(oof.information_date)
    market, _ = R.market_state(True)
    calendar = pd.DatetimeIndex(market.trade_date.drop_duplicates().sort_values())
    complete = 0
    for _, group in oof.groupby("signal_date", sort=True):
        information_date = pd.Timestamp(group.information_date.iloc[0])
        legal_dates = calendar[calendar <= information_date][-60:]
        assert len(legal_dates) <= 60
        assert len(legal_dates) == 0 or legal_dates.max() <= information_date
        history = pivot.reindex(index=legal_dates, columns=group.ticker.astype(str)).dropna(how="any")
        if len(history) >= 40:
            complete += 1
    assert complete == 609


def test_root_cause_and_coverage_gate_are_mechanically_recorded():
    summary = _json("covariance_restore_summary.json")
    root = pd.read_csv(RESTORE / "covariance_root_cause_summary.csv")
    assert summary["total_portfolio_dates"] == 609
    assert summary["old_complete_geometry_dates"] == 219
    assert summary["complete_geometry_dates"] == 609
    assert summary["COVARIANCE_GEOMETRY_COVERAGE"] == 1.0
    assert summary["AVOIDABLE_MISSING_GEOMETRY_DATES"] == 0
    assert summary["GENUINE_INSUFFICIENT_HISTORY_DATES"] == 0
    assert "INCORRECT_UNIVERSE_DEPENDENT_HISTORY_LOOKUP" in set(root.reason_code)


def test_no_2026_fit_search_or_outcome_access():
    audit = _json("covariance_restore_audit.json")
    assert audit["2026_outcome_reads"] == 0
    assert audit["2026_training_rows"] == 0
    assert audit["model_fit_count"] == 0
    assert audit["parameter_search_count"] == 0
    assert audit["threshold_search_count"] == 0
    assert audit["lookahead_violation_count"] == 0


def test_weights_caps_and_matched_exposure_are_exact():
    weights = pd.read_parquet(RESTORE / "risk_os_r1_weight_attribution.parquet")
    audit = _json("risk_os_r1_audit.json")
    assert weights.final_weight.ge(0).all()
    assert weights.final_weight.le(.06).all()
    assert audit["matched_exposure_absolute_difference"] < 1e-12
    assert audit["negative_weight_count"] == 0
    assert audit["weight_cap_violation_count"] == 0


def test_missing_history_policy_remains_fail_closed():
    contract = json.loads(R.CONTRACT_PATH.read_text(encoding="utf-8"))
    assert contract["modules"]["hard_limits"]["integrity_failure_action"] == "NO_NEW_RISK_TRUE"
    assert contract["modules"]["portfolio_geometry"]["lookback_sessions"] == 60
    assert contract["modules"]["portfolio_geometry"]["minimum_sessions"] == 40


def test_repaired_pre2026_replay_is_deterministic():
    weights = pd.read_parquet(RESTORE / "risk_os_r1_weight_attribution.parquet")
    positions = pd.read_parquet(R.R3.POSITION_LEDGER_PATH, columns=["date", "ticker", "raw_return"])
    positions["date"] = pd.to_datetime(positions.date)
    targets = R.target_maps(weights, "final_weight")
    first = R.simulate(targets, positions, R.BASE_COST)
    second = R.simulate(targets, positions, R.BASE_COST)
    pd.testing.assert_frame_equal(first, second, check_exact=True)


def test_closeout_is_consistent_with_strict_frozen_gate():
    summary = _json("covariance_restore_final_summary.json")
    assert summary["COVARIANCE_GEOMETRY_COVERAGE"] == 1.0
    assert summary["FULL_GEOMETRY_SCORE_COVERAGE"] == 569 / 609
    assert summary["A2_RISK_OS_R1_CLASSIFICATION"] == "E_INSUFFICIENT_AUTHORITATIVE_GEOMETRY_COVERAGE"
    assert summary["prospective_authorized"] is False
    assert summary["2026_RISK_OS_OUTCOME_READ_COUNT"] == 0
    assert summary["NEXT_AUTHORIZED_STEP"] == "PRESERVE_R1_RESEARCH_HISTORY_AND_STOP"
