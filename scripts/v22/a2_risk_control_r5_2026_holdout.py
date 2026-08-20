"""User-authorized one-shot exploratory 2026 holdout for frozen R5.

This runner performs no fitting, tuning, threshold search, model selection, or
policy selection.  It imports the frozen R5 construction and the authoritative
R11 2026 lineage builder, verifies exact reproduction of the preserved R11
scores/outcomes, and evaluates exactly Raw A2, Original R6-to-cash, and frozen
R5 constant-gross.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
R5_ROOT = RESULTS / "A2_RISK_CONTROL_R5_CONSTANT_GROSS_R6"
R11_ROOT = RESULTS / "A2_STOCK_RISK_R11_PROSPECTIVE"
OUTPUT = R5_ROOT / "USER_AUTHORIZED_EXPLORATORY_2026_HOLDOUT"
R5_CONTRACT = R5_ROOT / "r5_contract.json"
R5_CONTRACT_SHA256 = "720f1d62e9c8c724176d034067850fdf5d5f8df0d2b48551a003e9b453ae42d9"
R6_DEPLOY = R11_ROOT / "r6_frozen_deploy_r1.joblib"
R6_DEPLOY_SHA256 = "3e5f646fcfbf1b4e9196781f712305b044a7b2e57c0fe1b3fe202345561f4a08"
R11_PREDICTIONS = R11_ROOT / "r11_2026_r6_predictions.parquet"
TEST_LABEL = "USER_AUTHORIZED_EXPLORATORY_2026_HOLDOUT"
BASE_COST = 0.001
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILURE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def verify_frozen_identity() -> tuple[Any, dict[str, Any], dict[str, Any]]:
    if sha256_file(R5_CONTRACT) != R5_CONTRACT_SHA256:
        raise RuntimeError("R5_CONTRACT_IDENTITY_FAILURE")
    r5 = load_module("r5_2026_frozen_rule", REPO / "scripts/v22/a2_risk_control_r5.py")
    sources, identity = r5.verify_sources()
    if identity["live_frozen_identity"].get("verified_a2_artifact_count") != 46:
        raise RuntimeError("A2_46_OF_46_IDENTITY_FAILURE")
    if sha256_file(R6_DEPLOY) != R6_DEPLOY_SHA256:
        raise RuntimeError("R6_DEPLOY_IDENTITY_FAILURE")
    if (r5.RISK_THRESHOLD, r5.HIGH_RISK_MULTIPLIER, r5.NORMAL_MULTIPLIER, r5.MAX_WEIGHT, r5.BASE_COST) != (.90, .50, 1.0, .06, .001):
        raise RuntimeError("FROZEN_R5_RULE_IDENTITY_FAILURE")
    deploy = joblib.load(R6_DEPLOY)
    spec = deploy.get("spec", {})
    training_max = pd.Timestamp(spec.get("training_end_date"))
    if training_max >= TRAINING_CUTOFF or spec.get("2026_model_fit_rows") != 0:
        raise RuntimeError("ZERO_TRAINING_CONTRACT_FAILURE")
    frozen = {
        "A2_FROZEN_ARTIFACTS": "PASS_46_OF_46",
        "R6_DEPLOY_SHA256": sha256_file(R6_DEPLOY),
        "R5_CONTRACT_SHA256": sha256_file(R5_CONTRACT),
        "TRAINING_ROW_DATE_MAX": str(training_max.date()),
        "2026_TRAINING_ROWS": 0,
        "2026_PARAMETER_SEARCH_COUNT": 0,
        "2026_THRESHOLD_SEARCH_COUNT": 0,
        "2026_MODEL_SELECTION_COUNT": 0,
        "R5_RULE": "risk_percentile>=0.90=>0.50; otherwise=>1.00; same-gross waterfill; cap=0.06",
        "BASELINE_COST": BASE_COST,
        "R5_RUNNER_SHA256": sha256_file(REPO / "scripts/v22/a2_risk_control_r5.py"),
    }
    return r5, deploy, {"frozen": frozen, "source_manifest": sources, "a2_r6_identity": identity}


def holdout_contract(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_label": TEST_LABEL,
        "research_status": "EXPLORATORY_NOT_PREREGISTERED_PROSPECTIVE_PASS",
        "authorization": "user explicitly authorized one-shot 2026 outcome evaluation after pre-2026 R5 classification C",
        "r5_contract_sha256": R5_CONTRACT_SHA256,
        "frozen_identity": identity["frozen"],
        "strategies": ["RAW_A2", "ORIGINAL_FROZEN_R6", "R5_CONSTANT_GROSS"],
        "r6_mapping": {"risk_percentile>=0.90": .50, "otherwise": 1.0, "removed_weight_destination_original_r6": "CASH"},
        "r5_mapping": "multiply Raw A2 by frozen R6 multiplier, then deterministic same-date gross waterfill under inherited 0.06 cap",
        "cost_convention": "frozen R5 half-L1 drift-aware turnover * 0.001; first target initializes without entry cost",
        "maturity": "all 5-session-mature frozen R11 rows; 20-session diagnostics only where all 20 constituents have full paths",
        "classification": {
            "strong": "R5 beats Raw on cumulative return, Sharpe, MaxDD, Calmar and ES5; competitive with Original R6; predictive and mechanism support; no tail deterioration",
            "directional": "predictive support, at least two mechanism horizons positive, at least three core economic deltas positive, no >2pp MaxDD deterioration",
            "mixed": "predictive cross-sectional support persists but economics/mechanism are not consistently positive",
            "negative": "R5 cumulative return is worse and at least three core risk-adjusted metrics are worse, or MaxDD deteriorates by >2pp",
            "invalid": "identity, lineage, maturity, or engineering failure",
        },
        "prohibitions": ["NO_FIT", "NO_RECALIBRATION", "NO_THRESHOLD_CHANGE", "NO_MULTIPLIER_CHANGE", "NO_FEATURE_CHANGE", "NO_A2_CHANGE", "NO_R6_CHANGE", "NO_R5_CHANGE", "NO_CAP_CHANGE", "NO_COST_CHANGE", "NO_SUBPERIOD_SELECTION", "NO_RESCUE_EXPERIMENT"],
        "output_root": str(OUTPUT),
        "runner_sha256": sha256_file(Path(__file__)),
    }


def reproduce_authoritative_2026(r11: Any, deploy: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    mature, _, population_audit, context = r11.load_2026_population(deploy)
    reference = pd.read_parquet(R11_PREDICTIONS)
    for frame in (mature, reference):
        frame["signal_date"] = pd.to_datetime(frame.signal_date)
        frame["information_date"] = pd.to_datetime(frame.information_date)
        frame["target_end_date"] = pd.to_datetime(frame.target_end_date)
    joined = mature.merge(reference, on=["signal_date", "ticker"], suffixes=("_new", "_ref"), validate="one_to_one")
    columns = ["R6_frozen_risk_score", "R6_risk_percentile_using_pre2026_reference", "post_entry_forward_1d_return", "post_entry_forward_5d_return", "post_entry_5d_mae", "post_entry_5d_mfe", "bad_target"]
    errors = {column: float(np.max(np.abs(joined[f"{column}_new"].astype(float) - joined[f"{column}_ref"].astype(float)))) for column in columns}
    if len(reference) != 560 or reference.signal_date.nunique() != 28 or max(errors.values()) > 1e-15:
        raise RuntimeError(f"R11_AUTHORITATIVE_REPRODUCTION_FAILURE:{errors}")
    counts = reference.groupby("signal_date").agg(rows=("ticker", "size"), tickers=("ticker", "nunique"), ranks=("A2_RANK", "nunique"))
    if not counts.eq(20).all().all() or reference.R6_risk_percentile_using_pre2026_reference.isna().any():
        raise RuntimeError("R11_TOP20_OR_SCORE_COVERAGE_FAILURE")
    return reference.sort_values(["signal_date", "ticker"]).reset_index(drop=True), context, {"population_audit": population_audit, "reproduction_errors": errors}


def build_portfolio_panel(r5: Any, scored: pd.DataFrame, context: dict[str, Any]) -> tuple[Any, pd.DataFrame]:
    dates = pd.DatetimeIndex(sorted(scored.signal_date.unique()))
    groups = [group.copy() for _, group in scored.groupby("signal_date", sort=True)]
    tickers = [g.ticker.astype(str).to_numpy() for g in groups]
    raw = np.full((len(dates), 20), .05)
    multiplier = np.vstack([np.where(g.R6_risk_percentile_using_pre2026_reference.to_numpy(float) >= .90, .50, 1.0) for g in groups])
    original = raw * multiplier
    r5_weights = np.empty_like(raw); cap_binds = np.zeros(len(dates), int)
    for j in range(len(dates)):
        r5_weights[j], cap_binds[j] = r5.waterfill(original[j], target=1.0, cap=.06)
    prices = context["prices"].copy(); prices.trade_date = pd.to_datetime(prices.trade_date)
    open_lookup = prices.set_index(["ticker", "trade_date"]).open
    interval_returns: list[np.ndarray] = []; mappings: list[np.ndarray] = []
    for j in range(len(dates) - 1):
        previous, current = dates[j], dates[j + 1]
        values = []
        for ticker in tickers[j]:
            if (ticker, previous) not in open_lookup.index or (ticker, current) not in open_lookup.index:
                raise RuntimeError(f"MISSING_AUTHORITATIVE_OPEN_RETURN:{ticker}:{previous}:{current}")
            values.append(float(open_lookup.loc[(ticker, current)] / open_lookup.loc[(ticker, previous)] - 1))
        interval_returns.append(np.asarray(values, float))
        current_map = {ticker: k for k, ticker in enumerate(tickers[j + 1])}
        mappings.append(np.asarray([current_map.get(ticker, -1) for ticker in tickers[j]], int))
    rows = scored.copy()
    rows["raw_a2_weight"] = raw.ravel(); rows["r6_multiplier"] = multiplier.ravel(); rows["original_r6_weight"] = original.ravel(); rows["r5_weight"] = r5_weights.ravel()
    panel = r5.Panel(rows, dates, tickers, interval_returns, mappings, raw, original, r5_weights, np.empty_like(raw), cap_binds)
    gross = pd.DataFrame({"signal_date": dates, "raw_a2_gross": raw.sum(axis=1), "original_r6_gross": original.sum(axis=1), "r5_gross": r5_weights.sum(axis=1), "gross_match_error": np.abs(r5_weights.sum(axis=1) - raw.sum(axis=1)), "r5_max_weight": r5_weights.max(axis=1), "existing_cap_bind_count": cap_binds})
    if gross.gross_match_error.max() > 2e-15 or (r5_weights < -1e-15).any() or (r5_weights > .06 + 1e-14).any() or (gross.r5_gross > gross.raw_a2_gross + 2e-15).any():
        raise RuntimeError("2026_R5_WEIGHT_IDENTITY_FAILURE")
    return panel, gross


def metrics(daily: pd.DataFrame) -> dict[str, float]:
    r = pd.Series(daily.daily_return.to_numpy(float), index=pd.DatetimeIndex(daily.date)); n = len(r)
    equity = pd.Series(np.r_[1.0, np.cumprod(1.0 + r.to_numpy())]); total = float(equity.iloc[-1] - 1)
    annual = float((1 + total) ** (252 / n) - 1) if n and total > -1 else np.nan
    vol = float(r.std(ddof=1) * math.sqrt(252)); sharpe = float(r.mean() / r.std(ddof=1) * math.sqrt(252)) if r.std(ddof=1) else np.nan
    negative = r[r < 0]; downside = float(negative.std(ddof=1) * math.sqrt(252)); sortino = float(r.mean() * 252 / downside) if downside else np.nan
    dd = equity / equity.cummax() - 1; maxdd = float(dd.min()); calmar = annual / abs(maxdd) if maxdd else np.nan
    weekly = (1 + r).resample("W-FRI").prod() - 1; monthly = (1 + r).resample("ME").prod() - 1
    tail_n = max(1, math.ceil(.05 * n)); es5 = float(np.sort(r.to_numpy())[:tail_n].mean())
    return {"cumulative_return": total, "annualized_return_short_sample": annual, "annualized_volatility": vol, "sharpe": sharpe, "sortino": sortino, "maximum_drawdown": maxdd, "calmar_short_sample": calmar, "expected_shortfall_5": es5, "worst_day": float(r.min()), "worst_week": float(weekly.min()), "worst_month": float(monthly.min()), "average_gross_exposure": float(daily.target_gross.mean()), "turnover": float(daily.turnover.sum()), "transaction_costs": float(daily.transaction_cost_return.sum()), "realized_return_sessions": n}


def economics(r5: Any, panel: Any) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], pd.DataFrame]:
    definitions = {"RAW_A2": panel.raw_weights, "ORIGINAL_FROZEN_R6": panel.r6_weights, "R5_CONSTANT_GROSS": panel.r5_weights}
    sims = {name: r5.simulate(panel, weights, BASE_COST) for name, weights in definitions.items()}
    table = pd.DataFrame([{"strategy": name, **metrics(daily)} for name, daily in sims.items()])
    by = table.set_index("strategy"); pairs = [("ORIGINAL_FROZEN_R6_MINUS_RAW_A2", "ORIGINAL_FROZEN_R6", "RAW_A2"), ("R5_CONSTANT_GROSS_MINUS_RAW_A2", "R5_CONSTANT_GROSS", "RAW_A2"), ("R5_CONSTANT_GROSS_MINUS_ORIGINAL_FROZEN_R6", "R5_CONSTANT_GROSS", "ORIGINAL_FROZEN_R6")]
    columns = ["cumulative_return", "sharpe", "maximum_drawdown", "calmar_short_sample", "expected_shortfall_5"]
    deltas = pd.DataFrame([{"comparison": label, **{f"{column}_delta": float(by.loc[left, column] - by.loc[right, column]) for column in columns}} for label, left, right in pairs])
    return table, sims, deltas


def diagnostics(scored: pd.DataFrame, context: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    y = scored.bad_target.to_numpy(int); probability = scored.R6_frozen_risk_score.to_numpy(float); percentile = scored.R6_risk_percentile_using_pre2026_reference.to_numpy(float); top = percentile >= .90; base = float(y.mean())
    k = min(100, int(math.floor(.01 * len(scored)))); worst = scored.nsmallest(k, "post_entry_forward_5d_return"); best = scored.nlargest(k, "post_entry_forward_5d_return")
    predictive = {"base_event_rate": base, "auroc": float(roc_auc_score(y, probability)), "average_precision": float(average_precision_score(y, probability)), "average_precision_base_multiple": float(average_precision_score(y, probability) / base), "top_decile_bad_event_rate": float(y[top].mean()), "top_decile_lift": float(y[top].mean() / base), "top_decile_bad_event_capture": float(y[top].sum() / y.sum()), "worst_event_k": k, "worst_event_capture": float(worst.R6_risk_percentile_using_pre2026_reference.ge(.90).mean()), "best_event_capture": float(best.R6_risk_percentile_using_pre2026_reference.ge(.90).mean())}
    frame = scored.copy(); frame["risk_decile"] = np.clip(np.ceil(frame.R6_risk_percentile_using_pre2026_reference * 10), 1, 10).astype(int)
    deciles = frame.groupby("risk_decile", as_index=False).agg(row_count=("ticker", "size"), bad_event_rate=("bad_target", "mean"), mean_5d_return=("post_entry_forward_5d_return", "mean"), mean_5d_mae=("post_entry_5d_mae", "mean"), mean_5d_mfe=("post_entry_5d_mfe", "mean"))
    prices = context["prices"].copy(); prices.trade_date = pd.to_datetime(prices.trade_date); bars = prices.set_index(["ticker", "trade_date"]); calendar = context["calendar"]
    forward20 = []
    for row in frame[["signal_date", "ticker"]].itertuples(index=False):
        position = calendar.get_loc(row.signal_date); dates = calendar[position:position + 20]
        if len(dates) != 20 or any((row.ticker, date) not in bars.index for date in dates):
            forward20.append((np.nan, np.nan)); continue
        local = bars.loc[[(row.ticker, date) for date in dates]].reset_index().sort_values("trade_date"); entry = float(local.iloc[0].open)
        forward20.append((float(local.iloc[-1].close / entry - 1), float(local.low.min() / entry - 1)))
    frame[["post_entry_forward_20d_return", "post_entry_worst_20d_path"]] = forward20
    frame["weight_shift"] = frame.r5_weight - frame.raw_a2_weight; frame.loc[frame.weight_shift.abs() < 1e-12, "weight_shift"] = 0.0
    frame["removed"] = (-frame.weight_shift).clip(lower=0); frame["added"] = frame.weight_shift.clip(lower=0)
    transfer_rows = []
    for date, group in frame.groupby("signal_date", sort=True):
        removed, added = float(group.removed.sum()), float(group.added.sum())
        if removed <= 1e-12 or added <= 1e-12:
            continue
        def wavg(column: str, weight: str) -> float:
            valid = group[column].notna() & group[weight].gt(0)
            return float(np.average(group.loc[valid, column], weights=group.loc[valid, weight])) if valid.any() else np.nan
        row = {"signal_date": date, "transferred_gross": removed, "donor_average_r6_risk": wavg("R6_risk_percentile_using_pre2026_reference", "removed"), "receiver_average_r6_risk": wavg("R6_risk_percentile_using_pre2026_reference", "added"), "donor_average_a2_rank": wavg("A2_RANK", "removed"), "receiver_average_a2_rank": wavg("A2_RANK", "added")}
        for label, column in [("1d", "post_entry_forward_1d_return"), ("5d", "post_entry_forward_5d_return"), ("20d", "post_entry_forward_20d_return"), ("worst_20d", "post_entry_worst_20d_path")]:
            receive, donate = wavg(column, "added"), wavg(column, "removed"); row[f"receiving_{label}"] = receive; row[f"donating_{label}"] = donate; row[f"receiving_minus_donating_{label}"] = receive - donate if np.isfinite(receive) and np.isfinite(donate) else np.nan
        transfer_rows.append(row)
    transfers = pd.DataFrame(transfer_rows)
    mechanism = {"active_transfer_dates": len(transfers), "average_transferred_gross": float(transfers.transferred_gross.mean()) if len(transfers) else np.nan, "donor_average_r6_risk": float(transfers.donor_average_r6_risk.mean()) if len(transfers) else np.nan, "receiver_average_r6_risk": float(transfers.receiver_average_r6_risk.mean()) if len(transfers) else np.nan, "donor_average_a2_rank": float(transfers.donor_average_a2_rank.mean()) if len(transfers) else np.nan, "receiver_average_a2_rank": float(transfers.receiver_average_a2_rank.mean()) if len(transfers) else np.nan, "receiving_minus_donating_1d": float(transfers.receiving_minus_donating_1d.mean()) if len(transfers) else np.nan, "receiving_minus_donating_5d": float(transfers.receiving_minus_donating_5d.mean()) if len(transfers) else np.nan, "receiving_minus_donating_20d": float(transfers.receiving_minus_donating_20d.mean()) if transfers.receiving_minus_donating_20d.notna().any() else np.nan, "receiving_minus_donating_worst_20d": float(transfers.receiving_minus_donating_worst_20d.mean()) if transfers.receiving_minus_donating_worst_20d.notna().any() else np.nan, "mature_20d_stock_rows": int(frame.post_entry_forward_20d_return.notna().sum()), "mature_20d_dates": int(frame.loc[frame.post_entry_forward_20d_return.notna(), "signal_date"].nunique())}
    return predictive, deciles, transfers, mechanism


def classify(table: pd.DataFrame, predictive: dict[str, Any], mechanism: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    by = table.set_index("strategy"); raw, original, r5 = by.loc["RAW_A2"], by.loc["ORIGINAL_FROZEN_R6"], by.loc["R5_CONSTANT_GROSS"]
    core = {"cumulative_return": r5.cumulative_return > raw.cumulative_return, "sharpe": r5.sharpe > raw.sharpe, "maximum_drawdown": r5.maximum_drawdown >= raw.maximum_drawdown, "calmar": r5.calmar_short_sample > raw.calmar_short_sample, "es5": r5.expected_shortfall_5 >= raw.expected_shortfall_5}
    predictive_support = bool(predictive["auroc"] > .5 and predictive["average_precision_base_multiple"] > 1 and predictive["top_decile_lift"] > 1)
    mechanism_values = [mechanism["receiving_minus_donating_1d"], mechanism["receiving_minus_donating_5d"], mechanism["receiving_minus_donating_20d"], mechanism["receiving_minus_donating_worst_20d"]]
    mechanism_positive = sum(bool(np.isfinite(value) and value > 0) for value in mechanism_values)
    competitive_original = bool(r5.cumulative_return >= original.cumulative_return - .01 and r5.sharpe >= original.sharpe - .05)
    strong = bool(all(core.values()) and competitive_original and predictive_support and mechanism_positive >= 2)
    directional = bool(predictive_support and mechanism_positive >= 2 and sum(core.values()) >= 3 and r5.maximum_drawdown >= raw.maximum_drawdown - .02)
    negative = bool(r5.cumulative_return < raw.cumulative_return and (sum(not value for value in core.values()) >= 3 or r5.maximum_drawdown < raw.maximum_drawdown - .02))
    label = "HOLDOUT_STRONGLY_SUPPORTIVE" if strong else "HOLDOUT_DIRECTIONALLY_SUPPORTIVE" if directional else "HOLDOUT_NEGATIVE" if negative else "HOLDOUT_MIXED"
    return label, {"core_r5_vs_raw": core, "predictive_support": predictive_support, "mechanism_positive_horizons": mechanism_positive, "competitive_with_original_r6": competitive_original, "strong_gate": strong, "directional_gate": directional, "negative_gate": negative}


def run(output: Path = OUTPUT) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"OUTPUT_ALREADY_EXISTS:{output}")
    output.mkdir(parents=True, exist_ok=True)
    r5, deploy, identity = verify_frozen_identity()
    contract = holdout_contract(identity); write_json(output / "r5_2026_holdout_contract.json", contract); contract_hash = sha256_file(output / "r5_2026_holdout_contract.json"); (output / "r5_2026_holdout_contract_sha256.txt").write_text(contract_hash + "\n", encoding="ascii")
    r11 = load_module("r5_2026_r11_lineage", REPO / "scripts/v22/a2_stock_risk_r10_r11_fast_track.py")
    scored, context, reproduction = reproduce_authoritative_2026(r11, deploy)
    panel, gross = build_portfolio_panel(r5, scored, context)
    table, sims, deltas = economics(r5, panel)
    scored = panel.rows.copy()
    predictive, deciles, transfers, mechanism = diagnostics(scored, context)
    classification, gates = classify(table, predictive, mechanism)
    guard = sys.modules["r5_identity_r1"].R3.R1.guard_audit(); anti_bloat = guard.get("repository_guard_status") == "PASS"
    status = "COMPLETE_USER_AUTHORIZED_EXPLORATORY_2026_HOLDOUT" + ("_WITH_PREEXISTING_ANTI_BLOAT_HARD_GATE_FAILURE" if not anti_bloat else "")
    summary = {"A2_RISK_CONTROL_R5_2026_TEST_STATUS": status, "TEST_LABEL": TEST_LABEL, "R5_CONTRACT_SHA256": R5_CONTRACT_SHA256, "2026_TRAINING_ROWS": 0, "2026_PARAMETER_SEARCH_COUNT": 0, "2026_THRESHOLD_SEARCH_COUNT": 0, "2026_MODEL_SELECTION_COUNT": 0, "FIRST_2026_ELIGIBLE_DATE": str(panel.dates.min().date()), "LAST_2026_MATURED_DATE": str(panel.dates.max().date()), "2026_ELIGIBLE_DATE_COUNT": len(panel.dates), "2026_R5_DAILY_GROSS_MATCH_MAX_ERROR": float(gross.gross_match_error.max()), "R6_2026_CLASSIFICATION": "B_MODERATE_PROSPECTIVE_CONFIRMATION", "R5_2026_HOLDOUT_CLASSIFICATION": classification, "NEXT_AUTHORIZED_STEP": "PRESERVE_RESULTS_AND_STOP", "TRAINING_ROW_DATE_MAX": identity["frozen"]["TRAINING_ROW_DATE_MAX"], "classification_gates": gates, "mechanism": mechanism, "predictive": predictive, "holdout_contract_sha256": contract_hash, "anti_bloat_status": "PASS" if anti_bloat else "FAIL_PREEXISTING_REPOSITORY_HARD_GATE"}
    audit = {"summary": summary, "identity": identity, "authoritative_2026_reproduction": reproduction, "same_gross_max_error": float(gross.gross_match_error.max()), "leverage_increase_count": int((gross.r5_gross > gross.raw_a2_gross + 2e-15).sum()), "negative_position_count": int((panel.r5_weights < -1e-15).sum()), "cap_violation_count": int((panel.r5_weights > .06 + 1e-14).sum()), "existing_cap_bind_count": int(panel.cap_binds.sum()), "model_fit_count_2026": 0, "parameter_search_count_2026": 0, "threshold_search_count_2026": 0, "model_selection_count_2026": 0, "alternative_mapping_test_count": 0, "subperiod_selection_count": 0, "focused_tests": "PENDING_EXTERNAL_PYTEST", "repository_governance": guard}
    weights = scored[["information_date", "signal_date", "ticker", "A2_RANK", "A2_PREDICTION", "R6_frozen_risk_score", "R6_risk_percentile_using_pre2026_reference", "bad_target", "target_end_date", "raw_a2_weight", "r6_multiplier", "original_r6_weight", "r5_weight"]]
    daily = pd.concat([frame.assign(strategy=name) for name, frame in sims.items()], ignore_index=True)
    write_json(output / "r5_2026_identity_manifest.json", identity); write_json(output / "r5_2026_predictive_metrics.json", predictive); write_json(output / "r5_2026_mechanism_summary.json", mechanism); write_json(output / "r5_2026_audit.json", audit); write_json(output / "r5_2026_final_summary.json", summary)
    weights.to_parquet(output / "r5_2026_daily_weights.parquet", index=False); gross.to_csv(output / "r5_2026_daily_gross_identity.csv", index=False); daily.to_parquet(output / "r5_2026_daily_returns.parquet", index=False); table.to_csv(output / "r5_2026_economic_metrics.csv", index=False); deltas.to_csv(output / "r5_2026_economic_deltas.csv", index=False); deciles.to_csv(output / "r5_2026_risk_deciles.csv", index=False); transfers.to_csv(output / "r5_2026_capital_transfer.csv", index=False)
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    keys = ["A2_RISK_CONTROL_R5_2026_TEST_STATUS", "TEST_LABEL", "R5_CONTRACT_SHA256", "2026_TRAINING_ROWS", "2026_PARAMETER_SEARCH_COUNT", "2026_THRESHOLD_SEARCH_COUNT", "2026_MODEL_SELECTION_COUNT", "FIRST_2026_ELIGIBLE_DATE", "LAST_2026_MATURED_DATE", "2026_ELIGIBLE_DATE_COUNT", "2026_R5_DAILY_GROSS_MATCH_MAX_ERROR", "R6_2026_CLASSIFICATION", "R5_2026_HOLDOUT_CLASSIFICATION", "NEXT_AUTHORIZED_STEP"]
    for key in keys:
        value = summary[key]
        if isinstance(value, float): value = f"{value:.12g}"
        print(f"{key}={value}")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir", type=Path, default=OUTPUT); args = parser.parse_args()
    try:
        summary = run(args.output_dir.resolve()); print_summary(summary); return 0
    except Exception as exc:
        print("A2_RISK_CONTROL_R5_2026_TEST_STATUS=HOLDOUT_INVALID", file=sys.stderr); print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
