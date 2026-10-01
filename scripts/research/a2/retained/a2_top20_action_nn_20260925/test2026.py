"""Frozen 2026 inference and separate path scoring; invoke predict before score."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT = Path(__file__).resolve().parent
ASOF_DAY = pd.Timestamp("2026-09-24")  # last completed ET session at fixed TEST_ASOF
SOURCE = Path(r"D:\us-tech-quant-daily\A2_historical_top40\runs\20260924_gap_fill_complete")
E5 = Path(r"D:\us-tech-quant-results\A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS\run_a2_execution_efficiency_r2.py")
FEATURES = ["raw_rank_strength", "raw_score_z", "ret_1d", "ret_5d", "ret_20d",
            "realized_vol_20d", "downside_vol_20d", "max_drawdown_20d",
            "volume_ratio_5d_20d", "price_vs_ma20", "distance_from_high_20d",
            *(f"lag_ret_{i:02d}" for i in range(10))]


def digest(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def freeze() -> dict:
    record = json.loads((ROOT / "freeze.json").read_text(encoding="utf-8"))
    assert record["status"] == "PRE2026_FROZEN_BEFORE_2026_ECONOMIC_READ"
    assert digest(Path(__file__)) == record["evaluation_code_sha256"]
    assert record["features"] == FEATURES and record["test_last_completed_session_et"] == str(ASOF_DAY.date())
    for item in record["models"].values():
        assert digest(ROOT / item["path"]) == item["sha256"]
    assert digest(ROOT / "pre2026_oof_predictions.parquet") == record["oof_sha256"]
    assert digest(ROOT / "trials.csv") == record["trial_table_sha256"]
    return record


def zscore(frame: pd.DataFrame) -> pd.Series:
    groups = frame.groupby("signal_date").raw_score
    center = groups.transform("mean")
    spread = groups.transform(lambda x: x.std(ddof=0))
    return ((frame.raw_score - center) / spread.where(spread.gt(0), 1.0)).fillna(0.0)


def predict() -> None:
    record = freeze()
    assert not (ROOT / "2026_predictions.parquet").exists(), "FROZEN_PREDICTIONS_ALREADY_EXIST"
    ranked = ds.dataset(SOURCE / "top40.parquet", format="parquet").to_table(
        filter=(ds.field("target_date") >= "2026-01-01") &
               (ds.field("target_date") <= str(ASOF_DAY.date()))).to_pandas()
    ranked["signal_date"] = pd.to_datetime(ranked.target_date)
    assert not ranked.empty and ranked.signal_date.max() <= ASOF_DAY
    assert ranked.model_year.eq(2026).all()
    assert (pd.to_datetime(ranked.universe_effective_date) <= ranked.signal_date).all()
    assert ranked.duplicated(["signal_date", "ticker"]).sum() == 0
    assert ranked.groupby("signal_date").model_sha256.nunique().max() == 1
    ranked = ranked.rename(columns={"score": "raw_score", "rank": "raw_rank"})
    ranked["raw_rank_strength"] = 1.0 - (ranked.raw_rank.astype(float) - 1.0) / 39.0
    ranked["raw_score_z"] = zscore(ranked)
    features = ds.dataset(SOURCE / "inference_features.parquet", format="parquet").to_table(
        columns=["trade_date", "ticker", "ret_1d", "ret_5d", "ret_20d", "realized_vol_20d",
                 "downside_vol_20d", "max_drawdown_20d", "volume_ratio_5d_20d",
                 "price_vs_ma20", "distance_from_high_20d"],
        filter=ds.field("trade_date") <= ASOF_DAY.to_pydatetime()).to_pandas()
    features["trade_date"] = pd.to_datetime(features.trade_date)
    assert not features.duplicated(["trade_date", "ticker"]).any()
    features = features.sort_values(["ticker", "trade_date"])
    for k in range(10):
        features[f"lag_ret_{k:02d}"] = features.groupby("ticker", sort=False).ret_1d.shift(k)
    candidates = ranked.merge(features.rename(columns={"trade_date": "signal_date"}),
                              on=["signal_date", "ticker"], how="left", validate="one_to_one")
    missing = int(candidates["ret_1d"].isna().sum())
    assert not candidates.empty
    for name, item in record["models"].items():
        model = joblib.load(ROOT / item["path"])
        candidates[f"p_{name}"] = model.predict(candidates[FEATURES])
    candidates["p_MLP_MEAN"] = 0.5 * (candidates.p_MLP_20260925 + candidates.p_MLP_20260926)
    candidates["raw_top20"] = candidates.raw_rank.le(20)
    candidates.to_parquet(ROOT / "2026_predictions.parquet", index=False)
    receipt = {"status": "PREDICTIONS_COMMITTED_BEFORE_OUTCOME_SCORE", "test_asof_utc": record["test_asof_utc"],
               "source": "20260924_gap_fill_complete historical_top40 verified 2026 rebuilt-production lineage",
               "source_top40_sha256": digest(SOURCE / "top40.parquet"),
               "source_features_sha256": digest(SOURCE / "inference_features.parquet"),
               "prediction_sha256": digest(ROOT / "2026_predictions.parquet"),
               "rows": len(candidates), "dates": candidates.signal_date.nunique(),
               "inference_feature_missing_rows": missing,
               "feature_normalization": "same-date Top40 population zscore, fixed pre-2026 formula",
               "model_fit_calls": 0, "outcome_reads": 0}
    (ROOT / "2026_prediction_receipt.json").write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"PREDICTIONS_COMMITTED rows={len(candidates)} dates={receipt['dates']} missing={missing}")


def targets_for(pred: pd.DataFrame, column: str | None, mode: str) -> tuple[dict, pd.DataFrame]:
    held: set[str] = set()
    targets = {}
    actions = []
    for day, group in pred.groupby("signal_date", sort=True):
        group = group.sort_values(["raw_rank", "ticker"])
        raw = set(group.loc[group.raw_rank.le(20), "ticker"])
        complete = len(group) >= 40 and len(raw) == 20
        if not complete:
            targets[pd.Timestamp(day)] = {t: 0.05 for t in sorted(held)}
            actions.append({"signal_date": day, "ticker": None, "mode": mode,
                            "action": "CARRY_INCOMPLETE_RANKING", "prior_held": len(held)})
            continue
        target = set()
        for row in group.itertuples():
            old = row.ticker in held
            new = row.ticker in raw and not old
            p = float(getattr(row, column)) if column else np.nan
            if mode == "RAW":
                allow = row.ticker in raw
            elif mode == "BUY_ONLY":
                allow = (old and row.ticker in raw) or (new and p > 0.001)
            elif mode == "EXIT_ONLY":
                allow = new or (old and p > 0.0005)
            elif mode == "JOINT":
                allow = (new and p > 0.001) or (old and p > 0.0005)
            else:
                raise ValueError(mode)
            if allow:
                target.add(row.ticker)
            if new or old:
                actions.append({"signal_date": day, "ticker": row.ticker, "mode": mode,
                                "action": "BUY" if allow and new else "HOLD" if allow else "EXIT" if old else "WAIT",
                                "raw_rank": row.raw_rank, "prediction": p})
        held = target
        targets[pd.Timestamp(day)] = {t: 0.05 for t in sorted(target)}
    return targets, pd.DataFrame(actions)


def score() -> None:
    record = freeze()
    receipt = json.loads((ROOT / "2026_prediction_receipt.json").read_text(encoding="utf-8"))
    assert receipt["outcome_reads"] == 0 and receipt["model_fit_calls"] == 0
    assert digest(ROOT / "2026_predictions.parquet") == receipt["prediction_sha256"]
    assert not (ROOT / "2026_metrics.csv").exists(), "SCORE_ALREADY_EXISTS"
    pred = pd.read_parquet(ROOT / "2026_predictions.parquet")
    e5_spec = importlib.util.spec_from_file_location("a2_action_e5_test", E5)
    assert e5_spec and e5_spec.loader
    e5 = importlib.util.module_from_spec(e5_spec)
    sys.modules[e5_spec.name] = e5
    e5_spec.loader.exec_module(e5)
    tickers = set(pred.ticker.astype(str))
    _, prices, lineage = e5.load_2026_prices(tickers)
    prices = prices.loc[prices.trade_date.le(ASOF_DAY)].copy()
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    assert not calendar.empty and calendar.max() <= ASOF_DAY
    next_day = {pd.Timestamp(calendar[i]): pd.Timestamp(calendar[i + 1]) for i in range(len(calendar) - 1)}
    all_signals = pd.DatetimeIndex(sorted(pred.signal_date.unique()))
    execution = [next_day[pd.Timestamp(d)] for d in all_signals if pd.Timestamp(d) in next_day]
    signal_by_execution = {next_day[pd.Timestamp(d)]: pd.Timestamp(d) for d in all_signals if pd.Timestamp(d) in next_day}
    specs = [("RAW", None, "RAW"), ("RIDGE", "p_RIDGE_20260925", "JOINT"),
             ("HGB", "p_HGB_20260925", "JOINT"),
             ("MLP_JOINT", "p_MLP_MEAN", "JOINT"),
             ("MLP_BUY_ONLY", "p_MLP_MEAN", "BUY_ONLY"),
             ("MLP_EXIT_ONLY", "p_MLP_MEAN", "EXIT_ONLY")]
    metrics, paths, trades, actions = [], [], [], []
    for name, column, mode in specs:
        targets, act = targets_for(pred, column, mode)
        result = e5.replay(name, targets, prices, execution, signal_by_execution)
        x = result.daily
        metrics.append({"candidate": name, "status": "SCORED", "sessions": len(x),
                        "first_execution": x.execution_date.min(), "last_execution": x.execution_date.max(),
                        "net_return": float(x.nav.iloc[-1] - 1),
                        "max_drawdown": float((x.nav / x.nav.cummax() - 1).min()),
                        "turnover_sum": float(x.turnover.sum()),
                        "cost_sum_nav_fraction": float(x.transaction_cost_fraction.sum()),
                        "mean_cash_weight": float(x.cash_weight.mean()),
                        "skipped_buys": int(x.skipped_buy_count.sum()),
                        "blocked_sells": int(x.blocked_sell_count.sum()),
                        "final_nav": float(x.nav.iloc[-1])})
        paths.append(x)
        trades.append(result.trades)
        act["candidate"] = name
        actions.append(act)
    pd.DataFrame(metrics).to_csv(ROOT / "2026_metrics.csv", index=False)
    pd.concat(paths, ignore_index=True).to_parquet(ROOT / "2026_daily_paths.parquet", index=False)
    pd.concat(trades, ignore_index=True).to_parquet(ROOT / "2026_trades.parquet", index=False)
    pd.concat(actions, ignore_index=True).to_parquet(ROOT / "2026_actions.parquet", index=False)
    (ROOT / "2026_score_receipt.json").write_text(json.dumps({
        "prediction_sha256": receipt["prediction_sha256"], "test_asof_utc": record["test_asof_utc"],
        "price_lineage": lineage, "price_coordinate": "QFQ raw counterfactual, not independently certified total shareholder return",
        "last_completed_session": str(ASOF_DAY.date()), "fit_calls": 0,
        "ranking_incomplete_signal_dates": int(pred.groupby("signal_date").size().lt(40).sum()),
        "pending_prediction_dates_without_next_execution": [str(pd.Timestamp(d).date()) for d in all_signals if pd.Timestamp(d) not in next_day],
        "economic_result_scope": "price-coordinate NAV only until corporate-action total-return audit"}, indent=2, default=str) + "\n", encoding="utf-8")
    print("SCORE_COMPLETE", pd.DataFrame(metrics).to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["predict", "score"])
    args = parser.parse_args()
    predict() if args.phase == "predict" else score()
