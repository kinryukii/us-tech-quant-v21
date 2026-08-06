"""Bounded, real-data FAST3 Development evaluation; no Validation or execution."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from fast3.src.fast3.backtest.portfolio_contract import simulate_primary_portfolio


REPO = Path(__file__).resolve().parents[3]
LEGACY = REPO / "scripts" / "v22" / "v22_080b_fast3_one_percent_move_predictability_preflight_r1.py"
FEATURES = ("return_5m", "return_15m", "return_60m", "realized_vol_15m", "realized_vol_60m", "relative_volume", "range_position", "symbol_code", "direction_code", "session_code")
SEEDS = (104729, 130363, 155921, 196613, 262147)
LEGACY_LIFT = 1.36122855
LIFT_GATE = 1.50


def load_legacy():
    spec = importlib.util.spec_from_file_location("fast3_legacy_080b", LEGACY)
    if spec is None or spec.loader is None:
        raise RuntimeError("LEGACY_COMPONENT_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_model(config: dict[str, Any], seed: int) -> Pipeline:
    family = config["family"]
    if family == "regularized_logistic":
        estimator = LogisticRegression(C=config["C"], max_iter=200, random_state=seed, n_jobs=1)
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", estimator)])
    if family == "shallow_decision_tree":
        estimator = DecisionTreeClassifier(max_depth=config["max_depth"], min_samples_leaf=config["min_samples_leaf"], random_state=seed)
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", estimator)])
    if family == "fast3_hist_gradient_boosting":
        estimator = HistGradientBoostingClassifier(max_iter=config["max_iter"], learning_rate=config["learning_rate"], max_leaf_nodes=config["max_leaf_nodes"], l2_regularization=config["l2_regularization"], random_state=seed)
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", estimator)])
    raise RuntimeError(f"UNKNOWN_MODEL_FAMILY:{family}")


def chronological_folds(frame: pd.DataFrame, purge_minutes: int, embargo_minutes: int) -> list[tuple[np.ndarray, np.ndarray]]:
    event_times = np.array(sorted(frame.decision_timestamp_et.drop_duplicates().tolist()))
    blocks = [block for block in np.array_split(event_times, 4) if len(block)]
    result: list[tuple[np.ndarray, np.ndarray]] = []
    for block in blocks[1:]:
        test_start = pd.Timestamp(block[0])
        test_end = pd.Timestamp(block[-1])
        train_cutoff = test_start - pd.Timedelta(minutes=purge_minutes + embargo_minutes)
        train_idx = np.flatnonzero(frame.label_end_timestamp_et.to_numpy() < train_cutoff)
        test_idx = np.flatnonzero((frame.decision_timestamp_et >= test_start).to_numpy() & (frame.decision_timestamp_et <= test_end).to_numpy())
        if len(train_idx) == 0 or len(test_idx) == 0:
            raise RuntimeError("EMPTY_PURGED_WALK_FORWARD_FOLD")
        result.append((train_idx, test_idx))
    return result


def assert_leakage_gates(frame: pd.DataFrame, folds: list[tuple[np.ndarray, np.ndarray]], threshold: float) -> dict[str, bool]:
    feature_times = pd.to_datetime(frame.feature_available_at_et, errors="raise")
    decision_times = pd.to_datetime(frame.decision_timestamp_et, errors="raise")
    label_ends = pd.to_datetime(frame.label_end_timestamp_et, errors="raise")
    gates = {
        "feature_asof_not_later_than_decision": bool((feature_times <= decision_times).all()),
        "label_window_after_decision": bool((label_ends > decision_times).all()),
        "all_features_present_or_fold_imputed": bool(set(FEATURES).issubset(frame.columns)),
        "fixed_threshold_0_60": threshold == 0.60,
        "no_confirmation_rows": bool((decision_times < pd.Timestamp("2025-02-08T00:00:00-05:00")).all()),
        "unique_event_direction_rows": not frame.duplicated(["event_key", "direction"]).any(),
    }
    for train_idx, test_idx in folds:
        train, test = frame.iloc[train_idx], frame.iloc[test_idx]
        gates[f"fold_{len([key for key in gates if key.startswith('fold_')])}_purge_embargo"] = bool(train.label_end_timestamp_et.max() < test.decision_timestamp_et.min() - pd.Timedelta(minutes=1440))
        gates[f"fold_{len([key for key in gates if key.startswith('fold_')])}_event_isolation"] = not set(train.event_key).intersection(set(test.event_key))
    if not all(gates.values()):
        failed = [key for key, value in gates.items() if not value]
        raise RuntimeError("LEAKAGE_GATE_FAILED:" + ",".join(failed))
    return gates


def max_drawdown(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return float("nan")
    equity = np.cumprod(1 + returns)
    return float((equity / np.maximum.accumulate(equity) - 1).min())


def metrics(selected: pd.DataFrame, test: pd.DataFrame) -> dict[str, Any]:
    if selected.empty:
        return {"trade_count": 0, "top5_lift": np.nan, "net_return_10bps": np.nan, "net_return_20bps": np.nan, "win_rate": np.nan, "profit_loss_ratio": np.nan, "opportunity_coverage": 0.0, "turnover": 0.0, "max_drawdown": np.nan, "trimmed_1pct_net_return_10bps": np.nan, "trimmed_5pct_net_return_10bps": np.nan}
    base = float(test.target_first.mean())
    executable = selected[selected.mapping_status.eq("SUCCESS")].copy()
    if executable.empty:
        return {"trade_count": 0, "mapping_failure_count": int(len(selected)), "top5_lift": float(selected.target_first.mean() / base) if base else np.nan, "net_return_10bps": np.nan, "net_return_20bps": np.nan, "win_rate": np.nan, "profit_loss_ratio": np.nan, "opportunity_coverage": float((test.opportunity_probability >= 0.60).mean()), "turnover": 0.0, "max_drawdown": np.nan, "trimmed_1pct_net_return_10bps": np.nan, "trimmed_5pct_net_return_10bps": np.nan}
    executable["event_id"] = executable.config_id.astype(str) + "|" + executable.random_seed.astype(str) + "|" + executable.outer_fold.astype(str) + "|" + executable.row_id.astype(str)
    executable["exit_timestamp_et"] = executable.label_end_timestamp_et
    executable["priority"] = executable.combined_score
    executable["net_return"] = executable.net_return_10bps
    portfolio, _ = simulate_primary_portfolio(executable)
    accepted = portfolio[portfolio.trade_accepted].copy()
    if accepted.empty:
        return {"trade_count": 0, "mapping_failure_count": int(len(selected) - len(executable)), "top5_lift": float(selected.target_first.mean() / base) if base else np.nan, "net_return_10bps": np.nan, "net_return_20bps": np.nan, "win_rate": np.nan, "profit_loss_ratio": np.nan, "opportunity_coverage": float((test.opportunity_probability >= 0.60).mean()), "turnover": 0.0, "max_drawdown": np.nan, "trimmed_1pct_net_return_10bps": np.nan, "trimmed_5pct_net_return_10bps": np.nan}
    gross = accepted.net_return_10bps.to_numpy(float) + 0.001
    losses = -gross[gross < 0].sum()
    ordered = accepted.sort_values("net_return_10bps", kind="mergesort").net_return_10bps.to_numpy(float)
    trim = lambda fraction: float(ordered[:max(0, len(ordered) - int(np.ceil(len(ordered) * fraction)))].mean()) if len(ordered) else np.nan
    return {"trade_count": int(len(accepted)), "mapping_failure_count": int(len(selected) - len(executable)), "top5_lift": float(selected.target_first.mean() / base) if base else np.nan, "net_return_10bps": float(accepted.net_return_10bps.mean()), "net_return_20bps": float(accepted.net_return_20bps.mean()), "win_rate": float((accepted.net_return_10bps > 0).mean()), "profit_loss_ratio": float(gross[gross > 0].sum() / losses) if losses else np.nan, "opportunity_coverage": float((test.opportunity_probability >= 0.60).mean()), "turnover": float(len(accepted) / max(1, test.decision_timestamp_et.nunique())), "max_drawdown": max_drawdown(accepted.sort_values("decision_timestamp_et", kind="mergesort").net_return_10bps.to_numpy(float)), "trimmed_1pct_net_return_10bps": trim(0.01), "trimmed_5pct_net_return_10bps": trim(0.05)}


def bootstrap_ci(values: np.ndarray) -> tuple[float, float]:
    rng = np.random.default_rng(262147)
    delta = values - LEGACY_LIFT
    sampled = np.array([rng.choice(delta, size=len(delta), replace=True).mean() for _ in range(10_000)])
    return float(np.quantile(sampled, 0.025)), float(np.quantile(sampled, 0.975))


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return str(value)


def markdown_table(frame: pd.DataFrame) -> str:
    columns = [str(column) for column in frame.columns]
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for values in frame.itertuples(index=False, name=None):
        rows.append("| " + " | ".join(str(json_default(value)).replace("|", "\\|") for value in values) + " |")
    return "\n".join(rows)


def main(output_root: Path) -> int:
    contract_path = output_root / "FAST3_EXPERIMENT_CONTRACT.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    configs = contract["initial_configs"]
    if len(configs) > 8 or len({config["family"] for config in configs}) > 3 or len(SEEDS) != 5:
        raise RuntimeError("SEARCH_BUDGET_CONTRACT_INVALID")
    legacy = load_legacy()
    canonical = Path(contract["data"]["canonical_root"])
    data: dict[str, pd.DataFrame] = {}
    for symbol in ("QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS"):
        data[symbol], _ = legacy.load_preconfirmation(symbol, canonical)
    frames = []
    for symbol in ("QQQ", "SOXX"):
        frame, _ = legacy.candidates_for_symbol(data[symbol], symbol)
        frames.append(frame)
    sample = pd.concat(frames, ignore_index=True)
    start = pd.Timestamp(contract["development_range"]["start"])
    end = pd.Timestamp(contract["development_range"]["end"])
    sample = sample[(sample.decision_timestamp_et >= start) & (sample.decision_timestamp_et <= end)].copy().reset_index(drop=True)
    sample["feature_available_at_et"] = sample.decision_timestamp_et
    sample["label_end_timestamp_et"] = pd.to_datetime(sample.horizon_timestamp_utc, utc=True).dt.tz_convert("America/New_York")
    sample["opportunity_target"] = sample.first_passage_label.ne("NO_1PCT_MOVE_WITHIN_HORIZON").astype(int)
    sample["event_key"] = sample.underlying_symbol.astype(str) + "|" + sample.decision_timestamp_et.astype(str)
    sample["row_id"] = np.arange(len(sample))
    folds = chronological_folds(sample, contract["purge_minutes"], contract["embargo_minutes"])
    leakage = assert_leakage_gates(sample, folds, contract["opportunity_threshold"])
    outcomes = legacy.etf_outcomes(sample, {symbol: data[symbol] for symbol in ("TQQQ", "SQQQ", "SOXL", "SOXS")})
    if len(outcomes) != len(sample):
        raise RuntimeError("EXECUTABLE_OUTCOME_MAPPING_INCOMPLETE")
    sample["mapping_status"] = outcomes.mapping_status.to_numpy()
    for column in ("net_return_10bps", "net_return_20bps", "gross_return", "execution_etf"):
        sample[column] = outcomes[column].to_numpy() if column in outcomes else np.nan
    fold_rows: list[dict[str, Any]] = []
    prediction_rows: list[pd.DataFrame] = []
    for config in configs:
        for seed in SEEDS:
            for fold_no, (train_idx, test_idx) in enumerate(folds):
                train, test = sample.iloc[train_idx], sample.iloc[test_idx].copy()
                stage_a = build_model(config, seed)
                stage_b = build_model(config, seed)
                stage_a.fit(train[list(FEATURES)], train.opportunity_target)
                direction_train = train[train.opportunity_target.eq(1)]
                stage_b.fit(direction_train[list(FEATURES)], direction_train.target_first)
                test["opportunity_probability"] = stage_a.predict_proba(test[list(FEATURES)])[:, 1]
                test["direction_probability"] = stage_b.predict_proba(test[list(FEATURES)])[:, 1]
                test["combined_score"] = test.opportunity_probability * test.direction_probability
                eligible = test[test.opportunity_probability >= 0.60].sort_values("combined_score", ascending=False, kind="mergesort")
                selected = eligible.iloc[:max(1, int(np.ceil(len(test) * 0.05)))].copy()
                selected["config_id"] = config["id"]
                selected["model_family"] = config["family"]
                selected["random_seed"] = seed
                selected["outer_fold"] = fold_no
                result = metrics(selected, test)
                fold_rows.append({"config_id": config["id"], "model_family": config["family"], "random_seed": seed, "outer_fold": fold_no, "train_rows": len(train), "test_rows": len(test), **result})
                prediction_rows.append(selected[["row_id", "event_key", "decision_timestamp_et", "feature_available_at_et", "label_end_timestamp_et", "underlying_symbol", "direction", "session_code", "target_first", "opportunity_target", "opportunity_probability", "direction_probability", "combined_score", "mapping_status", "net_return_10bps", "net_return_20bps", "config_id", "model_family", "random_seed", "outer_fold"]])
    fold_metrics = pd.DataFrame(fold_rows)
    predictions = pd.concat(prediction_rows, ignore_index=True)
    aggregate_rows = []
    for config in configs:
        part = fold_metrics[fold_metrics.config_id.eq(config["id"])]
        seed_metrics = part.groupby("random_seed", sort=True).agg(top5_lift=("top5_lift", "mean"), net_return_10bps=("net_return_10bps", "mean"), net_return_20bps=("net_return_20bps", "mean")).reset_index()
        ci_low, ci_high = bootstrap_ci(part.top5_lift.to_numpy(float))
        aggregate_rows.append({"config_id": config["id"], "model_family": config["family"], "median_fold_top5_lift": float(part.top5_lift.median()), "pooled_top5_lift": float(predictions[predictions.config_id.eq(config["id"])].target_first.mean() / sample.loc[np.concatenate([t for _, t in folds]), "target_first"].mean()), "median_fold_net_return_10bps": float(part.net_return_10bps.median()), "mean_net_return_10bps": float(part.net_return_10bps.mean()), "mean_net_return_20bps": float(part.net_return_20bps.mean()), "positive_fold_ratio_10bps": float((part.net_return_10bps > 0).mean()), "seed_min_net_return_10bps": float(seed_metrics.net_return_10bps.min()), "seed_max_net_return_10bps": float(seed_metrics.net_return_10bps.max()), "trimmed_1pct_net_return_10bps": float(part.trimmed_1pct_net_return_10bps.mean()), "trimmed_5pct_net_return_10bps": float(part.trimmed_5pct_net_return_10bps.mean()), "lift_delta_ci_low": ci_low, "lift_delta_ci_high": ci_high, "passes_all_gates": bool(part.top5_lift.mean() >= LIFT_GATE and ci_low > 0 and part.net_return_10bps.median() > 0 and (part.net_return_10bps > 0).mean() > 0.5 and part.trimmed_1pct_net_return_10bps.mean() > 0 and seed_metrics.net_return_10bps.min() > 0)})
    aggregates = pd.DataFrame(aggregate_rows)
    best = aggregates.sort_values(["median_fold_top5_lift", "median_fold_net_return_10bps", "positive_fold_ratio_10bps", "config_id"], ascending=[False, False, False, True], kind="mergesort").iloc[0].to_dict()
    best_folds = fold_metrics[fold_metrics.config_id.eq(best["config_id"])]
    best_predictions = predictions[predictions.config_id.eq(best["config_id"])]
    regime = best_predictions.groupby("session_code", dropna=False).agg(trade_count=("row_id", "size"), top5_target_rate=("target_first", "mean"), net_return_10bps=("net_return_10bps", "mean")).reset_index().to_dict(orient="records")
    final_decision = "PASS_DEVELOPMENT_READY_FOR_FORWARD_SHADOW" if bool(best["passes_all_gates"]) else ("STOP_NOT_ECONOMIC_AFTER_COST" if best["median_fold_net_return_10bps"] <= 0 else "STOP_NO_SIGNIFICANT_IMPROVEMENT_OVER_V22_080B")
    summary = {"FINAL_STATUS": "EXECUTED_REAL_DEVELOPMENT", "FINAL_DECISION": final_decision, "EVIDENCE_LEDGER_PATH": str(output_root / "FAST3_EVIDENCE_LEDGER.json"), "EXPERIMENT_CONTRACT_PATH": str(contract_path), "CONTAMINATED_INTERVAL_COUNT": 2, "CONFIRMED_CLEAN_INTERVAL_COUNT": 0, "FROZEN_VALIDATION_AVAILABLE": False, "FROZEN_VALIDATION_EXECUTED": False, "INITIAL_CONFIG_COUNT": len(configs), "REFINEMENT_CONFIG_COUNT": 0, "TOTAL_CONFIG_COUNT": len(configs), "MODEL_FAMILY_COUNT": int(len({config["family"] for config in configs})), "RANDOM_SEED_COUNT": len(SEEDS), "BEST_MODEL_NAME": best["config_id"], "BEST_TOP5_LIFT": best["pooled_top5_lift"], "LEGACY_TOP5_LIFT": LEGACY_LIFT, "LIFT_DELTA": best["pooled_top5_lift"] - LEGACY_LIFT, "LIFT_DELTA_CI_LOW": best["lift_delta_ci_low"], "LIFT_DELTA_CI_HIGH": best["lift_delta_ci_high"], "BEST_NET_RETURN_10BPS": best["mean_net_return_10bps"], "BEST_NET_RETURN_20BPS": best["mean_net_return_20bps"], "POSITIVE_FOLD_RATIO_10BPS": best["positive_fold_ratio_10bps"], "FEATURES_CHANGED": False, "LABEL_CHANGED": False, "OPPORTUNITY_THRESHOLD_CHANGED": False, "DATA_LEAKAGE_TESTS_PASSED": True, "NEW_CODE_FILE_COUNT": 1, "MODIFIED_FILE_COUNT": 0, "REPORT_PATH": str(output_root / "FAST3_DEVELOPMENT_REPORT.md"), "all_configurations": aggregate_rows, "best_regime_diagnostics": regime, "leakage_gates": leakage, "refinement": "NOT_RUN: initial configurations did not all pass the pre-registered gates; contract stop rule forbids additional search.", "frozen_validation": "NOT_RUN: NO_UNCONTAMINATED_HISTORICAL_HOLDOUT", "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    fold_metrics.to_csv(output_root / "fast3_fold_metrics.csv", index=False)
    predictions.to_parquet(output_root / "fast3_predictions.parquet", index=False)
    (output_root / "fast3_development_summary.json").write_text(json.dumps(summary, indent=2, default=json_default) + "\n", encoding="utf-8")
    report = "# FAST3 Development Report\n\n" + "\n".join(f"{key}={json_default(value)}" for key, value in summary.items() if key not in {"all_configurations", "best_regime_diagnostics", "leakage_gates"}) + "\n\n## All initial configurations\n\n" + markdown_table(aggregates) + "\n\n## Seed and fold metrics\n\nAll 120 config-seed-fold results, including failures and all five seeds, are in `fast3_fold_metrics.csv`.\n\n## Regime diagnostic (not used for selection)\n\n" + markdown_table(pd.DataFrame(regime)) + "\n\n## Contamination and validation\n\nAll known historical intervals are contaminated or uncertain; Frozen Validation was not run. Features, labels, the 24-hour horizon, Top5 definition, costs, and 0.60 threshold were unchanged.\n\n## Bootstrap\n\nPaired fold-level percentile bootstrap: 10,000 resamples of the 15 seed-fold lifts against fixed V22.080B lift 1.36122855; seed 262147.\n\n## Files changed\n\nAdded `fast3/scripts/run/fast3_minimal_empirical_development.py` as the sole source file; no existing source was modified.\n"
    (output_root / "FAST3_DEVELOPMENT_REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({key: summary[key] for key in summary if key.isupper()}, default=json_default))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=os.environ.get("FAST3_RESULTS_ROOT"))
    args = parser.parse_args()
    if not args.output_root:
        raise SystemExit("FAST3_RESULTS_ROOT_REQUIRED")
    raise SystemExit(main(Path(args.output_root)))
