"""Frozen R6 constant-gross cross-sectional allocation research (R5).

The runner is deliberately no-fit and pre-2026-first.  It reuses the frozen
extended A2/R6 OOF panel, the authoritative adjusted-open execution chain, and
the existing transaction-cost convention.  The only primary-policy change is
deterministic same-date renormalization back to Raw A2 gross, subject to the
already-frozen 6% single-name hard limit.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE = Path(r"D:\us-tech-quant-cache")
OUTPUT = RESULTS / "A2_RISK_CONTROL_R5_CONSTANT_GROSS_R6"
HISTORY = RESULTS / "A2_RISK_HISTORY_EXTENSION_R1"
R6_ROOT = RESULTS / "A2_STOCK_RISK_R6"
R6E_ROOT = RESULTS / "A2_STOCK_RISK_R6E"
R10_ROOT = RESULTS / "A2_STOCK_RISK_R10_CLOSEOUT"
R11_ROOT = RESULTS / "A2_STOCK_RISK_R11_PROSPECTIVE"
R1_ROOT = RESULTS / "A2_RISK_OS_R1"
R2_ROOT = RESULTS / "A2_RISK_OS_R2"
R3_ROOT = RESULTS / "A2_RISK_CONTROL_R3_NON_PREDICTIVE_RISK_BUDGETING"
R4_ROOT = RESULTS / "A2_RISK_CONTROL_R4_STRUCTURAL_STRESS_VALIDATION"
OOF = HISTORY / "r6_historical_oof_predictions.parquet"
PRICES = CACHE / "a2_risk_history_extension_r1" / "adjusted_prices_pre2026.parquet"
BASE_R6_PORTFOLIO = HISTORY / "base_r6_historical_portfolio.parquet"

EXPECTED = {
    "r1_contract": "058dbbed6d5880da8f0bb0e0fbb921f669d62465ced64711cacd80eb939d997e",
    "r2_contract": "b486f6f194741b475fbedc7485639350eab9e31a36b48a15db034c836b044411",
    "r3_contract": "e14fdbae87eb181797d9405b8c6297f6524ac50d656a0842b16e0c043177f692",
    "r4_contract": "bc2f059f52d26eab7bf356843c5ebfcad7bf361d6b4a0e9809baf3b6d7c971a9",
    "r6_oof": "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4",
    "r6_deploy": "3e5f646fcfbf1b4e9196781f712305b044a7b2e57c0fe1b3fe202345561f4a08",
    "history_oof": "392c677d903b5e4f0016a49207a09db454ac927c11ca2ceaf9ce5ff405c3c219",
    "history_base_r6": "8ea1db4f8474996479923b297e73c9ae11744594f80abe67b8011e603416011b",
    "history_geometry": "4346dbf12737d005fcfb248eaf769fedd53ed2d12c851e274db7a48b31d35b2b",
    "r6e_audit": "22df8e358c34d68a846f34fad66c0ca52d3a731a3b35b4e49867b98a49d86ae9",
    "r10_freeze_manifest": "cc7687e8161ff152bbdffba85998e6fa8721c92277ca5369ad3791aa930ce03c",
}
REFERENCE_MODEL = "LGBM_BAD_ASYM_2"
RISK_THRESHOLD = 0.90
HIGH_RISK_MULTIPLIER = 0.50
NORMAL_MULTIPLIER = 1.00
MAX_WEIGHT = 0.06
BASE_COST = 0.001
RNG_SEED = 20260819
PLACEBO_COUNT = 500
BOOTSTRAP_REPS = 2000
CONTRACT_NAMES = ("r5_contract.json", "A2_RISK_CONTROL_R5_CONTRACT.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILURE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def source_paths() -> dict[str, Path]:
    return {
        "r1_contract": R1_ROOT / "risk_os_r1_contract.json",
        "r2_contract": R2_ROOT / "risk_os_r2_contract.json",
        "r3_contract": R3_ROOT / "A2_RISK_CONTROL_R3_CONTRACT.json",
        "r4_contract": R4_ROOT / "r4_contract.json",
        "r6_oof": R6_ROOT / "r6_oof_predictions.parquet",
        "r6_deploy": R11_ROOT / "r6_frozen_deploy_r1.joblib",
        "history_oof": OOF,
        "history_base_r6": BASE_R6_PORTFOLIO,
        "history_geometry": HISTORY / "portfolio_geometry_extended.parquet",
        "r6e_audit": R6E_ROOT / "r6e_audit.json",
        "r10_freeze_manifest": R10_ROOT / "r10_freeze_manifest.json",
    }


def verify_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    paths = source_paths()
    failures = []
    manifest: dict[str, Any] = {}
    for key, path in paths.items():
        actual = sha256_file(path) if path.is_file() else "MISSING"
        manifest[key] = {"path": str(path), "sha256": actual, "expected_sha256": EXPECTED[key]}
        if actual != EXPECTED[key]:
            failures.append(f"{key}:{actual}")
    if failures:
        raise RuntimeError("FROZEN_SOURCE_IDENTITY_FAILURE:" + ";".join(failures))
    r6e = json.loads((R6E_ROOT / "r6e_audit.json").read_text(encoding="utf-8"))
    exact_rule = {
        "removed_weight_destination": "CASH",
        "risk_percentile_at_least_90": 0.5,
        "risk_percentile_below_90": 1.0,
    }
    if r6e.get("position_rule") != exact_rule:
        raise RuntimeError("FROZEN_R6_ALLOCATION_RULE_IDENTITY_FAILURE")
    r4 = json.loads((R4_ROOT / "r4_final_summary.json").read_text(encoding="utf-8"))
    if r4.get("A2_RISK_CONTROL_R4_FINAL_CLASSIFICATION") != "D_NO_MATERIAL_STRUCTURAL_VALUE":
        raise RuntimeError("R4_HISTORY_IDENTITY_FAILURE")
    history = json.loads((HISTORY / "a2_risk_history_extension_summary.json").read_text(encoding="utf-8"))
    identity = history["frozen_identity"]
    if identity.get("verified_a2_artifact_count") != 46 or history.get("deployment_model_backcast_count") != 0:
        raise RuntimeError("A2_OR_HISTORICAL_OOF_IDENTITY_FAILURE")
    # Re-run the authoritative 46/46 A2 and R6 deploy verification.
    r1 = load_module("r5_identity_r1", REPO / "scripts/v22/a2_risk_os_r1.py")
    live_identity = r1.frozen_identity()
    if live_identity.get("verified_a2_artifact_count") != 46:
        raise RuntimeError("A2_46_OF_46_FAILURE")
    return manifest, {"history_summary": history, "live_frozen_identity": live_identity, "r4_summary": r4}


def inherited_policy_manifest() -> dict[str, Any]:
    return {
        "identity": "FROZEN_R6E_POSITION_RULE",
        "reference_model": REFERENCE_MODEL,
        "score_definition": "P(bad_asymmetry_5d), where bad asymmetry is fold-training MAE>=Q90 AND MFE<=Q50",
        "score_direction": "higher score and percentile mean higher downside risk",
        "calibration": "fold-local empirical percentile against training predicted probabilities; np.searchsorted(side='right')/training_count",
        "bucket_convention": "risk_decile=clip(ceil(risk_percentile*10),1,10); intervention uses percentile threshold directly",
        "stock_multiplier": {"risk_percentile>=0.90": 0.5, "risk_percentile<0.90": 1.0},
        "eligibility": "frozen A2 Top20 constituent with genuine historical R6 OOF row",
        "minimum_multiplier": 0.5,
        "maximum_multiplier": 1.0,
        "missing_score_literal_behavior": "pandas Series.ge returns False for NaN, hence inherited np.where mapping is 1.0; R5 historical coverage gate additionally requires zero missing scores",
        "tie_handling": "risk_percentile exactly 0.90 is high risk because comparison is >=",
        "normalization_behavior_original_r6_only": "none; removed weight remains cash",
        "timestamp_convention": "information at completed information_date close; target executes at next legal signal_date open",
        "cost_convention": "half-L1 turnover against drifted pretrade weights times 0.001 baseline cost; first target initializes without charged entry cost",
        "authoritative_evidence": {
            "r6e_audit": {"path": str(R6E_ROOT / "r6e_audit.json"), "sha256": EXPECTED["r6e_audit"]},
            "r10_freeze_manifest": {"path": str(R10_ROOT / "r10_freeze_manifest.json"), "sha256": EXPECTED["r10_freeze_manifest"]},
        },
    }


def contract_payload(sources: dict[str, Any], identity: dict[str, Any], policy_hash: str) -> dict[str, Any]:
    return {
        "experiment_id": "A2_RISK_CONTROL_R5_CONSTANT_GROSS_R6",
        "training_cutoff_exclusive": "2026-01-01",
        "a2_artifact_identities": identity["live_frozen_identity"],
        "r6_oof_artifact_identity": sources["r6_oof"],
        "r6_deploy_identity": sources["r6_deploy"],
        "inherited_r6_allocation_policy_sha256": policy_hash,
        "historical_oof_reconstruction_identity": {
            "artifact": sources["history_oof"], "dates": ["2022-01-03", "2025-12-03"],
            "expected_decision_dates": 984, "deployment_model_backcast_count": 0,
        },
        "prior_contract_hashes": {"R1": EXPECTED["r1_contract"], "R2": EXPECTED["r2_contract"], "R3": EXPECTED["r3_contract"], "R4": EXPECTED["r4_contract"]},
        "primary_formula": "u_i,t=w_A2_i,t*m_R6_i,t; w_R5_i,t=deterministic_cap_redistribute(u,target_gross=sum(abs(w_A2)),existing_cap=0.06)",
        "daily_gross_matching_rule": "match exact same-date Raw A2 gross; long and short sides would be normalized independently; frozen A2 is confirmed long-only",
        "position_integrity": "existing 0.06 single-name limit; iteratively cap and redistribute residual proportional to uncapped pre-normalized weights",
        "cost_convention": {"zero_gross": 0.0, "baseline": 0.001, "two_x": 0.002, "adverse": 0.003, "turnover": "half-L1 against drifted pretrade weights"},
        "corporate_action_convention": "MOOMOO_OPEND_RAW_PLUS_REHAB/PIT_FORWARD_REHAB_INDEX inherited from history reconstruction",
        "rebalance_convention": "daily legal-session open-to-open; first target initializes simulator without entry cost",
        "missing_score_policy": "inherited multiplier 1.0 literal mapping, with full-coverage hard gate requiring no historical missing score",
        "placebo_design": {"seed": RNG_SEED, "count_each": PLACEBO_COUNT, "within_date": "permute multiplier among all 20", "rank_conditioned": "permute within fixed ranks 1-5,6-10,11-15,16-20"},
        "reverse_diagnostic": "assign each date's 0.5 multipliers to the lowest-risk names, deterministic by risk then ticker; non-selectable",
        "evaluation_metrics": ["cumulative_return", "CAGR", "volatility", "Sharpe", "Sortino", "MaxDD", "Calmar", "ES5", "worst_day", "worst_week", "worst_month", "downside_deviation", "profit_factor", "gross", "net", "turnover", "transaction_costs"],
        "year_and_fold_useful_definition": "Sharpe>=Raw-0.03 AND at least two of cumulative return, MaxDD, Calmar, ES5 improve",
        "pre2026_gates": {
            "A": "all 14 preregistered A_STRONG_CONSTANT_GROSS_R6_VALUE requirements from master task",
            "B": "all 10 preregistered B_USEFUL_CONSTANT_GROSS_R6_VALUE requirements from master task",
            "C": "mechanism direction useful but constant-gross economics unconfirmed",
            "D": "no material constant-gross value", "E": "invalid or insufficient evidence",
        },
        "prospective_authorization_policy": "2026 may be read exactly once only after pre-2026 A or B, frozen code/evidence, and passing integrity checks",
        "output_roots": {"results": str(OUTPUT), "cache": str(CACHE), "repository": str(REPO)},
        "runner_sha256": sha256_file(Path(__file__)),
    }


def waterfill(pre: np.ndarray, target: float = 1.0, cap: float = MAX_WEIGHT) -> tuple[np.ndarray, int]:
    values = np.asarray(pre, float)
    if np.any(values < 0) or not np.isfinite(values).all() or values.sum() <= 0:
        raise RuntimeError("INVALID_PRENORMALIZED_WEIGHTS")
    result = np.zeros_like(values)
    active = np.ones(len(values), dtype=bool)
    binds = 0
    while active.any():
        remaining = target - result.sum()
        proposal = values[active] / values[active].sum() * remaining
        over = proposal > cap + 1e-15
        active_idx = np.flatnonzero(active)
        if not over.any():
            result[active_idx] = proposal
            break
        capped = active_idx[over]
        result[capped] = cap
        active[capped] = False
        binds += len(capped)
        if result.sum() > target + 1e-12 or target - result.sum() > cap * active.sum() + 1e-12:
            raise RuntimeError("INFEASIBLE_EXISTING_CAP_REDISTRIBUTION")
    if abs(result.sum() - target) > 2e-15 or result.max() > cap + 1e-14:
        raise RuntimeError("GROSS_OR_CAP_IDENTITY_FAILURE")
    return result, binds


@dataclass
class Panel:
    rows: pd.DataFrame
    dates: pd.DatetimeIndex
    tickers: list[np.ndarray]
    interval_returns: list[np.ndarray]
    prev_to_current: list[np.ndarray]
    raw_weights: np.ndarray
    r6_weights: np.ndarray
    r5_weights: np.ndarray
    reverse_weights: np.ndarray
    cap_binds: np.ndarray


def load_panel() -> Panel:
    columns = ["signal_date", "information_date", "ticker", "A2_RANK", "A2_PREDICTION", "predicted_bad_asymmetry_risk", "risk_percentile", "fold", "train_max_target_end", "embargo_cutoff", "target_end_date", "forward_5d_stock_return", "forward_5d_stock_mae", "forward_5d_stock_mfe", "bad_asymmetry_5d"]
    frame = pd.read_parquet(OOF, columns=columns)
    for column in ["signal_date", "information_date", "train_max_target_end", "embargo_cutoff", "target_end_date"]:
        frame[column] = pd.to_datetime(frame[column])
    frame = frame.sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    counts = frame.groupby("signal_date").agg(rows=("ticker", "size"), names=("ticker", "nunique"), ranks=("A2_RANK", "nunique"))
    if len(counts) != 984 or not counts.eq(20).all().all() or frame.risk_percentile.isna().any():
        raise RuntimeError("HISTORICAL_OOF_COVERAGE_FAILURE")
    if not (frame.information_date < frame.signal_date).all() or not (frame.train_max_target_end < frame.embargo_cutoff).all():
        raise RuntimeError("HISTORICAL_OOF_LOOKAHEAD_FAILURE")
    dates = pd.DatetimeIndex(sorted(frame.signal_date.unique()))
    grouped = [group.copy() for _, group in frame.groupby("signal_date", sort=True)]
    tickers = [g.ticker.astype(str).to_numpy() for g in grouped]
    raw = np.full((len(dates), 20), 0.05)
    multipliers = np.vstack([np.where(g.risk_percentile.to_numpy(float) >= RISK_THRESHOLD, HIGH_RISK_MULTIPLIER, NORMAL_MULTIPLIER) for g in grouped])
    r6 = raw * multipliers
    r5 = np.empty_like(raw); reverse = np.empty_like(raw); binds = np.zeros(len(dates), int)
    for j, g in enumerate(grouped):
        r5[j], binds[j] = waterfill(r6[j])
        count_low = int((multipliers[j] < 1).sum())
        order = np.lexsort((g.ticker.astype(str).to_numpy(), g.risk_percentile.to_numpy(float)))
        reverse_multiplier = np.ones(20); reverse_multiplier[order[:count_low]] = HIGH_RISK_MULTIPLIER
        reverse[j], _ = waterfill(raw[j] * reverse_multiplier)
    prices = pd.read_parquet(PRICES, columns=["trade_date", "ticker", "open", "close", "low"])
    prices.trade_date = pd.to_datetime(prices.trade_date)
    if prices.trade_date.ge("2026-01-01").any():
        # The approved cache may extend to 2025-12-31 but never beyond it.
        raise RuntimeError("PRICE_CACHE_2026_FIREWALL_FAILURE")
    open_lookup = prices.set_index(["trade_date", "ticker"]).open
    interval_returns: list[np.ndarray] = []
    mappings: list[np.ndarray] = []
    for j in range(len(dates) - 1):
        previous, current = dates[j], dates[j + 1]
        interval_returns.append(np.array([open_lookup.loc[(current, ticker)] / open_lookup.loc[(previous, ticker)] - 1 for ticker in tickers[j]], float))
        current_map = {ticker: k for k, ticker in enumerate(tickers[j + 1])}
        mappings.append(np.array([current_map.get(ticker, -1) for ticker in tickers[j]], int))
    frame["raw_a2_weight"] = raw.ravel()
    frame["r6_multiplier"] = multipliers.ravel()
    frame["original_r6_weight"] = r6.ravel()
    frame["r5_weight"] = r5.ravel()
    frame["reverse_r6_weight"] = reverse.ravel()
    return Panel(frame, dates, tickers, interval_returns, mappings, raw, r6, r5, reverse, binds)


def simulate(panel: Panel, weights: np.ndarray, cost_rate: float) -> pd.DataFrame:
    values = weights[0].copy(); cash = 1.0 - values.sum(); previous_nav = 1.0; rows = []
    for j in range(1, len(panel.dates)):
        values *= 1.0 + panel.interval_returns[j - 1]
        pretrade_nav = cash + values.sum()
        pretrade = values / pretrade_nav
        mapping = panel.prev_to_current[j - 1]
        current = weights[j]
        turnover_total = float(np.abs(pretrade[mapping < 0]).sum())
        overlap = mapping >= 0
        turnover_total += float(np.abs(pretrade[overlap] - current[mapping[overlap]]).sum())
        new_mask = np.ones(20, dtype=bool); new_mask[mapping[overlap]] = False
        turnover_total += float(np.abs(current[new_mask]).sum())
        turnover = 0.5 * turnover_total
        posttrade_nav = pretrade_nav * (1.0 - turnover * cost_rate)
        values = posttrade_nav * current
        cash = posttrade_nav * (1.0 - current.sum())
        rows.append({"date": panel.dates[j], "holding_signal_date": panel.dates[j - 1], "daily_return": posttrade_nav / previous_nav - 1.0, "turnover": turnover, "transaction_cost_return": turnover * cost_rate, "target_gross": float(np.abs(current).sum()), "target_net": float(current.sum())})
        previous_nav = posttrade_nav
    return pd.DataFrame(rows)


def performance(daily: pd.DataFrame) -> dict[str, float]:
    r = pd.Series(daily.daily_return.to_numpy(float), index=pd.DatetimeIndex(daily.date))
    n = len(r); equity = (1 + r).cumprod(); total = float(equity.iloc[-1] - 1)
    cagr = float((1 + total) ** (252 / n) - 1) if total > -1 else -1.0
    vol = float(r.std(ddof=1) * math.sqrt(252)); sharpe = float(r.mean() / r.std(ddof=1) * math.sqrt(252)) if r.std(ddof=1) else np.nan
    negative = r[r < 0]; downside = float(negative.std(ddof=1) * math.sqrt(252)); sortino = float(r.mean() * 252 / downside) if downside else np.nan
    dd = equity / equity.cummax() - 1; maxdd = float(dd.min()); calmar = cagr / abs(maxdd) if maxdd else np.nan
    weekly = (1 + r).resample("W-FRI").prod() - 1; monthly = (1 + r).resample("ME").prod() - 1
    tail_n = max(1, int(math.ceil(0.05 * n))); es5 = float(np.sort(r.to_numpy())[:tail_n].mean())
    gains, losses = float(r[r > 0].sum()), float(-r[r < 0].sum())
    return {"cumulative_return": total, "cagr": cagr, "annualized_volatility": vol, "sharpe": sharpe, "sortino": sortino, "maximum_drawdown": maxdd, "calmar": calmar, "expected_shortfall_5": es5, "worst_day": float(r.min()), "worst_week": float(weekly.min()), "worst_month": float(monthly.min()), "downside_deviation": downside, "profit_factor": gains / losses if losses else np.inf, "average_gross_exposure": float(daily.target_gross.mean()), "average_net_exposure": float(daily.target_net.mean()), "turnover": float(daily.turnover.sum()), "transaction_costs": float(daily.transaction_cost_return.sum())}


def strategy_economics(panel: Panel) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], pd.DataFrame]:
    definitions = {"RAW_A2": panel.raw_weights, "ORIGINAL_R6_ONLY": panel.r6_weights, "R5_CONSTANT_GROSS": panel.r5_weights, "CONSTANT_GROSS_A2_BASELINE": panel.raw_weights, "REVERSE_R6": panel.reverse_weights}
    rows = []; baseline_sims: dict[str, pd.DataFrame] = {}
    for case, cost in [("ZERO_GROSS", 0.0), ("BASELINE", BASE_COST), ("TWO_X", 0.002), ("ADVERSE", 0.003)]:
        for name, weights in definitions.items():
            daily = simulate(panel, weights, cost)
            if case == "BASELINE": baseline_sims[name] = daily
            rows.append({"cost_case": case, "cost_rate": cost, "strategy": name, **performance(daily)})
    metrics = pd.DataFrame(rows)
    raw = baseline_sims["RAW_A2"]
    original_ref = pd.read_parquet(BASE_R6_PORTFOLIO)
    reproduced = baseline_sims["ORIGINAL_R6_ONLY"].merge(original_ref, left_on="date", right_on="execution_date", validate="one_to_one")
    reproduction = pd.DataFrame([{
        "daily_return_max_abs_error": float(np.max(np.abs(reproduced.daily_return - reproduced.base_r6_daily_return))),
        "turnover_max_abs_error": float(np.max(np.abs(reproduced.turnover_x - reproduced.turnover_y))),
        "exposure_max_abs_error": float(np.max(np.abs(reproduced.target_gross - reproduced.target_exposure))),
        "rows": len(reproduced),
    }])
    return metrics, baseline_sims, reproduction


def slice_metrics(sims: dict[str, pd.DataFrame], labels: pd.Series, dimension: str) -> pd.DataFrame:
    rows = []
    for label in labels.dropna().unique():
        mask_dates = set(labels.index[labels.eq(label)])
        local = {name: daily.loc[daily.date.isin(mask_dates)].copy() for name, daily in sims.items() if name in {"RAW_A2", "ORIGINAL_R6_ONLY", "R5_CONSTANT_GROSS"}}
        if not local or min(map(len, local.values())) < 2:
            continue
        raw, r5 = performance(local["RAW_A2"]), performance(local["R5_CONSTANT_GROSS"])
        useful = bool(r5["sharpe"] >= raw["sharpe"] - 0.03 and sum([r5["cumulative_return"] > raw["cumulative_return"], r5["maximum_drawdown"] > raw["maximum_drawdown"], r5["calmar"] > raw["calmar"], r5["expected_shortfall_5"] > raw["expected_shortfall_5"]]) >= 2)
        for name, daily in local.items():
            rows.append({"dimension": dimension, "period": label, "strategy": name, **performance(daily), "r5_economically_useful": useful})
    return pd.DataFrame(rows)


def placebo_weights(panel: Panel, rng: np.random.Generator, rank_conditioned: bool) -> np.ndarray:
    result = np.empty_like(panel.r6_weights)
    rank_values = panel.rows.A2_RANK.to_numpy().reshape(len(panel.dates), 20)
    multipliers = panel.rows.r6_multiplier.to_numpy().reshape(len(panel.dates), 20)
    for j in range(len(panel.dates)):
        permuted = multipliers[j].copy()
        if rank_conditioned:
            for low, high in [(1, 5), (6, 10), (11, 15), (16, 20)]:
                idx = np.flatnonzero((rank_values[j] >= low) & (rank_values[j] <= high))
                permuted[idx] = rng.permutation(permuted[idx])
        else:
            permuted = rng.permutation(permuted)
        result[j], _ = waterfill(panel.raw_weights[j] * permuted)
    return result


def placebo_test(panel: Panel, raw_metrics: dict[str, float], actual: dict[str, float]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(RNG_SEED); rows = []
    for design in ["WITHIN_DATE", "RANK_CONDITIONED"]:
        for iteration in range(PLACEBO_COUNT):
            weights = placebo_weights(panel, rng, design == "RANK_CONDITIONED")
            metric = performance(simulate(panel, weights, BASE_COST))
            rows.append({"placebo_type": design, "iteration": iteration, **metric,
                         "sharpe_delta_vs_raw": metric["sharpe"] - raw_metrics["sharpe"],
                         "calmar_delta_vs_raw": metric["calmar"] - raw_metrics["calmar"],
                         "maxdd_improvement_vs_raw": metric["maximum_drawdown"] - raw_metrics["maximum_drawdown"],
                         "es5_improvement_vs_raw": metric["expected_shortfall_5"] - raw_metrics["expected_shortfall_5"]})
    distribution = pd.DataFrame(rows)
    summaries = []
    actual_values = {"cagr": actual["cagr"], "sharpe": actual["sharpe"], "calmar": actual["calmar"], "maxdd_improvement_vs_raw": actual["maximum_drawdown"] - raw_metrics["maximum_drawdown"], "es5_improvement_vs_raw": actual["expected_shortfall_5"] - raw_metrics["expected_shortfall_5"]}
    for design, group in distribution.groupby("placebo_type"):
        for metric, actual_value in actual_values.items():
            column = {"maxdd_improvement_vs_raw": "maxdd_improvement_vs_raw", "es5_improvement_vs_raw": "es5_improvement_vs_raw"}.get(metric, metric)
            summaries.append({"placebo_type": design, "metric": metric, "actual": actual_value, "placebo_mean": group[column].mean(), "placebo_median": group[column].median(), "actual_percentile": float((group[column] <= actual_value).mean())})
    summary = pd.DataFrame(summaries)
    return distribution, summary.loc[summary.placebo_type.eq("WITHIN_DATE")], summary.loc[summary.placebo_type.eq("RANK_CONDITIONED")]


def forward_diagnostics(panel: Panel) -> pd.DataFrame:
    frame = panel.rows.copy()
    prices = pd.read_parquet(PRICES, columns=["trade_date", "ticker", "open", "close", "low"])
    prices.trade_date = pd.to_datetime(prices.trade_date)
    calendar = pd.DatetimeIndex(sorted(prices.trade_date.unique()))
    bars = prices.set_index(["ticker", "trade_date"])
    records = []
    for row in frame[["signal_date", "ticker"]].itertuples(index=False):
        pos = calendar.get_loc(row.signal_date); dates = calendar[pos:pos + 20]
        if len(dates) != 20:
            records.append((np.nan, np.nan, np.nan)); continue
        local = bars.loc[[(row.ticker, date) for date in dates]].reset_index().sort_values("trade_date")
        entry = float(local.iloc[0].open)
        f1 = float(local.iloc[1].open / entry - 1)
        f20 = float(local.iloc[-1].close / entry - 1)
        worst20 = float(local.low.min() / entry - 1)
        records.append((f1, f20, worst20))
    frame[["future_1d_return", "future_20d_return", "future_worst_20d_path"]] = records
    frame["future_5d_return"] = frame.forward_5d_stock_return
    frame["future_worst_5d_path"] = -frame.forward_5d_stock_mae
    frame["risk_decile"] = np.clip(np.ceil(frame.risk_percentile * 10), 1, 10).astype(int)
    frame["a2_rank_band"] = pd.cut(frame.A2_RANK, bins=[0, 5, 10, 15, 20], labels=["1-5", "6-10", "11-15", "16-20"])
    frame["risk_quartile"] = pd.cut(frame.risk_percentile, bins=[-np.inf, .25, .50, .75, np.inf], labels=["Q1", "Q2", "Q3", "Q4"])
    return frame


def mechanism_outputs(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frame = frame.copy()
    frame["weight_shift"] = frame.r5_weight - frame.raw_a2_weight
    frame["removed"] = (-frame.weight_shift).clip(lower=0)
    frame["added"] = frame.weight_shift.clip(lower=0)
    frame["raw_pnl_1d"] = frame.raw_a2_weight * frame.future_1d_return
    frame["r5_pnl_1d"] = frame.r5_weight * frame.future_1d_return
    frame["raw_drawdown_contribution"] = frame.raw_a2_weight * frame.future_1d_return.clip(upper=0)
    frame["r5_drawdown_contribution"] = frame.r5_weight * frame.future_1d_return.clip(upper=0)
    buckets = frame.groupby("risk_decile", observed=True).agg(observation_count=("ticker", "size"), raw_a2_average_weight=("raw_a2_weight", "mean"), r5_average_weight=("r5_weight", "mean"), average_weight_shift=("weight_shift", "mean"), future_1d_return=("future_1d_return", "mean"), future_5d_return=("future_5d_return", "mean"), future_20d_return=("future_20d_return", "mean"), future_worst_5d_path=("future_worst_5d_path", "mean"), future_worst_20d_path=("future_worst_20d_path", "mean"), bad_event_rate=("bad_asymmetry_5d", "mean"), raw_pnl_contribution=("raw_pnl_1d", "sum"), r5_pnl_contribution=("r5_pnl_1d", "sum"), raw_drawdown_contribution=("raw_drawdown_contribution", "sum"), r5_drawdown_contribution=("r5_drawdown_contribution", "sum")).reset_index()
    transfer_rows = []
    for date, g in frame.groupby("signal_date", sort=True):
        removed, added = g.removed.sum(), g.added.sum()
        def wavg(column: str, weight: str) -> float:
            denom = g[weight].sum(); return float(np.average(g[column], weights=g[weight])) if denom > 0 else np.nan
        fold = g.fold.iloc[0]
        row = {"signal_date": date, "fold": fold, "year": date.year, "gross_capital_removed": removed, "gross_capital_added": added,
               "removed_weighted_a2_rank": wavg("A2_RANK", "removed"), "added_weighted_a2_rank": wavg("A2_RANK", "added"),
               "removed_weighted_r6_risk": wavg("risk_percentile", "removed"), "added_weighted_r6_risk": wavg("risk_percentile", "added")}
        for horizon in ["future_1d_return", "future_5d_return", "future_20d_return", "future_worst_20d_path"]:
            receive, donate = wavg(horizon, "added"), wavg(horizon, "removed")
            row[f"receiving_{horizon}"] = receive; row[f"donating_{horizon}"] = donate; row[f"receiving_minus_donating_{horizon}"] = receive - donate
        transfer_rows.append(row)
    transfers = pd.DataFrame(transfer_rows)
    grid = frame.groupby(["a2_rank_band", "risk_quartile"], observed=True).agg(observation_count=("ticker", "size"), average_forward_1d_return=("future_1d_return", "mean"), average_forward_5d_return=("future_5d_return", "mean"), bad_event_rate=("bad_asymmetry_5d", "mean"), tail_loss=("future_worst_20d_path", "mean"), raw_a2_weight=("raw_a2_weight", "sum"), r5_weight=("r5_weight", "sum"), raw_pnl_contribution=("raw_pnl_1d", "sum"), r5_pnl_contribution=("r5_pnl_1d", "sum")).reset_index()
    worst_idx = set(frame.nsmallest(100, "future_5d_return").index); best_idx = set(frame.nlargest(100, "future_5d_return").index)
    groups = {"ALL": frame.index, "WORST_100": list(worst_idx), "BEST_100": list(best_idx)}
    winner_rows = []
    for name, idx in groups.items():
        g = frame.loc[idx]
        avoided = float((-g.loc[(g.removed > 0) & (g.future_5d_return < 0), "removed"] * g.loc[(g.removed > 0) & (g.future_5d_return < 0), "future_5d_return"]).sum())
        sacrificed = float((g.loc[(g.removed > 0) & (g.future_5d_return > 0), "removed"] * g.loc[(g.removed > 0) & (g.future_5d_return > 0), "future_5d_return"]).sum())
        added_gain = float((g.loc[(g.added > 0) & (g.future_5d_return > 0), "added"] * g.loc[(g.added > 0) & (g.future_5d_return > 0), "future_5d_return"]).sum())
        added_loss = float((-g.loc[(g.added > 0) & (g.future_5d_return < 0), "added"] * g.loc[(g.added > 0) & (g.future_5d_return < 0), "future_5d_return"]).sum())
        winner_rows.append({"outcome_group": name, "observation_count": len(g), "weight_removed_future_losers": g.loc[g.future_5d_return < 0, "removed"].sum(), "weight_removed_future_winners": g.loc[g.future_5d_return > 0, "removed"].sum(), "avoided_loss": avoided, "sacrificed_gain": sacrificed, "added_gain": added_gain, "added_loss": added_loss, "net_reallocation_value": avoided + added_gain - sacrificed - added_loss})
    return buckets, transfers, grid, pd.DataFrame(winner_rows)


def concentration(panel: Panel) -> pd.DataFrame:
    frame = panel.rows; prices = pd.read_parquet(PRICES, columns=["trade_date", "ticker", "close"])
    prices.trade_date = pd.to_datetime(prices.trade_date)
    returns = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index().pct_change(fill_method=None)
    rows = []
    for j, (date, g) in enumerate(frame.groupby("signal_date", sort=True)):
        info = pd.Timestamp(g.information_date.iloc[0]); names = panel.tickers[j]
        corr = returns.loc[returns.index <= info, names].tail(60).dropna(how="any").corr().to_numpy(float)
        if corr.shape != (20, 20) or not np.isfinite(corr).all():
            raise RuntimeError(f"CONCENTRATION_HISTORY_FAILURE:{date}")
        adjacency = corr >= .70
        for strategy, weights in [("RAW_A2", panel.raw_weights[j]), ("R5_CONSTANT_GROSS", panel.r5_weights[j])]:
            hhi = float(np.square(weights).sum()); order = np.sort(weights)[::-1]
            visited = set(); cluster_shares = []
            for start in range(20):
                if start in visited: continue
                stack = [start]; component = set()
                while stack:
                    node = stack.pop()
                    if node in component: continue
                    component.add(node); stack.extend(np.flatnonzero(adjacency[node]).tolist())
                visited |= component; cluster_shares.append(float(weights[list(component)].sum()))
            corr_conc = float(weights @ corr @ weights)
            rows.append({"signal_date": date, "strategy": strategy, "hhi": hhi, "effective_number_positions": 1 / hhi, "top1_weight": order[0], "top5_weight_share": order[:5].sum(), "top10_weight_share": order[:10].sum(), "max_weight": order[0], "correlation_weighted_concentration": corr_conc, "effective_independent_bets": 1 / corr_conc if corr_conc > 0 else np.nan, "high_correlation_cluster_share": max(cluster_shares)})
    return pd.DataFrame(rows)


def turnover_attribution(panel: Panel, sims: dict[str, pd.DataFrame]) -> pd.DataFrame:
    entry_exit = 0.0; a2_change = 0.0; overlay = 0.0
    for j in range(1, len(panel.dates)):
        prev = {t: panel.raw_weights[j - 1, k] for k, t in enumerate(panel.tickers[j - 1])}; cur = {t: panel.raw_weights[j, k] for k, t in enumerate(panel.tickers[j])}
        shared = set(prev) & set(cur); entry_exit += .5 * (sum(prev[t] for t in set(prev) - shared) + sum(cur[t] for t in set(cur) - shared)); a2_change += .5 * sum(abs(cur[t] - prev[t]) for t in shared)
        prev_dev = {t: panel.r5_weights[j - 1, k] - panel.raw_weights[j - 1, k] for k, t in enumerate(panel.tickers[j - 1])}; cur_dev = {t: panel.r5_weights[j, k] - panel.raw_weights[j, k] for k, t in enumerate(panel.tickers[j])}
        overlay += .5 * sum(abs(cur_dev.get(t, 0) - prev_dev.get(t, 0)) for t in set(prev_dev) | set(cur_dev))
    rows = []
    for name in ["RAW_A2", "ORIGINAL_R6_ONLY", "R5_CONSTANT_GROSS"]:
        total = float(sims[name].turnover.sum())
        rows.append({"strategy": name, "constituent_entry_exit_target_turnover": entry_exit, "a2_common_name_weight_change_turnover": a2_change, "incremental_r6_reallocation_target_turnover": overlay if name == "R5_CONSTANT_GROSS" else 0.0, "total_realized_turnover": total, "realized_turnover_delta_vs_raw": total - float(sims["RAW_A2"].turnover.sum())})
    return pd.DataFrame(rows)


def capture_table(sims: dict[str, pd.DataFrame]) -> pd.DataFrame:
    raw = sims["RAW_A2"].set_index("date").daily_return
    rows = []
    for name in ["ORIGINAL_R6_ONLY", "R5_CONSTANT_GROSS", "REVERSE_R6"]:
        other = sims[name].set_index("date").daily_return
        rows.extend([{"strategy": name, "slice": "UPSIDE_CAPTURE", "value": float(other[raw > 0].sum() / raw[raw > 0].sum())}, {"strategy": name, "slice": "DOWNSIDE_CAPTURE", "value": float(other[raw < 0].sum() / raw[raw < 0].sum())}])
        for label, idx in [("TOP20_POSITIVE_DAYS", raw.nlargest(20).index), ("WORST20_NEGATIVE_DAYS", raw.nsmallest(20).index)]:
            rows.append({"strategy": name, "slice": label, "value": float(other.loc[idx].sum()), "raw_value": float(raw.loc[idx].sum())})
        rw = (1 + raw).resample("W-FRI").prod() - 1; ow = (1 + other).resample("W-FRI").prod() - 1
        for label, idx in [("TOP20_POSITIVE_WEEKS", rw.nlargest(20).index), ("WORST20_NEGATIVE_WEEKS", rw.nsmallest(20).index)]:
            rows.append({"strategy": name, "slice": label, "value": float(ow.loc[idx].sum()), "raw_value": float(rw.loc[idx].sum())})
    return pd.DataFrame(rows)


def bootstrap(sims: dict[str, pd.DataFrame]) -> pd.DataFrame:
    raw = sims["RAW_A2"].daily_return.to_numpy(float); r5 = sims["R5_CONSTANT_GROSS"].daily_return.to_numpy(float); n = len(raw)
    rng = np.random.default_rng(RNG_SEED + 1); rows = []
    def array_metrics(x: np.ndarray) -> tuple[float, float, float, float]:
        equity = np.cumprod(1 + x); total = equity[-1] - 1; cagr = (1 + total) ** (252 / len(x)) - 1
        sharpe = x.mean() / x.std(ddof=1) * np.sqrt(252); dd = equity / np.maximum.accumulate(equity) - 1; calmar = cagr / abs(dd.min()) if dd.min() else np.nan
        es = np.sort(x)[:max(1, math.ceil(.05 * len(x)))].mean(); return total, sharpe, calmar, es
    for block in [20, 40]:
        samples = {key: [] for key in ["cumulative_return_delta", "sharpe_delta", "calmar_delta", "es5_delta", "turnover_adjusted_net_advantage"]}
        blocks = math.ceil(n / block)
        for _ in range(BOOTSTRAP_REPS):
            starts = rng.integers(0, n, size=blocks); idx = np.concatenate([(start + np.arange(block)) % n for start in starts])[:n]
            rm, fm = array_metrics(raw[idx]), array_metrics(r5[idx])
            samples["cumulative_return_delta"].append(fm[0] - rm[0]); samples["sharpe_delta"].append(fm[1] - rm[1]); samples["calmar_delta"].append(fm[2] - rm[2]); samples["es5_delta"].append(fm[3] - rm[3]); samples["turnover_adjusted_net_advantage"].append(float((r5[idx] - raw[idx]).mean() * 252))
        for metric, values in samples.items():
            q = np.quantile(values, [.025, .5, .975]); rows.append({"block_sessions": block, "metric": metric, "ci_2_5": q[0], "median": q[1], "ci_97_5": q[2], "replicates": BOOTSTRAP_REPS})
    return pd.DataFrame(rows)


def classify(metrics: pd.DataFrame, yearly: pd.DataFrame, folds: pd.DataFrame, within: pd.DataFrame, rank: pd.DataFrame, concentration_frame: pd.DataFrame, winner: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    base = metrics.loc[metrics.cost_case.eq("BASELINE")].set_index("strategy"); raw, r5, rev = base.loc["RAW_A2"], base.loc["R5_CONSTANT_GROSS"], base.loc["REVERSE_R6"]
    years = yearly.drop_duplicates(["period", "r5_economically_useful"]); positive_years = int(years.r5_economically_useful.sum())
    fold_flags = folds.drop_duplicates(["period", "r5_economically_useful"]); positive_folds = int(fold_flags.r5_economically_useful.sum())
    w_pct = float(within.loc[within.metric.eq("sharpe"), "actual_percentile"].iloc[0]); rank_pct = float(rank.loc[rank.metric.eq("sharpe"), "actual_percentile"].iloc[0])
    conc = concentration_frame.groupby("strategy").mean(numeric_only=True); severe_concentration = bool(conc.loc["R5_CONSTANT_GROSS", "effective_number_positions"] < .80 * conc.loc["RAW_A2", "effective_number_positions"] or conc.loc["R5_CONSTANT_GROSS", "high_correlation_cluster_share"] > conc.loc["RAW_A2", "high_correlation_cluster_share"] + .10)
    all_winner = winner.set_index("outcome_group").loc["ALL"]; winner_ok = bool(all_winner.avoided_loss >= all_winner.sacrificed_gain)
    cost = metrics.set_index(["cost_case", "strategy"]); survives_base = cost.loc[("BASELINE", "R5_CONSTANT_GROSS"), "sharpe"] > cost.loc[("BASELINE", "RAW_A2"), "sharpe"]; survives_2x = cost.loc[("TWO_X", "R5_CONSTANT_GROSS"), "sharpe"] > cost.loc[("TWO_X", "RAW_A2"), "sharpe"]
    reverse_worse = bool(r5.sharpe > rev.sharpe and r5.calmar > rev.calmar)
    gross_match = abs(r5.average_gross_exposure - raw.average_gross_exposure) <= 1e-12
    a = bool(gross_match and r5.cagr >= raw.cagr and r5.sharpe >= raw.sharpe + .05 and r5.calmar >= raw.calmar + .10 and r5.maximum_drawdown >= raw.maximum_drawdown + .02 and r5.expected_shortfall_5 >= raw.expected_shortfall_5 and positive_years >= 3 and positive_folds > len(fold_flags) / 2 and w_pct > .80 and rank_pct > .70 and reverse_worse and survives_base and survives_2x and not severe_concentration)
    meaningful = bool((r5.sharpe > raw.sharpe or r5.calmar > raw.calmar) and (r5.maximum_drawdown > raw.maximum_drawdown or r5.expected_shortfall_5 > raw.expected_shortfall_5))
    b = bool(gross_match and meaningful and r5.cagr >= raw.cagr - .015 and (positive_years >= 3 or positive_folds > len(fold_flags) / 2) and w_pct > .50 and winner_ok and survives_base and not severe_concentration)
    mechanism = bool(winner_ok and all_winner.net_reallocation_value > 0)
    classification = "A_STRONG_CONSTANT_GROSS_R6_VALUE" if a else "B_USEFUL_CONSTANT_GROSS_R6_VALUE" if b else "C_CROSS_SECTIONAL_SIGNAL_ECONOMIC_VALUE_UNCONFIRMED" if mechanism else "D_NO_MATERIAL_CONSTANT_GROSS_VALUE"
    return classification, {"A_gate": a, "B_gate": b, "positive_years": positive_years, "positive_folds": positive_folds, "fold_count": len(fold_flags), "within_date_sharpe_percentile": w_pct, "rank_conditioned_sharpe_percentile": rank_pct, "reverse_directionally_worse": reverse_worse, "winner_destruction_not_larger": winner_ok, "survives_baseline_cost": survives_base, "survives_2x_cost": survives_2x, "severe_concentration_deterioration": severe_concentration}


def run(output: Path = OUTPUT) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"OUTPUT_ALREADY_EXISTS:{output}")
    output.mkdir(parents=True, exist_ok=True)
    sources, identity = verify_sources()
    policy = inherited_policy_manifest(); write_json(output / "r5_inherited_r6_policy_manifest.json", policy); policy_hash = sha256_file(output / "r5_inherited_r6_policy_manifest.json")
    (output / "r5_inherited_r6_policy_manifest_sha256.txt").write_text(policy_hash + "\n", encoding="ascii")
    panel = load_panel()
    # Required independent reproduction happens before contract/economic construction.
    original = simulate(panel, panel.r6_weights, BASE_COST); reference = pd.read_parquet(BASE_R6_PORTFOLIO)
    check = original.merge(reference, left_on="date", right_on="execution_date", validate="one_to_one")
    original_error = float(np.max(np.abs(check.daily_return - check.base_r6_daily_return)))
    if original_error > 1e-12:
        raise RuntimeError(f"ORIGINAL_R6_ECONOMIC_REPRODUCTION_FAILURE:{original_error}")
    contract = contract_payload(sources, identity, policy_hash)
    for name in CONTRACT_NAMES: write_json(output / name, contract)
    contract_hash = sha256_file(output / "r5_contract.json")
    if sha256_file(output / CONTRACT_NAMES[1]) != contract_hash:
        raise RuntimeError("DUPLICATE_CONTRACT_IDENTITY_FAILURE")
    (output / "r5_contract_sha256.txt").write_text(contract_hash + "\n", encoding="ascii")
    metrics, sims, reproduction = strategy_economics(panel)
    gross_error = float(np.max(np.abs(panel.r5_weights.sum(axis=1) - panel.raw_weights.sum(axis=1))))
    if gross_error > 2e-15 or np.any(panel.r5_weights.sum(axis=1) > panel.raw_weights.sum(axis=1) + 2e-15):
        raise RuntimeError(f"DAILY_GROSS_IDENTITY_FAILURE:{gross_error}")
    labels_year = pd.Series(pd.DatetimeIndex(sims["RAW_A2"].date).year.astype(str), index=pd.DatetimeIndex(sims["RAW_A2"].date))
    yearly = slice_metrics(sims, labels_year, "YEAR")
    fold_by_signal = panel.rows.drop_duplicates("signal_date").set_index("signal_date").fold
    fold_labels = pd.Series([fold_by_signal.loc[d] for d in sims["RAW_A2"].holding_signal_date], index=pd.DatetimeIndex(sims["RAW_A2"].date))
    folds = slice_metrics(sims, fold_labels, "OOF_FOLD")
    regime_map = {2022: "2022_RATE_GROWTH_DRAWDOWN", 2023: "2023_RECOVERY", 2024: "2024_TECH_AI_RISK_ON", 2025: "2025_TECH_AI_MIXED"}
    regimes = slice_metrics(sims, labels_year.map(lambda y: regime_map[int(y)]), "REGIME")
    base = metrics.loc[metrics.cost_case.eq("BASELINE")].set_index("strategy"); raw_m, r5_m = base.loc["RAW_A2"].to_dict(), base.loc["R5_CONSTANT_GROSS"].to_dict()
    distribution, within_summary, rank_summary = placebo_test(panel, raw_m, r5_m)
    forward = forward_diagnostics(panel); buckets, transfers, grid, winner = mechanism_outputs(forward)
    concentration_frame = concentration(panel); turnover = turnover_attribution(panel, sims); capture = capture_table(sims); boot = bootstrap(sims)
    classification, gates = classify(metrics, yearly, folds, within_summary, rank_summary, concentration_frame, winner)
    authorized = classification in {"A_STRONG_CONSTANT_GROSS_R6_VALUE", "B_USEFUL_CONSTANT_GROSS_R6_VALUE"}
    # A/B is additionally impossible while the active Anti-Bloat hard gate is failed.
    r1 = sys.modules["r5_identity_r1"]; guard = r1.R3.R1.guard_audit(); anti_bloat_pass = guard.get("repository_guard_status") == "PASS"
    if authorized and not anti_bloat_pass:
        classification = "E_INVALID_OR_INSUFFICIENT_EVIDENCE"; authorized = False; gates["authorization_blocker"] = "PREEXISTING_ANTI_BLOAT_HARD_GATE_FAILURE"
    weights_out = forward[["information_date", "signal_date", "ticker", "A2_RANK", "predicted_bad_asymmetry_risk", "risk_percentile", "fold", "raw_a2_weight", "r6_multiplier", "original_r6_weight", "r5_weight", "reverse_r6_weight"]]
    gross_identity = pd.DataFrame({"signal_date": panel.dates, "raw_a2_gross": panel.raw_weights.sum(axis=1), "r5_gross": panel.r5_weights.sum(axis=1), "gross_match_error": np.abs(panel.r5_weights.sum(axis=1) - panel.raw_weights.sum(axis=1)), "r5_max_weight": panel.r5_weights.max(axis=1), "existing_cap_bind_count": panel.cap_binds})
    reverse_diag = metrics.loc[(metrics.cost_case == "BASELINE") & metrics.strategy.isin(["RAW_A2", "R5_CONSTANT_GROSS", "REVERSE_R6"])].copy()
    source_manifest = {"sources": sources, "identity": identity, "policy_sha256": policy_hash, "contract_sha256": contract_hash, "runner_sha256": sha256_file(Path(__file__))}
    audit = {"contract_sha256": contract_hash, "inherited_r6_policy_identity": "PASS", "a2_frozen_identity": "PASS_46_OF_46", "r6_historical_oof_identity": "PASS", "r6_deploy_identity": "PASS", "r1_r4_identity": "PASS", "original_r6_reproduction_max_error": original_error, "historical_oof_past_only": True, "deployment_model_historical_backcast_count": 0, "lookahead_violation_count": 0, "PIT_violation_count": 0, "same_gross_max_error": gross_error, "leverage_increase_count": int((panel.r5_weights.sum(axis=1) > panel.raw_weights.sum(axis=1) + 2e-15).sum()), "missing_score_count": int(panel.rows.risk_percentile.isna().sum()), "existing_cap_bind_count": int(panel.cap_binds.sum()), "within_date_placebo_count": PLACEBO_COUNT, "rank_conditioned_placebo_count": PLACEBO_COUNT, "model_fit_count_r5": 0, "parameter_search_count": 0, "threshold_search_count": 0, "2026_R5_OUTCOME_READ_COUNT": 0, "anti_bloat": guard, "new_r5_anti_bloat_violation_count": guard.get("new_risk_r1_repo_violation_count", 0), "focused_tests": "PENDING_EXTERNAL_PYTEST"}
    summary = {"A2_RISK_CONTROL_R5_STATUS": "COMPLETE_PRE2026_WITH_PREEXISTING_ANTI_BLOAT_HARD_GATE_FAILURE" if not anti_bloat_pass else "COMPLETE_PRE2026", "A2_RISK_CONTROL_R5_PRE2026_CLASSIFICATION": classification, "A2_RISK_CONTROL_R5_CONTRACT_SHA256": contract_hash, "R5_INHERITED_R6_POLICY_IDENTITY": "PASS", "FIRST_LEGAL_R5_DATE": str(panel.dates.min().date()), "LAST_PRE2026_R5_DATE": str(panel.dates.max().date()), "R5_VALID_DATE_COUNT": len(panel.dates), "R5_DAILY_GROSS_MATCH_MAX_ERROR": gross_error, "R5_AVG_GROSS_EXPOSURE": float(sims["R5_CONSTANT_GROSS"].target_gross.mean()), "RAW_A2_AVG_GROSS_EXPOSURE": float(sims["RAW_A2"].target_gross.mean()), "R5_POSITIVE_YEARS": f"{gates['positive_years']}/4", "R5_POSITIVE_ECONOMIC_FOLDS": f"{gates['positive_folds']}/{gates['fold_count']}", "R5_PERMUTATION_SHARPE_PERCENTILE": gates["within_date_sharpe_percentile"], "R5_RANK_CONDITIONED_PLACEBO_PERCENTILE": gates["rank_conditioned_sharpe_percentile"], "R5_2026_AUTHORIZED": authorized, "2026_R5_OUTCOME_READ_COUNT": 0, "A2_RISK_CONTROL_R5_FINAL_CLASSIFICATION": classification, "NEXT_AUTHORIZED_STEP": "FREEZE_R5_AND_OPEN_MATURED_2026_ONCE" if authorized else "PRESERVE_R5_PRE2026_EVIDENCE;2026_OUTCOMES_UNREAD;STOP", "classification_gates": gates, "anti_bloat_status": "PASS" if anti_bloat_pass else "FAIL_PREEXISTING_REPOSITORY_HARD_GATE", "original_r6_reproduction_max_error": original_error, "R5_EXISTING_CAP_BIND_COUNT": int(panel.cap_binds.sum())}
    write_json(output / "r5_source_manifest.json", source_manifest); write_json(output / "r5_audit.json", audit); write_json(output / "r5_final_summary.json", summary)
    weights_out.to_parquet(output / "r5_daily_weights.parquet", index=False); gross_identity.to_csv(output / "r5_daily_gross_identity.csv", index=False)
    metrics.to_csv(output / "r5_economic_metrics.csv", index=False); yearly.to_csv(output / "r5_yearly_metrics.csv", index=False); regimes.to_csv(output / "r5_regime_metrics.csv", index=False); folds.to_csv(output / "r5_fold_metrics.csv", index=False)
    buckets.to_csv(output / "r5_risk_bucket_analysis.csv", index=False); transfers.to_parquet(output / "r5_capital_transfer_attribution.parquet", index=False); grid.to_csv(output / "r5_alpha_risk_grid.csv", index=False); winner.to_csv(output / "r5_winner_loser_attribution.csv", index=False); capture.to_csv(output / "r5_upside_downside_capture.csv", index=False); concentration_frame.to_csv(output / "r5_concentration_analysis.csv", index=False); turnover.to_csv(output / "r5_turnover_attribution.csv", index=False)
    metrics.to_csv(output / "r5_cost_sensitivity.csv", index=False); within_summary.to_csv(output / "r5_permutation_placebo_summary.csv", index=False); distribution.to_parquet(output / "r5_permutation_placebo_distribution.parquet", index=False); rank_summary.to_csv(output / "r5_rank_conditioned_placebo_summary.csv", index=False); reverse_diag.to_csv(output / "r5_reverse_r6_diagnostic.csv", index=False); boot.to_csv(output / "r5_bootstrap_summary.csv", index=False); reproduction.to_csv(output / "r5_original_r6_reproduction.csv", index=False)
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    keys = ["A2_RISK_CONTROL_R5_STATUS", "A2_RISK_CONTROL_R5_PRE2026_CLASSIFICATION", "A2_RISK_CONTROL_R5_CONTRACT_SHA256", "R5_INHERITED_R6_POLICY_IDENTITY", "FIRST_LEGAL_R5_DATE", "LAST_PRE2026_R5_DATE", "R5_VALID_DATE_COUNT", "R5_DAILY_GROSS_MATCH_MAX_ERROR", "R5_AVG_GROSS_EXPOSURE", "RAW_A2_AVG_GROSS_EXPOSURE", "R5_POSITIVE_YEARS", "R5_POSITIVE_ECONOMIC_FOLDS", "R5_PERMUTATION_SHARPE_PERCENTILE", "R5_RANK_CONDITIONED_PLACEBO_PERCENTILE", "R5_2026_AUTHORIZED", "2026_R5_OUTCOME_READ_COUNT", "A2_RISK_CONTROL_R5_FINAL_CLASSIFICATION", "NEXT_AUTHORIZED_STEP"]
    for key in keys:
        value = summary[key]
        if isinstance(value, float): value = f"{value:.12g}"
        print(f"{key}={value}")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir", type=Path, default=OUTPUT); args = parser.parse_args()
    try:
        summary = run(args.output_dir.resolve()); print_summary(summary); return 0
    except Exception as exc:
        print("A2_RISK_CONTROL_R5_STATUS=FAIL_CLOSED", file=sys.stderr)
        if "FROZEN_R6_ALLOCATION" in str(exc): print("A2_RISK_CONTROL_R5_STATUS=STOP_INVALID_FROZEN_R6_ALLOCATION_IDENTITY", file=sys.stderr)
        print("A2_RISK_CONTROL_R5_PRE2026_CLASSIFICATION=E_INVALID_OR_INSUFFICIENT_EVIDENCE", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
