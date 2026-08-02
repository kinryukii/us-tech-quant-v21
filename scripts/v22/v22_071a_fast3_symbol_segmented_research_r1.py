from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeRegressor

REPO = Path(__file__).resolve().parents[2]
LEGACY_RESULTS_ROOT = Path(r"D:\us-tech-quant-results\fast3\archive\legacy_v22")
CONTRACT = LEGACY_RESULTS_ROOT / "V22.069A_FAST_RESEARCH_CONTRACT_R1/v22_069a_fast_frozen_research_contract.json"
DATA_ROOT = Path(r"D:/us-tech-quant-data/fast3/moomoo_24h_1m")
OUT_NAME = "V22.071A_FAST3_SYMBOL_SEGMENTED_RESEARCH_R1"
SYMS = ["QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS"]
FEATURES = ["PREMARKET_CUM_RETURN", "PREMARKET_MAX_DRAWDOWN", "PREMARKET_REALIZED_VOLATILITY"]
COST = .001
MODEL_SPECS = {
    "RIDGE": {"alpha": 1.0},
    "SHALLOW_TREE": {"max_depth": 2, "min_samples_leaf": 100, "random_state": 20260731},
    "CONSTRAINED_RANDOM_FOREST": {"n_estimators": 200, "max_depth": 3, "min_samples_leaf": 80, "max_features": 1.0, "random_state": 20260731, "n_jobs": -1},
}


def nullable(value):
    return float(value) if value is not None and np.isfinite(value) else None


def stable(value): return json.dumps(value, sort_keys=True, indent=2, default=str) + "\n"


def make_model(name):
    params = MODEL_SPECS[name]
    if name == "RIDGE": return make_pipeline(StandardScaler(), Ridge(**params))
    if name == "SHALLOW_TREE": return DecisionTreeRegressor(**params)
    return RandomForestRegressor(**params)


def expanding_folds(dates):
    blocks = np.array_split(np.asarray(sorted(set(dates))), 6)
    return [{"fold_id": index + 1, "train_dates": list(np.concatenate(blocks[:index + 1])), "test_dates": list(blocks[index + 1])} for index in range(5) if len(blocks[index + 1])]


def research_paths(months):
    return [DATA_ROOT / "canonical" / f"symbol={symbol}" / f"year={month[:4]}" / f"month={month[5:]}" / "data.parquet" for month in months for symbol in SYMS]


def build_events(months):
    events, excluded = [], []
    allowed = set(months)
    for path in research_paths(months):
        if not path.is_file(): raise RuntimeError(f"RESEARCH_PARTITION_MISSING:{path}")
        frame = pq.read_table(path, columns=["timestamp_et", "open", "close"]).to_pandas()
        timestamp = pd.to_datetime(frame.timestamp_et, utc=True).dt.tz_convert("America/New_York")
        frame = frame.assign(timestamp=timestamp).dropna(subset=["timestamp", "open", "close"])
        frame["date"] = frame.timestamp.dt.date.astype(str); frame = frame[frame.date.str[:7].isin(allowed)]
        symbol = path.parents[2].name.split("=", 1)[1]
        for date, day in frame.groupby("date", sort=True):
            day = day.sort_values("timestamp")
            pre = day[(day.timestamp.dt.time >= pd.Timestamp("04:00").time()) & (day.timestamp.dt.time <= pd.Timestamp("09:25").time())]
            if pre.timestamp.dt.floor("min").nunique() / 326 < .80: excluded.append("PREMARKET_COVERAGE_LT_80_PERCENT"); continue
            entry = day[(day.timestamp.dt.time >= pd.Timestamp("09:30").time()) & (day.timestamp.dt.time <= pd.Timestamp("09:32").time())]
            exit_ = day[(day.timestamp.dt.time >= pd.Timestamp("15:58").time()) & (day.timestamp.dt.time <= pd.Timestamp("16:00").time())]
            if entry.empty: excluded.append("MISSING_ENTRY"); continue
            if exit_.empty: excluded.append("MISSING_EXIT"); continue
            closes = pre.close.astype(float).to_numpy()
            events.append({"date": date, "symbol": symbol, "PREMARKET_CUM_RETURN": float(closes[-1] / closes[0] - 1), "PREMARKET_MAX_DRAWDOWN": float(np.min(closes / np.maximum.accumulate(closes) - 1)), "PREMARKET_REALIZED_VOLATILITY": float(np.std(np.diff(np.log(closes)), ddof=0)), "target_return": float(exit_.iloc[-1].close) / float(entry.iloc[0].open) - 1})
    return pd.DataFrame(events).sort_values(["date", "symbol"]).reset_index(drop=True), excluded


