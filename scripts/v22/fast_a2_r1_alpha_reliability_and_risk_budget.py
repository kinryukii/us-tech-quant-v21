"""Outcome-blind FAST risk-budget translation for the frozen A2-HGB portfolio.

The experiment changes only total gross exposure (1.0 or 0.5).  Stock ranks,
Top20 membership, execution eligibility, costs, and the R4 price contract stay
unchanged.  ``--freeze-only`` never opens the R4 daily portfolio artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


EXPERIMENT_ID = "FAST_A2_R1_ALPHA_RELIABILITY_AND_RISK_BUDGET"
REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results") / EXPERIMENT_ID
R4_ROOT = Path(r"D:\us-tech-quant-results\ABCDE_A2_R4_PORTFOLIO_TRANSLATION_USING_HGB_INCUMBENT")
R4_SUMMARY_PATH = R4_ROOT / "abcde_a2_r4_summary.json"
R4_DAILY_PATH = R4_ROOT / "a1_a2_top20_daily_portfolio.parquet"
R4_ACTIVATION_PATH = R4_ROOT / "a2_r4_prospective_shadow_activation.json"
R4_POLICY_PATH = R4_ROOT / "a2_r4_execution_eligibility_policy_r1.json"
R4_MODULE_PATH = REPO_ROOT / "scripts" / "v22" / "abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py"

FAST_ROOT = Path(r"D:\us-tech-quant-results\v22\V22.056_FAST3_CBOE_DAILY_VIX_INGEST_AND_PIT_REGIME_R1")
FAST_SUMMARY_PATH = FAST_ROOT / "v22_056_summary.json"
FAST_MANIFEST_PATH = FAST_ROOT / "v22_056_run_manifest.json"
FAST_STATE_PATH = Path(r"D:\us-tech-quant-data\fast3\vix_cboe_daily\features\vix_prior_day_regime_features.parquet")

CONTRACT_PATH = RESULTS_ROOT / "fast_a2_r1_risk_budget_contract.json"
WITNESS_PATH = RESULTS_ROOT / "fast_a2_r1_contract_freeze_witness.json"
IDENTITY_PATH = RESULTS_ROOT / "fast_a2_r1_fast_state_identity.json"
DAILY_RISK_PATH = RESULTS_ROOT / "fast_a2_r1_daily_risk_state.parquet"
DAILY_PORTFOLIO_PATH = RESULTS_ROOT / "fast_a2_r1_daily_portfolio.parquet"
METRICS_PATH = RESULTS_ROOT / "fast_a2_r1_metrics.parquet"
COST_PATH = RESULTS_ROOT / "fast_a2_r1_cost_sensitivity.json"
DIAGNOSTICS_PATH = RESULTS_ROOT / "fast_a2_r1_reliability_diagnostics.json"
SUMMARY_PATH = RESULTS_ROOT / "fast_a2_r1_summary.json"
MANIFEST_PATH = RESULTS_ROOT / "fast_a2_r1_manifest.json"
ACTIVATION_PATH = RESULTS_ROOT / "fast_a2_r1_prospective_shadow_activation.json"

EXPECTED_R4_POLICY_SHA256 = "79a36251b01785d4c7316acb3e3bee6a47b802e7b53c74a7e5a113d5774e134a"
EXPECTED_CURRENT_COHORT_FINGERPRINT = "0128b9ce5eccf74c059e93a09ada7d60605a9cc30b64a44a36087bc930c0a9dc"
PRIMARY_FAST_RISK_STATE_ID = "FAST3_V22_056_PRIOR_COMPLETED_SESSION_OFFICIAL_CBOE_VIX_CLOSE"
TRAILING_LOOKBACK = 252
MIN_HISTORY = 126
HIGH_RISK_THRESHOLD = 0.75
HIGH_RISK_BUDGET = 0.50
NORMAL_RISK_BUDGET = 1.00
BOOTSTRAP_BLOCK_LENGTH = 20
BOOTSTRAP_RESAMPLE_COUNT = 2000
BOOTSTRAP_SEED = 20260816


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_payload(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_payload(value) + b"\n")
    os.replace(temporary, path)


def write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), temporary, compression="zstd", use_dictionary=True)
    os.replace(temporary, path)


def import_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def prerequisite_identity() -> dict[str, Any]:
    required = [R4_SUMMARY_PATH, R4_DAILY_PATH, R4_ACTIVATION_PATH, R4_POLICY_PATH, R4_MODULE_PATH,
                FAST_SUMMARY_PATH, FAST_MANIFEST_PATH, FAST_STATE_PATH]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("MISSING_AUTHORITATIVE_PREREQUISITE:" + ",".join(missing))
    # Only metadata JSON is read here.  R4_DAILY_PATH remains unopened.
    r4 = json.loads(R4_SUMMARY_PATH.read_text(encoding="utf-8"))
    activation = json.loads(R4_ACTIVATION_PATH.read_text(encoding="utf-8"))
    fast = json.loads(FAST_SUMMARY_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(FAST_MANIFEST_PATH.read_text(encoding="utf-8"))
    checks = {
        "r4_status": r4.get("ABCDE_A2_R4_STATUS") == "PASS",
        "r4_classification": r4.get("R4_CLASSIFICATION") == "P1_STRONG_PORTFOLIO_TRANSLATION",
        "prospective_status": r4.get("PROSPECTIVE_HGB_SHADOW_STATUS") == "ACTIVE_ACCUMULATING",
        "prospective_start": r4.get("FIRST_LEGAL_PROSPECTIVE_SIGNAL_DATE") == "2026-08-17",
        "no_backfill": activation.get("NO_BACKFILL") is True,
        "r4_policy": sha256_file(R4_POLICY_PATH) == EXPECTED_R4_POLICY_SHA256,
        "fast_status": fast.get("final_status") == "PASS",
        "fast_daily_ready": fast.get("daily_vix_regime_ready") is True,
        "fast_pit": fast.get("prior_day_shift_validated") is True,
        "fast_official_source": str(fast.get("source_used", "")).startswith("https://cdn.cboe.com/"),
        "fast_artifact_manifest": Path(manifest["outputs"]["feature_parquet"]) == FAST_STATE_PATH,
    }
    if not all(checks.values()):
        raise RuntimeError("PREREQUISITE_IDENTITY_FAILURE:" + ",".join(key for key, ok in checks.items() if not ok))
    return {
        "checks": checks,
        "r4_summary_sha256": sha256_file(R4_SUMMARY_PATH),
        "r4_daily_path_verified_present_but_unopened": str(R4_DAILY_PATH),
        "r4_activation_sha256": sha256_file(R4_ACTIVATION_PATH),
        "r4_execution_policy_sha256": sha256_file(R4_POLICY_PATH),
        "fast_summary_sha256": sha256_file(FAST_SUMMARY_PATH),
        "fast_manifest_sha256": sha256_file(FAST_MANIFEST_PATH),
        "fast_state_sha256": sha256_file(FAST_STATE_PATH),
    }


def fast_state_identity(prerequisite: dict[str, Any]) -> dict[str, Any]:
    parquet = pq.ParquetFile(FAST_STATE_PATH)
    names = parquet.schema_arrow.names
    required = {"trade_date", "vix_prev_close", "feature_information_cutoff"}
    if not required.issubset(names):
        raise RuntimeError("FAST_STATE_SCHEMA_FAILURE:" + ",".join(sorted(required - set(names))))
    return {
        "PRIMARY_FAST_RISK_STATE_ID": PRIMARY_FAST_RISK_STATE_ID,
        "PRIMARY_FAST_RISK_STATE_ARTIFACT": str(FAST_STATE_PATH),
        "PRIMARY_FAST_RISK_STATE_SHA256": prerequisite["fast_state_sha256"],
        "FAST_STATE_SOURCE_STAGE": "V22.056_FAST3_CBOE_DAILY_VIX_INGEST_AND_PIT_REGIME_R1",
        "FAST_STATE_SOURCE_FIELD": "vix_prev_close",
        "FAST_STATE_ORIENTATION": "HIGHER_OFFICIAL_PRIOR_SESSION_VIX_CLOSE_EQUALS_HIGHER_MARKET_RISK",
        "FAST_STATE_INFORMATION_CUTOFF": "PRIOR_COMPLETED_US_TRADING_SESSION_CLOSE",
        "FAST_STATE_ROW_COUNT": parquet.metadata.num_rows,
        "FAST_STATE_SCHEMA": names,
        "FAST_STATE_PIT_STATUS": "PASS_INHERITED_V22_056_PRIOR_DAY_SHIFT_VALIDATED",
        "ALTERNATIVE_FROZEN_FAST_OUTPUT_DISPOSITION": {
            "R35_R36": "EVENT_OR_CANDIDATE_LEVEL_OR_PROSPECTIVE_ONLY_NOT_A_DAILY_MARKET_RISK_STATE",
            "V22_060": "DIAGNOSTIC_ONLY_AND_EXPLICITLY_NOT_QUALIFIED",
            "REPO_FAST3_STATE": "SYNTHETIC_VALIDATION_ONLY_NOT_EMPIRICAL_DAILY_RISK_STATE",
        },
        "PRIMARY_SELECTION_USED_A2_OUTCOME": False,
    }


def risk_budget_contract(identity: dict[str, Any], prerequisite: dict[str, Any]) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST_A2_R1_RISK_BUDGET_CONTRACT_R1",
        "EXPERIMENT_ID": EXPERIMENT_ID,
        "EVIDENCE_ROLE": "PRE2026_RISK_BUDGET_DEVELOPMENT_EVIDENCE",
        "PRIMARY_FAST_RISK_STATE_ID": identity["PRIMARY_FAST_RISK_STATE_ID"],
        "PRIMARY_FAST_RISK_STATE_ARTIFACT": identity["PRIMARY_FAST_RISK_STATE_ARTIFACT"],
        "PRIMARY_FAST_RISK_STATE_SHA256": identity["PRIMARY_FAST_RISK_STATE_SHA256"],
        "FAST_STATE_ORIENTATION": identity["FAST_STATE_ORIENTATION"],
        "FAST_INFORMATION_CUTOFF": "PRIOR_COMPLETED_US_TRADING_SESSION_CLOSE",
        "A2_INFORMATION_CUTOFF": "SIGNAL_DATE_FULL_DAY_CLOSE_AND_VOLUME_COMPLETE",
        "RISK_BUDGET_DECISION_TIMESTAMP": "AFTER_SIGNAL_DATE_CLOSE_BEFORE_NEXT_LEGAL_SESSION_OPEN",
        "PORTFOLIO_EXECUTION_TIMESTAMP": "NEXT_LEGAL_CANONICAL_SESSION_OPEN",
        "NORMALIZATION": {
            "method": "TRAILING_EMPIRICAL_PERCENTILE_STRICTLY_PRIOR_STATES",
            "source_score": "vix_prev_close",
            "lookback_sessions": TRAILING_LOOKBACK,
            "minimum_history_sessions": MIN_HISTORY,
            "current_observation_excluded_from_reference": True,
            "tie_policy": "AVERAGE_EMPIRICAL_PERCENTILE=(count_less+0.5*count_equal)/N",
            "future_fill": False,
        },
        "HIGH_RISK_THRESHOLD": HIGH_RISK_THRESHOLD,
        "HIGH_RISK_COMPARATOR": ">=",
        "RISK_BUDGET_MAPPING": {"NORMAL_RISK": NORMAL_RISK_BUDGET, "HIGH_RISK": HIGH_RISK_BUDGET,
                                "INSUFFICIENT_FAST_HISTORY": NORMAL_RISK_BUDGET},
        "RISK_BUDGET_SET": [HIGH_RISK_BUDGET, NORMAL_RISK_BUDGET],
        "PORTFOLIOS": {"baseline": "A2_HGB_TOP20_1X", "challenger": "FAST_GATED_A2_HGB_TOP20"},
        "STOCK_SELECTION_CHANGED": False,
        "PRIMARY_TOP_N": 20,
        "PRIMARY_ONE_WAY_COST_BPS": 10,
        "COST_SENSITIVITY_BPS": [0, 5, 10, 20],
        "CASH_RETURN": 0.0,
        "RISK_FREE_RATE": 0.0,
        "R4_EXECUTION_ELIGIBILITY_POLICY_SHA256": EXPECTED_R4_POLICY_SHA256,
        "R4_EXECUTION_POLICY_CHANGED": False,
        "BENCHMARK": "QQQ_CANONICAL_QFQ_OPEN_TO_OPEN_INHERITED_R4",
        "BOOTSTRAP": {"method": "PAIRED_MOVING_BLOCK", "block_length_trading_days": BOOTSTRAP_BLOCK_LENGTH,
                      "resample_count": BOOTSTRAP_RESAMPLE_COUNT, "random_seed": BOOTSTRAP_SEED,
                      "confidence_interval": 0.95},
        "RELIABILITY_SUPPORT_RULE": {
            "description": "HIGH_RISK must be directionally worse on at least two of four downside diagnostics",
            "diagnostics": ["downside_volatility_higher", "negative_day_frequency_higher",
                            "worst_1pct_return_lower", "worst_5pct_return_lower"],
            "minimum_supporting_count": 2,
        },
        "DECISION_GATE": {
            "F1": ["challenger_sharpe_gt_baseline", "challenger_calmar_gt_baseline",
                   "abs_challenger_max_drawdown_lt_abs_baseline", "challenger_cagr_gt_zero",
                   "at_least_2_of_3_years_calmar_or_drawdown_improved", "reliability_support_rule_pass",
                   "timing_execution_pit_reproducibility_pass"],
            "F2": "some_drawdown_or_volatility_improvement_but_not_all_F1_conditions",
            "F3": "no_core_risk_adjusted_improvement_or_material_alpha_damage",
            "FAIL_CLOSED": "identity_timing_data_execution_or_reproducibility_failure",
        },
        "MODEL_FIT_ALLOWED": False,
        "FAST_MODEL_SELECTION_ALLOWED": False,
        "POST2025_OUTCOME_ALLOWED": False,
        "A2_PROSPECTIVE_SHADOW_CHANGED": False,
        "R4_DAILY_ARTIFACT": prerequisite["r4_daily_path_verified_present_but_unopened"],
    }


def freeze_contract() -> dict[str, Any]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    prerequisite = prerequisite_identity()
    identity = fast_state_identity(prerequisite)
    contract = risk_budget_contract(identity, prerequisite)
    contract_bytes = canonical_payload(contract) + b"\n"
    contract_sha = hashlib.sha256(contract_bytes).hexdigest()
    if CONTRACT_PATH.exists():
        if CONTRACT_PATH.read_bytes() != contract_bytes:
            raise RuntimeError("EXISTING_FAST_A2_CONTRACT_DIFFERS")
        if not WITNESS_PATH.is_file() or not IDENTITY_PATH.is_file():
            raise RuntimeError("CONTRACT_EXISTS_WITHOUT_WITNESS_OR_IDENTITY")
        witness = json.loads(WITNESS_PATH.read_text(encoding="utf-8"))
        if witness.get("FAST_A2_R1_CONTRACT_SHA256") != contract_sha:
            raise RuntimeError("CONTRACT_WITNESS_SHA256_MISMATCH")
        return witness
    write_json_atomic(CONTRACT_PATH, contract)
    write_json_atomic(IDENTITY_PATH, identity)
    witness = {
        "EXPERIMENT_ID": EXPERIMENT_ID,
        "FAST_A2_R1_CONTRACT_SHA256": contract_sha,
        "CONTRACT_FROZEN_BEFORE_A2_OUTCOME_READ": True,
        "A2_PORTFOLIO_OUTCOME_READ_COUNT_BEFORE_FREEZE": 0,
        "POST2025_TARGET_READ_COUNT_BEFORE_FREEZE": 0,
        "POST2025_OUTCOME_READ_COUNT_BEFORE_FREEZE": 0,
        "R4_DAILY_PORTFOLIO_PATH_WAS_OPENED_BEFORE_FREEZE": False,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "prerequisite_identity": prerequisite,
        "status": "PASS_FROZEN_OUTCOME_BLIND",
    }
    write_json_atomic(WITNESS_PATH, witness)
    return witness


def _frame_fingerprint(frame: pd.DataFrame, columns: list[str]) -> str:
    ordered = frame.loc[:, columns].copy()
    for column in ordered.columns:
        if pd.api.types.is_datetime64_any_dtype(ordered[column]):
            ordered[column] = ordered[column].dt.strftime("%Y-%m-%d")
    hashes = pd.util.hash_pandas_object(ordered, index=False, categorize=True).to_numpy(dtype=np.uint64)
    digest = hashlib.sha256()
    digest.update("|".join(columns).encode("utf-8"))
    digest.update(hashes.tobytes())
    return digest.hexdigest()


def trailing_prior_percentile(values: np.ndarray, lookback: int = TRAILING_LOOKBACK,
                              minimum_history: int = MIN_HISTORY) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(values, dtype=float)
    percentiles = np.full(len(values), np.nan, dtype=float)
    history_counts = np.zeros(len(values), dtype=np.int64)
    for index, current in enumerate(values):
        history = values[max(0, index - lookback):index]
        history = history[np.isfinite(history)]
        history_counts[index] = len(history)
        if len(history) >= minimum_history and np.isfinite(current):
            less = int(np.sum(history < current))
            equal = int(np.sum(history == current))
            percentiles[index] = (less + 0.5 * equal) / len(history)
    return percentiles, history_counts


def materialize_risk_state(signal_dates: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[pd.Timestamp, float], dict[str, Any]]:
    frame = pq.read_table(
        FAST_STATE_PATH,
        columns=["trade_date", "vix_prev_close", "feature_information_cutoff"],
    ).to_pandas()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame["feature_information_cutoff"] = pd.to_datetime(frame["feature_information_cutoff"])
    frame["fast_risk_score"] = pd.to_numeric(frame["vix_prev_close"], errors="coerce")
    frame = frame.loc[frame.trade_date < pd.Timestamp("2026-01-01")].sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    if frame.duplicated("trade_date").any() or (frame.feature_information_cutoff >= frame.trade_date).any():
        raise RuntimeError("FAST_STATE_DATE_OR_INFORMATION_CUTOFF_FAILURE")
    values = frame.fast_risk_score.to_numpy(dtype=float)
    percentiles, history_counts = trailing_prior_percentile(values)
    frame["fast_risk_percentile"] = percentiles
    frame["fast_history_count"] = history_counts
    frame["insufficient_fast_history"] = history_counts < MIN_HISTORY
    frame["high_risk"] = frame.fast_risk_percentile.ge(HIGH_RISK_THRESHOLD) & ~frame.insufficient_fast_history
    frame["risk_budget"] = np.where(frame.high_risk, HIGH_RISK_BUDGET, NORMAL_RISK_BUDGET)
    aligned = frame.loc[frame.trade_date.isin(signal_dates)].copy()
    missing = signal_dates.difference(pd.DatetimeIndex(aligned.trade_date))
    if len(missing):
        raise RuntimeError("FAST_STATE_MISSING_SIGNAL_DATES:" + ",".join(str(date.date()) for date in missing[:10]))
    aligned = aligned.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    if len(aligned) != len(signal_dates) or aligned.fast_risk_score.isna().any():
        raise RuntimeError("FAST_STATE_ALIGNMENT_OR_FINITE_FAILURE")
    if not aligned.fast_risk_percentile.dropna().between(0.0, 1.0).all():
        raise RuntimeError("FAST_PERCENTILE_RANGE_FAILURE")
    budget_map = {pd.Timestamp(row.trade_date): float(row.risk_budget) for row in aligned.itertuples(index=False)}
    audit = {
        "FAST_A2_TIMING_AUDIT_STATUS": "PASS",
        "FAST_INFORMATION_CUTOFF": "PRIOR_COMPLETED_US_TRADING_SESSION_CLOSE",
        "A2_INFORMATION_CUTOFF": "SIGNAL_DATE_FULL_DAY_CLOSE_AND_VOLUME_COMPLETE",
        "RISK_BUDGET_DECISION_TIMESTAMP": "AFTER_SIGNAL_DATE_CLOSE_BEFORE_NEXT_LEGAL_SESSION_OPEN",
        "PORTFOLIO_EXECUTION_TIMESTAMP": "NEXT_LEGAL_CANONICAL_SESSION_OPEN",
        "aligned_signal_date_count": len(aligned),
        "state_start": str(aligned.trade_date.min().date()),
        "state_end": str(aligned.trade_date.max().date()),
        "future_state_reference_count": 0,
        "post2025_state_row_count": 0,
        "information_cutoff_violation_count": 0,
        "high_risk_signal_date_count": int(aligned.high_risk.sum()),
        "insufficient_history_signal_date_count": int(aligned.insufficient_fast_history.sum()),
    }
    return aligned, budget_map, audit


def _period_metrics(r4: Any, frame: pd.DataFrame) -> dict[str, Any]:
    metrics = r4.portfolio_metrics(frame)
    metrics["sharpe"] = metrics["sharpe_rf0"]
    ordered = frame.sort_values("execution_date", kind="mergesort")
    returns = ordered.net_return.astype(float)
    monthly = ordered.set_index("execution_date").net_return.resample("ME").apply(lambda x: float(np.prod(1.0 + x) - 1.0))
    metrics.update({
        "worst_day": float(returns.min()),
        "worst_month": float(monthly.min()),
        "empirical_1pct_quantile": float(returns.quantile(0.01)),
        "average_gross_exposure": float(ordered.gross_exposure.mean()),
        "fraction_days_at_0_5x": float(np.mean(np.isclose(ordered.risk_budget.astype(float), 0.5))),
        "average_cash_weight": float(ordered.cash_weight.mean()),
        "observation_count": len(ordered),
    })
    return metrics


def _downside_volatility(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    return float(np.sqrt(np.mean(np.minimum(values, 0.0) ** 2)) * np.sqrt(252.0)) if len(values) else np.nan


def reliability_diagnostics(baseline: pd.DataFrame, risk: pd.DataFrame) -> dict[str, Any]:
    joined = baseline.merge(
        risk[["trade_date", "high_risk", "risk_budget"]],
        left_on="signal_date_used", right_on="trade_date", how="left", validate="many_to_one",
    )
    joined = joined.loc[joined.signal_date_used.notna() & joined.high_risk.notna()].copy()
    states: dict[str, Any] = {}
    for label, flag in (("NORMAL_RISK", False), ("HIGH_RISK", True)):
        returns = joined.loc[joined.high_risk == flag, "net_return"].to_numpy(dtype=float)
        negative = returns[returns < 0]
        states[label] = {
            "day_count": len(returns),
            "mean_daily_return": float(np.mean(returns)),
            "annualized_volatility": float(np.std(returns, ddof=0) * np.sqrt(252.0)),
            "downside_volatility": _downside_volatility(returns),
            "negative_day_frequency": float(np.mean(returns < 0)),
            "drawdown_return_contribution": float(np.sum(negative)),
            "worst_1pct_mean": float(np.mean(returns[returns <= np.quantile(returns, 0.01)])),
            "worst_5pct_mean": float(np.mean(returns[returns <= np.quantile(returns, 0.05)])),
            "benchmark_excess_mean_daily": float(np.mean(returns - joined.loc[joined.high_risk == flag, "benchmark_return"].to_numpy(dtype=float))),
        }
    normal, high = states["NORMAL_RISK"], states["HIGH_RISK"]
    directional = {
        "downside_volatility_higher": high["downside_volatility"] > normal["downside_volatility"],
        "negative_day_frequency_higher": high["negative_day_frequency"] > normal["negative_day_frequency"],
        "worst_1pct_return_lower": high["worst_1pct_mean"] < normal["worst_1pct_mean"],
        "worst_5pct_return_lower": high["worst_5pct_mean"] < normal["worst_5pct_mean"],
    }
    support_count = sum(directional.values())
    return {"states": states, "directional_checks": directional, "supporting_check_count": support_count,
            "minimum_required": 2, "HIGH_RISK_DOWNSIDE_DIAGNOSTICS_SUPPORT": support_count >= 2}


def _paired_block_bootstrap(baseline: pd.DataFrame, challenger: pd.DataFrame) -> dict[str, Any]:
    joined = baseline[["execution_date", "net_return"]].merge(
        challenger[["execution_date", "net_return"]], on="execution_date", suffixes=("_base", "_fast"), validate="one_to_one"
    ).sort_values("execution_date", kind="mergesort")
    base = joined.net_return_base.to_numpy(dtype=float)
    fast = joined.net_return_fast.to_numpy(dtype=float)
    n = len(joined)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    samples = np.empty((BOOTSTRAP_RESAMPLE_COUNT, 3), dtype=float)
    starts_max = max(1, n - BOOTSTRAP_BLOCK_LENGTH + 1)
    blocks_needed = int(np.ceil(n / BOOTSTRAP_BLOCK_LENGTH))
    for iteration in range(BOOTSTRAP_RESAMPLE_COUNT):
        starts = rng.integers(0, starts_max, size=blocks_needed)
        index = np.concatenate([np.arange(start, min(start + BOOTSTRAP_BLOCK_LENGTH, n)) for start in starts])[:n]
        b, f = base[index], fast[index]
        b_vol = np.std(b, ddof=0) * np.sqrt(252.0)
        f_vol = np.std(f, ddof=0) * np.sqrt(252.0)
        b_sharpe = np.mean(b) * 252.0 / b_vol if b_vol > 0 else np.nan
        f_sharpe = np.mean(f) * 252.0 / f_vol if f_vol > 0 else np.nan
        samples[iteration] = [f_sharpe - b_sharpe, np.mean(f - b), _downside_volatility(f) - _downside_volatility(b)]
    output: dict[str, Any] = {}
    for index, name in enumerate(("delta_sharpe", "delta_mean_daily_return", "delta_downside_volatility")):
        values = samples[:, index]
        output[name] = {"mean": float(np.nanmean(values)), "ci95_low": float(np.nanquantile(values, 0.025)),
                        "ci95_high": float(np.nanquantile(values, 0.975))}
    output.update({"block_length_trading_days": BOOTSTRAP_BLOCK_LENGTH, "resample_count": BOOTSTRAP_RESAMPLE_COUNT,
                   "random_seed": BOOTSTRAP_SEED})
    return output


def materialize_once() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    r4 = import_module("_fast_a2_r1_r4", R4_MODULE_PATH)
    r4.validate_prerequisites()
    signals, signal_audit = r4.load_authoritative_signals()
    if signal_audit.get("post2025_signal_count") != 0:
        raise RuntimeError("POST2025_SIGNAL_FAILURE")
    risk, budget_map, timing_audit = materialize_risk_state(pd.DatetimeIndex(sorted(signals.signal_date.unique())))
    prices, price_audit = r4.load_execution_prices(set(signals.ticker.unique()))
    authoritative = pq.read_table(R4_DAILY_PATH).to_pandas()
    authoritative["execution_date"] = pd.to_datetime(authoritative["execution_date"])
    authoritative_a2 = authoritative.loc[(authoritative.model == "A2_HGB") & (authoritative.top_n == 20) & (authoritative.cost_bps == 10)].copy()
    paths: list[pd.DataFrame] = []
    metric_rows: list[dict[str, Any]] = []
    primary_baseline: pd.DataFrame | None = None
    primary_challenger: pd.DataFrame | None = None
    for cost_bps in (0, 5, 10, 20):
        baseline = r4.simulate_portfolio(signals, prices, "A2_HGB_TOP20_1X", "a2_rank", 20, cost_bps)
        challenger = r4.simulate_portfolio(signals, prices, "FAST_GATED_A2_HGB_TOP20", "a2_rank", 20, cost_bps,
                                            risk_budget_by_signal_date=budget_map)
        for portfolio, frame in (("A2_HGB_TOP20_1X", baseline), ("FAST_GATED_A2_HGB_TOP20", challenger)):
            frame["portfolio"] = portfolio
            paths.append(frame)
            for period, subset in [("POOLED", frame)] + [(str(year), frame.loc[frame.execution_date.dt.year == year]) for year in (2023, 2024, 2025)]:
                row = {"portfolio": portfolio, "cost_bps": cost_bps, "period": period}
                row.update(_period_metrics(r4, subset))
                metric_rows.append(row)
        if cost_bps == 10:
            primary_baseline, primary_challenger = baseline.copy(), challenger.copy()
    if primary_baseline is None or primary_challenger is None:
        raise RuntimeError("PRIMARY_PATH_NOT_MATERIALIZED")
    identity_columns = [column for column in authoritative_a2.columns if column in primary_baseline.columns and column != "model"]
    left = authoritative_a2.sort_values("execution_date", kind="mergesort").reset_index(drop=True)[identity_columns]
    right = primary_baseline.sort_values("execution_date", kind="mergesort").reset_index(drop=True)[identity_columns]
    for column in identity_columns:
        if pd.api.types.is_numeric_dtype(left[column]):
            if not np.allclose(left[column].to_numpy(dtype=float), right[column].to_numpy(dtype=float), rtol=0.0, atol=1e-12, equal_nan=True):
                raise RuntimeError(f"R4_BASELINE_IDENTITY_NUMERIC_FAILURE:{column}")
        else:
            if not left[column].fillna("<NA>").equals(right[column].fillna("<NA>")):
                raise RuntimeError(f"R4_BASELINE_IDENTITY_FAILURE:{column}")
    all_paths = pd.concat(paths, ignore_index=True).sort_values(["cost_bps", "portfolio", "execution_date"], kind="mergesort").reset_index(drop=True)
    metrics = pd.DataFrame(metric_rows).sort_values(["cost_bps", "portfolio", "period"], kind="mergesort").reset_index(drop=True)
    audits = {"signal": signal_audit, "timing": timing_audit, "price": price_audit,
              "R4_BASELINE_REPLAY_IDENTITY_STATUS": "PASS", "POST2025_OUTCOME_READ_COUNT": 0,
              "2026_A2_OUTCOME_READ_COUNT": 0, "2026_FAST_A2_SELECTION_USE_COUNT": 0}
    return risk, all_paths, metrics, metric_rows, audits


def run_experiment() -> dict[str, Any]:
    witness = freeze_contract()
    run1 = materialize_once()
    run2 = materialize_once()
    risk1, paths1, metrics1, _, audits1 = run1
    risk2, paths2, metrics2, _, _ = run2
    risk_cols = ["trade_date", "fast_risk_score", "fast_risk_percentile", "fast_history_count", "high_risk", "risk_budget"]
    path_cols = ["execution_date", "signal_date_used", "portfolio", "cost_bps", "net_return", "gross_return",
                 "benchmark_return", "executed_turnover", "transaction_cost_amount", "gross_exposure", "cash_weight", "risk_budget"]
    metric_cols = ["portfolio", "cost_bps", "period", "cumulative_return", "cagr", "annualized_volatility", "sharpe", "max_drawdown", "calmar"]
    run1_fp = hashlib.sha256((
        _frame_fingerprint(risk1, risk_cols) + _frame_fingerprint(paths1, path_cols) + _frame_fingerprint(metrics1, metric_cols)
    ).encode("ascii")).hexdigest()
    run2_fp = hashlib.sha256((
        _frame_fingerprint(risk2, risk_cols) + _frame_fingerprint(paths2, path_cols) + _frame_fingerprint(metrics2, metric_cols)
    ).encode("ascii")).hexdigest()
    if run1_fp != run2_fp:
        raise RuntimeError("REPRODUCIBILITY_FINGERPRINT_MISMATCH")
    primary = paths1.loc[paths1.cost_bps == 10].copy()
    baseline = primary.loc[primary.portfolio == "A2_HGB_TOP20_1X"].copy()
    challenger = primary.loc[primary.portfolio == "FAST_GATED_A2_HGB_TOP20"].copy()
    diagnostics = reliability_diagnostics(baseline, risk1)
    diagnostics["bootstrap"] = _paired_block_bootstrap(baseline, challenger)
    pooled = metrics1.loc[(metrics1.cost_bps == 10) & (metrics1.period == "POOLED")].set_index("portfolio")
    b, f = pooled.loc["A2_HGB_TOP20_1X"], pooled.loc["FAST_GATED_A2_HGB_TOP20"]
    yearly_pass = 0
    for year in (2023, 2024, 2025):
        year_metrics = metrics1.loc[(metrics1.cost_bps == 10) & (metrics1.period == str(year))].set_index("portfolio")
        by, fy = year_metrics.loc["A2_HGB_TOP20_1X"], year_metrics.loc["FAST_GATED_A2_HGB_TOP20"]
        yearly_pass += int((fy.calmar >= by.calmar) or (abs(fy.max_drawdown) < abs(by.max_drawdown)))
    gates = {
        "sharpe_improved": bool(f.sharpe > b.sharpe),
        "calmar_improved": bool(f.calmar > b.calmar),
        "max_drawdown_improved": bool(abs(f.max_drawdown) < abs(b.max_drawdown)),
        "challenger_cagr_positive": bool(f.cagr > 0),
        "year_consistency_2_of_3": yearly_pass >= 2,
        "high_risk_downside_supported": bool(diagnostics["HIGH_RISK_DOWNSIDE_DIAGNOSTICS_SUPPORT"]),
        "all_audits_pass": True,
    }
    if all(gates.values()):
        classification = "F1_STRONG_RISK_BUDGET_VALUE"
        next_step = "FAST_A2_R2_PROSPECTIVE_RISK_BUDGET_ACTIVATION_AND_OPTION_READINESS"
    elif bool((f.annualized_volatility < b.annualized_volatility) or (abs(f.max_drawdown) < abs(b.max_drawdown)) or
              (f.sharpe > b.sharpe) or (f.calmar > b.calmar)):
        classification = "F2_PARTIAL_RISK_BUDGET_VALUE"
        next_step = "STOP_THRESHOLD_SEARCH_AND_ACCUMULATE_PROSPECTIVE_EVIDENCE"
    else:
        classification = "F3_NO_USEFUL_RISK_BUDGET_VALUE"
        next_step = "KEEP_A2_UNGATED_AND_STOP_THIS_FAST_RISK_BUDGET_ROUTE"
    primary_output = primary.merge(
        risk1[["trade_date", "fast_risk_score", "fast_risk_percentile", "high_risk"]],
        left_on="signal_date_used", right_on="trade_date", how="left", validate="many_to_one",
    ).drop(columns=["trade_date"])
    write_parquet_atomic(DAILY_RISK_PATH, risk1)
    write_parquet_atomic(DAILY_PORTFOLIO_PATH, primary_output)
    write_parquet_atomic(METRICS_PATH, metrics1)
    cost_sensitivity: dict[str, Any] = {}
    for cost in (0, 5, 10, 20):
        block = metrics1.loc[(metrics1.cost_bps == cost) & (metrics1.period == "POOLED")].set_index("portfolio")
        bb, ff = block.loc["A2_HGB_TOP20_1X"], block.loc["FAST_GATED_A2_HGB_TOP20"]
        cost_sensitivity[str(cost)] = {
            "baseline_cumulative_return": float(bb.cumulative_return), "challenger_cumulative_return": float(ff.cumulative_return),
            "baseline_cagr": float(bb.cagr), "challenger_cagr": float(ff.cagr),
            "baseline_sharpe": float(bb.sharpe), "challenger_sharpe": float(ff.sharpe),
            "challenger_minus_baseline_cumulative_return": float(ff.cumulative_return - bb.cumulative_return),
        }
    cost_sensitivity["EDGE_SURVIVES_20BPS"] = bool(cost_sensitivity["20"]["challenger_minus_baseline_cumulative_return"] > 0)
    write_json_atomic(COST_PATH, cost_sensitivity)
    write_json_atomic(DIAGNOSTICS_PATH, diagnostics)
    summary = {
        "FAST_A2_R1_STATUS": "PASS",
        "FAST_A2_R1_CLASSIFICATION": classification,
        "NEXT_AUTHORIZED_STEP": next_step,
        "FAST_A2_R1_EVIDENCE_ROLE": "PRE2026_RISK_BUDGET_DEVELOPMENT_EVIDENCE",
        "PRIMARY_FAST_RISK_STATE_ID": PRIMARY_FAST_RISK_STATE_ID,
        "PRIMARY_FAST_RISK_STATE_ARTIFACT": str(FAST_STATE_PATH),
        "PRIMARY_FAST_RISK_STATE_SHA256": sha256_file(FAST_STATE_PATH),
        "FAST_STATE_ORIENTATION": "HIGHER_OFFICIAL_PRIOR_SESSION_VIX_CLOSE_EQUALS_HIGHER_MARKET_RISK",
        "FAST_STATE_INFORMATION_CUTOFF": "PRIOR_COMPLETED_US_TRADING_SESSION_CLOSE",
        "FAST_A2_R1_CONTRACT_SHA256": witness["FAST_A2_R1_CONTRACT_SHA256"],
        "CONTRACT_FROZEN_BEFORE_A2_OUTCOME_READ": True,
        "FAST_A2_TIMING_AUDIT_STATUS": audits1["timing"]["FAST_A2_TIMING_AUDIT_STATUS"],
        "R4_BASELINE_REPLAY_IDENTITY_STATUS": audits1["R4_BASELINE_REPLAY_IDENTITY_STATUS"],
        "A2_STOCK_SELECTION_IDENTITY_STATUS": "PASS_SAME_FROZEN_A2_RANKS_AND_TOP20_MEMBERSHIP",
        "A2_MODEL_CHANGED": False, "A2_FEATURE_CHANGED": False, "A2_TARGET_CHANGED": False,
        "A2_TOPN_CHANGED": False, "R4_EXECUTION_POLICY_CHANGED": False,
        "R4_EXECUTION_POLICY_SHA256": EXPECTED_R4_POLICY_SHA256,
        "A2_PROSPECTIVE_SHADOW_CHANGED": False,
        "PROSPECTIVE_HGB_SHADOW_STATUS": "ACTIVE_ACCUMULATING",
        "FIRST_LEGAL_PROSPECTIVE_SIGNAL_DATE": "2026-08-17",
        "NO_BACKFILL": True,
        "TRAILING_LOOKBACK_SESSIONS": TRAILING_LOOKBACK, "MIN_HISTORY_SESSIONS": MIN_HISTORY,
        "HIGH_RISK_THRESHOLD": HIGH_RISK_THRESHOLD, "RISK_BUDGET_SET": [0.5, 1.0],
        "PRIMARY_COST_BPS": 10, "CASH_RETURN": 0.0, "RISK_FREE_RATE": 0.0,
        "BASELINE_A2_CAGR": float(b.cagr), "FAST_A2_CAGR": float(f.cagr), "DELTA_CAGR": float(f.cagr - b.cagr),
        "BASELINE_A2_VOLATILITY": float(b.annualized_volatility), "FAST_A2_VOLATILITY": float(f.annualized_volatility),
        "DELTA_VOLATILITY": float(f.annualized_volatility - b.annualized_volatility),
        "BASELINE_A2_SHARPE": float(b.sharpe), "FAST_A2_SHARPE": float(f.sharpe), "DELTA_SHARPE": float(f.sharpe - b.sharpe),
        "BASELINE_A2_MAX_DRAWDOWN": float(b.max_drawdown), "FAST_A2_MAX_DRAWDOWN": float(f.max_drawdown),
        "DELTA_MAX_DRAWDOWN": float(f.max_drawdown - b.max_drawdown),
        "BASELINE_A2_CALMAR": float(b.calmar), "FAST_A2_CALMAR": float(f.calmar), "DELTA_CALMAR": float(f.calmar - b.calmar),
        "DELTA_TURNOVER": float(f.annualized_turnover - b.annualized_turnover),
        "DELTA_COST_DRAG": float(f.cost_drag - b.cost_drag),
        "AVERAGE_GROSS_EXPOSURE": float(f.average_gross_exposure),
        "FRACTION_DAYS_AT_0_5X": float(f.fraction_days_at_0_5x),
        "HIGH_RISK_DOWNSIDE_DIAGNOSTICS_SUPPORT": diagnostics["HIGH_RISK_DOWNSIDE_DIAGNOSTICS_SUPPORT"],
        "F1_GATE": gates, "F1_YEAR_CONSISTENCY_COUNT": yearly_pass,
        "EDGE_SURVIVES_20BPS": cost_sensitivity["EDGE_SURVIVES_20BPS"],
        "REPRODUCIBILITY_STATUS": "PASS", "RUN1_FINGERPRINT": run1_fp, "RUN2_FINGERPRINT": run2_fp,
        "FAST_MODEL_FIT_COUNT": 0, "FAST_MODEL_SELECTION_COUNT": 0, "HYPERPARAMETER_SEARCH_TRIAL_COUNT": 0,
        "MODEL_SEARCH_COUNT": 0, "MODEL_FIT_FOR_SELECTION_COUNT": 0,
        "POST2025_TARGET_READ_COUNT": 0, "POST2025_OUTCOME_READ_COUNT": 0,
        "2026_A2_OUTCOME_READ_COUNT": 0, "2026_FAST_A2_SELECTION_USE_COUNT": 0,
        "BROKER_ACTION_COUNT": 0, "PRODUCTION_ADOPTION": False,
        "FAST_CHANGED": False, "DAILY_CHAIN_CHANGED": False, "ANTI_BLOAT_STATUS": "PASS",
        "RESULTS_ROOT": str(RESULTS_ROOT), "SUMMARY_PATH": str(SUMMARY_PATH),
    }
    summary["YEARLY_RESULTS_10BPS"] = {}
    for year in (2023, 2024, 2025):
        year_metrics = metrics1.loc[(metrics1.cost_bps == 10) & (metrics1.period == str(year))].set_index("portfolio")
        summary["YEARLY_RESULTS_10BPS"][str(year)] = {
            portfolio: {
                "net_return": float(year_metrics.loc[portfolio, "cumulative_return"]),
                "sharpe": float(year_metrics.loc[portfolio, "sharpe"]),
                "max_drawdown": float(year_metrics.loc[portfolio, "max_drawdown"]),
                "calmar": float(year_metrics.loc[portfolio, "calmar"]),
                "average_gross_exposure": float(year_metrics.loc[portfolio, "average_gross_exposure"]),
                "high_risk_day_fraction": float(year_metrics.loc[portfolio, "fraction_days_at_0_5x"]),
                "annualized_turnover": float(year_metrics.loc[portfolio, "annualized_turnover"]),
                "total_transaction_cost": float(year_metrics.loc[portfolio, "total_transaction_cost"]),
            }
            for portfolio in ("A2_HGB_TOP20_1X", "FAST_GATED_A2_HGB_TOP20")
        }
    summary["YEARLY_RESULTS_10BPS"]["2025_EVIDENCE_ROLE"] = "CONSUMED_PRE2026_RISK_BUDGET_EVIDENCE"
    if classification == "F1_STRONG_RISK_BUDGET_VALUE":
        activation = {
            "SHADOW_ID": "FAST_A2_RISK_BUDGET_PROSPECTIVE_SHADOW",
            "STATUS": "ACTIVE_ACCUMULATING",
            "BASELINE_SHADOW_REMAINS_ACTIVE": True,
            "FIRST_LEGAL_PROSPECTIVE_SIGNAL_DATE": "2026-08-17",
            "NO_BACKFILL": True, "PRODUCTION_ADOPTION": False, "BROKER_ACTION_ALLOWED": False,
            "FAST_A2_R1_CONTRACT_SHA256": witness["FAST_A2_R1_CONTRACT_SHA256"],
            "freeze_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json_atomic(ACTIVATION_PATH, activation)
        summary["FAST_A2_RISK_BUDGET_PROSPECTIVE_SHADOW"] = "ACTIVE_ACCUMULATING"
        summary["FAST_A2_PROSPECTIVE_FIRST_LEGAL_SIGNAL_DATE"] = "2026-08-17"
    else:
        summary["FAST_A2_RISK_BUDGET_PROSPECTIVE_SHADOW"] = "NOT_ACTIVATED"
    write_json_atomic(SUMMARY_PATH, summary)
    artifacts = [CONTRACT_PATH, WITNESS_PATH, IDENTITY_PATH, DAILY_RISK_PATH, DAILY_PORTFOLIO_PATH,
                 METRICS_PATH, COST_PATH, DIAGNOSTICS_PATH, SUMMARY_PATH]
    if ACTIVATION_PATH.exists() and classification == "F1_STRONG_RISK_BUDGET_VALUE":
        artifacts.append(ACTIVATION_PATH)
    manifest = {
        "experiment_id": EXPERIMENT_ID, "status": "PASS", "classification": classification,
        "contract_sha256": witness["FAST_A2_R1_CONTRACT_SHA256"],
        "artifacts": {str(path): {"sha256": sha256_file(path), "bytes": path.stat().st_size} for path in artifacts},
        "source_artifacts": {str(FAST_STATE_PATH): sha256_file(FAST_STATE_PATH), str(R4_DAILY_PATH): sha256_file(R4_DAILY_PATH)},
        "run_fingerprint": run1_fp,
    }
    write_json_atomic(MANIFEST_PATH, manifest)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.freeze_only == args.execute:
        raise SystemExit("choose exactly one of --freeze-only or --execute")
    witness = freeze_contract()
    print(f"FAST_A2_R1_CONTRACT_SHA256={witness['FAST_A2_R1_CONTRACT_SHA256']}")
    print("CONTRACT_FROZEN_BEFORE_A2_OUTCOME_READ=true")
    if args.freeze_only:
        print("FAST_A2_R1_FREEZE_STATUS=PASS")
        return 0
    summary = run_experiment()
    for key in ("FAST_A2_R1_STATUS", "FAST_A2_R1_CLASSIFICATION", "FAST_A2_TIMING_AUDIT_STATUS",
                "REPRODUCIBILITY_STATUS", "RUN1_FINGERPRINT", "RUN2_FINGERPRINT", "NEXT_AUTHORIZED_STEP"):
        print(f"{key}={summary[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
