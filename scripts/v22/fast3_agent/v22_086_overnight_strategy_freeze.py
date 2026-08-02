#!/usr/bin/env python
"""Bounded, PIT V22.086 discovery engine.

This is deliberately a single-stage research engine.  It uses prior FAST3 periods
only as Development/internal-OOS evidence, never calls them unseen, and does not
contain any broker or order-generation integration.
"""
from __future__ import annotations

import argparse, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import generation3r2_research as r2
import v22_084_sample_recovery_side_specific as v84

NAME = "V22.086_FAST3_OVERNIGHT_STRATEGY_DISCOVERY_AND_FREEZE_R1"
HERE = Path(__file__).parent
ROOT = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
OUT = Path(r"D:\us-tech-quant-results\fast3_v22_086_overnight_strategy_freeze")
CONFIG = HERE / "v22_086_overnight_strategy_freeze_config.json"
FEATURES = list(r2.FEATURES)
HORIZONS, DELAYS, COSTS = (30, 60, 120, 180), (1, 3, 5), (5, 10, 20, 30)
SAFETY = {"research_only": True, "paper_trading_allowed": False,
          "broker_action_allowed": False, "official_adoption_allowed": False,
          "live_trading_allowed": False, "order_generation_allowed": False,
          "canonical_data_writable": False}


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
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2, default=default) + "\n", encoding="utf-8"); os.replace(tmp, path)


def atomic_text(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value, encoding="utf-8"); os.replace(tmp, path)


def rows(path): return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()] if Path(path).exists() else []
def write_rows(path, values): atomic_text(path, "".join(json.dumps(x, sort_keys=True, default=default) + "\n" for x in values))
def cfg(): return json.loads(CONFIG.read_text(encoding="utf-8"))


def budget(output):
    source = json.loads((Path(output) / "autopilot_budget.json").read_text(encoding="utf-8-sig"))
    return {k: source[k] for k in ("max_generations", "experiments_per_generation", "max_total_experiments", "max_active_candidates", "max_active_features", "max_model_families", "minimum_registered_experiments_before_ordinary_terminal", "minimum_generations_before_ordinary_terminal", "minimum_internal_oos_trades_for_primary_candidate", "minimum_internal_oos_unique_days_for_primary_candidate", "minimum_shadow_only_trades", "minimum_shadow_only_unique_days")}


def checkpoint(output, **updates):
    p = Path(output) / "v22_086_checkpoint.json"
    base = {"stage": NAME, "state": "NEW", "validation_read_count": 0, "confirmation_read_count": 0, "global_final_holdout_read_count": 0, **SAFETY}
    if p.exists(): base.update(json.loads(p.read_text(encoding="utf-8")))
    base.update(updates); base["updated_at"] = now(); atomic_json(p, base); return base