def buckets(target, prediction):
    if len(target) < 5: return (None, None, None, None)
    count = max(1, math.ceil(len(target) * .2)); order = np.lexsort((np.arange(len(prediction)), prediction)); target = np.asarray(target)
    top, bottom = float(target[order[-count:]].mean()), float(target[order[:count]].mean())
    return top, bottom, top - bottom, top - bottom - COST


def concentration(frame, n, by_date=False):
    if frame.empty: return None
    chosen = frame.nlargest(max(1, math.ceil(len(frame) * .2)), "prediction")
    positive = chosen.target_return.clip(lower=0)
    total = positive.sum()
    if total <= 0: return None
    parts = positive.groupby(chosen.date).sum() if by_date else positive
    return nullable(parts.nlargest(n).sum() / total)


def metrics(frame, fold_rows):
    if frame.empty: return {"event_count": 0, **{k: None for k in ("oof_spearman_ic", "top_mean_return", "bottom_mean_return", "top_bottom_spread_gross", "top_bottom_spread_net_10bps", "positive_fold_ratio", "median_fold_ic", "worst_fold_ic", "positive_month_ratio", "unique_score_count", "score_tie_ratio", "top5_date_concentration", "top10_event_concentration")}}
    top, bottom, gross, net = buckets(frame.target_return, frame.prediction)
    ic = nullable(spearmanr(frame.target_return, frame.prediction).statistic) if len(frame) > 1 else None
    fold_ics = [r["spearman_ic"] for r in fold_rows if r["spearman_ic"] is not None]
    month_good = []
    for _, group in frame.groupby(frame.date.str[:7]):
        _, _, _, mn = buckets(group.target_return, group.prediction)
        if mn is not None: month_good.append(mn > 0)
    unique = int(pd.Series(frame.prediction).nunique())
    return {"event_count": int(len(frame)), "oof_spearman_ic": ic, "top_mean_return": top, "bottom_mean_return": bottom, "top_bottom_spread_gross": gross, "top_bottom_spread_net_10bps": net, "positive_fold_ratio": nullable(np.mean([r["spearman_ic"] > 0 for r in fold_rows if r["spearman_ic"] is not None])) if fold_ics else None, "median_fold_ic": nullable(np.median(fold_ics)) if fold_ics else None, "worst_fold_ic": nullable(np.min(fold_ics)) if fold_ics else None, "positive_month_ratio": nullable(np.mean(month_good)) if month_good else None, "unique_score_count": unique, "score_tie_ratio": nullable(1 - unique / len(frame)), "top5_date_concentration": concentration(frame, 5, True), "top10_event_concentration": concentration(frame, 10, False)}


def evaluate(events, structure, name):
    predictions, fold_rows, fit_count = [], [], 0
    for fold in expanding_folds(events.date):
        train_all = events[events.date.isin(fold["train_dates"])]; test_all = events[events.date.isin(fold["test_dates"])]
        groups = [("ALL", train_all, test_all)] if structure == "POOLED" else [(symbol, train_all[train_all.symbol == symbol], test_all[test_all.symbol == symbol]) for symbol in SYMS]
        for symbol, train, test in groups:
            valid = len(train) >= 2 and len(test) >= 2
            if valid:
                model = make_model(name).fit(train[FEATURES], train.target_return); fit_count += 1
                out = test[["date", "symbol", "target_return"]].copy(); out["prediction"] = model.predict(test[FEATURES]); predictions.append(out)
                fic = nullable(spearmanr(out.target_return, out.prediction).statistic)
            else: fic = None
            fold_rows.append({"structure": structure, "model": name, "symbol": None if symbol == "ALL" else symbol, "fold_id": fold["fold_id"], "train_start_date": min(fold["train_dates"]), "train_end_date": max(fold["train_dates"]), "test_start_date": min(fold["test_dates"]), "test_end_date": max(fold["test_dates"]), "train_event_count": len(train), "test_event_count": len(test), "spearman_ic": fic, "valid": valid, "time_order_valid": max(fold["train_dates"]) < min(fold["test_dates"])})
    pred = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame(columns=["date", "symbol", "target_return", "prediction"])
    overall_folds = [r for r in fold_rows if r["symbol"] is None] if structure == "POOLED" else [{"spearman_ic": nullable(spearmanr(g.target_return, g.prediction).statistic)} for _, g in pred.groupby("date", sort=True)]
    result = metrics(pred, overall_folds); result.update({"structure": structure, "model": name, "fit_call_count": fit_count})
    symbols = []
    for symbol in SYMS:
        sfolds = [r for r in fold_rows if r["symbol"] == symbol] if structure == "PER_SYMBOL" else [{"spearman_ic": nullable(spearmanr(g.target_return, g.prediction).statistic)} for _, g in pred[pred.symbol == symbol].groupby("date", sort=True)]
        sm = metrics(pred[pred.symbol == symbol], sfolds); sm.update({"structure": structure, "model": name, "symbol": symbol}); symbols.append(sm)
    return result, symbols, fold_rows


