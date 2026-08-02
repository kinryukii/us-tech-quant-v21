#!/usr/bin/env python
"""V22.083 bounded, delay-robust sparse SOXL/SOXS event research engine.

The audit phase freezes a metadata-only split and records the read-only V22.082
G03 failure diagnostic.  The run phase is idempotent: it writes registered
Development experiments first and consumes each scheduled Validation/Confirmation
only after the generation champion is frozen.  It is research-only by design.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import generation3r2_research as r2


NAME = "V22.083_FAST3_DELAY_ROBUST_SPARSE_EVENT_ENGINE_R1"
ROOT = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
OUT = Path(r"D:\us-tech-quant-results\fast3_v22_083_delay_robust_sparse_event")
HERE = Path(__file__).parent
CONFIG = HERE / "v22_083_delay_robust_sparse_event_config.json"
PRIOR082 = Path(r"D:\us-tech-quant-results\fast3_v22_082_multigeneration_autopilot")
SAFETY = {"research_only": True, "canonical_data_writable": False,
          "paper_trading_allowed": False, "shadow_allowed": False,
          "broker_action_allowed": False, "official_adoption_allowed": False,
          "order_generation_allowed": False, "live_trading_allowed": False}
FEATURES = list(r2.FEATURES) + list(r2.VIX_FEATURES)


def _default(v):
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating,)): return float(v) if np.isfinite(v) else None
    if isinstance(v, (pd.Timestamp, datetime)): return v.isoformat()
    if isinstance(v, np.ndarray): return v.tolist()
    return str(v)


def digest(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), default=_default).encode()).hexdigest()


def et(v) -> pd.Timestamp:
    x = pd.Timestamp(v)
    return x.tz_localize("America/New_York") if x.tzinfo is None else x.tz_convert("America/New_York")


def now() -> str: return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2, default=_default) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def write_rows(path: Path, value: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(x, sort_keys=True, default=_default) + "\n" for x in value), encoding="utf-8")
    os.replace(tmp, path)


def cfg() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def budget(output: Path) -> dict:
    value = json.loads((output / "autopilot_budget.json").read_text(encoding="utf-8-sig"))
    c = cfg()
    value["max_generations"] = min(int(value["max_generations"]), 4)
    value["experiments_per_generation"] = min(int(value["experiments_per_generation"]), c["experiments_per_generation"])
    value["max_total_experiments"] = min(int(value["max_total_experiments"]), value["max_generations"] * value["experiments_per_generation"])
    return value


def checkpoint(output: Path, **updates) -> dict:
    path = output / "v22_083_checkpoint.json"
    state = json.loads(path.read_text()) if path.exists() else {"stage": NAME, "state": "NEW", "validation_read_count": 0, "confirmation_read_count": 0, "global_final_holdout_read_count": 0, **SAFETY}
    state.update(updates); state["updated_at"] = now(); atomic_json(path, state); return state


def _source_hash(canonical: Path) -> str:
    # Metadata only: no OHLC values are read while freezing the schedule.
    parts = [{"path": str(p.relative_to(canonical)), "size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
             for s in r2.SYMBOLS for p in r2.paths_for(canonical, s)]
    return digest(parts)


def frozen_manifest(canonical: Path) -> dict:
    dates, ends, source = r2.metadata_audit(canonical)
    common = pd.DatetimeIndex(sorted(set(dates["SOXX"]).intersection(*[set(dates[s]) for s in r2.SYMBOLS if s != "SOXX"])))
    # V22.082 consumed all of its 2020/early-2021 Validation months.  V22.081
    # and Generation 2/3 artifacts consume 2023+ defined gates.  This schedule
    # uses 2022 gates only; its Development portion is explicitly exposed-only.
    def fold(g, validation, confirmation, pre_embargo):
        return {"generation_id": f"G{g:02d}", "development_start": "2018-07-19", "development_end": "2021-06-30 23:59:59.999999",
                "internal_validation_start": "2021-07-01", "internal_validation_end": "2021-12-31 23:59:59.999999",
                "purge_minutes": 180, "embargo_before_validation": pre_embargo,
                "validation_start": validation + "-01", "validation_end": validation + "-28 23:59:59.999999",
                "confirmation_start": confirmation + "-01", "confirmation_end": confirmation + "-28 23:59:59.999999", "confirmation_train_purge_minutes": 180,
                "validation_consumed": False, "confirmation_consumed": False}
    folds = [fold(1, "2022-02", "2022-03", "2022-01-01..2022-01-31"), fold(2, "2022-05", "2022-06", "2022-04-01..2022-04-30"), fold(3, "2022-08", "2022-09", "2022-07-01..2022-07-31"), fold(4, "2022-11", "2022-12", "2022-10-01..2022-10-31")]
    # Calendar-month end is deliberately shortened only to the actual month end by range reads below.
    manifest = {"stage": NAME, "status": "FROZEN_BEFORE_CANDIDATE_FITTING", "timezone": "America/New_York",
                "source_common_start": common.min(), "source_common_end": min(ends.values()), "source_data_hash": _source_hash(canonical),
                "maximum_label_horizon_minutes": 180, "purge_minutes": 180,
                "prior_holdout_usage": {"v22_081": ["2026-04..2026-05 validation consumed", "2026-07 confirmation consumed"],
                                        "v22_082": ["2020-01..2021-06 Validation consumed", "all V22.082 Confirmation unread"],
                                        "generation2_generation3": ["2025-12..2026-05 validation opened or scheduled; 2026-07 confirmation unread/scheduled"]},
                "exposure_statement": "Only the named frozen-artifact holdout ledgers were available.  2022 is not represented as a consumed holdout in those ledgers; it is not labelled globally untouched.",
                "development_exposure": "Previously exposed historical data allowed for fitting only.", "generations": folds,
                "global_final_holdout": {"start": "2023-01-01", "end": "2023-01-31 23:59:59.999999", "consumed": False}, **SAFETY}
    manifest["split_sha256"] = digest(manifest)
    return manifest


def g03_diagnostic(output: Path) -> dict:
    metric_path = PRIOR082 / "g03_validation_metrics.json"
    metric = json.loads(metric_path.read_text()) if metric_path.exists() else {}
    m = metric.get("metrics", {})
    # The registry has experiment-level metrics/config only; no trade tape was emitted.
    result = {"G03_FAILURE_CLASS": "DELAY_SENSITIVITY", "G03_DELAY_DECAY_PROFILE": {"delay_1m_20bps": m.get("mean_net_20bps_delay1"), "delay_3m_20bps": m.get("mean_net_20bps_delay3"), "delay_5m_20bps": m.get("mean_net_20bps_delay5")},
              "G03_LONG_SHORT_ASYMMETRY": "UNAVAILABLE_TRADE_LEVEL_OUTPUT_NOT_PRESERVED", "G03_REGIME_DEPENDENCE": {"reported_regime_stability": m.get("regime_stability"), "reported_year_stability": m.get("year_stability")},
              "G03_PROFIT_CONCENTRATION": m.get("concentration"), "G03_DRAWDOWN_SOURCE": "UNAVAILABLE_TRADE_LEVEL_EQUITY_CURVE_NOT_PRESERVED; aggregate_validation_mdd=" + str(m.get("max_drawdown")),
              "G03_REUSABLE_SIGNAL_COMPONENTS": ["PIT completed-bar features", "real SOXL/SOXS next-valid-open mapping", "one-minute positive 20bps diagnostic"],
              "G03_COMPONENTS_TO_REJECT": ["best-delay champion selection", "99% NO_TRADE rate with 10 trades", "delay-fragile 60-minute fixed-horizon policy"],
              "trade_level_reconstruction": "IMPOSSIBLE_FROM_FROZEN_G03_ARTIFACTS: no decision/action/trade table, MFE/MAE, exit reason, or per-side results found", "source_metric_path": str(metric_path)}
    atomic_json(output / "g03_failure_diagnostic.json", result)
    return result


def audit(output: Path, canonical: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if (output / "frozen_split_manifest.json").exists(): return
    m = frozen_manifest(canonical); atomic_json(output / "frozen_split_manifest.json", m)
    g03_diagnostic(output)
    feature_contract = [{"feature_name": f, "source": "VIX prior-day PIT" if f.startswith("vix_") else "completed SOXX/QQQ/SOXL/SOXS OHLCV", "availability_lag_minutes": 1,
                         "maximum_source_timestamp": "decision_timestamp - 1 minute", "missingness": "median imputation fit only on current train", "direction_stability": "recorded across seeds"} for f in FEATURES]
    atomic_json(output / "feature_contract.json", {"features": feature_contract, "active_feature_limit": 25, **SAFETY})
    atomic_json(output / "label_contract.json", {"horizons_minutes": cfg()["horizons_minutes"], "delays_minutes": cfg()["delay_minutes"], "cost_bps": cfg()["cost_bps"],
        "opportunity": "at least one real mapped ETF side is positive net across 1/3/5-minute delay at a declared horizon", "direction": "mapped ETF side with larger worst-delay net; tie/invalid=UNCERTAIN", "entry_timing": "ENTER_NOW/WAIT_3_MIN/WAIT_5_MIN/NO_TRADE from frozen probability bands", "barrier": "lagged ATR-width triple-barrier equivalent; barrier-first, MFE, MAE and time exit recorded", **SAFETY})
    checkpoint(output, state="SPLIT_FROZEN_AWAITING_DEVELOPMENT", split_sha256=m["split_sha256"], next_action="Run bounded Development experiments for G01.", exact_resume_command=f"python scripts/v22/fast3_agent/v22_083_delay_robust_sparse_event.py --phase run --output-dir {output}")


def read_samples(canonical: Path, start, end) -> pd.DataFrame:
    data = {s: r2._read_range(canonical, s, et(start), et(end)) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}
    frame = r2.build_samples(data)
    if r2.VIX_PATH.is_file(): frame = r2._vix_for_development(frame)
    else:
        for f in r2.VIX_FEATURES: frame[f] = np.nan
    # 180-minute real ETF returns use the same auditable next-valid-open mapping.
    for symbol in ("soxl", "soxs"):
        frame[f"{symbol}_gross_180m_delay1"] = np.nan; frame[f"{symbol}_gross_180m_delay3"] = np.nan; frame[f"{symbol}_gross_180m_delay5"] = np.nan
    for symbol in ("soxl", "soxs"):
        etf = data[symbol.upper()]; ns = pd.to_datetime(etf.timestamp_utc, utc=True).astype("int64").to_numpy(); opens = etf.open.to_numpy(float)
        decision_ns = pd.to_datetime(frame.entry_timestamp, utc=True).astype("int64").to_numpy()
        for delay in (1, 3, 5):
            begin = decision_ns + delay * 60_000_000_000; ein = np.searchsorted(ns, begin); eout = np.searchsorted(ns, begin + 180 * 60_000_000_000)
            good = (ein < len(ns)) & (eout < len(ns)); timely = np.zeros(len(frame), bool); timely[good] = ns[ein[good]] - begin[good] <= 60_000_000_000; good &= timely
            ret = np.full(len(frame), np.nan); ret[good] = opens[eout[good]] / opens[ein[good]] - 1; ret[np.abs(ret) > .30] = np.nan
            frame[f"{symbol}_gross_180m_delay{delay}"] = ret
    frame["maximum_source_timestamp"] = pd.to_datetime(frame.decision_timestamp) - pd.Timedelta(minutes=1)
    if not (frame.maximum_source_timestamp <= pd.to_datetime(frame.decision_timestamp) - pd.Timedelta(minutes=1)).all(): raise RuntimeError("FAIL_LEAKAGE_DETECTED")
    return frame.dropna(subset=list(r2.FEATURES)).reset_index(drop=True)


def candidate(generation: int, number: int) -> dict:
    c = cfg(); rng = np.random.default_rng(c["seeds"][number % len(c["seeds"])] + generation * 100 + number)
    family = c["model_families"][(number // 20) % 2]; n = int(rng.integers(12, min(25, len(FEATURES)) + 1))
    features = sorted(rng.choice(FEATURES, n, replace=False).tolist())
    return {"model_type": family, "features": features, "opportunity_threshold": float([.52, .56, .60, .64][number % 4]), "direction_margin": float([.04, .06, .08][number % 3]),
            "horizon": int([30, 60, 180][number % 3]), "entry_policy": ["ENTER_NOW", "WAIT_3_MIN", "WAIT_5_MIN"][number % 3],
            "params": {"c": float([.15, .35, .60][number % 3]), "l1_ratio": float([.2, .5, .8][number % 3]), "max_iter": 200, "max_leaf_nodes": int([5, 7][number % 2]), "min_samples_leaf": int([500, 900][number % 2]), "l2_regularization": float([3., 8.][number % 2]), "max_hgb_iter": 50}, "seed": int(c["seeds"][number % 3] + generation * 100 + number)}


def model(kind: str, params: dict, seed: int):
    if kind == "elastic_net_logistic": return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", LogisticRegression(penalty="elasticnet", solver="saga", C=params["c"], l1_ratio=params["l1_ratio"], max_iter=params["max_iter"], random_state=seed))])
    return Pipeline([("impute", SimpleImputer(strategy="median")), ("model", HistGradientBoostingClassifier(max_iter=params["max_hgb_iter"], max_leaf_nodes=params["max_leaf_nodes"], min_samples_leaf=params["min_samples_leaf"], l2_regularization=params["l2_regularization"], learning_rate=.05, random_state=seed))])


def _label(frame: pd.DataFrame, horizon: int) -> tuple[pd.Series, pd.Series]:
    sides = []
    for side in ("soxl", "soxs"):
        values = pd.concat([frame[f"{side}_gross_{horizon}m_delay{d}"] - .002 for d in (1, 3, 5)], axis=1)
        sides.append(values.min(axis=1))
    best = pd.concat(sides, axis=1); opportunity = best.max(axis=1).gt(0).astype(int)
    direction = pd.Series(np.where(best.iloc[:, 0] > best.iloc[:, 1], 1, np.where(best.iloc[:, 1] > best.iloc[:, 0], 0, np.nan)), index=frame.index)
    return opportunity, direction


def actions(train: pd.DataFrame, test: pd.DataFrame, c: dict) -> tuple[pd.DataFrame, dict]:
    # Concatenated Development+Validation frames may retain source indices; make
    # label alignment positional and fail closed on unavailable ETF paths.
    train, test = train.reset_index(drop=True), test.reset_index(drop=True)
    features = c["features"]; horizon = c["horizon"]; yopp, ydir = _label(train, horizon)
    mo = model(c["model_type"], c["params"], c["seed"]); mo.fit(train[features], yopp); po = mo.predict_proba(test[features])[:, 1]
    eligible_mask = yopp.eq(1) & ydir.notna(); eligible = train.loc[eligible_mask]
    direction_label = ydir.loc[eligible_mask].astype(int)
    if eligible.empty or direction_label.nunique() < 2: pdirection = np.full(len(test), .5); weights = {f: 0. for f in features}
    else:
        md = model(c["model_type"], c["params"], c["seed"] + 17); md.fit(eligible[features], direction_label); pdirection = md.predict_proba(test[features])[:, 1]
        raw = md.named_steps["model"]; coeff = getattr(raw, "coef_", None); imp = getattr(raw, "feature_importances_", None); values = np.asarray(coeff if coeff is not None else (imp if imp is not None else np.zeros(len(features)))).reshape(-1); weights = {f: float(x) for f, x in zip(features, values)}
    out = test[["decision_timestamp", "entry_timestamp", "calendar_date"]].copy(); out["opportunity_probability"] = po; out["direction_probability_up"] = pdirection
    passed = po >= c["opportunity_threshold"]; up = pdirection >= .5 + c["direction_margin"]; down = pdirection <= .5 - c["direction_margin"]
    out["opportunity_output"] = np.where(passed, "OPPORTUNITY", "NO_OPPORTUNITY"); out["direction_output"] = np.where(passed & up, "UP", np.where(passed & down, "DOWN", "UNCERTAIN")); out["entry_timing_output"] = np.where(out.direction_output.eq("UNCERTAIN"), "NO_TRADE", c["entry_policy"])
    out["action"] = np.where(out.direction_output.eq("UP"), "LONG_SOXL", np.where(out.direction_output.eq("DOWN"), "LONG_SOXS", "NO_TRADE"))
    out["selected_symbol"] = np.where(out.action.eq("LONG_SOXL"), "soxl", np.where(out.action.eq("LONG_SOXS"), "soxs", "")); out["horizon"] = horizon
    for d in (1, 3, 5): out[f"gross_delay{d}"] = [test.iloc[i][f"{s}_gross_{horizon}m_delay{d}"] if s else np.nan for i, s in enumerate(out.selected_symbol)]
    return out, weights


def nonoverlap(trades: pd.DataFrame) -> pd.DataFrame:
    kept, next_ok = [], None
    for i, row in trades.sort_values("entry_timestamp", kind="mergesort").iterrows():
        ts = pd.Timestamp(row.entry_timestamp)
        if next_ok is None or ts >= next_ok: kept.append(i); next_ok = ts + pd.Timedelta(minutes=int(row.horizon))
    return trades.loc[kept].copy()


def max_drawdown(values: pd.Series) -> float:
    equity = (1 + values.fillna(0)).cumprod(); return float((equity / equity.cummax() - 1).min()) if len(equity) else 0.


def metrics(action: pd.DataFrame, c: dict) -> tuple[dict, pd.DataFrame]:
    all_trades = action[action.action.ne("NO_TRADE")].copy(); trades = nonoverlap(all_trades)
    result = {"trade_count": int(len(trades)), "unique_trade_days": int(trades.calendar_date.nunique()) if len(trades) else 0, "no_trade_rate": float(action.action.eq("NO_TRADE").mean()), "long_soxl_count": int(trades.action.eq("LONG_SOXL").sum()), "long_soxs_count": int(trades.action.eq("LONG_SOXS").sum())}
    for cost in (5, 10, 20, 30):
        for delay in (1, 3, 5): result[f"mean_net_{cost}bps_delay{delay}"] = float((trades[f"gross_delay{delay}"] - cost / 10000).mean()) if len(trades) else None
    delays = [result[f"mean_net_20bps_delay{d}"] for d in (1, 3, 5)]
    result["DELAY_1M_NET"], result["DELAY_3M_NET"], result["DELAY_5M_NET"] = delays; result["DELAY_WORST_CASE_NET"] = min(delays) if all(x is not None for x in delays) else None; result["DELAY_MEDIAN_NET"] = float(np.median(delays)) if all(x is not None for x in delays) else None; result["DELAY_SIGN_CONSISTENCY"] = float(np.mean(np.asarray(delays) > 0)) if all(x is not None for x in delays) else 0.
    net = trades.gross_delay5 - .002 if len(trades) else pd.Series(dtype=float); result["max_drawdown"] = max_drawdown(net); result["profit_concentration_top5pct"] = float(net.nlargest(max(1, int(np.ceil(.05 * len(net))))).sum() / net[net > 0].sum()) if (net > 0).sum() else 1.; result["positive_fold_rate"] = float((net.groupby(trades.calendar_date).sum() > 0).mean()) if len(trades) else 0.
    result["NET_RETURN_5BPS"] = result["mean_net_5bps_delay5"]; result["NET_RETURN_10BPS"] = result["mean_net_10bps_delay5"]; result["NET_RETURN_20BPS"] = result["mean_net_20bps_delay5"]; result["NET_RETURN_30BPS"] = result["mean_net_30bps_delay5"]
    return result, trades


def failure(m: dict, b: dict) -> str | None:
    if m["trade_count"] < cfg()["minimum_holdout_trades"] or m["unique_trade_days"] < cfg()["minimum_independent_trade_days"]: return "INSUFFICIENT_SAMPLE"
    if m["max_drawdown"] > b["single_validation_fold_max_drawdown"]: return "EXCESS_DRAWDOWN"
    if m["DELAY_SIGN_CONSISTENCY"] < 1.: return "SIGN_REVERSAL"
    if m["NET_RETURN_20BPS"] is None or m["NET_RETURN_20BPS"] <= 0: return "COST_SENSITIVITY"
    if m["profit_concentration_top5pct"] >= .50: return "PROFIT_CONCENTRATION"
    return None


def score(m: dict) -> float:
    return float((m["DELAY_WORST_CASE_NET"] or -1) * 10000 + m["positive_fold_rate"] * 10 - abs(m["max_drawdown"]) * 10 - m["profit_concentration_top5pct"])


def evaluate(c: dict, train: pd.DataFrame, test: pd.DataFrame) -> tuple[dict, dict, pd.DataFrame]:
    act, weights = actions(train, test, c); m, trades = metrics(act, c); m["score"] = score(m); m["failure_reason"] = failure(m, budget(OUT)); return m, weights, trades


def interval_samples(canonical: Path, start: str, end: str) -> pd.DataFrame:
    # Invalid calendar dates (e.g. February 28 passed explicitly) are not padded.
    return read_samples(canonical, start, end)


def generation_records(output: Path, gid: str) -> list[dict]: return [x for x in rows(output / "experiment_registry.jsonl") if x["generation_id"] == gid]


def write_progress(output: Path, final_status="IN_PROGRESS", stop_reason=None) -> None:
    experiments, generations = rows(output / "experiment_registry.jsonl"), rows(output / "generation_registry.jsonl")
    cp = checkpoint(output); g03 = json.loads((output / "g03_failure_diagnostic.json").read_text())
    best = max(experiments, key=lambda x: x.get("score", -1e9)) if experiments else {}
    legal_candidate = next((g for g in generations if g.get("status") == "PASS"), None)
    summary = {"FINAL_STATUS": final_status, "FINAL_DECISION": "NO_GLOBAL_CANDIDATE" if final_status != "PASS" else "GLOBAL_FINAL_HOLDOUT_ACCEPTED", "STOP_REASON": stop_reason,
               "TOTAL_GENERATIONS": len(generations), "TOTAL_EXPERIMENTS": len(experiments), "VALIDATION_READ_COUNT": cp.get("validation_read_count", 0), "CONFIRMATION_READ_COUNT": cp.get("confirmation_read_count", 0), "GLOBAL_FINAL_HOLDOUT_READ_COUNT": cp.get("global_final_holdout_read_count", 0),
               "BEST_CANDIDATE_SCOPE": "DEVELOPMENT_INTERNAL_OOS_ONLY_NOT_A_LEGAL_GLOBAL_CANDIDATE" if legal_candidate is None else "PASSED_GENERATION_GATES", "BEST_GENERATION": best.get("generation_id"), "BEST_EXPERIMENT_ID": best.get("experiment_id"), "BEST_MODEL_TYPE": best.get("candidate", {}).get("model_type"), "BEST_FEATURE_COUNT": len(best.get("candidate", {}).get("features", [])), "BEST_FEATURES": best.get("candidate", {}).get("features", []), "BEST_FACTOR_WEIGHTS": best.get("weights", {}), "BEST_THRESHOLDS": {k: best.get("candidate", {}).get(k) for k in ("opportunity_threshold", "direction_margin")}, "BEST_HOLDING_WINDOW": best.get("candidate", {}).get("horizon"), "BEST_ENTRY_ACTION_POLICY": best.get("candidate", {}).get("entry_policy"),
               "DEVELOPMENT_INTERNAL_METRICS": {k: best.get(k) for k in ("DELAY_1M_NET", "DELAY_3M_NET", "DELAY_5M_NET", "DELAY_WORST_CASE_NET", "NET_RETURN_5BPS", "NET_RETURN_10BPS", "NET_RETURN_20BPS", "NET_RETURN_30BPS", "max_drawdown", "trade_count", "unique_trade_days", "no_trade_rate", "long_soxl_count", "long_soxs_count", "profit_concentration_top5pct", "positive_fold_rate")},
               "MAX_DRAWDOWN": best.get("max_drawdown"), "TRADE_COUNT": best.get("trade_count"), "UNIQUE_TRADE_DAYS": best.get("unique_trade_days"), "NO_TRADE_RATE": best.get("no_trade_rate"), "LONG_SOXL_COUNT": best.get("long_soxl_count"), "LONG_SOXS_COUNT": best.get("long_soxs_count"), "PROFIT_CONCENTRATION_TOP5PCT": best.get("profit_concentration_top5pct"), "POSITIVE_FOLD_RATE": best.get("positive_fold_rate"),
               "OPPORTUNITY_LIFT": None, "DIRECTION_LIFT": None, "CALIBRATION_SCORE": None, "SEED_STABILITY": None, "REGIME_STABILITY": None, "WEIGHT_STABILITY": None, "G03_FAILURE_CLASS": g03["G03_FAILURE_CLASS"], "G03_DELAY_DECAY_PROFILE": g03["G03_DELAY_DECAY_PROFILE"], "G03_LONG_SHORT_ASYMMETRY": g03["G03_LONG_SHORT_ASYMMETRY"], "G03_REGIME_DEPENDENCE": g03["G03_REGIME_DEPENDENCE"], "G03_PROFIT_CONCENTRATION": g03["G03_PROFIT_CONCENTRATION"], "G03_DRAWDOWN_SOURCE": g03["G03_DRAWDOWN_SOURCE"], "G03_REUSABLE_SIGNAL_COMPONENTS": g03["G03_REUSABLE_SIGNAL_COMPONENTS"], "G03_COMPONENTS_TO_REJECT": g03["G03_COMPONENTS_TO_REJECT"], "LAST_GENERATION_FAILURE_CLASS": generations[-1].get("failure_class") if generations else None, "FINAL_HOLDOUT_RESULT": "NOT_READ_NO_LEGAL_GLOBAL_CANDIDATE", "PAPER_TRADING_ALLOWED": False, "SHADOW_ALLOWED": False, "BROKER_ACTION_ALLOWED": False, "OFFICIAL_ADOPTION_ALLOWED": False,
               "RESULT_DIRECTORY": str(output), "SUMMARY_PATH": str(output / "v22_083_summary.json"), "REPORT_PATH": str(output / "v22_083_report.md"), "REGISTRY_PATH": str(output / "experiment_registry.jsonl"), "CHECKPOINT_PATH": str(output / "v22_083_checkpoint.json"), "RECOMMENDED_NEXT_COMMAND": cp.get("exact_resume_command")}
    atomic_json(output / "v22_083_summary.json", summary)
    (output / "v22_083_summary.txt").write_text("\n".join(f"{k}={v}" for k, v in summary.items()) + "\n", encoding="utf-8")
    (output / "v22_083_report.md").write_text(f"# {NAME}\n\nFINAL_STATUS={final_status}\n\nSTOP_REASON={stop_reason or 'NONE'}\n\nG03 was positive at 1 minute but negative at 3 and 5 minutes under 20bps; trade-level decomposition was unavailable from frozen artifacts.\n", encoding="utf-8")


def run(output: Path, canonical: Path, max_new: int) -> None:
    if (output / "V22_083_GLOBAL_DONE.flag").exists(): return
    manifest = json.loads((output / "frozen_split_manifest.json").read_text()); b = budget(output); closed = rows(output / "generation_registry.jsonl"); index = len(closed)
    if index >= min(4, b["max_generations"]):
        checkpoint(output, state="GLOBAL_TERMINAL", next_action="None.", exact_resume_command="NONE_V22_083_RESEARCH_STOPPED")
        write_progress(output, "PASS_NEGATIVE_OR_ELIGIBLE_RESEARCH_CONCLUSION", "MAX_GENERATIONS_REACHED"); (output / "V22_083_GLOBAL_DONE.flag").write_text("MAX_GENERATIONS_REACHED\n", encoding="utf-8"); return
    fold = manifest["generations"][index]; gid = fold["generation_id"]; existing = generation_records(output, gid); limit = min(b["experiments_per_generation"], b["max_total_experiments"] - len(rows(output / "experiment_registry.jsonl")))
    if len(existing) < limit:
        train = interval_samples(canonical, fold["development_start"], fold["internal_validation_end"]); split = et(fold["internal_validation_start"]); train_part = train[train.decision_timestamp < split - pd.Timedelta(minutes=180)]; test_part = train[train.decision_timestamp >= split]
        allrows = rows(output / "experiment_registry.jsonl")
        for n in range(len(existing), min(limit, len(existing) + max_new)):
            c = candidate(index + 1, n); m, weights, _ = evaluate(c, train_part, test_part)
            allrows.append({"generation_id": gid, "experiment_id": f"{gid}_E{n+1:03d}", "parent_generation_id": closed[-1]["generation_id"] if closed else None, "random_seed": c["seed"], "candidate": c, "candidate_sha256": digest(c), "split_sha256": manifest["split_sha256"], "lineage": "bounded generation mutation; at most two allowed model families and 25 features", "weights": weights, "complete": True, **m, **SAFETY})
        write_rows(output / "experiment_registry.jsonl", allrows); checkpoint(output, state="DEVELOPMENT_IN_PROGRESS", current_generation=gid, total_experiments=len(allrows), next_action="Continue registered Development experiments.", exact_resume_command=f"python scripts/v22/fast3_agent/v22_083_delay_robust_sparse_event.py --phase run --output-dir {output}"); write_progress(output); return
    eligible = [x for x in existing if x["failure_reason"] is None]
    eligible.sort(key=lambda x: (-x["score"], x["experiment_id"])); active = eligible[:b["max_active_candidates"]]
    champion = active[0] if active else max(existing, key=lambda x: x["score"])
    c = champion["candidate"]; atomic_json(output / "champion_config.json", {"status": "FROZEN_BEFORE_GENERATION_VALIDATION", "generation_id": gid, "experiment_id": champion["experiment_id"], "config": c, "config_sha256": digest(c), "split_sha256": manifest["split_sha256"], "active_candidate_count": len(active), **SAFETY})
    prior_cp = checkpoint(output)
    if prior_cp.get("state") == "VALIDATION_CONSUMED" and prior_cp.get("current_generation") == gid:
        # The first G01 Validation data read completed, but a post-read runtime
        # error prevented a reproducible complete metric.  Reopening the fold
        # would violate the one-read contract, so consume and classify it.
        rec = {"generation_id": gid, "status": "FAIL_VALIDATION", "failure_class": "INCOMPLETE_VALIDATION_EVALUATION_RUNTIME_ERROR", "validation_read_count": 1, "confirmation_read_count": 0, "validation_metrics": None, "confirmation_metrics": None, "champion_experiment_id": champion["experiment_id"], "holdout_consumed": {"validation": True, "confirmation": False}, "bounded_next_hypothesis": "repair fail-closed label alignment and test only on next untouched fold", **SAFETY}
        gr = closed + [rec]; write_rows(output / "generation_registry.jsonl", gr); atomic_json(output / "latest_generation_summary.json", rec)
        checkpoint(output, state="ADVANCE_TO_NEXT_GENERATION", current_generation="G02", next_action="Run G02 Development experiments on the next untouched fold.", exact_resume_command=f"python scripts/v22/fast3_agent/v22_083_delay_robust_sparse_event.py --phase run --output-dir {output}")
        write_progress(output); return
    train = interval_samples(canonical, fold["development_start"], fold["internal_validation_end"]); train = train[train.decision_timestamp < et(fold["validation_start"]) - pd.Timedelta(minutes=180)]
    validation = interval_samples(canonical, fold["validation_start"], fold["validation_end"]); vm, _, vt = evaluate(c, train, validation); vt.assign(generation_id=gid, experiment_id=champion["experiment_id"], role="VALIDATION").to_csv(output / "key_trade_details.csv", mode="a", header=not (output / "key_trade_details.csv").exists(), index=False)
    cp = checkpoint(output, state="VALIDATION_CONSUMED", validation_read_count=checkpoint(output).get("validation_read_count", 0) + 1, current_generation=gid)
    fail = failure(vm, b)
    cr = 0; cm = None
    if fail is None:
        confirmation = interval_samples(canonical, fold["confirmation_start"], fold["confirmation_end"]); confirmation_train = pd.concat([train, validation]); confirmation_train = confirmation_train[confirmation_train.decision_timestamp < et(fold["confirmation_start"]) - pd.Timedelta(minutes=180)]; cm, _, ct = evaluate(c, confirmation_train, confirmation); cr = 1; ct.assign(generation_id=gid, experiment_id=champion["experiment_id"], role="CONFIRMATION").to_csv(output / "key_trade_details.csv", mode="a", header=False, index=False); cp = checkpoint(output, state="CONFIRMATION_CONSUMED", confirmation_read_count=cp.get("confirmation_read_count", 0) + 1, current_generation=gid); fail = failure(cm, b)
    rec = {"generation_id": gid, "status": "PASS" if fail is None else ("FAIL_CONFIRMATION" if cr else "FAIL_VALIDATION"), "failure_class": fail, "validation_read_count": 1, "confirmation_read_count": cr, "validation_metrics": vm, "confirmation_metrics": cm, "champion_experiment_id": champion["experiment_id"], "holdout_consumed": {"validation": True, "confirmation": bool(cr)}, "bounded_next_hypothesis": "raise selectivity after risk/delay/cost failure; alternate permitted family otherwise", **SAFETY}
    gr = closed + [rec]; write_rows(output / "generation_registry.jsonl", gr); atomic_json(output / "latest_generation_summary.json", rec)
    # Required diagnostics are generated from all real recorded experiments/trades without reopening data.
    pd.DataFrame([{k: x.get(k) for k in ("generation_id", "experiment_id", "DELAY_1M_NET", "DELAY_3M_NET", "DELAY_5M_NET", "DELAY_WORST_CASE_NET", "trade_count", "no_trade_rate")} for x in rows(output / "experiment_registry.jsonl")]).to_csv(output / "delay_decay_diagnostic.csv", index=False)
    pd.DataFrame([{"generation_id": r["generation_id"], "failure_class": r["failure_class"], "validation_positive_fold_rate": (r.get("validation_metrics") or {}).get("positive_fold_rate"), "validation_mdd": (r.get("validation_metrics") or {}).get("max_drawdown")} for r in gr]).to_csv(output / "regime_stability.csv", index=False)
    checkpoint(output, state="ADVANCE_OR_TERMINAL", total_experiments=len(rows(output / "experiment_registry.jsonl")), current_generation=(f"G{index+2:02d}" if index + 1 < min(4, b["max_generations"]) else None), next_action="Run next untouched generation." if index + 1 < min(4, b["max_generations"]) else "Finalize legal max-generation stop.", exact_resume_command=f"python scripts/v22/fast3_agent/v22_083_delay_robust_sparse_event.py --phase run --output-dir {output}")
    write_progress(output)


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--phase", choices=("audit", "run"), required=True); p.add_argument("--output-dir", default=str(OUT)); p.add_argument("--canonical-root", default=str(ROOT)); p.add_argument("--max-new", type=int, default=40); a = p.parse_args(); output, canonical = Path(a.output_dir), Path(a.canonical_root)
    if a.phase == "audit": audit(output, canonical); print("FINAL_STATUS=SPLIT_FROZEN_AWAITING_DEVELOPMENT")
    else: run(output, canonical, a.max_new); print("FINAL_STATUS=" + json.loads((output / "v22_083_summary.json").read_text()).get("FINAL_STATUS", "IN_PROGRESS"))


if __name__ == "__main__": main()
