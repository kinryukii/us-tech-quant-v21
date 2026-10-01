"""Frozen 2026 inference submission, then unified E5 economic replay."""
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

import optimize_route
import prepare
import risk_aux
import rl_policy
from trade_detail import detail

ROOT = Path(__file__).resolve().parent
SOURCE = Path(r"D:\us-tech-quant-daily\A2_historical_top40\runs\20260924_gap_fill_complete")
ASOF_DAY = pd.Timestamp("2026-09-24")
END = pd.Timestamp("2026-01-01")
OUT = ROOT / "test2026"


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def frozen():
    record = json.loads((ROOT / "freeze_manifest.json").read_text(encoding="utf-8"))
    if record["status"] != "PRE2026_ALL_CANDIDATES_FROZEN" or record["test_last_completed_session_et"] != "2026-09-24":
        raise RuntimeError("FREEZE_CONTRACT")
    for relative, digest in record["artifacts_sha256"].items():
        if sha(ROOT / relative) != digest:
            raise RuntimeError(f"FROZEN_ARTIFACT_CHANGED:{relative}")
    return record


def ranked_features():
    ranking = ds.dataset(SOURCE / "top40.parquet", format="parquet").to_table(
        filter=(ds.field("target_date") >= "2026-01-01") &
               (ds.field("target_date") <= "2026-09-24")).to_pandas()
    ranking["signal_date"] = pd.to_datetime(ranking.target_date)
    if ranking.empty or ranking.signal_date.max() > ASOF_DAY or not ranking.model_year.eq(2026).all():
        raise RuntimeError("RANKING_COVERAGE_OR_LINEAGE")
    if not (pd.to_datetime(ranking.universe_effective_date) <= ranking.signal_date).all():
        raise RuntimeError("FUTURE_UNIVERSE")
    if ranking.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("DUPLICATE_RANK")
    ranking = ranking.rename(columns={"score": "raw_score", "rank": "raw_rank"})
    ranking["raw_rank_strength"] = 1 - (ranking.raw_rank.astype(float) - 1) / 39
    group = ranking.groupby("signal_date").raw_score
    ranking["raw_score_z"] = (ranking.raw_score - group.transform("mean")) / group.transform(lambda x: x.std(ddof=0))
    features = ds.dataset(SOURCE / "inference_features.parquet", format="parquet").to_table(
        columns=["trade_date", "ticker", *prepare.BASE_FEATURES],
        filter=ds.field("trade_date") <= ASOF_DAY.to_pydatetime()).to_pandas()
    features["trade_date"] = pd.to_datetime(features.trade_date)
    features = features.sort_values(["ticker", "trade_date"])
    if features.duplicated(["trade_date", "ticker"]).any():
        raise RuntimeError("DUPLICATE_FEATURE")
    for k in range(10):
        features[f"lag_ret_{k:02d}"] = features.groupby("ticker", sort=False).ret_1d.shift(k)
    panel = ranking.merge(features.rename(columns={"trade_date": "signal_date"}),
                          on=["signal_date", "ticker"], how="left", validate="one_to_one")
    if panel.groupby("signal_date").raw_rank.apply(lambda x: (x <= 20).sum()).ne(20).any():
        raise RuntimeError("INCOMPLETE_TOP20")
    return panel