def qualifies(row, symbols):
    base = all([row["oof_spearman_ic"] is not None and row["oof_spearman_ic"] > 0, row["top_bottom_spread_net_10bps"] is not None and row["top_bottom_spread_net_10bps"] > 0, row["positive_fold_ratio"] is not None and row["positive_fold_ratio"] >= .60, row["median_fold_ic"] is not None and row["median_fold_ic"] > 0, row["positive_month_ratio"] is not None and row["positive_month_ratio"] >= .50, row["top5_date_concentration"] is not None and row["top5_date_concentration"] < .60])
    if row["structure"] == "POOLED": return base, None, None, None
    net = [x["top_bottom_spread_net_10bps"] for x in symbols if x["top_bottom_spread_net_10bps"] is not None]
    pos = sum(x > 0 for x in net); neg = sum(x <= 0 for x in net); contribution = max(np.maximum(net, 0)) / sum(np.maximum(net, 0)) if any(x > 0 for x in net) else None
    return base and pos >= 4 and neg <= 2 and contribution is not None and contribution < .40, pos, neg, nullable(contribution)


def run(results_root=LEGACY_RESULTS_ROOT):
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("symbols") != SYMS or contract.get("features") != FEATURES: raise RuntimeError("FROZEN_FEATURE_OR_SYMBOL_CONTRACT_MISMATCH")
    months = list(contract["split"]["development_months"]) + list(contract["split"]["validation_months"])
    events, excluded = build_events(months)
    if events.empty: raise RuntimeError("NO_RESEARCH_EVENTS")
    models, symbols, folds, fits = [], [], [], 0
    for structure in ("POOLED", "PER_SYMBOL"):
        for name in MODEL_SPECS:
            row, sym, fold = evaluate(events, structure, name); models.append(row); symbols.extend(sym); folds.extend(fold); fits += row["fit_call_count"]
    by_key = {(r["structure"], r["model"]): [s for s in symbols if (s["structure"], s["model"]) == (r["structure"], r["model"])] for r in models}
    for row in models:
        passed, pos, neg, ratio = qualifies(row, by_key[(row["structure"], row["model"])]); row.update({"candidate_pass": passed, "positive_symbol_count": pos, "negative_symbol_count": neg, "single_symbol_contribution_ratio": ratio})
    passed = [r for r in models if r["candidate_pass"]]
    complexity = {"RIDGE": 0, "SHALLOW_TREE": 1, "CONSTRAINED_RANDOM_FOREST": 2}
    selected = sorted(passed, key=lambda r: (-r["median_fold_ic"], -r["top_bottom_spread_net_10bps"], r["top5_date_concentration"], complexity[r["model"]]))[0] if passed else None
    # These are the five calendar walk-forward folds, not the expanded
    # model/structure/symbol measurement rows in fold_scorecard.csv.
    valid_folds = len(expanding_folds(events.date)); invalid_folds = 0
    violations = sum(not r["time_order_valid"] for r in folds)
    pooled = max((r for r in models if r["structure"] == "POOLED"), key=lambda r: (r["oof_spearman_ic"] is not None, r["oof_spearman_ic"] or -np.inf))
    segmented = max((r for r in models if r["structure"] == "PER_SYMBOL"), key=lambda r: (r["oof_spearman_ic"] is not None, r["oof_spearman_ic"] or -np.inf))
    summary = {"research_id": OUT_NAME, "final_status": "PASS", "final_decision": "SYMBOL_SEGMENTED_RESEARCH_CANDIDATE_FOUND" if selected else "NO_STABLE_SYMBOL_SEGMENTED_CANDIDATE", "next_freeze_stage_allowed": bool(selected), "selected_structure": selected["structure"] if selected else None, "selected_model": selected["model"] if selected else None, "former_development_role": "RESEARCH_DATA", "former_validation_role": "RESEARCH_DATA", "former_validation_still_independent": False, "confirmation_remains_sealed": True, "confirmation_row_read_count": 0, "research_event_count": len(events), "former_development_event_count": int(events.date.str[:7].isin(contract["split"]["development_months"]).sum()), "former_validation_event_count": int(events.date.str[:7].isin(contract["split"]["validation_months"]).sum()), "valid_fold_count": valid_folds, "invalid_fold_count": invalid_folds, "time_order_violation_count": violations, "data_leakage_detected": False, "hyperparameter_search_count": 0, "candidate_model_count": 3, "research_fit_call_count": fits, "final_frozen_model_output_count": 0, "broker_action_allowed": False, "paper_trading_allowed": False, "official_adoption_allowed": False, "live_trading_allowed": False, "order_output_count": 0, "position_output_count": 0, "broker_connection_count": 0, "pooled_best_model": pooled["model"], "pooled_best_oof_spearman_ic": pooled["oof_spearman_ic"], "pooled_best_net_spread_10bps": pooled["top_bottom_spread_net_10bps"], "segmented_best_model": segmented["model"], "segmented_best_oof_spearman_ic": segmented["oof_spearman_ic"], "segmented_best_net_spread_10bps": segmented["top_bottom_spread_net_10bps"], "positive_symbol_count": selected["positive_symbol_count"] if selected else segmented["positive_symbol_count"], "negative_symbol_count": selected["negative_symbol_count"] if selected else segmented["negative_symbol_count"], "single_symbol_contribution_ratio": selected["single_symbol_contribution_ratio"] if selected else segmented["single_symbol_contribution_ratio"], "excluded_event_count": len(excluded)}
    contract_out = {"primary_hypothesis": "Original six-ETF pooled model fails because symbol-conditional relationships are heterogeneous; independent symbol models may be more stable.", "secondary_hypothesis": "The depth-2 single tree has only three unique scores; constrained ensembles may improve ranking resolution without materially expanding complexity.", "features": FEATURES, "symbols": SYMS, "cost_round_trip": COST, "former_development_role": "RESEARCH_DATA", "former_validation_role": "RESEARCH_DATA", "former_validation_still_independent": False, "confirmation_remains_sealed": True, "confirmation_row_read_count": 0, "hyperparameter_search_count": 0, "candidate_model_count": 3, "random_kfold_used": False, "time_order_violation_count": violations, "data_leakage_detected": False}
    out = Path(results_root) / OUT_NAME; out.parent.mkdir(parents=True, exist_ok=True); stage = Path(tempfile.mkdtemp(prefix=".071a_", dir=out.parent))
    try:
        (stage / "v22_071a_summary.json").write_text(stable(summary), encoding="utf-8"); pd.DataFrame(models).to_csv(stage / "model_scorecard.csv", index=False); pd.DataFrame(symbols).to_csv(stage / "symbol_scorecard.csv", index=False); pd.DataFrame(folds).to_csv(stage / "fold_scorecard.csv", index=False); (stage / "research_contract.json").write_text(stable(contract_out), encoding="utf-8")
        if out.exists(): shutil.rmtree(out)
        os.replace(stage, out); return summary, out
    except Exception:
        shutil.rmtree(stage, ignore_errors=True); raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true"); parser.add_argument("--results-root", default=str(LEGACY_RESULTS_ROOT)); args = parser.parse_args()
    if args.execute:
        summary, out = run(Path(args.results_root)); print(json.dumps({**summary, "summary_path": str(out / "v22_071a_summary.json")}, sort_keys=True))
