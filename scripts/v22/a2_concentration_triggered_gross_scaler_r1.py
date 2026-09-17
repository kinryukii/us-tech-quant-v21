"""Outcome-independent concentration-triggered gross scaler for frozen A2.

The four primary arms preserve membership and within-arm normalized weights.
The only new decision is a deterministic daily gross in [0.80, 1.00] obtained
from contemporaneous Raw/S1 FF12 and FF48 HHI.  The contract and target-map
hash are persisted before any new-arm economic path is constructed.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


TASK_ID = "A2_CONCENTRATION_TRIGGERED_GROSS_SCALER_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_ID
DUAL_ROOT = RESULTS / "A2_FIXED_TOP20_DUAL_SECTOR_CASH_OVERLAY_R1"
DUAL_CONTRACT = DUAL_ROOT / "overlay_contract.json"
DUAL_DIAGNOSTICS = DUAL_ROOT / "concentration_and_cash_diagnostics.csv"
CASH_SOURCE = REPO / "scripts" / "v22" / "a2_fixed_top20_dual_sector_cash_overlay_r1.py"
BASE_SOURCE = REPO / "scripts" / "v22" / "stage_sec_pit_taxonomy.py"
R0F_SOURCE = REPO / "scripts" / "v22" / "fast_a2_r0f_corporate_action_and_nav_forensic_audit.py"
PRETOP_SOURCE = REPO / "scripts" / "v22" / "a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py"
TOP20 = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "top20_selections.parquet"
PORTFOLIO = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "portfolio_daily.parquet"
TAXONOMY = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1" / "pit_ff12_ff48_taxonomy.parquet"

GROSS_FLOOR = 0.80
TOP_N = 20
TOL = 1e-12
NEAR_BINDING_TOL = 1e-10
HAC_LAGS = 5
BOOTSTRAP_BLOCK = 10
BOOTSTRAP_REPETITIONS = 2000
BOOTSTRAP_SEED = 20260823
PREEXISTING_ACL_EXCEPTIONS = 2
EXPECTED_DUAL_CONTRACT_HASH = "9ad4de34ea734679183e5742332d796850ded7c6a1e013f89c7ac61bac633ea0"
FINAL_FILES = [
    "final_report.md", "gross_scaler_contract.json", "arm_summary.csv",
    "gross_and_concentration_diagnostics.csv", "paired_statistics.csv",
    "classification.json", "hash_manifest.json",
]


class GateFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise GateFailure(f"{code}:{detail}")


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def gross_component(raw_hhi: float, s1_hhi: float) -> float:
    require(raw_hhi > 0 and s1_hhi > 0, "INVALID_HHI")
    if raw_hhi <= s1_hhi:
        return 1.0
    return min(1.0, math.sqrt(s1_hhi / raw_hhi))


def gross_rule(raw12: float, raw48: float, s112: float, s148: float) -> tuple[float, float, float, float]:
    g12, g48 = gross_component(raw12, s112), gross_component(raw48, s148)
    unclipped = min(1.0, g12, g48)
    return g12, g48, unclipped, max(GROSS_FLOOR, unclipped)


def load_and_verify_inputs(cash) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any], pd.DataFrame]:
    joined, _, identity = cash.load_mechanical_inputs()
    dual_manifest = cash.verify_manifest(DUAL_ROOT)
    contract = json.loads(DUAL_CONTRACT.read_text(encoding="utf-8"))
    require(contract["overlay_contract_hash"] == EXPECTED_DUAL_CONTRACT_HASH, "DUAL_CONTRACT_IDENTITY")
    require(contract["spec_mutation_forbidden"] is True and contract["2026_outcome_used"] is False, "DUAL_CONTRACT_GOVERNANCE")
    manifest_row = next(row for row in dual_manifest["artifacts"] if row["name"] == "overlay_contract.json")
    require(cash.sha256_file(DUAL_CONTRACT) == manifest_row["sha256"], "DUAL_CONTRACT_FILE_HASH")
    prior_gross = pd.read_csv(
        DUAL_DIAGNOSTICS, usecols=["row_type", "signal_date", "dual_gross"], low_memory=False
    )
    prior_gross = prior_gross.loc[prior_gross.row_type.eq("SESSION")].copy()
    prior_gross["signal_date"] = pd.to_datetime(prior_gross.signal_date).dt.normalize()
    prior_gross["dual_gross"] = pd.to_numeric(prior_gross.dual_gross)
    require(len(prior_gross) == 750 and prior_gross.signal_date.max() < pd.Timestamp("2026-01-01"), "DUAL_GROSS_SUPPORT")
    identity.update({
        "dual_manifest_sha256": cash.sha256_file(DUAL_ROOT / "hash_manifest.json"),
        "dual_contract_file_sha256": cash.sha256_file(DUAL_CONTRACT),
        "dual_contract_hash": contract["overlay_contract_hash"],
        "dual_target_map_hash": contract["target_map_hash"],
    })
    return joined, identity, contract, prior_gross[["signal_date", "dual_gross"]]


def build_primary_targets(cash, joined: pd.DataFrame, prior_gross: pd.DataFrame) -> tuple[dict[str, dict[pd.Timestamp, dict[str, float]]], pd.DataFrame, dict[str, Any]]:
    base = import_file("a2_gross_s1", PRETOP_SOURCE)
    targets = {name: {} for name in ("RAW_A2", "S1_SOFT_025", "RAW_CONCENTRATION_GROSS_SCALED", "S1_CONCENTRATION_GROSS_SCALED")}
    rows: list[dict[str, Any]] = []
    for date, day in joined.groupby("signal_date", sort=True):
        date = pd.Timestamp(date)
        raw = {str(ticker): 1.0 / TOP_N for ticker in day.ticker}
        s1 = base.s1_weights(day)
        raw_metrics = cash.concentration_row(raw, day, "raw")
        s1_metrics = cash.concentration_row(s1, day, "s1")
        g12, g48, unclipped, gross = gross_rule(
            raw_metrics["raw_ff12_hhi"], raw_metrics["raw_ff48_hhi"],
            s1_metrics["s1_ff12_hhi"], s1_metrics["s1_ff48_hhi"],
        )
        raw_scaled = {ticker: gross * weight for ticker, weight in raw.items()}
        s1_scaled = {ticker: gross * weight for ticker, weight in s1.items()}
        raw_scaled_metrics = cash.concentration_row(raw_scaled, day, "raw_scaled")
        s1_scaled_metrics = cash.concentration_row(s1_scaled, day, "s1_scaled")
        require(set(raw) == set(s1) == set(raw_scaled) == set(s1_scaled), "MEMBERSHIP_CHANGED", date)
        require(abs(sum(raw_scaled.values()) - sum(s1_scaled.values())) <= TOL, "SCALED_GROSS_MISMATCH")
        require(GROSS_FLOOR - TOL <= gross <= 1.0 + TOL, "GROSS_BOUND")
        require(abs(raw_scaled_metrics["raw_scaled_ff12_hhi"] - raw_metrics["raw_ff12_hhi"]) <= TOL, "RAW_SCALED_FF12_NORMALIZED_HHI")
        require(abs(raw_scaled_metrics["raw_scaled_ff48_hhi"] - raw_metrics["raw_ff48_hhi"]) <= TOL, "RAW_SCALED_FF48_NORMALIZED_HHI")
        require(abs(s1_scaled_metrics["s1_scaled_ff12_hhi"] - s1_metrics["s1_ff12_hhi"]) <= TOL, "S1_SCALED_FF12_NORMALIZED_HHI")
        require(abs(s1_scaled_metrics["s1_scaled_ff48_hhi"] - s1_metrics["s1_ff48_hhi"]) <= TOL, "S1_SCALED_FF48_NORMALIZED_HHI")
        targets["RAW_A2"][date], targets["S1_SOFT_025"][date] = raw, s1
        targets["RAW_CONCENTRATION_GROSS_SCALED"][date] = raw_scaled
        targets["S1_CONCENTRATION_GROSS_SCALED"][date] = s1_scaled
        rows.append({
            "row_type": "SESSION", "signal_date": date, "g12": g12, "g48": g48,
            "gross_unclipped": unclipped, "simple_gross": gross, "simple_cash": 1.0 - gross,
            "gross_floor_binding": gross <= GROSS_FLOOR + TOL,
            "g12_binding": g12 <= min(1.0, g48) + NEAR_BINDING_TOL and g12 < 1.0 - NEAR_BINDING_TOL,
            "g48_binding": g48 <= min(1.0, g12) + NEAR_BINDING_TOL and g48 < 1.0 - NEAR_BINDING_TOL,
            "both_near_binding": abs(g12 - g48) <= NEAR_BINDING_TOL and min(g12, g48) < 1.0 - NEAR_BINDING_TOL,
            **raw_metrics, **s1_metrics, **raw_scaled_metrics, **s1_scaled_metrics,
            "raw_ff12_max_absolute_exposure": gross * raw_metrics["raw_ff12_max_weight"],
            "raw_ff48_max_absolute_exposure": gross * raw_metrics["raw_ff48_max_weight"],
            "s1_ff12_max_absolute_exposure": gross * s1_metrics["s1_ff12_max_weight"],
            "s1_ff48_max_absolute_exposure": gross * s1_metrics["s1_ff48_max_weight"],
        })
    diagnostics = pd.DataFrame(rows).sort_values("signal_date", kind="mergesort").reset_index(drop=True)
    diagnostics = diagnostics.merge(prior_gross, on="signal_date", validate="one_to_one")
    diagnostics["dual_gross_abs_difference"] = (diagnostics.simple_gross - diagnostics.dual_gross).abs()
    diagnostics["raw_ff12_hhi_quintile"] = pd.qcut(diagnostics.raw_ff12_hhi.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    diagnostics["raw_ff48_hhi_quintile"] = pd.qcut(diagnostics.raw_ff48_hhi.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    mechanics = {
        "average_gross": float(diagnostics.simple_gross.mean()), "median_gross": float(diagnostics.simple_gross.median()),
        "p10_gross": float(diagnostics.simple_gross.quantile(.10)), "min_gross": float(diagnostics.simple_gross.min()),
        "average_cash": float(diagnostics.simple_cash.mean()), "median_cash": float(diagnostics.simple_cash.median()),
        "p90_cash": float(diagnostics.simple_cash.quantile(.90)), "max_cash": float(diagnostics.simple_cash.max()),
        "pct_sessions_gross_1": float(diagnostics.simple_gross.ge(1.0 - TOL).mean()),
        "pct_sessions_gross_floor_080": float(diagnostics.gross_floor_binding.mean()),
        "g12_binding_pct": float(diagnostics.g12_binding.mean()), "g48_binding_pct": float(diagnostics.g48_binding.mean()),
        "both_near_binding_pct": float(diagnostics.both_near_binding.mean()),
        "corr_raw_ff12_hhi_cash": float(diagnostics.raw_ff12_hhi.corr(diagnostics.simple_cash)),
        "corr_raw_ff48_hhi_cash": float(diagnostics.raw_ff48_hhi.corr(diagnostics.simple_cash)),
        "simple_vs_dual_gross_correlation": float(diagnostics.simple_gross.corr(diagnostics.dual_gross)),
        "simple_vs_dual_gross_mean_absolute_difference": float(diagnostics.dual_gross_abs_difference.mean()),
        "simple_vs_dual_gross_median_absolute_difference": float(diagnostics.dual_gross_abs_difference.median()),
        "simple_vs_dual_gross_p90_absolute_difference": float(diagnostics.dual_gross_abs_difference.quantile(.90)),
        "max_primary_gross_mismatch": float((diagnostics.raw_scaled_gross - diagnostics.s1_scaled_gross).abs().max()),
        "max_cash_identity_error": float((diagnostics.simple_gross + diagnostics.simple_cash - 1.0).abs().max()),
        "max_raw_scaled_ff12_normalized_hhi_error": float((diagnostics.raw_scaled_ff12_hhi - diagnostics.raw_ff12_hhi).abs().max()),
        "max_raw_scaled_ff48_normalized_hhi_error": float((diagnostics.raw_scaled_ff48_hhi - diagnostics.raw_ff48_hhi).abs().max()),
        "max_s1_scaled_ff12_normalized_hhi_error": float((diagnostics.s1_scaled_ff12_hhi - diagnostics.s1_ff12_hhi).abs().max()),
        "max_s1_scaled_ff48_normalized_hhi_error": float((diagnostics.s1_scaled_ff48_hhi - diagnostics.s1_ff48_hhi).abs().max()),
        "average_gross_by_raw_ff12_hhi_quintile": {str(k): float(v) for k, v in diagnostics.groupby("raw_ff12_hhi_quintile").simple_gross.mean().items()},
        "average_cash_by_raw_ff12_hhi_quintile": {str(k): float(v) for k, v in diagnostics.groupby("raw_ff12_hhi_quintile").simple_cash.mean().items()},
        "average_gross_by_raw_ff48_hhi_quintile": {str(k): float(v) for k, v in diagnostics.groupby("raw_ff48_hhi_quintile").simple_gross.mean().items()},
        "average_cash_by_raw_ff48_hhi_quintile": {str(k): float(v) for k, v in diagnostics.groupby("raw_ff48_hhi_quintile").simple_cash.mean().items()},
    }
    return targets, diagnostics, mechanics


def freeze_contract(cash, identity: dict[str, Any], targets: dict[str, dict[pd.Timestamp, dict[str, float]]], mechanics: dict[str, Any]) -> dict[str, Any]:
    spec = {
        "task_id": TASK_ID, "role": "FORWARD_ONLY_EXPERIMENTAL_GROSS_CONTROLLER",
        "formula": "G=max(0.80,min(1,g12,g48));gL=1_if_raw_hhi<=s1_hhi_else_sqrt(s1_hhi/raw_hhi)",
        "gross_floor": GROSS_FLOOR, "top20_fixed": True, "within_arm_relative_weights_unchanged": True,
        "raw_scaled_weights": "G*RAW_NORMALIZED_WEIGHTS", "s1_scaled_weights": "G*S1_NORMALIZED_WEIGHTS",
        "cash_convention": "RESIDUAL_1_MINUS_TARGET_EQUITY_GROSS_PLUS_EXISTING_LEDGER_CASH",
        "cost_convention": "AUTHORITATIVE_POSITION_LEDGER_10BPS_ONE_WAY",
        "equity_normalized_hhi_interpretation": "UNCHANGED_BY_UNIFORM_SCALING",
        "absolute_hhi_interpretation": "G_SQUARED_TIMES_EQUITY_NORMALIZED_HHI",
        "rule_is_outcome_independent": True, "no_parameter_search": True, "no_model_fit": True,
        "paired_inference": {"hac_lags": HAC_LAGS, "block_length": BOOTSTRAP_BLOCK, "repetitions": BOOTSTRAP_REPETITIONS, "seed": BOOTSTRAP_SEED},
        "classification_rules": {
            "complex_material": "Dual-vs-simple Sharpe delta>=0.10 AND MaxDD delta>=2pp AND HAC t>=1.0",
            "simple_sufficient": "simple capture of Dual MaxDD improvement>=75% AND abs Dual-vs-simple Sharpe delta<0.10 AND abs paired annual mean<3% AND abs HAC t<1.96",
            "s1_plus_promising": "S1-scaled Sharpe retention vs S1>=90% AND MaxDD improvement vs S1>=3pp AND same-gross S1 Sharpe delta>0 AND paired annual mean>=0",
            "too_defensive": "scaled Raw Sharpe retention<90% OR CAGR retention<75%, unless simple-sufficient or S1-plus-promising",
            "otherwise": "MECHANISM_INCONCLUSIVE",
        },
        "primary_target_map_hash": cash.target_map_hash(targets),
        "authoritative_hashes": {
            "top20": identity["raw_top20_sha256"], "portfolio": identity["portfolio_sha256"],
            "taxonomy_file": identity["taxonomy_file_sha256"], "taxonomy_logical": identity["taxonomy_logical_hash"],
            "dual_contract_file": identity["dual_contract_file_sha256"], "dual_contract_hash": identity["dual_contract_hash"],
        },
        "2023_2025_role": "EXPOSED_DIAGNOSTIC_ONLY", "2026_outcome_used": False,
    }
    contract_hash = cash.stable_hash(spec)
    contract = {**spec, "gross_scaler_contract_hash": contract_hash, "freeze_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "mechanical_metrics_at_freeze": mechanics, "economic_outcome_read_count_at_freeze": 0, "contract_mutation_forbidden": True}
    path = OUT / "gross_scaler_contract.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        require(existing["gross_scaler_contract_hash"] == contract_hash, "FROZEN_CONTRACT_MUTATION")
        contract = existing
    else:
        cash.atomic_json(path, contract)
    require(json.loads(path.read_text(encoding="utf-8"))["gross_scaler_contract_hash"] == contract_hash, "CONTRACT_FREEZE_WRITE")
    return contract


def concentration_summary(diagnostics: pd.DataFrame, prefix: str, gross_column: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "average_equity_gross": float(diagnostics[gross_column].mean()),
        "average_cash": float((1.0 - diagnostics[gross_column]).mean()),
    }
    for level in ("ff12", "ff48"):
        hhi = diagnostics[f"{prefix}_{level}_hhi"]
        maximum = diagnostics[f"{prefix}_{level}_max_weight"]
        absolute = diagnostics[gross_column] * maximum
        result.update({
            f"{level}_hhi": float(hhi.mean()), f"{level}_effective_count": float((1.0 / hhi).mean()),
            f"{level}_max_weight": float(maximum.mean()),
            f"{level}_max_absolute_exposure": float(absolute.mean()),
            f"{level}_max_absolute_exposure_p90": float(absolute.quantile(.90)),
            f"{level}_max_absolute_exposure_p95": float(absolute.quantile(.95)),
            f"{level}_max_absolute_exposure_max": float(absolute.max()),
        })
    return result


def replay_paths(cash, joined: pd.DataFrame, primary_targets: dict[str, dict[pd.Timestamp, dict[str, float]]], contract: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any], pd.DataFrame]:
    require(contract["economic_outcome_read_count_at_freeze"] == 0 and (OUT / "gross_scaler_contract.json").is_file(), "CONTRACT_NOT_FROZEN")
    dual_targets_all, dual_diagnostics, _ = cash.build_mechanical_targets(joined)
    dual_contract = json.loads(DUAL_CONTRACT.read_text(encoding="utf-8"))
    require(cash.target_map_hash(dual_targets_all) == dual_contract["target_map_hash"], "DUAL_TARGET_MAP_REPLAY")
    targets = {**primary_targets, "DUAL_SECTOR_CASH_REFERENCE": dual_targets_all["DUAL_SECTOR_CASH"]}
    expected_dual_gross = dual_diagnostics.set_index("signal_date").dual_gross
    for date, weights in targets["DUAL_SECTOR_CASH_REFERENCE"].items():
        require(abs(sum(weights.values()) - float(expected_dual_gross.loc[pd.Timestamp(date)])) <= 1e-10, "DUAL_GROSS_REPLAY", date)
    pretop = import_file("a2_gross_prices", PRETOP_SOURCE)
    r0f = import_file("a2_gross_r0f", R0F_SOURCE)
    wanted = {ticker for mapping in targets.values() for weights in mapping.values() for ticker in weights}
    prices, price_hashes = pretop.load_pre2026_qfq(wanted)
    require(prices.trade_date.max() < pd.Timestamp("2026-01-01"), "2026_PRICE_READ")
    signal_dates = sorted(primary_targets["RAW_A2"])
    paths = {arm: r0f.reconstruct_path(model=arm, target_map=mapping, qfq=prices, signal_dates=signal_dates, cost_bps=10) for arm, mapping in targets.items()}
    return paths, dual_diagnostics, price_hashes, prices


def exact_reconciliation(cash, paths: dict[str, Any]) -> dict[str, Any]:
    authoritative = pd.read_parquet(PORTFOLIO, columns=[
        "execution_date", "reconstructed_daily_return", "reconstructed_nav", "reconstructed_turnover", "reconstructed_transaction_cost"
    ]).sort_values("execution_date", kind="mergesort")
    authoritative["execution_date"] = pd.to_datetime(authoritative.execution_date).dt.normalize()
    require(authoritative.execution_date.max() < pd.Timestamp("2026-01-01"), "2026_AUTHORITATIVE_READ")
    raw = paths["RAW_A2"].daily.sort_values("execution_date", kind="mergesort")
    merged = authoritative.merge(raw, on="execution_date", suffixes=("_authoritative", "_replay"), validate="one_to_one")
    errors = {
        key: float((merged[f"{column}_authoritative"] - merged[f"{column}_replay"]).abs().max())
        for key, column in (("return", "reconstructed_daily_return"), ("nav", "reconstructed_nav"),
                            ("turnover", "reconstructed_turnover"), ("cost", "reconstructed_transaction_cost"))
    }
    require(max(errors.values()) <= TOL, "RAW_EXACT_REPLAY", errors)
    prior_arms = pd.read_csv(DUAL_ROOT / "arm_summary.csv").set_index("arm")
    for arm, previous_name in (("S1_SOFT_025", "S1_SOFT_025"), ("DUAL_SECTOR_CASH_REFERENCE", "DUAL_SECTOR_CASH")):
        metrics = cash.performance_metrics(paths[arm].daily)
        for key in ("cagr", "sharpe", "max_drawdown", "turnover", "cost"):
            require(abs(float(metrics[key]) - float(prior_arms.loc[previous_name, key])) <= TOL, f"{arm}_EXACT_REPLAY", key)
    return {"raw_reconciliation": "PASS_EXACT_1E-12", "raw_errors": errors, "s1_reconciliation": "PASS_EXACT_1E-12", "dual_reference_status": "PASS_FROZEN_CONTRACT_AND_TARGET_MAP_EXACT_REPLAY"}


def paired_rows(cash, daily: dict[str, pd.DataFrame]) -> pd.DataFrame:
    comparisons = {
        "RAW_SCALED_MINUS_RAW": ("RAW_CONCENTRATION_GROSS_SCALED", "RAW_A2"),
        "S1_SCALED_MINUS_S1": ("S1_CONCENTRATION_GROSS_SCALED", "S1_SOFT_025"),
        "S1_SCALED_MINUS_RAW_SCALED": ("S1_CONCENTRATION_GROSS_SCALED", "RAW_CONCENTRATION_GROSS_SCALED"),
        "DUAL_MINUS_RAW_SCALED": ("DUAL_SECTOR_CASH_REFERENCE", "RAW_CONCENTRATION_GROSS_SCALED"),
    }
    rows = []
    for name, (left, right) in comparisons.items():
        delta = daily[left].reconstructed_daily_return.to_numpy(float) - daily[right].reconstructed_daily_return.to_numpy(float)
        rows.append({"comparison": name, **cash.paired_inference(delta)})
    return pd.DataFrame(rows)


def drawdown_period(cash, daily: dict[str, pd.DataFrame], diagnostics: pd.DataFrame) -> dict[str, Any]:
    peak, trough = cash.drawdown_interval(daily["RAW_A2"])
    result: dict[str, Any] = {"peak_date": str(peak.date()), "trough_date": str(trough.date())}
    selected = diagnostics.loc[diagnostics.signal_date.ge(peak) & diagnostics.signal_date.le(trough)]
    for arm, frame in daily.items():
        part = frame.loc[frame.execution_date.gt(peak) & frame.execution_date.le(trough)]
        target_gross = 1.0
        if arm in {"RAW_CONCENTRATION_GROSS_SCALED", "S1_CONCENTRATION_GROSS_SCALED"}:
            target_gross = float(selected.simple_gross.mean())
        elif arm == "DUAL_SECTOR_CASH_REFERENCE":
            target_gross = float(selected.dual_gross.mean())
        result[arm] = {
            "return": float(np.prod(1.0 + part.reconstructed_daily_return) - 1.0),
            "average_gross": target_gross, "average_cash": 1.0 - target_gross,
            "average_raw_ff12_hhi": float(selected.raw_ff12_hhi.mean()),
            "average_raw_ff48_hhi": float(selected.raw_ff48_hhi.mean()),
        }
    return result


def year_diagnostics(cash, paths: dict[str, Any], prices: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for year in (2023, 2024, 2025):
        result[str(year)] = {}
        for arm in ("RAW_CONCENTRATION_GROSS_SCALED", "S1_CONCENTRATION_GROSS_SCALED"):
            part = paths[arm].daily.loc[paths[arm].daily.execution_date.dt.year.eq(year)].copy()
            result[str(year)][arm] = {**cash.performance_metrics(part), **cash.factor_metrics(part, prices), "role": "EXPOSED_DIAGNOSTIC_ONLY"}
    return result


def classify(arms: pd.DataFrame, paired: pd.DataFrame) -> dict[str, Any]:
    by = arms.set_index("arm")
    raw, s1 = by.loc["RAW_A2"], by.loc["S1_SOFT_025"]
    raw_scaled, s1_scaled, dual = by.loc["RAW_CONCENTRATION_GROSS_SCALED"], by.loc["S1_CONCENTRATION_GROSS_SCALED"], by.loc["DUAL_SECTOR_CASH_REFERENCE"]
    pair = paired.set_index("comparison")
    dual_vs_simple = pair.loc["DUAL_MINUS_RAW_SCALED"]
    s1_same_gross = pair.loc["S1_SCALED_MINUS_RAW_SCALED"]
    maxdd_den = float(dual.max_drawdown - raw.max_drawdown)
    beta_den = float(raw.qqq_beta - dual.qqq_beta)
    downside_den = float(raw.downside_capture - dual.downside_capture)
    capture_dd = float((raw_scaled.max_drawdown - raw.max_drawdown) / maxdd_den) if abs(maxdd_den) > TOL else None
    capture_beta = float((raw.qqq_beta - raw_scaled.qqq_beta) / beta_den) if abs(beta_den) > TOL else None
    capture_downside = float((raw.downside_capture - raw_scaled.downside_capture) / downside_den) if abs(downside_den) > TOL else None
    complex_material = float(dual.sharpe - raw_scaled.sharpe) >= .10 and float(dual.max_drawdown - raw_scaled.max_drawdown) >= .02 and float(dual_vs_simple.hac_tstat) >= 1.0
    simple_sufficient = capture_dd is not None and capture_dd >= .75 and abs(float(dual.sharpe - raw_scaled.sharpe)) < .10 and abs(float(dual_vs_simple.annualized_mean_delta)) < .03 and abs(float(dual_vs_simple.hac_tstat)) < 1.96
    s1_plus = float(s1_scaled.sharpe / s1.sharpe) >= .90 and float(s1_scaled.max_drawdown - s1.max_drawdown) >= .03 and float(s1_scaled.sharpe - raw_scaled.sharpe) > 0 and float(s1_same_gross.annualized_mean_delta) >= 0
    too_defensive = (float(raw_scaled.sharpe / raw.sharpe) < .90 or float(raw_scaled.cagr / raw.cagr) < .75) and not simple_sufficient and not s1_plus
    if complex_material:
        classification = "COMPLEX_DUAL_CASH_ADDS_MATERIAL_VALUE"
    elif simple_sufficient:
        classification = "SIMPLE_GROSS_CONTROLLER_SUFFICIENT"
    elif s1_plus:
        classification = "S1_PLUS_GROSS_CONTROLLER_PROMISING"
    elif too_defensive:
        classification = "GROSS_CONTROLLER_TOO_DEFENSIVE"
    else:
        classification = "MECHANISM_INCONCLUSIVE"
    forward = "EXPERIMENTAL_FORWARD_ONLY" if classification in {"SIMPLE_GROSS_CONTROLLER_SUFFICIENT", "S1_PLUS_GROSS_CONTROLLER_PROMISING", "MECHANISM_INCONCLUSIVE"} else "NOT_FORWARD_WORTHY"
    recommended = "RAW_A2|S1_SOFT_025|S1_CONCENTRATION_GROSS_SCALED;CAUSAL_DIAGNOSTIC=RAW_CONCENTRATION_GROSS_SCALED" if forward == "EXPERIMENTAL_FORWARD_ONLY" else "RAW_A2|S1_SOFT_025"
    return {
        "gross_controller_classification": classification,
        "simple_capture_of_dual_maxdd_improvement": capture_dd,
        "simple_capture_of_dual_beta_reduction": capture_beta,
        "simple_capture_of_dual_downside_improvement": capture_downside,
        "does_simple_scaler_capture_most_dual_value": bool(simple_sufficient),
        "does_s1_remain_valuable_at_same_gross": bool(float(s1_same_gross.annualized_mean_delta) > 0 and float(s1_scaled.sharpe) > float(raw_scaled.sharpe)),
        "is_s1_plus_gross_scaler_forward_worthy": bool(forward == "EXPERIMENTAL_FORWARD_ONLY" and not too_defensive),
        "forward_eligibility": forward, "recommended_forward_arms": recommended,
        "raw_scaled_cagr_sacrifice_per_1pp_maxdd_improvement": float((raw.cagr - raw_scaled.cagr) / (raw_scaled.max_drawdown - raw.max_drawdown)) if raw_scaled.max_drawdown > raw.max_drawdown else None,
        "raw_scaled_sharpe_retention": float(raw_scaled.sharpe / raw.sharpe),
        "raw_scaled_residual_sharpe_retention": float(raw_scaled.residual_sharpe / raw.residual_sharpe),
        "s1_scaled_sharpe_retention": float(s1_scaled.sharpe / s1.sharpe),
        "s1_scaled_residual_sharpe_retention": float(s1_scaled.residual_sharpe / s1.residual_sharpe),
    }


def run_economics(cash, joined: pd.DataFrame, primary_targets: dict[str, dict[pd.Timestamp, dict[str, float]]], diagnostics: pd.DataFrame, contract: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    paths, dual_diagnostics, price_hashes, prices = replay_paths(cash, joined, primary_targets, contract)
    identity = exact_reconciliation(cash, paths)
    diagnostics = diagnostics.merge(
        dual_diagnostics[["signal_date", "dual_ff12_hhi", "dual_ff48_hhi", "dual_ff12_max_weight", "dual_ff48_max_weight"]],
        on="signal_date", validate="one_to_one",
    )
    daily = {arm: path.daily.sort_values("execution_date", kind="mergesort").reset_index(drop=True) for arm, path in paths.items()}
    prefix_gross = {
        "RAW_A2": ("raw", "raw_gross"), "S1_SOFT_025": ("s1", "s1_gross"),
        "RAW_CONCENTRATION_GROSS_SCALED": ("raw_scaled", "simple_gross"),
        "S1_CONCENTRATION_GROSS_SCALED": ("s1_scaled", "simple_gross"),
        "DUAL_SECTOR_CASH_REFERENCE": ("dual", "dual_gross"),
    }
    rows = []
    for arm, frame in daily.items():
        prefix, gross_col = prefix_gross[arm]
        rows.append({"arm": arm, "evidence_role": "EXPOSED_HISTORICAL_DIAGNOSTIC_ONLY", **cash.performance_metrics(frame),
                     **cash.factor_metrics(frame, prices), **concentration_summary(diagnostics, prefix, gross_col)})
    arms = pd.DataFrame(rows)
    paired = paired_rows(cash, daily)
    result = {
        **identity, "year_diagnostics": year_diagnostics(cash, paths, prices),
        "raw_maxdd_period": drawdown_period(cash, daily, diagnostics),
        "classification": classify(arms, paired), "price_input_hashes": price_hashes,
    }
    by, p = arms.set_index("arm"), paired.set_index("comparison")
    raw, s1, raw_scaled, s1_scaled, dual = (by.loc[name] for name in (
        "RAW_A2", "S1_SOFT_025", "RAW_CONCENTRATION_GROSS_SCALED", "S1_CONCENTRATION_GROSS_SCALED", "DUAL_SECTOR_CASH_REFERENCE"))
    result["most_damaging_evidence"] = (
        f"Simple captured only {result['classification']['simple_capture_of_dual_maxdd_improvement']:.1%} of Dual MaxDD improvement; "
        f"Dual MaxDD remained {dual.max_drawdown-raw_scaled.max_drawdown:+.2%} better than simple Raw scaling."
    )
    result["strongest_supporting_evidence"] = (
        f"S1-scaled retained {s1_scaled.sharpe/s1.sharpe:.1%} of S1 Sharpe while improving MaxDD "
        f"{s1_scaled.max_drawdown-s1.max_drawdown:+.2%}; same-gross S1-minus-Raw Sharpe delta was {s1_scaled.sharpe-raw_scaled.sharpe:+.3f}."
    )
    return arms, paired, {**result, "diagnostics": diagnostics}


def add_quintile_rows(diagnostics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dimension, column in (("FF12", "raw_ff12_hhi_quintile"), ("FF48", "raw_ff48_hhi_quintile")):
        for quintile, group in diagnostics.groupby(column, sort=True):
            rows.append({"row_type": "QUINTILE_SUMMARY", "quintile_dimension": dimension, "quintile": int(quintile),
                         "session_count": int(len(group)), "simple_gross": float(group.simple_gross.mean()), "simple_cash": float(group.simple_cash.mean())})
    return pd.concat([diagnostics, pd.DataFrame(rows)], ignore_index=True, sort=False)


def write_report(result: dict[str, Any], arms: pd.DataFrame, mechanics: dict[str, Any]) -> None:
    by = arms.set_index("arm")
    raw, s1, rs, ss, dual = (by.loc[name] for name in ("RAW_A2", "S1_SOFT_025", "RAW_CONCENTRATION_GROSS_SCALED", "S1_CONCENTRATION_GROSS_SCALED", "DUAL_SECTOR_CASH_REFERENCE"))
    c = result["classification"]
    lines = [
        "# A2 concentration-triggered gross scaler R1", "",
        f"TASK_STATUS={result['task_status']}", "2026_OUTCOME_USED=FALSE", "",
        "## Executive verdict", "",
        f"The fixed square-root rule produced average gross {mechanics['average_gross']:.2%} and minimum gross {mechanics['min_gross']:.2%}. Uniform scaling preserved equity-normalized HHI exactly; it only reduced absolute capital exposure.",
        f"Raw-scaled CAGR/Sharpe/MaxDD were {rs.cagr:.2%}/{rs.sharpe:.3f}/{rs.max_drawdown:.2%}. S1-scaled values were {ss.cagr:.2%}/{ss.sharpe:.3f}/{ss.max_drawdown:.2%}.",
        f"Simple Raw scaling captured {c['simple_capture_of_dual_maxdd_improvement']:.1%} of frozen Dual's MaxDD improvement. Classification: `{c['gross_controller_classification']}`.",
        f"The same-gross S1-minus-Raw Sharpe delta was {ss.sharpe-rs.sharpe:+.3f}; S1 remains valuable at the same gross: `{c['does_s1_remain_valuable_at_same_gross']}`.", "",
        "## Frozen identities", "",
        f"- Raw: `{result['raw_reconciliation']}`; S1: `{result['s1_reconciliation']}`.",
        f"- Dual reference: `{result['dual_reference_status']}`.",
        f"- Gross-scaler contract: `{result['contract']['gross_scaler_contract_hash']}`.",
        "- Rule, floor, taxonomy, cash and cost conventions were frozen before economic replay.", "",
        "## Arm scorecard", "",
        "| Arm | CAGR | Sharpe | MaxDD | QQQ beta | Residual Sharpe | Downside capture | Avg gross |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in by.index:
        row = by.loc[arm]
        lines.append(f"| {arm} | {row.cagr:.4f} | {row.sharpe:.4f} | {row.max_drawdown:.4f} | {row.qqq_beta:.4f} | {row.residual_sharpe:.4f} | {row.downside_capture:.4f} | {row.average_equity_gross:.4f} |")
    lines += ["", "## Interpretation", "", f"- Strongest support: {result['strongest_supporting_evidence']}",
              f"- Most damaging evidence: {result['most_damaging_evidence']}",
              "- Lower absolute sector exposure is not lower equity-normalized concentration.",
              f"- Forward eligibility: `{c['forward_eligibility']}`; recommended arms: `{c['recommended_forward_arms']}`.",
              "- All 2023–2025 economics are `EXPOSED_DIAGNOSTIC_ONLY`.", ""]
    (OUT / "final_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_manifest(cash, extra: dict[str, Any]) -> dict[str, Any]:
    artifacts = []
    for name in sorted(item for item in FINAL_FILES if item != "hash_manifest.json"):
        path = OUT / name
        require(path.is_file(), "MISSING_FINAL_ARTIFACT", name)
        artifacts.append({"name": name, "bytes": path.stat().st_size, "sha256": cash.sha256_file(path)})
    manifest = {
        "task_id": TASK_ID, "status": "PASS_HASH_VERIFIED", "2026_outcome_used": False,
        "artifact_count_including_manifest": len(artifacts) + 1, "artifacts": artifacts,
        "authoritative_inputs": {str(TOP20): cash.sha256_file(TOP20), str(PORTFOLIO): cash.sha256_file(PORTFOLIO), str(TAXONOMY): cash.sha256_file(TAXONOMY), str(DUAL_CONTRACT): cash.sha256_file(DUAL_CONTRACT)},
        "extra_lineage": extra, "task_source_sha256": cash.sha256_file(Path(__file__)),
    }
    require(manifest["artifact_count_including_manifest"] <= 7, "ARTIFACT_BUDGET")
    cash.atomic_json(OUT / "hash_manifest.json", manifest)
    return manifest


def fmt(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).upper()
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def terminal_summary(result: dict[str, Any], arms: pd.DataFrame, paired: pd.DataFrame, mechanics: dict[str, Any]) -> str:
    by, p = arms.set_index("arm"), paired.set_index("comparison")
    raw, s1, rs, ss, dual = (by.loc[name] for name in ("RAW_A2", "S1_SOFT_025", "RAW_CONCENTRATION_GROSS_SCALED", "S1_CONCENTRATION_GROSS_SCALED", "DUAL_SECTOR_CASH_REFERENCE"))
    c, years = result["classification"], result["year_diagnostics"]
    year_line = lambda year, arm: f"CAGR_{years[str(year)][arm]['cagr']:.6f}|SHARPE_{years[str(year)][arm]['sharpe']:.6f}|MAXDD_{years[str(year)][arm]['max_drawdown']:.6f}|EXPOSED_DIAGNOSTIC_ONLY"
    lines = ["=" * 60, f"{TASK_ID}_FINAL", "=" * 60, "", f"TASK_STATUS={result['task_status']}", "2026_OUTCOME_USED=FALSE", "",
        "-"*60, "IDENTITY", "-"*60, "", f"RAW_RECONCILIATION={result['raw_reconciliation']}", f"S1_RECONCILIATION={result['s1_reconciliation']}",
        "TAXONOMY_STATUS=PASS_FROZEN_HASH_EXACT", f"DUAL_CASH_REFERENCE_STATUS={result['dual_reference_status']}", "", f"GROSS_SCALER_CONTRACT_HASH={result['contract']['gross_scaler_contract_hash']}", "",
        "-"*60, "GROSS MECHANISM", "-"*60, "", f"AVG_GROSS={fmt(mechanics['average_gross'])}", f"MEDIAN_GROSS={fmt(mechanics['median_gross'])}", f"MIN_GROSS={fmt(mechanics['min_gross'])}", "",
        f"AVG_CASH={fmt(mechanics['average_cash'])}", f"P90_CASH={fmt(mechanics['p90_cash'])}", f"MAX_CASH={fmt(mechanics['max_cash'])}", "", f"PCT_GROSS_FLOOR_BINDING={fmt(mechanics['pct_sessions_gross_floor_080'])}", "",
        f"G12_BINDING_PCT={fmt(mechanics['g12_binding_pct'])}", f"G48_BINDING_PCT={fmt(mechanics['g48_binding_pct'])}", "",
        f"CORR_FF12_HHI_CASH={fmt(mechanics['corr_raw_ff12_hhi_cash'])}", f"CORR_FF48_HHI_CASH={fmt(mechanics['corr_raw_ff48_hhi_cash'])}", "",
        f"SIMPLE_VS_DUAL_GROSS_CORRELATION={fmt(mechanics['simple_vs_dual_gross_correlation'])}", f"SIMPLE_VS_DUAL_GROSS_MAE={fmt(mechanics['simple_vs_dual_gross_mean_absolute_difference'])}", "",
        "-"*60, "RAW", "-"*60, "", f"RAW_CAGR={fmt(raw.cagr)}", f"RAW_SHARPE={fmt(raw.sharpe)}", f"RAW_MAXDD={fmt(raw.max_drawdown)}", f"RAW_QQQ_BETA={fmt(raw.qqq_beta)}", f"RAW_RESIDUAL_SHARPE={fmt(raw.residual_sharpe)}", f"RAW_DOWNSIDE_CAPTURE={fmt(raw.downside_capture)}", "",
        "-"*60, "S1", "-"*60, "", f"S1_CAGR={fmt(s1.cagr)}", f"S1_SHARPE={fmt(s1.sharpe)}", f"S1_MAXDD={fmt(s1.max_drawdown)}", f"S1_QQQ_BETA={fmt(s1.qqq_beta)}", f"S1_RESIDUAL_SHARPE={fmt(s1.residual_sharpe)}", f"S1_DOWNSIDE_CAPTURE={fmt(s1.downside_capture)}", "",
        "-"*60, "RAW + SIMPLE GROSS", "-"*60, "", f"RAW_SCALED_CAGR={fmt(rs.cagr)}", f"RAW_SCALED_SHARPE={fmt(rs.sharpe)}", f"RAW_SCALED_MAXDD={fmt(rs.max_drawdown)}", f"RAW_SCALED_QQQ_BETA={fmt(rs.qqq_beta)}", f"RAW_SCALED_RESIDUAL_SHARPE={fmt(rs.residual_sharpe)}", f"RAW_SCALED_DOWNSIDE_CAPTURE={fmt(rs.downside_capture)}", "",
        "-"*60, "S1 + SIMPLE GROSS", "-"*60, "", f"S1_SCALED_CAGR={fmt(ss.cagr)}", f"S1_SCALED_SHARPE={fmt(ss.sharpe)}", f"S1_SCALED_MAXDD={fmt(ss.max_drawdown)}", f"S1_SCALED_QQQ_BETA={fmt(ss.qqq_beta)}", f"S1_SCALED_RESIDUAL_SHARPE={fmt(ss.residual_sharpe)}", f"S1_SCALED_DOWNSIDE_CAPTURE={fmt(ss.downside_capture)}", "",
        "-"*60, "SAME-GROSS S1 VALUE", "-"*60, "", f"S1_SCALED_MINUS_RAW_SCALED_CAGR={fmt(ss.cagr-rs.cagr)}", f"S1_SCALED_MINUS_RAW_SCALED_SHARPE={fmt(ss.sharpe-rs.sharpe)}", f"S1_SCALED_MINUS_RAW_SCALED_MAXDD={fmt(ss.max_drawdown-rs.max_drawdown)}", "",
        f"S1_SCALED_VS_RAW_SCALED_HAC_TSTAT={fmt(p.loc['S1_SCALED_MINUS_RAW_SCALED','hac_tstat'])}", f"S1_SCALED_VS_RAW_SCALED_BOOTSTRAP_P_POSITIVE={fmt(p.loc['S1_SCALED_MINUS_RAW_SCALED','bootstrap_probability_positive'])}", "",
        "-"*60, "SIMPLE VS DUAL CASH", "-"*60, "", f"DUAL_CAGR={fmt(dual.cagr)}", f"DUAL_SHARPE={fmt(dual.sharpe)}", f"DUAL_MAXDD={fmt(dual.max_drawdown)}", "",
        f"SIMPLE_RAW_SCALED_MINUS_DUAL_CAGR={fmt(rs.cagr-dual.cagr)}", f"SIMPLE_RAW_SCALED_MINUS_DUAL_SHARPE={fmt(rs.sharpe-dual.sharpe)}", f"SIMPLE_RAW_SCALED_MINUS_DUAL_MAXDD={fmt(rs.max_drawdown-dual.max_drawdown)}", "",
        f"SIMPLE_CAPTURE_OF_DUAL_MAXDD_IMPROVEMENT={fmt(c['simple_capture_of_dual_maxdd_improvement'])}", f"SIMPLE_CAPTURE_OF_DUAL_BETA_REDUCTION={fmt(c['simple_capture_of_dual_beta_reduction'])}", f"SIMPLE_CAPTURE_OF_DUAL_DOWNSIDE_IMPROVEMENT={fmt(c['simple_capture_of_dual_downside_improvement'])}", "",
        f"DUAL_VS_SIMPLE_HAC_TSTAT={fmt(p.loc['DUAL_MINUS_RAW_SCALED','hac_tstat'])}", f"DUAL_VS_SIMPLE_BOOTSTRAP_P_POSITIVE={fmt(p.loc['DUAL_MINUS_RAW_SCALED','bootstrap_probability_positive'])}", "",
        "-"*60, "EXPOSED DIAGNOSTICS", "-"*60, "", f"2023_RAW_SCALED={year_line(2023,'RAW_CONCENTRATION_GROSS_SCALED')}", f"2023_S1_SCALED={year_line(2023,'S1_CONCENTRATION_GROSS_SCALED')}", "",
        f"2024_RAW_SCALED={year_line(2024,'RAW_CONCENTRATION_GROSS_SCALED')}", f"2024_S1_SCALED={year_line(2024,'S1_CONCENTRATION_GROSS_SCALED')}", "", f"2025_RAW_SCALED={year_line(2025,'RAW_CONCENTRATION_GROSS_SCALED')}", f"2025_S1_SCALED={year_line(2025,'S1_CONCENTRATION_GROSS_SCALED')}", "",
        f"RAW_MAXDD_PERIOD_SCALED_RESULT={result['raw_maxdd_period']['RAW_CONCENTRATION_GROSS_SCALED']}", "", "-"*60, "VERDICT", "-"*60, "", f"GROSS_CONTROLLER_CLASSIFICATION={c['gross_controller_classification']}", "",
        f"DOES_SIMPLE_SCALER_CAPTURE_MOST_DUAL_VALUE={fmt(c['does_simple_scaler_capture_most_dual_value'])}", f"DOES_S1_REMAIN_VALUABLE_AT_SAME_GROSS={fmt(c['does_s1_remain_valuable_at_same_gross'])}", f"IS_S1_PLUS_GROSS_SCALER_FORWARD_WORTHY={fmt(c['is_s1_plus_gross_scaler_forward_worthy'])}", "",
        f"MOST_DAMAGING_EVIDENCE={result['most_damaging_evidence']}", f"STRONGEST_SUPPORTING_EVIDENCE={result['strongest_supporting_evidence']}", "", f"FORWARD_ELIGIBILITY={c['forward_eligibility']}", f"RECOMMENDED_FORWARD_ARMS={c['recommended_forward_arms']}", "",
        "ANTI_OVERFIT_STATUS=PASS_FIXED_OUTCOME_INDEPENDENT_RULE_EXPOSED_DIAGNOSTICS_ONLY", "TASK_LOCAL_ANTI_BLOAT_STATUS=PASS", f"PREEXISTING_ACL_EXCEPTION_COUNT={PREEXISTING_ACL_EXCEPTIONS}", "", f"OUTPUT_DIR={OUT}", f"FINAL_ARTIFACT_COUNT={result['manifest']['artifact_count_including_manifest']}", f"HASH_MANIFEST_STATUS={result['manifest']['status']}", "", "="*60]
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cash = import_file("a2_gross_cash_base", CASH_SOURCE)
    joined, identity, _, prior_gross = load_and_verify_inputs(cash)
    primary_targets, diagnostics, mechanics = build_primary_targets(cash, joined, prior_gross)
    contract = freeze_contract(cash, identity, primary_targets, mechanics)
    arms, paired, economics = run_economics(cash, joined, primary_targets, diagnostics, contract)
    task_status = "RESEARCH_COMPLETE_WITH_PREEXISTING_REPOSITORY_ANTI_BLOAT_HARD_GATE_FAIL"
    result = {**economics, "task_id": TASK_ID, "task_status": task_status, "contract": contract,
              "mechanics": mechanics, "2026_outcome_used": False, "2026_leakage_count": 0,
              "anti_overfit_status": "PASS_FIXED_OUTCOME_INDEPENDENT_RULE_EXPOSED_DIAGNOSTICS_ONLY",
              "task_local_anti_bloat_status": "PASS", "preexisting_acl_exception_count": PREEXISTING_ACL_EXCEPTIONS}
    cash.atomic_csv(OUT / "arm_summary.csv", arms)
    cash.atomic_csv(OUT / "gross_and_concentration_diagnostics.csv", add_quintile_rows(economics.pop("diagnostics")))
    cash.atomic_csv(OUT / "paired_statistics.csv", paired)
    result.pop("diagnostics", None)
    cash.atomic_json(OUT / "classification.json", result)
    write_report(result, arms, mechanics)
    manifest = write_manifest(cash, {"gross_scaler_contract_hash": contract["gross_scaler_contract_hash"], **economics["price_input_hashes"]})
    result["manifest"] = manifest
    print(terminal_summary(result, arms, paired, mechanics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