def predict():
    frozen()
    OUT.mkdir(exist_ok=True)
    if (OUT / "predictions.parquet").exists():
        raise RuntimeError("PREDICTIONS_ALREADY_SUBMITTED")
    panel = ranked_features()
    manifest = json.loads((ROOT / "supervised_manifest.json").read_text(encoding="utf-8"))
    if prepare.FEATURES != manifest["features"]:
        raise RuntimeError("FEATURE_MISMATCH")
    for name, item in manifest["artifacts"].items():
        model = joblib.load(ROOT / item["path"])
        if name.startswith("LOGISTIC"):
            panel["pred_logistic"] = model.predict_proba(panel[prepare.FEATURES])[:, 1]
        else:
            label = name.split("_")[0].lower()
            col = f"pred_{label}" + (f"_{name.split('_')[1]}" if label == "mlp" else "")
            panel[col] = model.predict(panel[prepare.FEATURES])
    panel["pred_mlp_mean"] = (panel.pred_mlp_2026092501 + panel.pred_mlp_2026092502) / 2
    risk = risk_aux.load_bundle(ROOT / "risk_artifacts" / "final_pre2026.joblib")
    aux = risk_aux.aux_scores(risk, panel)
    panel = panel.merge(aux, on=["signal_date", "ticker"], validate="one_to_one")
    panel.to_parquet(OUT / "predictions.parquet", index=False)
    receipt = {"status": "2026_PREDICTIONS_SUBMITTED_BEFORE_PRICE_SCORE", "rows": len(panel),
               "dates": int(panel.signal_date.nunique()), "last_signal": str(panel.signal_date.max().date()),
               "missing_base_feature_rows": int(panel.ret_1d.isna().sum()),
               "prediction_sha256": sha(OUT / "predictions.parquet"), "model_fit_calls": 0,
               "economic_price_reads": 0, "asof": "2026-09-25T15:34:48Z"}
    (OUT / "prediction_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("2026_PREDICTIONS_SUBMITTED", receipt)


def score():
    freeze = frozen()
    receipt = json.loads((OUT / "prediction_receipt.json").read_text(encoding="utf-8"))
    if sha(OUT / "predictions.parquet") != receipt["prediction_sha256"] or receipt["economic_price_reads"] != 0:
        raise RuntimeError("PREDICTION_SUBMISSION_CHANGED")
    if (OUT / "summary.csv").exists():
        raise RuntimeError("SCORE_ALREADY_RUN")
    panel = pd.read_parquet(OUT / "predictions.parquet")
    e5 = rl_policy.load_module("a2_e5_final_2026", rl_policy.E5)
    _, prices, lineage = e5.load_2026_prices(set(panel.ticker.astype(str)))
    prices = prices.loc[prices.trade_date.le(ASOF_DAY)].copy()
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    if calendar.empty or calendar.max() > ASOF_DAY:
        raise RuntimeError("TEST_PRICE_CALENDAR")
    risk = risk_aux.load_bundle(ROOT / "risk_artifacts" / "final_pre2026.joblib")
    chosen = freeze["supervised_representative"]
    specs = [("RAW", None), (chosen, optimize_route.SPECS[chosen])]
    # One factor and one diagonal risk comparison remain predeclared even if
    # internal selection falls back to Raw; no new candidate is trained here.
    if chosen != "HGB_DIAG_5":
        specs.append(("HGB_DIAG_5", optimize_route.SPECS["HGB_DIAG_5"]))
    if chosen != "HGB_FACTOR_5":
        specs.append(("HGB_FACTOR_5", optimize_route.SPECS["HGB_FACTOR_5"]))
    summaries = []
    for name, spec in specs:
        result, decisions = optimize_route.replay_spec(name, spec, panel, prices, risk,
                                                        "2026-01-01", "2026-09-25")
        summaries.append({"candidate": name, **optimize_route.summarize(result),
                          "solver_fallbacks": int(decisions.loc[decisions.solver_failed, "signal_date"].nunique())})
        result.daily.to_parquet(OUT / f"{name.lower()}_daily.parquet", index=False)
        result.trades.to_parquet(OUT / f"{name.lower()}_trades.parquet", index=False)
        decisions.to_parquet(OUT / f"{name.lower()}_decisions.parquet", index=False)
        detail(result.trades, result.daily, prices, decisions).to_parquet(
            OUT / f"{name.lower()}_executed.parquet", index=False)
    norm = np.load(ROOT / "rl_artifacts" / "normalization.npz")
    days = rl_policy.build_days(panel, norm["mean"], norm["scale"])
    replay = rl_policy.dynamic_e5_replay(e5)
    _, executions, signal_by_execution = optimize_route.dates_for(prices, panel, "2026-01-01", "2026-09-25")
    for rl_name, seed in freeze["rl_test_policies"].items():
        records = []
        callback = rl_policy.frozen_callback(days, seed=seed, records=records)
        result = replay(rl_name, callback, prices, executions, signal_by_execution)
        summaries.append({"candidate": rl_name, **optimize_route.summarize(result), "solver_fallbacks": 0})
        result.daily.to_parquet(OUT / f"{rl_name.lower()}_daily.parquet", index=False)
        result.trades.to_parquet(OUT / f"{rl_name.lower()}_trades.parquet", index=False)
        targets = pd.DataFrame(records)
        targets["candidate"] = rl_name
        targets.to_parquet(OUT / f"{rl_name.lower()}_targets.parquet", index=False)
        detail(result.trades, result.daily, prices, targets).to_parquet(
            OUT / f"{rl_name.lower()}_executed.parquet", index=False)
    pd.DataFrame(summaries).to_csv(OUT / "summary.csv", index=False)
    (OUT / "score_receipt.json").write_text(json.dumps({"status": "FROZEN_2026_SCORE_COMPLETE",
        "asof": "2026-09-25T15:34:48Z", "price_lineage": lineage,
        "price_last_session": str(calendar.max().date()), "last_completed_session": "2026-09-24",
        "prediction_sha256": receipt["prediction_sha256"], "fit_calls": 0,
        "economic_scope": "QFQ price-coordinate proxy, not certified shareholder total return",
        "historical_2026_exposure_prior_batch": True}, indent=2, default=str) + "\n", encoding="utf-8")
    print(pd.DataFrame(summaries).to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("predict", "score"))
    args = parser.parse_args()
    predict() if args.phase == "predict" else score()
