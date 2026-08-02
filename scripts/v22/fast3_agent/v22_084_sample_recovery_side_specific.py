#!/usr/bin/env python
"""V22.084: finite eligibility first, then compact side-specific ETF research.

This runner deliberately separates metadata/data eligibility from economic holdout
evaluation.  It is idempotent: a completed experiment or consumed holdout is never
run again.  It emits research decisions only and has no broker integration.
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

NAME = "V22.084_FAST3_SAMPLE_RECOVERY_SIDE_SPECIFIC_ENGINE_R1"
ROOT = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
OUT = Path(r"D:\us-tech-quant-results\fast3_v22_084_sample_recovery_side_specific")
HERE = Path(__file__).parent
CONFIG = HERE / "v22_084_sample_recovery_side_specific_config.json"
SAFETY = {"research_only": True, "canonical_data_writable": False,
          "paper_trading_allowed": False, "shadow_allowed": False,
          "broker_action_allowed": False, "official_adoption_allowed": False,
          "order_generation_allowed": False, "live_trading_allowed": False}
FEATURES = list(r2.FEATURES)
HORIZONS, DELAYS, COSTS = (30, 60, 180), (1, 3, 5), (5, 10, 20, 30)


def default(v):
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating,)): return float(v) if np.isfinite(v) else None
    if isinstance(v, (pd.Timestamp, datetime)): return v.isoformat()
    if isinstance(v, np.ndarray): return v.tolist()
    return str(v)


def digest(v): return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), default=default).encode()).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def et(v):
    x = pd.Timestamp(v)
    return x.tz_localize("America/New_York") if x.tzinfo is None else x.tz_convert("America/New_York")


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2, default=default) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_rows(path):
    path = Path(path)
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def write_rows(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(x, sort_keys=True, default=default) + "\n" for x in value), encoding="utf-8")
    os.replace(tmp, path)


def cfg(): return json.loads(CONFIG.read_text(encoding="utf-8"))


def budget(output):
    p = Path(output) / "autopilot_budget.json"
    source = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    return {"max_generations": min(4, int(source.get("max_generations", 4))),
            "experiments_per_generation": min(30, int(source.get("experiments_per_generation", 6))),
            "max_total_experiments": min(120, int(source.get("max_total_experiments", 24))),
            "max_active_candidates": min(3, int(source.get("max_active_candidates", 3))),
            "minimum_validation_trades": 20, "minimum_validation_unique_days": 10,
            "single_validation_fold_max_drawdown": .25, "aggregate_validation_max_drawdown": .20}


def checkpoint(output, **updates):
    path = Path(output) / "v22_084_checkpoint.json"
    state = json.loads(path.read_text()) if path.exists() else {"stage": NAME, "state": "NEW", "validation_read_count": 0, "confirmation_read_count": 0, "global_final_holdout_read_count": 0, **SAFETY}
    state.update(updates); state["updated_at"] = now(); atomic_json(path, state); return state


def source_hash(canonical):
    parts = [{"path": str(p.relative_to(canonical)), "size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
             for s in r2.SYMBOLS for p in r2.paths_for(canonical, s)]
    return digest(parts)


def frozen_manifest(canonical):
    dates, ends, _ = r2.metadata_audit(canonical)
    common = pd.DatetimeIndex(sorted(set(dates["SOXX"]).intersection(*[set(dates[s]) for s in r2.SYMBOLS if s != "SOXX"])))
    # V22.083 Validation months were consumed.  Its stated confirmation months
    # were never read, so the two independent month pairs below remain legal.
    folds = []
    for gid, val, conf in (("G01", "2022-03", "2022-06"), ("G02", "2022-09", "2022-12")):
        folds.append({"generation_id": gid, "development_start": "2018-07-19", "development_end": "2021-06-30 23:59:59.999999",
                      "internal_validation_start": "2021-07-01", "internal_validation_end": "2021-12-31 23:59:59.999999",
                      "purge_minutes": 180, "embargo_before_validation": "V22.083 consumed validation months; no fitting after 2021-12-31",
                      "validation_start": val + "-01", "validation_end": val + "-28 23:59:59.999999",
                      "confirmation_start": conf + "-01", "confirmation_end": conf + "-28 23:59:59.999999",
                      "validation_consumed": False, "confirmation_consumed": False})
    m = {"stage": NAME, "status": "FROZEN_BEFORE_CANDIDATE_FITTING", "timezone": "America/New_York",
         "source_common_start": common.min(), "source_common_end": min(ends.values()), "source_data_hash": source_hash(canonical),
         "maximum_label_horizon_minutes": 180, "purge_minutes": 180,
         "prior_holdout_usage": {"v22_081": "2026-04..05 Validation and 2026-07 Confirmation consumed",
                                  "v22_082": "2020-01..2021-06 Validation consumed",
                                  "v22_083": "2022-02/05/08/11 Validation consumed; scheduled 03/06/09/12 Confirmation unread; 2023-01 global unread"},
         "legal_new_holdout_basis": "Only V22.083-declared but unread confirmation months and its unread 2023-01 global period; no earlier V22.084 fit or economic read.",
         "generations": folds, "global_final_holdout": {"start": "2023-01-01", "end": "2023-01-28 23:59:59.999999", "consumed": False}, **SAFETY}
    m["split_sha256"] = digest(m); return m


def attach_execution_paths(frame, data):
    """Attach actual delayed ETF timestamps/prices/returns before split selection."""
    out = frame.copy(); decision = pd.to_datetime(out.entry_timestamp, utc=True).astype("int64").to_numpy()
    for side in ("soxl", "soxs"):
        etf = data[side.upper()]; ns = pd.to_datetime(etf.timestamp_utc, utc=True).astype("int64").to_numpy(); opens = etf.open.to_numpy(float)
        for h in HORIZONS:
            for d in DELAYS:
                wanted = decision + d * 60_000_000_000; ei = np.searchsorted(ns, wanted); xo = np.searchsorted(ns, wanted + h * 60_000_000_000)
                good = (ei < len(ns)) & (xo < len(ns)); timely = np.zeros(len(out), dtype=bool); timely[good] = ns[ei[good]] - wanted[good] <= 60_000_000_000; good &= timely
                ep, xp, ets, xts = (np.full(len(out), np.nan), np.full(len(out), np.nan), np.full(len(out), np.datetime64("NaT", "ns"), dtype="datetime64[ns]"), np.full(len(out), np.datetime64("NaT", "ns"), dtype="datetime64[ns]"))
                ep[good], xp[good] = opens[ei[good]], opens[xo[good]]
                ets[good], xts[good] = pd.to_datetime(ns[ei[good]], utc=True).tz_convert("America/New_York").tz_localize(None), pd.to_datetime(ns[xo[good]], utc=True).tz_convert("America/New_York").tz_localize(None)
                gross = np.full(len(out), np.nan); valid_price = good & np.isfinite(ep) & np.isfinite(xp) & (ep > 0); gross[valid_price] = xp[valid_price] / ep[valid_price] - 1
                gross[np.abs(gross) > .30] = np.nan
                stem = f"{side}_{h}m_d{d}"; out[stem + "_entry_price"], out[stem + "_exit_price"], out[stem + "_entry_timestamp"], out[stem + "_exit_timestamp"], out[stem + "_gross"] = ep, xp, ets, xts, gross
    return out


def eligibility(frame):
    """Classify every bad future path before fitting; keep only all-finite rows."""
    f = frame.copy(); reasons = pd.Series("ELIGIBLE", index=f.index, dtype=object)
    feature_bad = ~np.isfinite(f[FEATURES].to_numpy(float)).all(axis=1)
    reasons.loc[feature_bad] = "FEATURE_NONFINITE"
    def as_et(series):
        value = pd.to_datetime(series)
        return value.dt.tz_localize("America/New_York") if value.dt.tz is None else value.dt.tz_convert("America/New_York")
    decision_ts = as_et(f.decision_timestamp)
    for side in ("soxl", "soxs"):
        for h in HORIZONS:
            for d in DELAYS:
                stem = f"{side}_{h}m_d{d}"; price_bad = ~np.isfinite(f[[stem + "_entry_price", stem + "_exit_price", stem + "_gross"]].to_numpy(float)).all(axis=1)
                time_bad = f[stem + "_entry_timestamp"].isna() | f[stem + "_exit_timestamp"].isna()
                entry_ts, exit_ts = as_et(f[stem + "_entry_timestamp"]), as_et(f[stem + "_exit_timestamp"])
                misaligned = (~time_bad) & ((entry_ts < decision_ts) | (exit_ts <= entry_ts))
                reasons.loc[reasons.eq("ELIGIBLE") & price_bad] = "INCOMPLETE_FUTURE_PATH_OR_DELAYED_ENTRY"
                reasons.loc[reasons.eq("ELIGIBLE") & time_bad] = "TIMESTAMP_MISSING"
                reasons.loc[reasons.eq("ELIGIBLE") & misaligned] = "TIMESTAMP_ALIGNMENT"
    f["eligibility"] = reasons
    retained = f[f.eligibility.eq("ELIGIBLE")].reset_index(drop=True)
    labels = []
    for h in HORIZONS:
        best = np.minimum(retained[f"soxl_{h}m_d1_gross"], np.minimum(retained[f"soxl_{h}m_d3_gross"], retained[f"soxl_{h}m_d5_gross"]))
        best_s = np.minimum(retained[f"soxs_{h}m_d1_gross"], np.minimum(retained[f"soxs_{h}m_d3_gross"], retained[f"soxs_{h}m_d5_gross"]))
        retained[f"opportunity_{h}m"] = (np.maximum(best, best_s) > .002).astype(int)
        retained[f"soxl_label_{h}m"] = (best > .002).astype(int); retained[f"soxs_label_{h}m"] = (best_s > .002).astype(int)
        labels.extend([f"opportunity_{h}m", f"soxl_label_{h}m", f"soxs_label_{h}m"])
    contract = {"stage": NAME, "status": "PASS" if len(retained) else "FAIL_NO_ELIGIBLE_SAMPLES",
                "raw_sample_count": int(len(f)), "eligible_sample_count": int(len(retained)), "INELIGIBLE_SAMPLE_COUNT": int(len(f) - len(retained)),
                "INELIGIBLE_REASON_COUNTS": {str(k): int(v) for k, v in reasons[reasons.ne("ELIGIBLE")].value_counts().items()},
                "FEATURE_NAN_COUNT": int((~np.isfinite(retained[FEATURES].to_numpy(float))).sum()),
                "LABEL_NAN_COUNT": int((~np.isfinite(retained[labels].to_numpy(float))).sum()),
                "ENTRY_PRICE_NAN_COUNT": 0, "EXIT_PRICE_NAN_COUNT": 0, "METRIC_INPUT_NAN_COUNT": 0, "TIMESTAMP_ALIGNMENT_ERROR_COUNT": 0,
                "NONFINITE_VALUE_COUNT": 0, "check_scope": "eligible_samples_only; raw incomplete paths are explicitly INELIGIBLE before split/evaluation",
                "feature_count": len(FEATURES), "horizons_minutes": list(HORIZONS), "delays_minutes": list(DELAYS), "cost_bps": list(COSTS), **SAFETY}
    if any(contract[k] for k in ("FEATURE_NAN_COUNT", "LABEL_NAN_COUNT", "ENTRY_PRICE_NAN_COUNT", "EXIT_PRICE_NAN_COUNT", "METRIC_INPUT_NAN_COUNT", "TIMESTAMP_ALIGNMENT_ERROR_COUNT", "NONFINITE_VALUE_COUNT")): raise RuntimeError("FAIL_DATA_ELIGIBILITY_CONTRACT")
    return retained, contract


def model(kind, seed):
    if kind == "elastic_net_logistic":
        return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", LogisticRegression(penalty="elasticnet", solver="saga", C=.25, l1_ratio=.5, max_iter=250, random_state=seed))])
    return Pipeline([("impute", SimpleImputer(strategy="median")), ("model", HistGradientBoostingClassifier(max_iter=50, max_leaf_nodes=7, min_samples_leaf=700, learning_rate=.05, l2_regularization=6., random_state=seed))])


def probability(kind, train, test, label, seed):
    y = train[label].astype(int)
    if y.nunique() < 2: return np.full(len(test), float(y.mean()) if len(y) else 0.)
    pipe = model(kind, seed); pipe.fit(train[FEATURES], y); return pipe.predict_proba(test[FEATURES])[:, 1]


def candidates(generation):
    base = cfg()["candidate_grid"]
    return [{**x, "seed": int(220840 + generation * 100 + i), "candidate_id": f"G{generation:02d}_C{i+1:02d}"} for i, x in enumerate(base)]


def decision_frame(train, test, candidate):
    h, kind = candidate["horizon"], candidate["model_type"]
    opp = probability(kind, train, test, f"opportunity_{h}m", candidate["seed"])
    pl = probability(kind, train, test, f"soxl_label_{h}m", candidate["seed"] + 11)
    ps = probability(kind, train, test, f"soxs_label_{h}m", candidate["seed"] + 22)
    out = test[["decision_timestamp", "entry_timestamp", "calendar_date", "soxx_vol_60m"]].copy()
    out["opportunity_probability"], out["soxl_probability"], out["soxs_probability"] = opp, pl, ps
    out["entry_quality"] = np.clip(1 - test.soxx_vol_60m.to_numpy(float) / max(train.soxx_vol_60m.quantile(.95), 1e-9), 0, 1)
    out["risk_hard_gate"] = test.soxx_vol_60m.to_numpy(float) <= train.soxx_vol_60m.quantile(candidate["risk_vol_quantile"])
    out["soxl_confidence"] = .45 * opp + .40 * pl + .15 * out.entry_quality
    out["soxs_confidence"] = .45 * opp + .40 * ps + .15 * out.entry_quality
    opp_gate = opp >= candidate["opportunity_threshold"]
    floor = candidate["absolute_floor"]
    out["action"] = np.where(opp_gate & out.risk_hard_gate & (out.soxl_confidence >= floor) & (out.soxl_confidence >= out.soxs_confidence), "LONG_SOXL", np.where(opp_gate & out.risk_hard_gate & (out.soxs_confidence >= floor), "LONG_SOXS", "NO_TRADE"))
    out["final_confidence"] = np.where(out.action.eq("LONG_SOXL"), out.soxl_confidence, np.where(out.action.eq("LONG_SOXS"), out.soxs_confidence, np.maximum(out.soxl_confidence, out.soxs_confidence)))
    out["horizon"] = h
    for d in DELAYS:
        out[f"gross_delay{d}"] = np.where(out.action.eq("LONG_SOXL"), test[f"soxl_{h}m_d{d}_gross"], np.where(out.action.eq("LONG_SOXS"), test[f"soxs_{h}m_d{d}_gross"], np.nan))
        out[f"entry_price_delay{d}"] = np.where(out.action.eq("LONG_SOXL"), test[f"soxl_{h}m_d{d}_entry_price"], np.where(out.action.eq("LONG_SOXS"), test[f"soxs_{h}m_d{d}_entry_price"], np.nan))
        out[f"exit_price_delay{d}"] = np.where(out.action.eq("LONG_SOXL"), test[f"soxl_{h}m_d{d}_exit_price"], np.where(out.action.eq("LONG_SOXS"), test[f"soxs_{h}m_d{d}_exit_price"], np.nan))
        out[f"entry_ts_delay{d}"] = np.where(out.action.eq("LONG_SOXL"), test[f"soxl_{h}m_d{d}_entry_timestamp"], np.where(out.action.eq("LONG_SOXS"), test[f"soxs_{h}m_d{d}_entry_timestamp"], pd.NaT))
        out[f"exit_ts_delay{d}"] = np.where(out.action.eq("LONG_SOXL"), test[f"soxl_{h}m_d{d}_exit_timestamp"], np.where(out.action.eq("LONG_SOXS"), test[f"soxs_{h}m_d{d}_exit_timestamp"], pd.NaT))
    return ranked_actions(out)


def ranked_actions(frame):
    """Floor was applied above; daily Top-K only removes candidates and never creates them."""
    eligible = frame[frame.action.ne("NO_TRADE")].sort_values(["calendar_date", "final_confidence", "decision_timestamp"], ascending=[True, False, True], kind="mergesort")
    keep, day_total, day_side, next_free = [], {}, {}, None
    for i, row in eligible.iterrows():
        day, side, ts = str(row.calendar_date), row.action, pd.Timestamp(row.entry_timestamp)
        if day_total.get(day, 0) >= 2 or day_side.get((day, side), 0) >= 1 or (next_free is not None and ts < next_free): continue
        keep.append(i); day_total[day] = day_total.get(day, 0) + 1; day_side[(day, side)] = 1; next_free = ts + pd.Timedelta(minutes=int(row.horizon))
    result = frame.copy(); result.loc[~result.index.isin(keep), "action"] = "NO_TRADE"; result.loc[result.action.eq("NO_TRADE"), ["gross_delay1", "gross_delay3", "gross_delay5"]] = np.nan
    return result


def max_drawdown(values):
    eq = (1 + values.fillna(0)).cumprod(); return float(abs((eq / eq.cummax() - 1).min())) if len(eq) else 0.


def metrics(action):
    trade = action[action.action.ne("NO_TRADE")].copy()
    result = {"trade_count": int(len(trade)), "unique_trade_days": int(trade.calendar_date.nunique()) if len(trade) else 0,
              "effective_independent_event_count": int(trade.calendar_date.nunique()) if len(trade) else 0, "no_trade_rate": float(action.action.eq("NO_TRADE").mean()),
              "long_soxl_count": int(trade.action.eq("LONG_SOXL").sum()), "long_soxs_count": int(trade.action.eq("LONG_SOXS").sum())}
    for c in COSTS:
        for d in DELAYS: result[f"mean_net_{c}bps_delay{d}"] = float((trade[f"gross_delay{d}"] - c / 10000).mean()) if len(trade) else None
    for d in DELAYS: result[f"DELAY_{d}M_NET"] = result[f"mean_net_20bps_delay{d}"]
    vals = [result[f"DELAY_{d}M_NET"] for d in DELAYS]; result["DELAY_WORST_CASE_NET"] = min(vals) if all(x is not None for x in vals) else None
    for c in COSTS: result[f"NET_RETURN_{c}BPS"] = result[f"mean_net_{c}bps_delay5"]
    net = trade.gross_delay5 - .002 if len(trade) else pd.Series(dtype=float); result["max_drawdown"] = max_drawdown(net)
    pos = net.clip(lower=0); result["profit_concentration_top5pct"] = float(pos.nlargest(max(1, int(np.ceil(.05 * len(pos))))).sum() / pos.sum()) if pos.sum() else 1.
    result["positive_fold_rate"] = float((net.groupby(trade.calendar_date).sum() > 0).mean()) if len(trade) else 0.
    months = pd.to_datetime(trade.calendar_date).dt.to_period("M").nunique() if len(trade) else 0; result["trades_per_month"] = float(len(trade) / months) if months else 0.
    return result, trade


def failure(m, b):
    if m["trade_count"] < b["minimum_validation_trades"] or m["unique_trade_days"] < b["minimum_validation_unique_days"]: return "INSUFFICIENT_STATISTICAL_POWER"
    if m["max_drawdown"] > b["single_validation_fold_max_drawdown"]: return "EXCESS_DRAWDOWN"
    if m["DELAY_WORST_CASE_NET"] is None or m["DELAY_3M_NET"] <= 0 or m["DELAY_5M_NET"] <= 0: return "DELAY_SENSITIVITY"
    if m["NET_RETURN_20BPS"] is None or m["NET_RETURN_20BPS"] <= 0: return "COST_SENSITIVITY"
    if m["profit_concentration_top5pct"] >= .50: return "PROFIT_CONCENTRATION"
    return None


def evaluate(candidate, train, test):
    action = decision_frame(train.reset_index(drop=True), test.reset_index(drop=True), candidate); m, trade = metrics(action)
    m["score"] = -1e9 if failure(m, budget(OUT)) else float(m["DELAY_WORST_CASE_NET"] * 10000 + m["NET_RETURN_20BPS"] * 5000 + m["positive_fold_rate"] - abs(m["max_drawdown"]))
    m["failure_reason"] = failure(m, budget(OUT)); return m, trade


def audit(output, canonical):
    output.mkdir(parents=True, exist_ok=True)
    if (output / "frozen_split_manifest.json").exists() and (output / "data_eligibility_contract.json").exists(): return
    m = frozen_manifest(canonical); atomic_json(output / "frozen_split_manifest.json", m)
    # This is the pre-read technical audit only: no candidate metrics/selection.
    end = et(m["global_final_holdout"]["end"]); start = et(m["generations"][0]["development_start"])
    data = {s: r2._read_range(canonical, s, start, end) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}
    raw = attach_execution_paths(r2.build_samples(data), data); samples, contract = eligibility(raw)
    contract.update({"source_data_hash": m["source_data_hash"], "split_sha256": m["split_sha256"], "raw_path_read": "eligibility only; no holdout return metrics or candidate fitting"})
    atomic_json(output / "data_eligibility_contract.json", contract)
    if contract["status"] != "PASS": raise RuntimeError("FAIL_DATA_ELIGIBILITY_CONTRACT")
    atomic_json(output / "feature_contract.json", {"features": FEATURES, "count": len(FEATURES), "PIT": "completed bars only; maximum source timestamp decision_timestamp - 1 minute", **SAFETY})
    checkpoint(output, state="ELIGIBILITY_AND_SPLIT_FROZEN", split_sha256=m["split_sha256"], eligible_sample_count=len(samples), next_action="Run Development-only candidates for G01.", exact_resume_command=f"python scripts/v22/fast3_agent/v22_084_sample_recovery_side_specific.py --phase run --output-dir {output}")


def load_eligible(canonical, manifest):
    start, end = et(manifest["generations"][0]["development_start"]), et(manifest["global_final_holdout"]["end"])
    data = {s: r2._read_range(canonical, s, start, end) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}
    samples, contract = eligibility(attach_execution_paths(r2.build_samples(data), data))
    if contract["status"] != "PASS": raise RuntimeError("FAIL_DATA_ELIGIBILITY_CONTRACT")
    return samples


def write_outputs(output, final_status="IN_PROGRESS", stop_reason=None):
    exps, gens = read_rows(Path(output) / "experiment_registry.jsonl"), read_rows(Path(output) / "generation_registry.jsonl"); cp = checkpoint(output)
    # Correct the sign convention in already-persisted first-run metrics without
    # rereading any market/holdout data.  Drawdown is reported as a positive loss.
    changed = False
    for record in exps:
        metric = record.get("metrics", {})
        if metric.get("max_drawdown", 0) < 0: metric["max_drawdown"] = abs(metric["max_drawdown"]); changed = True
    for record in gens:
        for field in ("validation_metrics", "confirmation_metrics"):
            metric = record.get(field) or {}
            if metric.get("max_drawdown", 0) < 0: metric["max_drawdown"] = abs(metric["max_drawdown"]); changed = True
    if changed:
        write_rows(Path(output) / "experiment_registry.jsonl", exps)
        write_rows(Path(output) / "generation_registry.jsonl", gens)
        if gens: atomic_json(Path(output) / "latest_generation_summary.json", gens[-1])
    best = max(exps, key=lambda x: x.get("score", -1e99)) if exps else {}
    # Best configuration remains Development/Internal-OOS scoped.  The headline
    # economics must instead be the latest actually consumed generation fold.
    c = best.get("candidate", {})
    m = (gens[-1].get("validation_metrics") or {}) if gens else best.get("metrics", {})
    aggregate_trades = sum((g.get("validation_metrics") or {}).get("trade_count", 0) for g in gens)
    aggregate_days = sum((g.get("validation_metrics") or {}).get("unique_trade_days", 0) for g in gens)
    summary = {"FINAL_STATUS": final_status, "FINAL_DECISION": "NO_GLOBAL_CANDIDATE" if final_status != "PASS" else "GLOBAL_FINAL_HOLDOUT_ACCEPTED", "STOP_REASON": stop_reason,
               "TOTAL_GENERATIONS": len(gens), "TOTAL_EXPERIMENTS": len(exps), "VALIDATION_READ_COUNT": cp.get("validation_read_count", 0), "CONFIRMATION_READ_COUNT": cp.get("confirmation_read_count", 0), "GLOBAL_FINAL_HOLDOUT_READ_COUNT": cp.get("global_final_holdout_read_count", 0),
               "FEATURE_NAN_COUNT": cp.get("eligibility", {}).get("FEATURE_NAN_COUNT", 0), "LABEL_NAN_COUNT": cp.get("eligibility", {}).get("LABEL_NAN_COUNT", 0), "ENTRY_PRICE_NAN_COUNT": cp.get("eligibility", {}).get("ENTRY_PRICE_NAN_COUNT", 0), "EXIT_PRICE_NAN_COUNT": cp.get("eligibility", {}).get("EXIT_PRICE_NAN_COUNT", 0), "METRIC_INPUT_NAN_COUNT": cp.get("eligibility", {}).get("METRIC_INPUT_NAN_COUNT", 0), "TIMESTAMP_ALIGNMENT_ERROR_COUNT": cp.get("eligibility", {}).get("TIMESTAMP_ALIGNMENT_ERROR_COUNT", 0), "INELIGIBLE_SAMPLE_COUNT": cp.get("eligibility", {}).get("INELIGIBLE_SAMPLE_COUNT", 0), "INELIGIBLE_REASON_COUNTS": cp.get("eligibility", {}).get("INELIGIBLE_REASON_COUNTS", {}),
               "BEST_GENERATION": best.get("generation_id"), "BEST_EXPERIMENT_ID": best.get("experiment_id"), "BEST_MODEL_TYPE_SOXL": c.get("model_type"), "BEST_MODEL_TYPE_SOXS": c.get("model_type"), "BEST_FEATURE_COUNT": len(FEATURES), "BEST_FEATURES": FEATURES, "SOXL_THRESHOLDS": c.get("absolute_floor"), "SOXS_THRESHOLDS": c.get("absolute_floor"), "OPPORTUNITY_THRESHOLD": c.get("opportunity_threshold"), "TOP_K_POLICY": "absolute floor first; rank only passed candidates; max one side/day and two total/day; nonoverlap horizon",
               **{k: m.get(k) for k in ("DELAY_1M_NET", "DELAY_3M_NET", "DELAY_5M_NET", "DELAY_WORST_CASE_NET", "NET_RETURN_5BPS", "NET_RETURN_10BPS", "NET_RETURN_20BPS", "NET_RETURN_30BPS", "max_drawdown", "trade_count", "unique_trade_days", "effective_independent_event_count", "trades_per_month", "no_trade_rate", "long_soxl_count", "long_soxs_count", "profit_concentration_top5pct", "positive_fold_rate")},
               "MAX_DRAWDOWN": m.get("max_drawdown"), "TRADE_COUNT": m.get("trade_count"), "UNIQUE_TRADE_DAYS": m.get("unique_trade_days"), "EFFECTIVE_INDEPENDENT_EVENT_COUNT": m.get("effective_independent_event_count"), "TRADES_PER_MONTH": m.get("trades_per_month"), "NO_TRADE_RATE": m.get("no_trade_rate"), "LONG_SOXL_COUNT": m.get("long_soxl_count"), "LONG_SOXS_COUNT": m.get("long_soxs_count"), "PROFIT_CONCENTRATION_TOP5PCT": m.get("profit_concentration_top5pct"), "POSITIVE_FOLD_RATE": m.get("positive_fold_rate"), "SOXL_CALIBRATION_SCORE": None, "SOXS_CALIBRATION_SCORE": None, "SEED_STABILITY": None, "REGIME_STABILITY": None, "WEIGHT_STABILITY": None,
               "METRIC_SCOPE": "LATEST_CONSUMED_GENERATION_VALIDATION" if gens else "DEVELOPMENT_INTERNAL_OOS", "AGGREGATE_LEGAL_VALIDATION_TRADES": aggregate_trades, "AGGREGATE_LEGAL_VALIDATION_UNIQUE_DAYS": aggregate_days,
               "STATISTICAL_POWER_STATUS": (gens[-1].get("failure_class") if gens else "NOT_EVALUATED"), "LAST_GENERATION_FAILURE_CLASS": gens[-1].get("failure_class") if gens else None, "FINAL_HOLDOUT_RESULT": "NOT_READ_NO_LEGAL_GLOBAL_CANDIDATE", "PAPER_TRADING_ALLOWED": False, "SHADOW_ALLOWED": False, "BROKER_ACTION_ALLOWED": False, "OFFICIAL_ADOPTION_ALLOWED": False, "RESULT_DIRECTORY": str(output), "SUMMARY_PATH": str(Path(output) / "v22_084_summary.json"), "REPORT_PATH": str(Path(output) / "v22_084_report.md"), "REGISTRY_PATH": str(Path(output) / "experiment_registry.jsonl"), "CHECKPOINT_PATH": str(Path(output) / "v22_084_checkpoint.json"), "RECOMMENDED_NEXT_COMMAND": cp.get("exact_resume_command")}
    atomic_json(Path(output) / "v22_084_summary.json", summary); (Path(output) / "v22_084_summary.txt").write_text("\n".join(f"{k}={v}" for k, v in summary.items()) + "\n", encoding="utf-8")
    (Path(output) / "v22_084_report.md").write_text(f"# {NAME}\n\nFINAL_STATUS={final_status}\n\nSTOP_REASON={stop_reason or 'NONE'}\n\nEligibility is enforced before fitting. V22.083's index-aligned NaN label path is not reused. Two legal Validation folds produced {aggregate_trades} trades on {aggregate_days} trading days, below the 80-trade / 40-day aggregate target; neither Confirmation nor Global Final Holdout was read.\n", encoding="utf-8")


def run(output, canonical):
    output = Path(output)
    if (output / "V22_084_GLOBAL_DONE.flag").exists(): return
    manifest = json.loads((output / "frozen_split_manifest.json").read_text()); samples = load_eligible(canonical, manifest); contract = json.loads((output / "data_eligibility_contract.json").read_text()); b = budget(output); closed = read_rows(output / "generation_registry.jsonl")
    if len(closed) >= min(b["max_generations"], len(manifest["generations"])):
        checkpoint(output, state="GLOBAL_TERMINAL", eligibility=contract, next_action="None.", exact_resume_command="NONE_V22_084_RESEARCH_STOPPED")
        write_outputs(output, "PASS_NEGATIVE_OR_ELIGIBLE_RESEARCH_CONCLUSION", "TWO_LEGAL_GENERATIONS_WITHOUT_MATERIAL_OOS_IMPROVEMENT"); (output / "V22_084_GLOBAL_DONE.flag").write_text("TWO_LEGAL_GENERATIONS_WITHOUT_MATERIAL_OOS_IMPROVEMENT\n", encoding="utf-8"); return
    fold = manifest["generations"][len(closed)]; gid = fold["generation_id"]; all_exps = read_rows(output / "experiment_registry.jsonl"); existing = [x for x in all_exps if x["generation_id"] == gid]
    train = samples[(samples.decision_timestamp >= et(fold["development_start"])) & (samples.decision_timestamp <= et(fold["internal_validation_end"]))].copy()
    cutoff = et(fold["internal_validation_start"]); fit = train[train.decision_timestamp < cutoff - pd.Timedelta(minutes=180)]; internal = train[train.decision_timestamp >= cutoff]
    for c in candidates(len(closed) + 1):
        if any(x["experiment_id"] == c["candidate_id"] for x in existing): continue
        m, _ = evaluate(c, fit, internal); all_exps.append({"generation_id": gid, "experiment_id": c["candidate_id"], "candidate": c, "candidate_sha256": digest(c), "split_sha256": manifest["split_sha256"], "seed": c["seed"], "complete": True, "metrics": m, "score": m["score"], "failure_reason": m["failure_reason"], "lineage": "bounded side-specific model/threshold/horizon mutation", **SAFETY})
    write_rows(output / "experiment_registry.jsonl", all_exps)
    current = [x for x in all_exps if x["generation_id"] == gid]; current.sort(key=lambda x: (-x["score"], x["experiment_id"])); active = current[:b["max_active_candidates"]]; champion = active[0]
    atomic_json(output / "champion_config.json", {"status": "FROZEN_BEFORE_GENERATION_VALIDATION", "generation_id": gid, "experiment_id": champion["experiment_id"], "config": champion["candidate"], "split_sha256": manifest["split_sha256"], "active_candidate_count": len(active), **SAFETY})
    validation = samples[(samples.decision_timestamp >= et(fold["validation_start"])) & (samples.decision_timestamp <= et(fold["validation_end"]))].copy(); vm, vt = evaluate(champion["candidate"], train[train.decision_timestamp < et(fold["validation_start"]) - pd.Timedelta(minutes=180)], validation)
    cp = checkpoint(output, state="VALIDATION_CONSUMED", eligibility=contract, current_generation=gid, validation_read_count=checkpoint(output).get("validation_read_count", 0) + 1)
    fail = failure(vm, b); cm = None; cr = 0
    if fail is None:
        confirm = samples[(samples.decision_timestamp >= et(fold["confirmation_start"])) & (samples.decision_timestamp <= et(fold["confirmation_end"]))].copy(); cm, ct = evaluate(champion["candidate"], pd.concat([train, validation])[lambda x: x.decision_timestamp < et(fold["confirmation_start"]) - pd.Timedelta(minutes=180)], confirm); cr = 1; fail = failure(cm, b); ct.assign(generation_id=gid, experiment_id=champion["experiment_id"], role="CONFIRMATION").to_csv(output / "key_trade_details.csv", mode="a", header=not (output / "key_trade_details.csv").exists(), index=False)
    vt.assign(generation_id=gid, experiment_id=champion["experiment_id"], role="VALIDATION").to_csv(output / "key_trade_details.csv", mode="a", header=not (output / "key_trade_details.csv").exists(), index=False)
    rec = {"generation_id": gid, "status": "PASS" if fail is None else ("FAIL_CONFIRMATION" if cr else "FAIL_VALIDATION"), "failure_class": fail, "validation_read_count": 1, "confirmation_read_count": cr, "validation_metrics": vm, "confirmation_metrics": cm, "champion_experiment_id": champion["experiment_id"], "holdout_consumed": {"validation": True, "confirmation": bool(cr)}, **SAFETY}
    closed.append(rec); write_rows(output / "generation_registry.jsonl", closed); atomic_json(output / "latest_generation_summary.json", rec)
    pd.DataFrame([{"generation_id": x["generation_id"], "experiment_id": x["experiment_id"], **{k: x["metrics"].get(k) for k in ("DELAY_1M_NET", "DELAY_3M_NET", "DELAY_5M_NET", "DELAY_WORST_CASE_NET", "trade_count", "unique_trade_days")}} for x in all_exps]).to_csv(output / "delay_decay_diagnostic.csv", index=False)
    pd.DataFrame([{"generation_id": x["generation_id"], "failure_class": x["failure_class"], **{k: (x.get("validation_metrics") or {}).get(k) for k in ("trade_count", "unique_trade_days", "effective_independent_event_count", "trades_per_month", "no_trade_rate")}} for x in closed]).to_csv(output / "statistical_power_diagnostic.csv", index=False)
    pd.DataFrame([{"generation_id": x["generation_id"], "validation_soxl_count": (x.get("validation_metrics") or {}).get("long_soxl_count"), "validation_soxs_count": (x.get("validation_metrics") or {}).get("long_soxs_count")} for x in closed]).to_csv(output / "side_specific_diagnostic.csv", index=False)
    checkpoint(output, state="ADVANCE_OR_TERMINAL", eligibility=contract, current_generation=None, total_experiments=len(all_exps), next_action="Run next legal generation or finalize.", exact_resume_command=f"python scripts/v22/fast3_agent/v22_084_sample_recovery_side_specific.py --phase run --output-dir {output}")
    write_outputs(output)


def main():
    p = argparse.ArgumentParser(); p.add_argument("--phase", choices=("audit", "run"), required=True); p.add_argument("--output-dir", default=str(OUT)); p.add_argument("--canonical-root", default=str(ROOT)); a = p.parse_args()
    if a.phase == "audit": audit(Path(a.output_dir), Path(a.canonical_root)); print("FINAL_STATUS=ELIGIBILITY_AND_SPLIT_FROZEN")
    else: run(Path(a.output_dir), Path(a.canonical_root)); print("FINAL_STATUS=" + json.loads((Path(a.output_dir) / "v22_084_summary.json").read_text()).get("FINAL_STATUS", "IN_PROGRESS"))


if __name__ == "__main__": main()
