"""R5 aggregated stock-risk portfolio diagnostics with a fail-closed Q90 gate."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUTPUT_DIR = RESULTS_ROOT / "A2_RISK_R5"
R3A_SCRIPT = REPO_ROOT / "scripts" / "v22" / "a2_stock_risk_r3a_r3r.py"
R3R_ROOT = RESULTS_ROOT / "A2_STOCK_RISK_R3A_R3R"
R3R_OOF_PATH = R3R_ROOT / "r3r_oof_predictions.parquet"
REFERENCE_CANDIDATE = "LGBM_STOCK_Q90_1"
EXPECTED_R3R_HASH = "636d87b1fb0c8981d95cfc41524dbfd6e7afa86f361f27432b6799412a649399"
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R3A = _load_module(R3A_SCRIPT, "a2_stock_risk_r3a_r3r_for_r5")
R3 = R3A.R3


def load_authoritative_oof() -> pd.DataFrame:
    actual_hash = R3.R1.sha256_file(R3R_OOF_PATH)
    if actual_hash != EXPECTED_R3R_HASH:
        raise RuntimeError(f"R3R risk signal hash mismatch: {actual_hash}")
    oof = pd.read_parquet(R3R_OOF_PATH)
    oof["signal_date"] = pd.to_datetime(oof.signal_date)
    selected = oof.loc[oof.candidate_id.eq(REFERENCE_CANDIDATE)].copy()
    if selected.empty or selected.signal_date.ge(TRAINING_CUTOFF).any():
        raise RuntimeError("R5 authoritative OOF firewall failure")
    return selected


def aggregate_tail_load(selected: pd.DataFrame) -> pd.DataFrame:
    counts = selected.groupby("signal_date").size()
    if not counts.eq(20).all() or selected.groupby("signal_date").ticker.nunique().ne(20).any():
        raise RuntimeError("R5 OOF date does not contain exact frozen Top20")
    rows = []
    for date, group in selected.groupby("signal_date", sort=True):
        scores = group.predicted_q90.to_numpy(dtype=float)
        folds = group.fold.unique()
        if len(folds) != 1:
            raise RuntimeError("R5 fold not unique within signal date")
        rows.append({"signal_date": date, "fold": folds[0], "portfolio_tail_load": float(scores.mean()), "maximum_stock_predicted_risk": float(scores.max()), "top5_average_predicted_risk": float(np.sort(scores)[-5:].mean()), "fraction_top20_above_training_q90_score": float(group.risk_percentile.ge(0.90).mean())})
    return pd.DataFrame(rows)


def portfolio_outcomes(signal_dates: pd.Series, daily: pd.DataFrame) -> pd.DataFrame:
    series = daily.set_index("execution_date").reconstructed_daily_return.sort_index()
    sessions = pd.DatetimeIndex(series.index)
    rows = []
    for date in pd.DatetimeIndex(signal_dates):
        position = int(sessions.get_loc(date))
        forward_dates = sessions[position + 1 : position + 6]
        returns = series.reindex(forward_dates).to_numpy(dtype=float)
        if len(returns) != 5 or not np.isfinite(returns).all():
            continue
        path = np.cumprod(1.0 + returns) - 1.0
        rows.append({"signal_date": date, "next_day_return_date": pd.Timestamp(forward_dates[0]), "next_day_a2_return": float(returns[0]), "forward_5d_a2_return": float(path[-1]), "forward_5d_a2_mae": max(0.0, float(-path.min())), "forward_5d_a2_mfe": max(0.0, float(path.max())), "target_end_date": pd.Timestamp(forward_dates[-1])})
    return pd.DataFrame(rows)


def add_fold_severe_labels(frame: pd.DataFrame, all_outcomes: pd.DataFrame, sessions: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    result = frame.copy()
    fold_rows = []
    result["portfolio_severe_5d"] = False
    for fold_name, start, end in R3.FOLDS:
        train, valid, cutoff = R3.fold_split(all_outcomes, sessions, start, end)
        threshold = float(train.forward_5d_a2_mae.quantile(0.90))
        mask = result.fold.eq(fold_name)
        result.loc[mask, "portfolio_severe_5d"] = result.loc[mask, "forward_5d_a2_mae"].gt(threshold)
        fold_rows.append({"fold": fold_name, "training_outcome_rows": len(train), "validation_outcome_rows": len(valid), "portfolio_mae_training_q90": threshold, "embargo_cutoff": cutoff})
    return result, pd.DataFrame(fold_rows)


def predictive_diagnostics(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    relationships = []
    for target in ["next_day_a2_return", "forward_5d_a2_return", "forward_5d_a2_mae", "forward_5d_a2_mfe"]:
        relationships.append({"target": target, "spearman": float(spearmanr(frame.portfolio_tail_load, frame[target]).statistic), "pearson": float(pearsonr(frame.portfolio_tail_load, frame[target]).statistic)})
    percentile = frame.portfolio_tail_load.rank(method="average", pct=True)
    frame = frame.copy()
    frame["tail_load_percentile"] = percentile
    frame["tail_load_decile"] = np.clip(np.ceil(percentile * 10), 1, 10).astype(int)
    deciles = frame.groupby("tail_load_decile", sort=True).agg(observation_count=("signal_date", "size"), mean_portfolio_tail_load=("portfolio_tail_load", "mean"), mean_next_day_a2_return=("next_day_a2_return", "mean"), mean_forward_5d_a2_return=("forward_5d_a2_return", "mean"), mean_forward_5d_a2_mae=("forward_5d_a2_mae", "mean"), mean_forward_5d_a2_mfe=("forward_5d_a2_mfe", "mean"), portfolio_severe_loss_incidence=("portfolio_severe_5d", "mean")).reset_index()
    fold_rows = []
    positive = 0
    for fold_name, _, _ in R3.FOLDS:
        fold = frame.loc[frame.fold.eq(fold_name)].copy()
        fold["fold_decile"] = np.clip(np.ceil(fold.portfolio_tail_load.rank(method="average", pct=True) * 10), 1, 10).astype(int)
        spearman = float(spearmanr(fold.portfolio_tail_load, fold.forward_5d_a2_mae).statistic)
        lift = float(fold.loc[fold.fold_decile.eq(10), "forward_5d_a2_mae"].mean() / fold.forward_5d_a2_mae.mean())
        direction = bool(spearman > 0 and lift > 1.0)
        positive += int(direction)
        fold_rows.append({"fold": fold_name, "observation_count": len(fold), "tail_load_5d_mae_spearman": spearman, "top_decile_portfolio_risk_lift": lift, "predictive_direction_positive": direction})
    top = deciles.loc[deciles.tail_load_decile.eq(10)].iloc[0]
    summary = {"TAIL_LOAD_5D_MAE_SPEARMAN": float(spearmanr(frame.portfolio_tail_load, frame.forward_5d_a2_mae).statistic), "TAIL_LOAD_5D_MAE_PEARSON": float(pearsonr(frame.portfolio_tail_load, frame.forward_5d_a2_mae).statistic), "TAIL_LOAD_TOP_DECILE_RISK_LIFT": float(top.mean_forward_5d_a2_mae / frame.forward_5d_a2_mae.mean()), "TAIL_LOAD_TOP_DECILE_SEVERE_LIFT": float(top.portfolio_severe_loss_incidence / frame.portfolio_severe_5d.mean()), "POSITIVE_DIRECTION_FOLDS": positive}
    return pd.DataFrame(relationships), deciles, pd.DataFrame(fold_rows), frame, summary


def day_capture(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    count_5pct = max(1, math.ceil(0.05 * len(frame)))
    groups = {"WORST_10": frame.nsmallest(10, "next_day_a2_return"), "WORST_20": frame.nsmallest(20, "next_day_a2_return"), "WORST_5PCT": frame.nsmallest(count_5pct, "next_day_a2_return"), "BEST_10": frame.nlargest(10, "next_day_a2_return"), "BEST_20": frame.nlargest(20, "next_day_a2_return"), "BEST_5PCT": frame.nlargest(count_5pct, "next_day_a2_return")}
    rows = []
    for group_name, group in groups.items():
        for row in group.itertuples(index=False):
            rows.append({"outcome_group": group_name, "signal_date": row.signal_date, "a2_return_date": row.next_day_return_date, "next_day_a2_return": row.next_day_a2_return, "portfolio_tail_load": row.portfolio_tail_load, "tail_load_percentile": row.tail_load_percentile, "captured_in_top_tail_load_decile": row.tail_load_percentile >= 0.90})
    summary = {"WORST_5PCT_DAY_CAPTURE_IN_TOP_TAIL_LOAD_DECILE": float((groups["WORST_5PCT"].tail_load_percentile >= 0.90).mean()), "BEST_5PCT_DAY_CAPTURE_IN_TOP_TAIL_LOAD_DECILE": float((groups["BEST_5PCT"].tail_load_percentile >= 0.90).mean())}
    return pd.DataFrame(rows), summary


def training_threshold_availability(labeled: pd.DataFrame, tail_load: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    available_dates = set(pd.to_datetime(tail_load.signal_date))
    rows = []
    for fold_name, start, end in R3.FOLDS:
        train, _, cutoff = R3.fold_split(labeled, sessions, start, end)
        expected = set(pd.to_datetime(train.signal_date.unique()))
        available = expected & available_dates
        rows.append({"fold": fold_name, "expected_training_tail_load_dates": len(expected), "available_authoritative_training_tail_load_dates": len(available), "missing_training_tail_load_dates": len(expected - available), "threshold_available": expected == available, "embargo_cutoff": cutoff})
    return pd.DataFrame(rows)


def print_summary(summary: dict[str, Any]) -> None:
    keys = ["A2_RISK_R5_STATUS", "A2_RISK_R5_CLASSIFICATION", "R3R_RISK_SIGNAL_HASH", "TAIL_LOAD_5D_MAE_SPEARMAN", "TAIL_LOAD_TOP_DECILE_RISK_LIFT", "POSITIVE_DIRECTION_FOLDS", "R5_TRIGGER_FREQUENCY", "R5_MEAN_EXPOSURE", "RAW_A2_RETURN", "CONSTANT_RETURN", "R3_RETURN", "R4_RETURN", "R5_RETURN", "RAW_A2_MDD", "CONSTANT_MDD", "R5_MDD", "RAW_A2_ES5", "CONSTANT_ES5", "R5_ES5", "R5_RETURN_RETENTION", "R5_MDD_REDUCTION", "R5_ES5_IMPROVEMENT", "LOSS_AVOIDED_ON_TRIGGER_DATES", "UPSIDE_SACRIFICED_ON_TRIGGER_DATES", "NET_TRIGGER_VALUE", "R5_USEFUL_ECONOMIC_FOLDS", "TRAINING_DATA_2026_COUNT", "HOLDOUT_FILE_READ_COUNT", "MODEL_FIT_COUNT_R5", "LOOKAHEAD_VIOLATION_COUNT", "NEW_RISK_R5_REPO_VIOLATION_COUNT", "NEXT_AUTHORIZED_STEP"]
    for key in keys:
        value = summary.get(key)
        if isinstance(value, float) and np.isfinite(value):
            value = f"{value:.12g}"
        print(f"{key}={value}")


def run(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"fail closed: output directory not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    selected = load_authoritative_oof()
    tail_load = aggregate_tail_load(selected)
    labeled, score_panel, daily, _, _ = R3.build_panels()
    all_outcomes = portfolio_outcomes(score_panel.signal_date.drop_duplicates(), daily)
    frame = tail_load.merge(all_outcomes, on="signal_date", validate="one_to_one")
    frame, outcome_thresholds = add_fold_severe_labels(frame, all_outcomes, pd.DatetimeIndex(daily.execution_date))
    relationships, deciles, predictive_folds, diagnostic_frame, predictive_summary = predictive_diagnostics(frame)
    captures, capture_summary = day_capture(diagnostic_frame)
    threshold_availability = training_threshold_availability(all_outcomes, tail_load, pd.DatetimeIndex(daily.execution_date))
    threshold_blocked = bool((~threshold_availability.threshold_available).any())
    if not threshold_blocked:
        raise RuntimeError("R5 threshold unexpectedly available; economic implementation is intentionally not implicit")
    guard = R3.R1.guard_audit()
    lookahead = int((selected.information_date >= selected.signal_date).sum() + (selected.train_max_target_end >= selected.embargo_cutoff).sum())
    na_fields = {key: "NA" for key in ["R5_TRIGGER_FREQUENCY", "R5_MEAN_EXPOSURE", "RAW_A2_RETURN", "CONSTANT_RETURN", "R3_RETURN", "R4_RETURN", "R5_RETURN", "RAW_A2_MDD", "CONSTANT_MDD", "R5_MDD", "RAW_A2_ES5", "CONSTANT_ES5", "R5_ES5", "R5_RETURN_RETENTION", "R5_MDD_REDUCTION", "R5_ES5_IMPROVEMENT", "LOSS_AVOIDED_ON_TRIGGER_DATES", "UPSIDE_SACRIFICED_ON_TRIGGER_DATES", "NET_TRIGGER_VALUE", "R5_USEFUL_ECONOMIC_FOLDS"]}
    summary = {"A2_RISK_R5_STATUS": "FAIL_CLOSED_MISSING_FOLD_TRAINING_R3R_TAIL_LOAD", "A2_RISK_R5_CLASSIFICATION": "E", "R3R_RISK_SIGNAL_HASH": EXPECTED_R3R_HASH, **predictive_summary, **capture_summary, **na_fields, "TRAINING_DATA_2026_COUNT": 0, "HOLDOUT_FILE_READ_COUNT": 0, "MODEL_FIT_COUNT_R5": 0, "2026_USED_FOR_RULE_SELECTION_COUNT": 0, "LOOKAHEAD_VIOLATION_COUNT": lookahead, "NEW_RISK_R5_REPO_VIOLATION_COUNT": guard["new_risk_r1_repo_violation_count"], "NEXT_AUTHORIZED_STEP": "STOP_R5_FAIL_CLOSED;REQUIRE_PRESERVED_FOLD_TRAINING_R3R_SCORES;DO_NOT_RETRAIN_R3R;DO_NOT_OPEN_2026;DO_NOT_SEARCH_ANOTHER_THRESHOLD"}
    audit = {"summary": summary, "authoritative_oof_path": str(R3R_OOF_PATH), "authoritative_oof_sha256": R3.R1.sha256_file(R3R_OOF_PATH), "portfolio_tail_load_formula": "equal-weight mean of Top20 R3R predicted_q90", "secondary_diagnostics_used_for_rule_selection_count": 0, "threshold_contract": "fold-training Q90 of portfolio_tail_load", "threshold_status": "UNAVAILABLE_MISSING_COMPLETE_FOLD_TRAINING_R3R_SCORES", "economic_simulation_count": 0, "model_fit_count_r5": 0, "risk_model_retrain_count": 0, "parameter_search_count": 0, "training_data_2026_count": 0, "holdout_file_read_count": 0, "lookahead_violation_count": lookahead, "repository_governance": guard}
    R3.R1.write_parquet(output / "r5_portfolio_tail_load_oof.parquet", diagnostic_frame)
    R3.R1.write_csv(output / "r5_predictive_relationships.csv", relationships)
    R3.R1.write_csv(output / "r5_tail_load_deciles.csv", deciles)
    R3.R1.write_csv(output / "r5_predictive_fold_metrics.csv", predictive_folds)
    R3.R1.write_csv(output / "r5_worst_best_day_capture.csv", captures)
    R3.R1.write_csv(output / "r5_outcome_threshold_folds.csv", outcome_thresholds)
    R3.R1.write_csv(output / "r5_training_threshold_availability.csv", threshold_availability)
    R3.R1.write_json(output / "r5_audit.json", audit)
    R3.R1.write_json(output / "r5_summary.json", summary)
    print_summary(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    try:
        run(args.output_dir.resolve())
        return 0
    except Exception as exc:
        print("A2_RISK_R5_STATUS=FAIL_CLOSED", file=sys.stderr)
        print("A2_RISK_R5_CLASSIFICATION=E", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