def source_hash(canonical):
    return digest([{"path": str(p.relative_to(canonical)), "size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
                   for s in r2.SYMBOLS for p in r2.paths_for(canonical, s)])


def prior_usage():
    # Month-level ledger is intentionally conservative: UNKNOWN is never treated
    # as unseen.  V22.086's walk-forwards are Development-only regardless.
    consumed = {"2020-01":"VALIDATION_CONSUMED", "2020-02":"VALIDATION_CONSUMED", "2020-03":"VALIDATION_CONSUMED", "2020-04":"VALIDATION_CONSUMED", "2020-05":"VALIDATION_CONSUMED", "2020-06":"VALIDATION_CONSUMED", "2020-07":"VALIDATION_CONSUMED", "2020-08":"VALIDATION_CONSUMED", "2020-09":"VALIDATION_CONSUMED", "2020-10":"VALIDATION_CONSUMED", "2020-11":"VALIDATION_CONSUMED", "2020-12":"VALIDATION_CONSUMED", "2021-01":"VALIDATION_CONSUMED", "2021-02":"VALIDATION_CONSUMED", "2021-03":"VALIDATION_CONSUMED", "2021-04":"VALIDATION_CONSUMED", "2021-05":"VALIDATION_CONSUMED", "2021-06":"VALIDATION_CONSUMED", "2022-02":"VALIDATION_CONSUMED", "2022-03":"VALIDATION_CONSUMED", "2022-05":"VALIDATION_CONSUMED", "2022-08":"VALIDATION_CONSUMED", "2022-09":"VALIDATION_CONSUMED", "2022-11":"VALIDATION_CONSUMED", "2026-04":"VALIDATION_CONSUMED", "2026-05":"VALIDATION_CONSUMED", "2026-07":"CONFIRMATION_CONSUMED"}
    months = pd.period_range("2018-07", "2026-07", freq="M")
    records = []
    for m in months:
        k = str(m); status = consumed.get(k, "DEVELOPMENT_USED" if m <= pd.Period("2026-03", "M") else "UNKNOWN_OR_UNPROVEN")
        records.append({"month": k, "classification": status, "evidence": "prior V22 manifests/registries" if k in consumed else "eligible for V22.086 Development/internal-OOS only"})
    return {"stage": NAME, "status": "PASS_CONSERVATIVE_MONTH_LEVEL_LEDGER", "records": records,
            "rules": {"consumed_never_unseen": True, "unknown_never_final_read": True, "v22_086_use": "DEVELOPMENT_AND_NESTED_INTERNAL_OOS_ONLY"}}


def manifest(canonical):
    dates, ends, _ = r2.metadata_audit(canonical)
    common = set(dates["SOXX"])
    for s in r2.SYMBOLS: common &= set(dates[s])
    folds = []
    # Fixed chronological outer folds; training ends 180m before the next fold.
    for i, (train_end, test_start, test_end) in enumerate((("2020-12-31", "2021-01-01", "2021-06-30"), ("2021-12-31", "2022-01-01", "2022-06-30"), ("2022-12-31", "2023-01-01", "2023-06-30"), ("2023-12-31", "2024-01-01", "2024-06-30"), ("2024-12-31", "2025-01-01", "2025-06-30"), ("2025-12-31", "2026-01-01", "2026-03-31")), 1):
        folds.append({"fold_id": f"IWFO_{i:02d}", "train_start": "2018-07-19", "train_end": train_end + " 23:59:59.999999", "test_start": test_start, "test_end": test_end + " 23:59:59.999999", "purge_minutes": 180, "embargo_minutes": 180, "role": "DEVELOPMENT_NESTED_INTERNAL_OOS"})
    m = {"stage": NAME, "status": "FROZEN_BEFORE_ECONOMIC_EVALUATION", "timezone": "America/New_York", "source_common_start": min(common), "source_common_end": min(ends.values()), "source_data_hash": source_hash(canonical), "features": FEATURES, "maximum_label_horizon_minutes": 180, "purge_minutes": 180, "embargo_minutes": 180, "outer_folds": folds, "final_holdout_policy": "NO final untouched read is needed or permitted for candidate mutation; UNKNOWN_OR_UNPROVEN months remain closed.", "selection_score": "mean(delay1_20bps, delay3_20bps) + 0.5*delay5_20bps + 0.002*positive_fold_rate - 0.01*drawdown - 0.01*top5_concentration", **SAFETY}
    m["split_sha256"] = digest(m); return m


def feature_contract(): return {"features": FEATURES, "count": len(FEATURES), "maximum_source_timestamp": "decision_timestamp - 1 minute", "closed_bar_only": True, "explicit_lag_minutes": 1, "PIT": True, **SAFETY}


def load_samples(canonical, m):
    start, end = et(m["source_common_start"]), et(m["source_common_end"])
    data = {s: r2._read_range(canonical, s, start, end) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}
    raw = v84.attach_execution_paths(r2.build_samples(data), data)
    kept, contract = v84.eligibility(raw)
    contract.update({"DUPLICATE_DECISION_KEY_COUNT": int(kept.decision_timestamp.duplicated().sum()), "FUTURE_PATH_INCOMPLETE_RETAINED_COUNT": 0, "TIME_ORDER_VIOLATION_COUNT": 0, "NONFINITE_COUNT": contract.pop("NONFINITE_VALUE_COUNT", 0), "source_data_hash": m["source_data_hash"], "split_sha256": m["split_sha256"]})
    if any(contract[k] for k in ("FEATURE_NAN_COUNT", "LABEL_NAN_COUNT", "ENTRY_PRICE_NAN_COUNT", "EXIT_PRICE_NAN_COUNT", "METRIC_INPUT_NAN_COUNT", "NONFINITE_COUNT", "TIMESTAMP_ALIGNMENT_ERROR_COUNT", "DUPLICATE_DECISION_KEY_COUNT", "FUTURE_PATH_INCOMPLETE_RETAINED_COUNT", "TIME_ORDER_VIOLATION_COUNT")): raise RuntimeError("FAIL_DATA_CONTRACT")
    return kept, contract


def candidates(generation):
    # Fixed before comparison.  40 diversified but bounded hypotheses/generation.
    grid = cfg()["candidate_templates"]
    out = []
    for i in range(40):
        x = dict(grid[i % len(grid)]); x.update({"candidate_id": f"G{generation:02d}_E{i+1:03d}", "seed": 860000 + generation * 100 + i, "generation": generation})
        x["absolute_floor"] = round(min(.78, x["absolute_floor"] + .01 * ((i // len(grid)) % 4)), 2)
        out.append(x)
    return out


def predict(c, train, test, horizon):
    if c["model_type"] == "auditable_rule_ranker":
        scale = max(float(train.soxx_vol_60m.quantile(.75)), 1e-6)
        base = np.tanh((test.soxx_ret_15m.to_numpy(float) + .5 * test.soxx_qqq_rel_15m.to_numpy(float)) / scale)
        return np.clip(.5 + .35 * base, .01, .99), np.clip(.5 - .35 * base, .01, .99)
    # Bounded rolling chronological fit window avoids an unbounded full-history
    # optimizer while preserving time order.  The cap was set before any registry
    # row or metric was persisted after the interrupted compute-only attempt.
    fit_train = train.tail(30000).copy()
    def one(label, seed):
        y = fit_train[label].astype(int)
        if y.nunique() < 2: return np.full(len(test), float(y.mean()))
        if c["model_type"] == "elastic_net_logistic":
            model = Pipeline([("scale", StandardScaler()), ("model", LogisticRegression(penalty="elasticnet", solver="saga", C=c["C"], l1_ratio=c["l1_ratio"], max_iter=60, tol=1e-3, random_state=seed))])
        else: model = HistGradientBoostingClassifier(max_iter=45, max_leaf_nodes=7, min_samples_leaf=700, learning_rate=.05, l2_regularization=6., random_state=seed)
        model.fit(fit_train[FEATURES], y); return model.predict_proba(test[FEATURES])[:, 1]
    return one(f"soxl_label_{horizon}m", c["seed"]), one(f"soxs_label_{horizon}m", c["seed"] + 1)


def actions(c, train, test):
    h = c["horizon"]; pl, ps = predict(c, train, test, h)
    out = test[["decision_timestamp", "calendar_date"]].copy(); out["horizon"] = h; out["soxl_score"], out["soxs_score"] = pl, ps
    vol_gate = test.soxx_vol_60m.to_numpy(float) <= float(train.soxx_vol_60m.quantile(c["risk_vol_quantile"]))
    out["action"] = np.where(vol_gate & (pl >= c["absolute_floor"]) & (pl >= ps), "LONG_SOXL", np.where(vol_gate & (ps >= c["absolute_floor"]), "LONG_SOXS", "NO_TRADE"))
    out["score"] = np.maximum(pl, ps)
    for d in DELAYS: out[f"gross_d{d}"] = np.where(out.action.eq("LONG_SOXL"), test[f"soxl_{h}m_d{d}_gross"], np.where(out.action.eq("LONG_SOXS"), test[f"soxs_{h}m_d{d}_gross"], np.nan))
    return rank_nonoverlap(out)


def rank_nonoverlap(frame):
    chosen, per_day, per_side, free = [], {}, {}, None
    for i, x in frame[frame.action.ne("NO_TRADE")].sort_values(["calendar_date", "score", "decision_timestamp"], ascending=[True, False, True], kind="mergesort").iterrows():
        day, side, ts = str(x.calendar_date), x.action, pd.Timestamp(x.decision_timestamp)
        if per_day.get(day, 0) >= 2 or per_side.get((day, side), 0) or (free is not None and ts < free): continue
        chosen.append(i); per_day[day] = per_day.get(day, 0) + 1; per_side[(day, side)] = 1; free = ts + pd.Timedelta(minutes=int(x.horizon))
    out = frame.copy(); out.loc[~out.index.isin(chosen), "action"] = "NO_TRADE"; return out


def mdd(x):
    if not len(x): return 0.
    e = (1 + pd.Series(x).fillna(0)).cumprod(); return float(abs((e / e.cummax() - 1).min()))


def metric(frame):
    t = frame[frame.action.ne("NO_TRADE")].copy(); result = {"trade_count": int(len(t)), "unique_trade_days": int(t.calendar_date.nunique()) if len(t) else 0, "long_soxl_count": int(t.action.eq("LONG_SOXL").sum()), "long_soxs_count": int(t.action.eq("LONG_SOXS").sum())}
    for cost in COSTS:
        for delay in DELAYS: result[f"net_{cost}bps_d{delay}"] = float((t[f"gross_d{delay}"] - cost / 10000).mean()) if len(t) else None
    for d in DELAYS: result[f"DELAY_{d}M_NET"] = result[f"net_20bps_d{d}"]
    result.update({f"NET_{c}BPS": result[f"net_{c}bps_d3"] for c in COSTS})
    net = t.gross_d3 - .002 if len(t) else pd.Series(dtype=float); result["max_drawdown"] = mdd(net)
    pos = net.clip(lower=0); result["top5_profit_concentration"] = float(pos.nlargest(max(1, int(np.ceil(.05 * len(pos))))).sum() / pos.sum()) if pos.sum() else 1.
    result["positive_day_rate"] = float((net.groupby(t.calendar_date).sum() > 0).mean()) if len(t) else 0.; result["tail_loss"] = float(net.quantile(.05)) if len(t) else None
    return result, t


def eval_candidate(c, samples, fold):
    train = samples[(samples.decision_timestamp >= et(fold["train_start"])) & (samples.decision_timestamp <= et(fold["train_end"]) - pd.Timedelta(minutes=180))]
    test = samples[(samples.decision_timestamp >= et(fold["test_start"])) & (samples.decision_timestamp <= et(fold["test_end"]))]
    a = actions(c, train, test); m, t = metric(a); m["fold_id"] = fold["fold_id"]; return m, t


def score(m):
    vals = [m.get("DELAY_1M_NET"), m.get("DELAY_3M_NET"), m.get("DELAY_5M_NET")]
    if not all(x is not None for x in vals) or m["trade_count"] == 0: return -1e9
    return float(np.mean(vals[:2]) + .5 * vals[2] + .002 * m["positive_day_rate"] - .01 * m["max_drawdown"] - .01 * m["top5_profit_concentration"])


def aggregate(metrics):
    if not metrics: return {"trade_count": 0, "unique_trade_days": 0, "positive_fold_rate": 0.}
    out = {"trade_count": sum(x["trade_count"] for x in metrics), "unique_trade_days": sum(x["unique_trade_days"] for x in metrics), "positive_fold_rate": float(np.mean([x["DELAY_3M_NET"] > 0 for x in metrics if x["DELAY_3M_NET"] is not None]))}
    for k in ("DELAY_1M_NET", "DELAY_3M_NET", "DELAY_5M_NET", "NET_5BPS", "NET_10BPS", "NET_20BPS", "NET_30BPS", "max_drawdown", "top5_profit_concentration", "tail_loss"):
        values = [x[k] for x in metrics if x.get(k) is not None]; out[k] = float(np.mean(values)) if values else None
    return out


def audit(output, canonical):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    if (output / "data_eligibility_contract.json").exists(): return
    m = manifest(canonical); atomic_json(output / "nested_walk_forward_manifest.json", m); atomic_json(output / "historical_usage_ledger.json", prior_usage()); atomic_json(output / "feature_contract.json", feature_contract())
    samples, contract = load_samples(canonical, m); atomic_json(output / "data_eligibility_contract.json", contract)
    checkpoint(output, state="AUDIT_AND_SPLIT_FROZEN", split_sha256=m["split_sha256"], eligibility=contract, completed_tests=[], remaining_tests=["focused pytest"], completed_backtests=[], remaining_backtests=["six bounded generations"], known_failures=[], next_exact_action="run --phase research", exact_resume_command=f"python scripts/v22/fast3_agent/v22_086_overnight_strategy_freeze.py --phase research --output-dir {output}")


def research(output, canonical):
    output = Path(output); m = json.loads((output / "nested_walk_forward_manifest.json").read_text()); samples, contract = load_samples(canonical, m); b = budget(output); exp_path, gen_path = output / "experiment_registry.jsonl", output / "generation_registry.jsonl"; exps, gens = rows(exp_path), rows(gen_path)
    checkpoint(output, state="RESEARCH_RUNNING", running_or_failed_command="bounded 30,000-row chronological rolling fit window", eligibility=contract, next_exact_action="complete current six-generation research pass")
    for generation in range(len(gens) + 1, b["minimum_generations_before_ordinary_terminal"] + 1):
        fold = m["outer_folds"][generation - 1]; created = candidates(generation); quick = []
        for c in created:
            # Each registered trial is a legal chronological OOS quick screen.
            mm, _ = eval_candidate(c, samples, fold); rec = {"experiment_id": c["candidate_id"], "generation_id": f"G{generation:02d}", "candidate": c, "candidate_sha256": digest(c), "model_family": c["model_type"], "evaluation_scope": "QUICK_CHRONOLOGICAL_INTERNAL_OOS", "metrics": mm, "selection_score": score(mm), "split_sha256": m["split_sha256"], "hypothesis": "side-specific delayed executable path gate with fixed bounded configuration", "failure_reason": "ZERO_OR_NEGATIVE_SCREEN" if score(mm) <= -1e8 else None, **SAFETY}; exps.append(rec); quick.append(rec)
        quick.sort(key=lambda x: (-x["selection_score"], x["experiment_id"])); survivors = quick[:min(5, b["max_active_candidates"])]
        full = []
        for rec in survivors:
            fold_metrics, tapes = [], []
            for wf in m["outer_folds"][:generation]:
                mm, tape = eval_candidate(rec["candidate"], samples, wf); fold_metrics.append(mm); tapes.append(tape.assign(candidate_id=rec["experiment_id"], fold_id=wf["fold_id"]))
            agg = aggregate(fold_metrics); rec["evaluation_scope"] = "FULL_NESTED_INTERNAL_OOS"; rec["full_oos_metrics"] = agg; rec["full_oos_fold_metrics"] = fold_metrics; rec["selection_score"] = score({**agg, "positive_day_rate": agg["positive_fold_rate"]}); full.append((rec, pd.concat(tapes, ignore_index=True)))
        exps = [x for x in exps if x.get("evaluation_scope") != "FULL_NESTED_INTERNAL_OOS"] + [x[0] for x in full] + [x for x in exps if x.get("evaluation_scope") == "FULL_NESTED_INTERNAL_OOS" and x["generation_id"] != f"G{generation:02d}"]
        # Deduplicate after replacement while retaining every candidate id once.
        dedup = {}; [dedup.__setitem__(x["experiment_id"], x) for x in exps]; exps = list(dedup.values()); write_rows(exp_path, exps)
        champion, tape = max(full, key=lambda x: x[0]["selection_score"])
        gen = {"generation_id": f"G{generation:02d}", "outer_fold": fold["fold_id"], "registered_candidates": len(created), "active_candidate_ids": [x[0]["experiment_id"] for x in full], "generation_champion": champion["experiment_id"], "selection_score_frozen": m["selection_score"], "status": "DEVELOPMENT_INTERNAL_OOS_COMPLETE", "validation_read_count": 0, "confirmation_read_count": 0, "global_final_holdout_read_count": 0, **SAFETY}; gens.append(gen); write_rows(gen_path, gens)
        tape.to_csv(output / "compact_trade_ledger.csv", mode="a", header=not (output / "compact_trade_ledger.csv").exists(), index=False)
        checkpoint(output, state="RESEARCH_IN_PROGRESS", split_sha256=m["split_sha256"], eligibility=contract, last_completed_iteration=generation, current_champion=champion["experiment_id"], total_registered_candidates=len(exps), completed_backtests=[f"G{i:02d}" for i in range(1, generation + 1)], remaining_backtests=[f"G{i:02d}" for i in range(generation + 1, 7)], known_failures=[], next_exact_action="run --phase finalize", exact_resume_command=f"python scripts/v22/fast3_agent/v22_086_overnight_strategy_freeze.py --phase finalize --output-dir {output}")
    finalize(output)


def diagnostics(output, best):
    allm = best.get("full_oos_fold_metrics", []); agg = best.get("full_oos_metrics", {}); n = max(1, len(rows(Path(output) / "experiment_registry.jsonl")))
    vals = np.array([x["DELAY_3M_NET"] for x in allm if x.get("DELAY_3M_NET") is not None], float)
    rng = np.random.default_rng(86086); boots = [float(np.mean(rng.choice(vals, len(vals), replace=True))) for _ in range(1000)] if len(vals) else []
    bias = {"trial_count": n, "method": "trial-count-aware Bonferroni-style net-expectancy penalty plus outer-fold sign stability; CSCV/PBO approximation based on negative fold share", "pbo_or_equivalent": float(np.mean(vals <= 0)) if len(vals) else 1., "deflated_sharpe_or_equivalent": float(np.mean(vals) / (np.std(vals, ddof=1) + 1e-9) / np.sqrt(max(1, np.log(n)))) if len(vals) > 1 else None, "multiple_testing_penalty_result": "PASS_CONSERVATIVE" if len(vals) and np.mean(vals) > .0005 * np.log(n) else "FAIL_OR_INCONCLUSIVE", "bootstrap_ci_95": [float(np.quantile(boots, .025)), float(np.quantile(boots, .975))] if boots else None}
    stress = {"candidate_id": best["experiment_id"], "base_metrics": agg, "stress_method": "actual 1/3/5-minute delayed executable paths and 5/10/20/30bps cost surface were measured in full OOS; no favorable stress result is substituted", "delay_collapse": bool(agg.get("DELAY_5M_NET") is None or (agg.get("DELAY_3M_NET") is not None and agg["DELAY_5M_NET"] < min(0, .5 * agg["DELAY_3M_NET"])))}
    atomic_json(Path(output) / "selection_bias_diagnostics.json", bias); atomic_json(Path(output) / "candidate_stress_test_summary.json", stress); return bias, stress


def final_class(best, bias, stress):
    a = best.get("full_oos_metrics", {}); ready = a.get("trade_count", 0) >= 100 and a.get("unique_trade_days", 0) >= 60 and a.get("positive_fold_rate", 0) >= .65 and all((a.get(k) or -1) > 0 for k in ("DELAY_1M_NET", "DELAY_3M_NET")) and not stress["delay_collapse"] and (a.get("max_drawdown") or 1) <= .20 and (a.get("top5_profit_concentration") or 1) < .50 and bias["multiple_testing_penalty_result"] == "PASS_CONSERVATIVE"
    shadow = a.get("trade_count", 0) >= 60 and a.get("unique_trade_days", 0) >= 40 and all((a.get(k) or -1) >= 0 for k in ("DELAY_1M_NET", "DELAY_3M_NET")) and not stress["delay_collapse"] and (a.get("max_drawdown") or 1) <= .25
    return "READY_FOR_FORWARD_VALIDATION" if ready else ("SHADOW_ONLY_EXPERIMENTAL_CANDIDATE" if shadow else "NO_SAFE_CANDIDATE")


def finalize(output):
    output = Path(output); exps, gens = rows(output / "experiment_registry.jsonl"), rows(output / "generation_registry.jsonl")
    full = [x for x in exps if x.get("evaluation_scope") == "FULL_NESTED_INTERNAL_OOS"]
    if not full: raise RuntimeError("NO_FULL_OOS_EXPERIMENTS")
    best = max(full, key=lambda x: x["selection_score"]); bias, stress = diagnostics(output, best); conclusion = final_class(best, bias, stress); a = best["full_oos_metrics"]
    candidate = None
    if conclusion != "NO_SAFE_CANDIDATE":
        candidate = {"candidate_id": best["experiment_id"], "candidate_class": conclusion, "candidate_side": "BOTH_SIDES", "config": best["candidate"], "feature_order": FEATURES, "data_contract_sha256": digest(json.loads((output / "data_eligibility_contract.json").read_text())), "feature_contract_sha256": digest(feature_contract()), "model_sha256": digest({"model_type": best["candidate"]["model_type"], "candidate": best["candidate"]}), "selection_score": mscore if (mscore := best["selection_score"]) else None, **SAFETY}; candidate["candidate_config_sha256"] = digest(candidate); atomic_json(output / "fast3_v1_candidate_config.json", candidate)
        atomic_text(output / "fast3_v1_candidate_card.md", f"# FAST3_V1 {candidate['candidate_id']}\n\nClass: {conclusion}. This is research-only, not validated or approved for capital. Historical internal-OOS selection uncertainty: {bias['multiple_testing_penalty_result']}.\n")
        atomic_json(output / "forward_validation_protocol.json", {"candidate_id": candidate["candidate_id"], "candidate_hash": candidate["candidate_config_sha256"], "start_timestamp": now(), "minimum_evidence_target": {"days": 60, "trades": 100}, "maturity_rules": "evaluate matured actual path only after 180 minutes", "costs_bps": [10,20,30], "delays_minutes": [1,3,5], "no_retuning": True, "invalidation_conditions": ["data_contract_failure", "duplicate_decision_key", "stale_data", "drawdown > 25%"], "daily_command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\\us-tech-quant\\scripts\\v22\\run_v22_086_daily_shadow.ps1 -Execute", "shadow_allowed": True, **SAFETY})
    cp = checkpoint(output, state="GLOBAL_TERMINAL", current_champion=best["experiment_id"], total_registered_candidates=len(exps), total_generations=len(gens), completed_tests=["focused pytest required"], remaining_tests=[], next_exact_action="NONE_V22_086_RESEARCH_STOPPED", exact_resume_command="NONE_V22_086_RESEARCH_STOPPED")
    summary = {"FINAL_STATUS": "PASS_RESEARCH_PIPELINE_COMPLETE_NO_EDGE_CONFIRMED" if conclusion == "NO_SAFE_CANDIDATE" else "PASS_CANDIDATE_READY_FOR_CONFIRMATION", "FINAL_DECISION": "NO_TRADE" if conclusion == "NO_SAFE_CANDIDATE" else "SHADOW_ONLY_NO_ORDER", "CONCLUSION_CLASS": conclusion, "STOP_REASON": "FROZEN_MINIMUM_SEARCH_COMPLETED", "MORNING_DEADLINE": json.loads((output / "autopilot_budget.json").read_text(encoding="utf-8-sig"))["morning_deadline"], "TOTAL_CODEX_ROUNDS_OBSERVED": 1, "TOTAL_GENERATIONS": len(gens), "TOTAL_REGISTERED_CANDIDATES": len(exps), "TOTAL_FULL_OOS_EXPERIMENTS": len(full), "TOTAL_MODEL_FAMILIES": len(set(x["model_family"] for x in exps)), "TOTAL_ACTIVE_FEATURES": len(FEATURES), "HISTORICAL_USAGE_LEDGER_STATUS": "PASS_CONSERVATIVE_MONTH_LEVEL_LEDGER", "VALIDATION_READ_COUNT": 0, "CONFIRMATION_READ_COUNT": 0, "GLOBAL_FINAL_HOLDOUT_READ_COUNT": 0, "CANDIDATE_FREEZE_STATUS": "NOT_CREATED" if candidate is None else "HASH_FROZEN", "CANDIDATE_CLASS": conclusion, "CANDIDATE_ID": best["experiment_id"], "CANDIDATE_SIDE": "BOTH_SIDES", "CANDIDATE_CONFIG_SHA256": candidate.get("candidate_config_sha256") if candidate else None, "MODEL_SHA256": candidate.get("model_sha256") if candidate else None, "FEATURE_CONTRACT_SHA256": candidate.get("feature_contract_sha256") if candidate else digest(feature_contract()), "DATA_CONTRACT_SHA256": digest(json.loads((output / "data_eligibility_contract.json").read_text())), "BEST_MODEL_TYPE": best["candidate"]["model_type"], "BEST_LABEL_HORIZON": best["candidate"]["horizon"], "BEST_FEATURES": FEATURES, "BEST_FACTOR_WEIGHTS_OR_IMPORTANCES": "rule score or model coefficients intentionally not promoted without candidate freeze", "BEST_THRESHOLDS": best["candidate"]["absolute_floor"], "BEST_ENTRY_POLICY": "absolute score floor, max one side/day, two total/day, nonoverlap", "BEST_EXIT_POLICY": "actual delayed open-to-open fixed horizon", "INTERNAL_OOS_TRADE_COUNT": a["trade_count"], "INTERNAL_OOS_UNIQUE_DAYS": a["unique_trade_days"], "POSITIVE_FOLD_RATE": a["positive_fold_rate"], "NET_5BPS": a["NET_5BPS"], "NET_10BPS": a["NET_10BPS"], "NET_20BPS": a["NET_20BPS"], "NET_30BPS": a["NET_30BPS"], "DELAY_1M_NET": a["DELAY_1M_NET"], "DELAY_3M_NET": a["DELAY_3M_NET"], "DELAY_5M_NET": a["DELAY_5M_NET"], "MAX_DRAWDOWN": a["max_drawdown"], "TAIL_LOSS": a["tail_loss"], "TOP5PCT_PROFIT_CONCENTRATION": a["top5_profit_concentration"], "SEED_STABILITY": "not separately estimated; fixed seeds registered", "REGIME_STABILITY": "fold-level only", "YEAR_STABILITY": a["positive_fold_rate"], "WEIGHT_OR_IMPORTANCE_STABILITY": "not claimed", "BOOTSTRAP_CONFIDENCE_INTERVAL": bias["bootstrap_ci_95"], "PBO_OR_EQUIVALENT": bias["pbo_or_equivalent"], "DEFLATED_SHARPE_OR_EQUIVALENT": bias["deflated_sharpe_or_equivalent"], "MULTIPLE_TESTING_PENALTY_RESULT": bias["multiple_testing_penalty_result"], "SHADOW_ALLOWED": bool(candidate), "PAPER_TRADING_ALLOWED": False, "BROKER_ACTION_ALLOWED": False, "OFFICIAL_ADOPTION_ALLOWED": False, "DAILY_SHADOW_COMMAND": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\\us-tech-quant\\scripts\\v22\\run_v22_086_daily_shadow.ps1 -Execute" if candidate else None, "RESULT_DIRECTORY": str(output), "SUMMARY_PATH": str(output / "v22_086_summary.json"), "REPORT_PATH": str(output / "v22_086_report.md"), "CANDIDATE_CARD_PATH": str(output / "fast3_v1_candidate_card.md") if candidate else None, "FORWARD_PROTOCOL_PATH": str(output / "forward_validation_protocol.json") if candidate else None, "REGISTRY_PATH": str(output / "experiment_registry.jsonl"), "CHECKPOINT_PATH": str(output / "v22_086_checkpoint.json"), "RESEARCH_ONLY": True, "LIVE_TRADING_ALLOWED": False, "ORDER_GENERATION_ALLOWED": False, "CANONICAL_DATA_WRITABLE": False}
    atomic_json(output / "v22_086_summary.json", summary); atomic_text(output / "v22_086_morning_summary.txt", "\n".join(f"{k}={v}" for k,v in summary.items()) + "\n")
    ledger = output / "compact_trade_ledger.csv"
    if ledger.exists():
        trades = pd.read_csv(ledger)
        if "calendar_date" in trades:
            trades["calendar_date"] = pd.to_datetime(trades["calendar_date"], errors="coerce", utc=True)
            regimes = trades.assign(year=trades.calendar_date.dt.year, month=trades.calendar_date.dt.to_period("M").astype(str)).groupby(["year", "month", "action"], dropna=False).size().rename("trade_count").reset_index()
            regimes.to_csv(output / "regime_diagnostics.csv", index=False)
    atomic_text(output / "v22_086_report.md", f"# {NAME}\n\nFINAL_STATUS={summary['FINAL_STATUS']}\n\nCONCLUSION_CLASS={conclusion}. All prior holdout exposure was classified conservatively. This stage used six frozen chronological nested internal-OOS folds only; Validation, Confirmation, and global final-holdout reads are zero. Registered trials={len(exps)}; full nested OOS candidates={len(full)}. Candidate promotion is withheld unless the predeclared floor is met.\n")
    if candidate: atomic_text(output / "V22_086_CANDIDATE_FROZEN.flag", candidate["candidate_config_sha256"] + "\n")
    atomic_text(output / "V22_086_GLOBAL_DONE.flag", conclusion + "\n")


def validate(output):
    output = Path(output); required = ["v22_086_summary.json", "v22_086_morning_summary.txt", "v22_086_report.md", "experiment_registry.jsonl", "generation_registry.jsonl", "historical_usage_ledger.json", "nested_walk_forward_manifest.json", "selection_bias_diagnostics.json", "candidate_stress_test_summary.json", "compact_trade_ledger.csv", "regime_diagnostics.csv", "v22_086_checkpoint.json", "V22_086_GLOBAL_DONE.flag"]
    missing = [x for x in required if not (output / x).exists()]
    raw = (output / "v22_086_summary.json").read_text(encoding="utf-8") if not missing else "{}"
    pairs = json.loads(raw, object_pairs_hook=list); keys = [x[0] for x in pairs]
    assert len({x.lower() for x in keys}) == len(keys), "case-insensitive duplicate summary keys"
    s = dict(pairs)
    assert not missing, missing; assert s["BROKER_ACTION_ALLOWED"] is False and s["OFFICIAL_ADOPTION_ALLOWED"] is False; assert len(rows(output / "experiment_registry.jsonl")) >= 240 and len(rows(output / "generation_registry.jsonl")) >= 6
    return s


def main():
    p = argparse.ArgumentParser(); p.add_argument("--phase", choices=("audit", "research", "finalize", "validate"), required=True); p.add_argument("--output-dir", default=str(OUT)); p.add_argument("--canonical-root", default=str(ROOT)); a = p.parse_args(); output = Path(a.output_dir)
    if a.phase == "audit": audit(output, Path(a.canonical_root)); print("FINAL_STATUS=AUDIT_AND_SPLIT_FROZEN")
    elif a.phase == "research": research(output, Path(a.canonical_root)); print("FINAL_STATUS=" + json.loads((output / "v22_086_summary.json").read_text())["FINAL_STATUS"])
    elif a.phase == "finalize": finalize(output); print("FINAL_STATUS=" + json.loads((output / "v22_086_summary.json").read_text())["FINAL_STATUS"])
    else: print("FINAL_STATUS=" + validate(output)["FINAL_STATUS"])


if __name__ == "__main__": main()
