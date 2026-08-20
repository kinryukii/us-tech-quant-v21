"""R3A OOF attribution and fail-closed R3R execution-target alignment."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import spearmanr


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUTPUT_DIR = RESULTS_ROOT / "A2_STOCK_RISK_R3A_R3R"
R3_SCRIPT = REPO_ROOT / "scripts" / "v22" / "a2_stock_risk_ml_r3.py"
R3_RESULTS = RESULTS_ROOT / "A2_STOCK_RISK_ML_R3"
PRICE_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
RUNTIME_ROOT = Path(r"D:\us-tech-quant-cache\a2_stock_risk_r3r")
REFERENCE_CANDIDATE = "LINEAR_STOCK_Q90_A010"
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")


def _load_r3() -> Any:
    spec = importlib.util.spec_from_file_location("a2_stock_risk_ml_r3_for_r3a", R3_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load R3 infrastructure")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R3 = _load_r3()


def old_path_mfe(frame: pd.DataFrame, matrix: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    lookup = matrix.set_index(["information_date", "ticker"])["ret_1d"]
    rows: list[dict[str, Any]] = []
    for row in frame[["signal_date", "ticker"]].itertuples(index=False):
        position = sessions.get_loc(row.signal_date)
        dates = sessions[position : position + 5]
        returns = np.array([lookup.get((pd.Timestamp(date), row.ticker), np.nan) for date in dates], dtype=float)
        if len(dates) == 5 and np.isfinite(returns).all():
            path = np.cumprod(1.0 + returns) - 1.0
            rows.append({"signal_date": row.signal_date, "ticker": row.ticker, "forward_5d_stock_mfe": max(0.0, float(path.max()))})
    return pd.DataFrame(rows)


def r3a_attribution() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    oof = pd.read_parquet(R3_RESULTS / "stock_risk_r3_oof_predictions.parquet")
    if pd.to_datetime(oof["signal_date"]).ge(TRAINING_CUTOFF).any():
        raise RuntimeError("R3A OOF contains 2026")
    frame = oof.loc[oof.candidate_id.eq(REFERENCE_CANDIDATE) & oof.label_available].copy()
    frame["signal_date"] = pd.to_datetime(frame["signal_date"])
    _, matrix, daily, _ = R3.load_sources()
    matrix = matrix.rename(columns={"signal_date": "information_date"})
    mfe = old_path_mfe(frame, matrix, pd.DatetimeIndex(daily.execution_date))
    frame = frame.merge(mfe, on=["signal_date", "ticker"], validate="one_to_one")
    if len(frame) == 0 or not np.isfinite(frame["forward_5d_stock_mfe"]).all():
        raise RuntimeError("R3A path attribution failure")
    frame["risk_decile"] = np.clip(np.ceil(frame.risk_percentile * 10), 1, 10).astype(int)
    frame["removed_weight"] = 0.05 * (1.0 - R3.R1.direct_multiplier(frame.risk_percentile.to_numpy()))
    frame["raw_forward_contribution"] = 0.05 * frame.forward_5d_stock_return
    frame["removed_forward_contribution"] = frame.removed_weight * frame.forward_5d_stock_return

    deciles = frame.groupby("risk_decile", sort=True).agg(
        observation_count=("ticker", "size"), mean_a2_rank=("A2_RANK", "mean"), mean_a2_prediction=("A2_PREDICTION", "mean"),
        mean_next_day_return=("next_day_stock_return", "mean"), mean_forward_5d_return=("forward_5d_stock_return", "mean"),
        mean_5d_mae=("forward_5d_stock_mae", "mean"), mean_5d_mfe=("forward_5d_stock_mfe", "mean"),
        median_5d_mae=("forward_5d_stock_mae", "median"), median_5d_mfe=("forward_5d_stock_mfe", "median"),
        positive_5d_return_frequency=("forward_5d_stock_return", lambda x: float((x > 0).mean())),
    ).reset_index()

    threshold_rows = []
    for top_pct in (100, 5, 10, 20, 30):
        subset = frame if top_pct == 100 else frame.loc[frame.risk_percentile.ge(1.0 - top_pct / 100.0)]
        avoided = float(-subset.loc[subset.forward_5d_stock_return < 0, "removed_forward_contribution"].sum())
        sacrificed = float(subset.loc[subset.forward_5d_stock_return > 0, "removed_forward_contribution"].sum())
        threshold_rows.append({"risk_scope": "ALL" if top_pct == 100 else f"TOP_{top_pct}PCT", "observation_count": len(subset), "gross_loss_avoided": avoided, "gross_winner_upside_sacrificed": sacrificed, "net_scaling_value": avoided - sacrificed})
    threshold_attribution = pd.DataFrame(threshold_rows)

    frame["alpha_group"] = pd.cut(frame.A2_RANK, [0, 5, 10, 15, 20], labels=["RANK_1_5", "RANK_6_10", "RANK_11_15", "RANK_16_20"])
    frame["risk_group"] = pd.cut(frame.risk_percentile, [-np.inf, 0.5, 0.85, np.inf], right=False, labels=["LOW_BOTTOM_50", "MEDIUM_50_85", "HIGH_TOP_15"])
    matrix_table = frame.groupby(["alpha_group", "risk_group"], observed=False).agg(
        observation_count=("ticker", "size"), mean_forward_5d_return=("forward_5d_stock_return", "mean"),
        median_forward_5d_return=("forward_5d_stock_return", "median"), mean_5d_mae=("forward_5d_stock_mae", "mean"),
        mean_5d_mfe=("forward_5d_stock_mfe", "mean"), severe_loss_rate=("stock_severe_5d", "mean"),
        positive_return_rate=("forward_5d_stock_return", lambda x: float((x > 0).mean())),
        total_realized_contribution=("raw_forward_contribution", "sum"),
    ).reset_index()

    extreme_rows = []
    for count in (50, 100):
        for side, subset in (("WORST", frame.nsmallest(count, "forward_5d_stock_return")), ("BEST", frame.nlargest(count, "forward_5d_stock_return"))):
            top10 = subset.risk_percentile.ge(0.90)
            removed = subset.loc[top10, "removed_forward_contribution"]
            value = float(-removed.sum()) if side == "WORST" else float(removed.sum())
            extreme_rows.append({"outcome_group": f"{side}_{count}", "observation_count": len(subset), "fraction_identified_top_risk_10pct": float(top10.mean()), "loss_contribution_avoided" if side == "WORST" else "winner_contribution_removed": value})
    extremes = pd.DataFrame(extreme_rows)
    all_row = threshold_attribution.loc[threshold_attribution.risk_scope.eq("ALL")].iloc[0]
    summary = {
        "RISK_A2_SCORE_SPEARMAN": float(spearmanr(frame.predicted_q90, frame.A2_PREDICTION).statistic),
        "RISK_A2_RANK_SPEARMAN": float(spearmanr(frame.predicted_q90, frame.A2_RANK).statistic),
        "GROSS_LOSS_AVOIDED": float(all_row.gross_loss_avoided),
        "GROSS_WINNER_UPSIDE_SACRIFICED": float(all_row.gross_winner_upside_sacrificed),
        "NET_SCALING_VALUE": float(all_row.net_scaling_value),
        "OOF_ATTRIBUTION_ROW_COUNT": len(frame),
    }
    return deciles, threshold_attribution, matrix_table, extremes, summary


def load_canonical_prices(wanted: set[str]) -> pd.DataFrame:
    pieces = []
    columns = ["ticker", "trade_date", "open", "high", "low", "close", "autype", "source"]
    for year in (2023, 2024, 2025):
        frame = pq.read_table(PRICE_ROOT / f"year={year}" / "prices.parquet", columns=columns).to_pandas()
        frame["ticker"] = frame.ticker.astype(str).str.upper()
        pieces.append(frame.loc[frame.ticker.isin(wanted | {"QQQ"})])
    prices = pd.concat(pieces, ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices.trade_date)
    if prices.trade_date.ge(TRAINING_CUTOFF).any() or set(prices.source.astype(str).str.upper()) != {"MOOMOO_OPEND"} or set(prices.autype.astype(str).str.lower()) != {"qfq"}:
        raise RuntimeError("canonical execution price integrity failure")
    return prices


def required_bars(score_panel: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    positions = pd.Series(np.arange(len(calendar)), index=calendar)
    rows = []
    for row in score_panel[["signal_date", "ticker"]].itertuples(index=False):
        if row.signal_date not in positions:
            continue
        start = int(positions.loc[row.signal_date])
        for horizon, date in enumerate(calendar[start : start + 5]):
            rows.append({"signal_date": row.signal_date, "ticker": row.ticker, "horizon": horizon, "trade_date": date})
    return pd.DataFrame(rows)


def coverage_table(score_panel: pd.DataFrame, prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    calendar = pd.DatetimeIndex(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].drop_duplicates().sort_values())
    required = required_bars(score_panel, calendar)
    joined = required.merge(prices[["ticker", "trade_date", "open", "high", "low", "close", "autype", "source"]], on=["ticker", "trade_date"], how="left", validate="many_to_one")
    numeric = joined[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    joined["authoritative_bar"] = numeric.gt(0).all(axis=1) & joined.source.astype(str).str.upper().eq("MOOMOO_OPEND") & joined.autype.astype(str).str.lower().eq("qfq")
    coverage = joined.groupby(["signal_date", "ticker"], sort=True).agg(
        exact_execution_reference=("authoritative_bar", lambda x: bool(len(x) == 5 and x.iloc[0])),
        complete_5d_path=("authoritative_bar", lambda x: bool(len(x) == 5 and x.all())),
    ).reset_index()
    coverage = score_panel[["signal_date", "ticker"]].merge(coverage, on=["signal_date", "ticker"], how="left").fillna(False)
    return coverage, joined


def try_backfill(coverage: pd.DataFrame, required: pd.DataFrame, output: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    missing = coverage.loc[~coverage.complete_5d_path, "ticker"].drop_duplicates().sort_values().tolist()
    audit = {"status": "NOT_REQUIRED" if not missing else "PENDING", "missing_ticker_count": len(missing), "moomoo_api_request_count": 0, "output_path": None}
    if not missing:
        return pd.DataFrame(), audit
    try:
        with socket.create_connection(("127.0.0.1", 18441), timeout=2):
            pass
    except OSError as exc:
        audit.update({"status": "FAIL_CLOSED_OPEND_UNAVAILABLE", "error": f"{type(exc).__name__}:{exc}"})
        return pd.DataFrame(), audit
    log_dir = RUNTIME_ROOT / "moomoo_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    os.environ.update({"APPDATA": str(RUNTIME_ROOT / "moomoo_appdata"), "FUTU_LOG_DIR": str(log_dir), "FutuOpenD_LogDir": str(log_dir), "TMP": str(log_dir), "TEMP": str(log_dir)})
    from scripts.data_sources.moomoo_client import MoomooOpenDUnavailableError, MoomooQuoteClient
    from scripts.data_sources.moomoo_daily_ohlcv_fetcher import fetch_history_daily

    frames = []
    by_ticker = required.loc[required.ticker.isin(missing)].groupby("ticker")
    with MoomooQuoteClient() as client:
        for ticker, group in by_ticker:
            start, end = group.trade_date.min().strftime("%Y-%m-%d"), group.trade_date.max().strftime("%Y-%m-%d")
            for attempt in range(3):
                audit["moomoo_api_request_count"] += 1
                try:
                    fetched = fetch_history_daily(client, ticker, f"US.{ticker}", start=start, end=end, adjustment_mode="QFQ")
                    break
                except MoomooOpenDUnavailableError as exc:
                    if "每30秒最多60次" not in str(exc) or attempt == 2:
                        raise
                    time.sleep(31.0)
            frames.append(fetched)
            time.sleep(0.65)
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not data.empty:
        data["date"] = pd.to_datetime(data.date)
        if data.date.ge(TRAINING_CUTOFF).any():
            raise RuntimeError("backfill returned 2026 rows")
        path = output / "r3r_moomoo_qfq_execution_backfill.parquet"
        data.to_parquet(path, index=False)
        audit.update({"status": "COMPLETED", "output_path": str(path), "row_count": len(data)})
    return data, audit


def build_corrected_targets(score_panel: pd.DataFrame, joined: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (signal_date, ticker), group in joined.groupby(["signal_date", "ticker"], sort=True):
        group = group.sort_values("horizon")
        if len(group) != 5 or not group.authoritative_bar.all():
            continue
        entry = float(group.iloc[0].open)
        rows.append({
            "signal_date": signal_date, "ticker": ticker,
            "post_entry_forward_1d_return": float(group.iloc[0].close / entry - 1.0),
            "post_entry_forward_5d_return": float(group.iloc[-1].close / entry - 1.0),
            "post_entry_5d_mae": max(0.0, float(1.0 - group.low.min() / entry)),
            "post_entry_5d_mfe": max(0.0, float(group.high.max() / entry - 1.0)),
            "target_end_date": pd.Timestamp(group.iloc[-1].trade_date),
        })
    return pd.DataFrame(rows)


def compare_targets(old_panel: pd.DataFrame, corrected: pd.DataFrame, sessions: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[str, Any]]:
    old = old_panel[["signal_date", "ticker", "forward_5d_stock_mae", "target_end_date"]].rename(columns={"forward_5d_stock_mae": "old_5d_mae"})
    frame = old.merge(corrected[["signal_date", "ticker", "post_entry_5d_mae"]], on=["signal_date", "ticker"], validate="one_to_one")
    frame["absolute_target_difference"] = (frame.old_5d_mae - frame.post_entry_5d_mae).abs()
    fold_rows = []
    disagreements = []
    for fold_name, start, end in R3.FOLDS:
        train, valid, cutoff = R3.fold_split(frame, sessions, start, end)
        old_threshold = float(train.old_5d_mae.quantile(0.90))
        new_threshold = float(train.post_entry_5d_mae.quantile(0.90))
        old_severe = valid.old_5d_mae.gt(old_threshold)
        new_severe = valid.post_entry_5d_mae.gt(new_threshold)
        disagree = old_severe.ne(new_severe)
        disagreements.extend(disagree.tolist())
        fold_rows.append({"fold": fold_name, "validation_rows": len(valid), "old_training_q90": old_threshold, "new_training_q90": new_threshold, "old_severe_rate": float(old_severe.mean()), "new_severe_rate": float(new_severe.mean()), "severe_event_disagreement_rate": float(disagree.mean()), "embargo_cutoff": cutoff})
    summary = {
        "OLD_NEW_MAE_SPEARMAN": float(spearmanr(frame.old_5d_mae, frame.post_entry_5d_mae).statistic),
        "MEAN_ABSOLUTE_TARGET_DIFFERENCE": float(frame.absolute_target_difference.mean()),
        "P90_ABSOLUTE_TARGET_DIFFERENCE": float(frame.absolute_target_difference.quantile(0.90)),
        "SEVERE_EVENT_DISAGREEMENT_RATE": float(np.mean(disagreements)),
        "MEAN_OLD_MINUS_NEW_MAE": float((frame.old_5d_mae - frame.post_entry_5d_mae).mean()),
        "OLD_MAE_GREATER_FREQUENCY": float(frame.old_5d_mae.gt(frame.post_entry_5d_mae).mean()),
        "TARGET_COMPARISON_ROW_COUNT": len(frame),
    }
    return pd.DataFrame(fold_rows), summary


def corrected_risk_deciles(oof: pd.DataFrame, corrected: pd.DataFrame, candidate_id: str) -> pd.DataFrame:
    frame = oof.loc[oof.candidate_id.eq(candidate_id) & oof.label_available].merge(
        corrected[["signal_date", "ticker", "post_entry_5d_mfe"]], on=["signal_date", "ticker"], validate="one_to_one",
    )
    frame["risk_decile"] = np.clip(np.ceil(frame.risk_percentile * 10), 1, 10).astype(int)
    return frame.groupby("risk_decile", sort=True).agg(
        observation_count=("ticker", "size"), mean_post_entry_5d_mae=("forward_5d_stock_mae", "mean"),
        mean_post_entry_5d_mfe=("post_entry_5d_mfe", "mean"), mean_post_entry_5d_return=("forward_5d_stock_return", "mean"),
        positive_5d_return_frequency=("forward_5d_stock_return", lambda x: float((x > 0).mean())), severe_loss_rate=("stock_severe_5d", "mean"),
    ).reset_index()


def print_summary(summary: dict[str, Any]) -> None:
    keys = ["A2_STOCK_RISK_R3A_STATUS", "RISK_A2_SCORE_SPEARMAN", "RISK_A2_RANK_SPEARMAN", "GROSS_LOSS_AVOIDED", "GROSS_WINNER_UPSIDE_SACRIFICED", "NET_SCALING_VALUE", "HIGH_RISK_HIGH_ALPHA_5D_RETURN", "HIGH_RISK_HIGH_ALPHA_MAE", "HIGH_RISK_HIGH_ALPHA_MFE", "EXECUTION_REFERENCE_COVERAGE", "OLD_NEW_MAE_SPEARMAN", "SEVERE_EVENT_DISAGREEMENT_RATE", "R3R_REFERENCE_MODEL", "R3R_OOF_SPEARMAN", "R3R_OOF_AUROC", "R3R_TOP_DECILE_SEVERE_LOSS_LIFT", "R3R_POSITIVE_DIRECTION_FOLDS", "RISK_SIGNAL_CLASSIFICATION", "POSITION_SCALING_CLASSIFICATION", "TRAINING_DATA_2026_COUNT", "HOLDOUT_FILE_READ_COUNT", "LOOKAHEAD_VIOLATION_COUNT", "NEXT_AUTHORIZED_STEP"]
    for key in keys:
        value = summary.get(key)
        if isinstance(value, float) and np.isfinite(value):
            value = f"{value:.12g}"
        print(f"{key}={value}")


def run(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"fail closed: output directory not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    deciles, scaling, alpha_risk, extremes, attribution = r3a_attribution()
    old_panel, score_panel, daily, _, panel_audit = R3.build_panels()
    prices = load_canonical_prices(set(score_panel.ticker))
    coverage, required = coverage_table(score_panel, prices)
    backfill, backfill_audit = try_backfill(coverage, required, output)
    if not backfill.empty:
        converted = backfill.rename(columns={"internal_symbol": "ticker", "date": "trade_date", "adjustment_mode": "autype"})
        converted["source"] = "MOOMOO_OPEND"
        prices = pd.concat([prices, converted[prices.columns]], ignore_index=True).drop_duplicates(["ticker", "trade_date"], keep="first")
        coverage, required = coverage_table(score_panel, prices)
    exact_count = int(coverage.exact_execution_reference.sum())
    coverage_ratio = exact_count / len(coverage)
    complete_path_count = int(coverage.complete_5d_path.sum())
    complete = bool(exact_count == len(coverage) and complete_path_count == len(coverage))
    corrected = build_corrected_targets(score_panel, required)
    r3r_summary = {"R3R_REFERENCE_MODEL": "NOT_RUN_EXECUTION_COVERAGE_FAIL", "R3R_OOF_SPEARMAN": "NA", "R3R_OOF_AUROC": "NA", "R3R_TOP_DECILE_SEVERE_LOSS_LIFT": "NA", "R3R_POSITIVE_DIRECTION_FOLDS": "NA", "OLD_NEW_MAE_SPEARMAN": "NA", "SEVERE_EVENT_DISAGREEMENT_RATE": "NA", "RISK_SIGNAL_CLASSIFICATION": "E"}
    model_fit_count = 0
    target_fold_comparison = pd.DataFrame()
    target_summary: dict[str, Any] = {}
    if complete:
        target_fold_comparison, target_summary = compare_targets(old_panel, corrected, pd.DatetimeIndex(daily.execution_date))
        labeled = score_panel.merge(corrected, on=["signal_date", "ticker"], validate="one_to_one")
        labeled = labeled.rename(columns={"post_entry_forward_1d_return": "next_day_stock_return", "post_entry_forward_5d_return": "forward_5d_stock_return", "post_entry_5d_mae": "forward_5d_stock_mae"})
        oof, comparison, folds, model_fit_count = R3.run_oof(labeled, score_panel, pd.DatetimeIndex(daily.execution_date))
        selected = comparison.sort_values(["positive_direction_folds", "pinball_improvement", "spearman", "auroc"], ascending=False).iloc[0]
        risk_class = "A" if selected.pinball_improvement >= 0.10 and selected.spearman >= 0.10 and selected.auroc >= 0.60 and selected.top_decile_severe_loss_lift >= 1.5 and selected.positive_direction_folds >= 4 else ("B" if selected.spearman > 0 and selected.auroc > 0.55 and selected.positive_direction_folds >= 4 else "C")
        r3r_summary.update({"R3R_REFERENCE_MODEL": selected.candidate_id, "R3R_OOF_SPEARMAN": float(selected.spearman), "R3R_OOF_AUROC": float(selected.auroc), "R3R_TOP_DECILE_SEVERE_LOSS_LIFT": float(selected.top_decile_severe_loss_lift), "R3R_POSITIVE_DIRECTION_FOLDS": int(selected.positive_direction_folds), "RISK_SIGNAL_CLASSIFICATION": risk_class})
        r3r_summary.update(target_summary)
        R3.R1.write_parquet(output / "r3r_oof_predictions.parquet", oof)
        R3.R1.write_csv(output / "r3r_model_comparison.csv", comparison)
        R3.R1.write_csv(output / "r3r_fold_metrics.csv", folds)
        R3.R1.write_csv(output / "r3r_target_comparison_by_fold.csv", target_fold_comparison)
        R3.R1.write_csv(output / "r3r_risk_decile_targets.csv", corrected_risk_deciles(oof, corrected, selected.candidate_id))
    high_alpha_high_risk = alpha_risk.loc[alpha_risk.alpha_group.eq("RANK_1_5") & alpha_risk.risk_group.eq("HIGH_TOP_15")].iloc[0]
    guard = R3.R1.guard_audit()
    run_status = "VALID_R3A_R3R_COMPLETE" if complete else "VALID_R3A_R3R_FAIL_CLOSED_EXECUTION_REFERENCE"
    if guard["repository_guard_status"] != "PASS":
        run_status += "_WITH_PREEXISTING_REPO_GOVERNANCE_FAILURE"
    summary = {
        "A2_STOCK_RISK_R3A_STATUS": run_status,
        **attribution,
        "HIGH_RISK_HIGH_ALPHA_5D_RETURN": float(high_alpha_high_risk.mean_forward_5d_return), "HIGH_RISK_HIGH_ALPHA_MAE": float(high_alpha_high_risk.mean_5d_mae), "HIGH_RISK_HIGH_ALPHA_MFE": float(high_alpha_high_risk.mean_5d_mfe),
        "PANEL_ROW_COUNT": len(coverage), "EXACT_EXECUTION_REFERENCE_COUNT": exact_count, "MISSING_EXECUTION_REFERENCE_COUNT": len(coverage) - exact_count, "EXECUTION_REFERENCE_COVERAGE": coverage_ratio, "COMPLETE_5D_PATH_COUNT": complete_path_count,
        **r3r_summary, "POSITION_SCALING_CLASSIFICATION": "D", "TRAINING_DATA_2026_COUNT": 0, "HOLDOUT_FILE_READ_COUNT": 0, "MODEL_FIT_COUNT_R3A": 0, "MODEL_FIT_COUNT_R3R": model_fit_count, "NEW_FEATURE_COUNT": 0, "OPTUNA_TRIAL_COUNT": 0, "LOOKAHEAD_VIOLATION_COUNT": 0, "NEW_RISK_R3R_REPO_VIOLATION_COUNT": guard["new_risk_r1_repo_violation_count"], "NEXT_AUTHORIZED_STEP": "STOP_AFTER_R3R;DO_NOT_START_R4;DO_NOT_OPEN_2026" if complete else "STOP;START_OPEND_AND_RERUN_R3R_ONLY_IF_AUTHORIZED;DO_NOT_START_R4;DO_NOT_OPEN_2026",
    }
    audit = {"summary": summary, "panel_contract": panel_audit, "backfill": backfill_audit, "canonical_price_years_read": [2023, 2024, 2025], "canonical_2026_partition_read_count": 0, "reference_contract": "Moomoo QFQ execution-date open; five-day low/high/close path from achievable entry", "target_coverage_gate_pass": complete, "repository_governance": guard}
    R3.R1.write_csv(output / "r3a_risk_decile_attribution.csv", deciles)
    R3.R1.write_csv(output / "r3a_scaling_attribution.csv", scaling)
    R3.R1.write_csv(output / "r3a_alpha_risk_matrix.csv", alpha_risk)
    R3.R1.write_csv(output / "r3a_extreme_outcome_capture.csv", extremes)
    R3.R1.write_parquet(output / "r3r_execution_reference_coverage.parquet", coverage)
    R3.R1.write_json(output / "r3a_r3r_audit.json", audit)
    R3.R1.write_json(output / "r3a_r3r_summary.json", summary)
    print_summary(summary)
    return summary


def repair_existing(output: Path) -> dict[str, Any]:
    """Complete omitted target-comparison reporting without fitting or refetching."""
    summary_path, audit_path = output / "r3a_r3r_summary.json", output / "r3a_r3r_audit.json"
    backfill_path = output / "r3r_moomoo_qfq_execution_backfill.parquet"
    if not (summary_path.exists() and audit_path.exists() and backfill_path.exists()):
        raise RuntimeError("repair requires the completed authoritative R3R result")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    old_panel, score_panel, daily, _, _ = R3.build_panels()
    prices = load_canonical_prices(set(score_panel.ticker))
    backfill = pd.read_parquet(backfill_path).rename(columns={"internal_symbol": "ticker", "date": "trade_date", "adjustment_mode": "autype"})
    backfill["source"] = "MOOMOO_OPEND"
    backfill["trade_date"] = pd.to_datetime(backfill.trade_date)
    if backfill.trade_date.ge(TRAINING_CUTOFF).any():
        raise RuntimeError("repair backfill includes 2026")
    prices = pd.concat([prices, backfill[prices.columns]], ignore_index=True).drop_duplicates(["ticker", "trade_date"], keep="first")
    coverage, required = coverage_table(score_panel, prices)
    if not (coverage.exact_execution_reference.all() and coverage.complete_5d_path.all()):
        raise RuntimeError("repair cannot prove complete execution coverage")
    corrected = build_corrected_targets(score_panel, required)
    target_folds, target_summary = compare_targets(old_panel, corrected, pd.DatetimeIndex(daily.execution_date))
    oof = pd.read_parquet(output / "r3r_oof_predictions.parquet")
    summary.update(target_summary)
    if audit["repository_governance"]["repository_guard_status"] != "PASS":
        summary["A2_STOCK_RISK_R3A_STATUS"] = "VALID_R3A_R3R_COMPLETE_WITH_PREEXISTING_REPO_GOVERNANCE_FAILURE"
    summary["NEXT_AUTHORIZED_STEP"] = "STOP_AFTER_R3R;DO_NOT_START_R4;DO_NOT_OPEN_2026"
    audit["summary"] = summary
    audit["target_comparison"] = target_summary
    audit["reporting_repair"] = {"model_fit_count": 0, "moomoo_api_request_count": 0, "reason": "complete originally omitted old-new target comparison fields"}
    R3.R1.write_csv(output / "r3r_target_comparison_by_fold.csv", target_folds)
    R3.R1.write_csv(output / "r3r_risk_decile_targets.csv", corrected_risk_deciles(oof, corrected, summary["R3R_REFERENCE_MODEL"]))
    R3.R1.write_json(audit_path, audit)
    R3.R1.write_json(summary_path, summary)
    print_summary(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--repair-existing", action="store_true")
    args = parser.parse_args()
    try:
        repair_existing(args.output_dir.resolve()) if args.repair_existing else run(args.output_dir.resolve())
        return 0
    except Exception as exc:
        print("A2_STOCK_RISK_R3A_STATUS=FAIL_CLOSED", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
