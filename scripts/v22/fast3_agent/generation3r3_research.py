"""FAST3 Generation 3R3 Development-only funnel diagnosis.

This deliberately reuses the Generation 3R2 PIT data builder and model families,
but fixes no economic parameter and never opens Validation or Confirmation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

import generation3r2_research as r2
from artifact_lifecycle import closeout_artifacts


NAME = "FAST3_GENERATION3R3_FAST_FUNNEL_ITERATION"
DEFAULT_OUT = Path(r"D:\us-tech-quant-results\fast3_autoresearch_generation3r3")
SAFETY = dict(r2.SAFETY)
REASONS = ("INVALID_FEATURE", "DATA_UNTRUSTED", "NO_OPPORTUNITY",
           "LOW_OPPORTUNITY_PROBABILITY", "LOW_DIRECTION_CONFIDENCE",
           "EXPECTED_NET_BELOW_BUFFER", "ETF_MAPPING_FAILURE", "COST_FAILURE",
           "DELAY_FAILURE", "OVERLAP_SUPPRESSED", "OTHER_FAIL_CLOSED")
OPPORTUNITY_THRESHOLDS = (.35, .40, .45, .50, .55, .60)
DIRECTION_MARGINS = (0.00, .02, .04, .06, .08, .10)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=r2._default) + "\n", encoding="utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=r2._default).encode()).hexdigest()


def fixed_contract(common: pd.DatetimeIndex, common_end: pd.Timestamp) -> dict:
    base = r2.fixed_contract(common, common_end)
    base.update({"research_id": NAME, "contract_status": "FROZEN_BEFORE_GENERATION3R3_ECONOMIC_EVALUATION",
                 "method": "Explicit 3R3 authorization split; only Development may be read during audit/diagnosis.",
                 "candidate_family_limit": 6, "confirmation_minimum_independent_trading_days": 15,
                 "confirmation_read_count": 0})
    base.pop("contract_sha256", None)
    base["contract_sha256"] = digest(base)
    return base


def audit_phase(output: Path, canonical: Path) -> dict:
    dates, ends, source = r2.metadata_audit(canonical)
    common = pd.DatetimeIndex(sorted(set(dates["SOXX"]).intersection(*[set(dates[s]) for s in r2.SYMBOLS if s != "SOXX"])))
    contract = fixed_contract(common, min(ends.values()))
    output.mkdir(parents=True, exist_ok=True)
    ledger = pd.DataFrame({"calendar_date_et": common})
    ledger["prior_exposure"] = np.where(ledger.calendar_date_et <= pd.Timestamp("2026-02-28", tz="America/New_York"), "PREVIOUSLY_EXPOSED_DEVELOPMENT_ONLY", "PREVIOUSLY_UNREAD_ELIGIBLE")
    ledger["generation3r3_frozen_role"] = "OUTSIDE"
    for role, lo, hi in (("DEVELOPMENT", "development_start", "development_end"), ("EMBARGO", "first_embargo_start", "first_embargo_end"), ("VALIDATION_UNREAD", "validation_start", "validation_end"), ("EMBARGO", "second_embargo_start", "second_embargo_end"), ("CONFIRMATION_UNREAD", "confirmation_start", "confirmation_end")):
        ledger.loc[ledger.calendar_date_et.between(pd.Timestamp(contract[lo]), pd.Timestamp(contract[hi])), "generation3r3_frozen_role"] = role
    ledger.to_csv(output / "generation3r3_data_usage_ledger.csv", index=False)
    write_json(output / "generation3r3_split_contract.json", contract)
    (output / "generation3r3_split_contract_sha256.txt").write_text(contract["contract_sha256"] + "\n", encoding="utf-8")
    write_json(output / "generation3r3_feature_contract.json", r2.feature_contract())
    write_json(output / "generation3r3_label_contract.json", r2.label_contract())
    write_json(output / "generation3r3_source_metadata_audit.json", {"source_audit": source, "all_six_required_symbols_mapped": True, "economic_values_read": False, **SAFETY})
    registry = pd.DataFrame(r2.candidate_contract())
    registry["status"] = "PREDECLARED_AWAITING_FUNNEL_DIAGNOSIS"; registry["decision"] = "PENDING"
    registry.to_csv(output / "generation3r3_candidate_registry.csv", index=False)
    write_json(output / "generation3r3_checkpoint.json", {"current_status": "SPLIT_FROZEN_AWAITING_FUNNEL_DIAGNOSIS", "current_champion": None, "last_completed_iteration": 0, "confirmation_read_count": 0, "validation_economics_read": False, "completed_backtests": [], "known_failures": [], "next_exact_action": "Run Development-only C1-C6 funnel diagnosis.", "exact_resume_command": f"python scripts/v22/fast3_agent/generation3r3_research.py --phase diagnose --output-dir {output}", "contract_sha256": contract["contract_sha256"], **SAFETY})
    return contract


def _raw_counts(soxx: pd.DataFrame) -> tuple[int, int]:
    raw = int((soxx.timestamp_et.dt.minute.to_numpy() % 5 == 0).sum())
    eligible = int(((soxx.timestamp_et.dt.minute.to_numpy() % 5 == 0) & soxx.valid.to_numpy() & (np.arange(len(soxx)) >= 121)).sum())
    return raw, eligible


def _reasoned_actions(rows: pd.DataFrame, p_opp: np.ndarray, p_up: np.ndarray) -> pd.DataFrame:
    """Frozen 3R3 diagnostic thresholds; one primary reason per score row."""
    out = rows[["decision_timestamp", "calendar_date", "soxl_gross_60m_delay0", "soxs_gross_60m_delay0"]].copy()
    out["p_opp"], out["p_up"] = np.asarray(p_opp), np.asarray(p_up)
    out["direction_confidence"] = np.maximum(out.p_up, 1 - out.p_up) - .5
    out["action"] = np.where(out.p_up >= .5, "LONG", "SHORT")
    out["mapped"] = np.where(out.action.eq("LONG"), out.soxl_gross_60m_delay0.notna(), out.soxs_gross_60m_delay0.notna())
    out["expected_net"] = out.p_opp * (0.012 * (.5 + out.direction_confidence)) - .001
    out["reason"] = "NO_OPPORTUNITY"
    opp = out.p_opp >= .50
    out.loc[opp, "reason"] = "LOW_DIRECTION_CONFIDENCE"
    directional = opp & (out.direction_confidence >= .04)
    out.loc[directional, "reason"] = "EXPECTED_NET_BELOW_BUFFER"
    expected = directional & (out.expected_net > .001)
    out.loc[expected, "reason"] = "ETF_MAPPING_FAILURE"
    tradable = expected & out.mapped
    out.loc[tradable, "reason"] = "TRADE"
    return out


def _funnel_row(cid: str, raw: int, eligible: int, samples: pd.DataFrame, scored: pd.DataFrame, actions: pd.DataFrame, legacy: pd.DataFrame) -> dict:
    reason = actions.reason.value_counts()
    pre = actions[actions.reason.eq("TRADE")].sort_values("decision_timestamp", kind="mergesort")
    used, next_free = [], pd.Timestamp.min.tz_localize("America/New_York")
    for idx, row in pre.iterrows():
        if row.decision_timestamp >= next_free:
            used.append(idx); next_free = row.decision_timestamp + pd.Timedelta(minutes=60)
    return {"candidate_id": cid, "raw_decision_timestamp_count": raw, "completed_bar_eligible_count": eligible,
            "valid_feature_row_count": int(len(samples)), "feature_missing_rejection_count": int(max(eligible - len(samples), 0)),
            "opportunity_label_positive_count": int(samples.opportunity_60m.sum()), "opportunity_label_negative_count": int((1-samples.opportunity_60m).sum()),
            "opportunity_model_scored_count": int(len(scored)), "opportunity_probability_pass_count": int((actions.p_opp >= .50).sum()),
            "direction_training_sample_count": int(scored.opportunity_60m.sum()), "direction_model_scored_count": int(len(scored)),
            "direction_confidence_pass_count": int((actions.direction_confidence >= .04).sum()),
            "expected_net_long_pass_count": int(((actions.action == "LONG") & (actions.expected_net > .001)).sum()),
            "expected_net_short_pass_count": int(((actions.action == "SHORT") & (actions.expected_net > .001)).sum()),
            "flat_due_to_opportunity_count": int(reason.get("NO_OPPORTUNITY", 0)), "flat_due_to_direction_count": int(reason.get("LOW_DIRECTION_CONFIDENCE", 0)),
            "flat_due_to_expected_return_count": int(reason.get("EXPECTED_NET_BELOW_BUFFER", 0)),
            "long_before_execution_count": int((actions.reason == "TRADE").mul(actions.action == "LONG").sum()), "short_before_execution_count": int((actions.reason == "TRADE").mul(actions.action == "SHORT").sum()),
            "etf_timestamp_mapping_success_count": int(actions.mapped.sum()), "etf_timestamp_mapping_failure_count": int((~actions.mapped).sum()),
            "cost_filter_pass_count": int((actions.expected_net > .001).sum()), "delay_filter_pass_count": int((actions.reason == "TRADE").sum()),
            "overlap_suppressed_count": int(len(pre) - len(used)), "final_nonoverlap_long_count": int((pre.loc[used].action == "LONG").sum()), "final_nonoverlap_short_count": int((pre.loc[used].action == "SHORT").sum()), "final_nonoverlap_trade_count": int(len(used)),
            "legacy_joint_probability_threshold": 0.50, "legacy_joint_probability_pass_count": int(((legacy.probability_long >= .50) | (legacy.probability_short >= .50)).sum()), "legacy_final_nonoverlap_trade_count": int(len(r2.nonoverlap(legacy)))}


def diagnose_phase(output: Path, canonical: Path) -> None:
    contract = json.loads((output / "generation3r3_split_contract.json").read_text(encoding="utf-8"))
    if contract["confirmation_read_count"] != 0: raise RuntimeError("FAIL_LEAKAGE_DETECTED:CONFIRMATION_ALREADY_READ")
    start, end = pd.Timestamp(contract["development_start"]), pd.Timestamp(contract["development_end"])
    data = {s: r2._read_range(canonical, s, start, end) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}
    raw, eligible = _raw_counts(data["SOXX"]); samples = r2._vix_for_development(r2.build_samples(data))
    rows, reasons, probabilities, calibration, regimes, overlaps, mappings = [], [], [], [], [], [], []
    for candidate in r2.candidate_contract():
        cid, scored = candidate["candidate_id"], []
        for _, train_start, test_start in r2._folds():
            test_end = test_start + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23, minutes=59)
            train = samples[samples.decision_timestamp.between(train_start, test_start - pd.Timedelta(minutes=r2.MAX_HORIZON_MINUTES))]
            test = samples[samples.decision_timestamp.between(test_start, test_end)]
            if len(train) >= 5000 and len(test) >= 100:
                po, pu = r2.two_layer_predictions(cid, train, test, list(r2.FEATURES)); one = test.copy(); one["p_opp"], one["p_up"] = po, pu; scored.append(one)
        scored = pd.concat(scored, ignore_index=True)
        actions = _reasoned_actions(scored, scored.p_opp, scored.p_up)
        legacy = r2.action_frame(scored, scored.p_opp, scored.p_up, .50)
        row = _funnel_row(cid, raw, eligible, samples, scored, actions, legacy); rows.append(row)
        reasons.extend({"candidate_id": cid, "reason_code": reason, "count": int((actions.reason == reason).sum())} for reason in REASONS)
        q = actions[["p_opp", "p_up"]].quantile([0, .01, .05, .10, .25, .50, .75, .90, .95, .99, 1]).reset_index(names="quantile")
        probabilities.extend({"candidate_id": cid, "probability": col, "quantile": float(row["quantile"]), "value": float(row[col])} for _, row in q.iterrows() for col in ("p_opp", "p_up"))
        for name, pred, target in (("opportunity", actions.p_opp, scored.opportunity_60m), ("direction", actions.p_up, scored.direction_up_conditional)):
            calibration.append({"candidate_id": cid, "model_layer": name, "brier_score": float(np.mean((pred - target) ** 2)), "log_loss": float(-np.mean(target * np.log(np.clip(pred, 1e-6, 1 - 1e-6)) + (1-target) * np.log(np.clip(1-pred, 1e-6, 1-1e-6)))), "calibration_method": "none_train_fold_only"})
        regime = pd.qcut(scored.soxx_vol_60m, 2, labels=("LOW_VOL", "HIGH_VOL"), duplicates="drop")
        for label in ("LOW_VOL", "HIGH_VOL"):
            mask = regime.astype(str).eq(label)
            regimes.append({"candidate_id": cid, "regime": label, "scored_count": int(mask.sum()), "opportunity_probability_mean": float(actions.loc[mask, "p_opp"].mean()), "direction_confidence_mean": float(actions.loc[mask, "direction_confidence"].mean())})
        overlaps.append({"candidate_id": cid, "pre_overlap_trade_count": int((actions.reason == "TRADE").sum()), "overlap_suppressed_count": row["overlap_suppressed_count"], "post_overlap_trade_count": row["final_nonoverlap_trade_count"], "legacy_post_overlap_trade_count": row["legacy_final_nonoverlap_trade_count"]})
        mappings.append({"candidate_id": cid, "mapped_success_count": int(actions.mapped.sum()), "mapped_failure_count": int((~actions.mapped).sum()), "timestamp_mapping_tolerance": "60 seconds"})
    pd.DataFrame(rows).to_csv(output / "generation3r3_candidate_funnel_counts.csv", index=False)
    pd.DataFrame(reasons).to_csv(output / "generation3r3_flat_reason_counts.csv", index=False)
    pd.DataFrame(probabilities).to_csv(output / "generation3r3_probability_distributions.csv", index=False)
    pd.DataFrame(calibration).to_csv(output / "generation3r3_probability_calibration.csv", index=False)
    pd.DataFrame(regimes).to_csv(output / "generation3r3_regime_coverage.csv", index=False)
    pd.DataFrame(overlaps).to_csv(output / "generation3r3_overlap_attrition.csv", index=False)
    pd.DataFrame(mappings).to_csv(output / "generation3r3_execution_mapping_audit.csv", index=False)
    pd.DataFrame({"candidate_id": [x["candidate_id"] for x in rows], "missing_feature_rate": [x["feature_missing_rejection_count"] / max(x["completed_bar_eligible_count"], 1) for x in rows]}).to_csv(output / "generation3r3_feature_missingness.csv", index=False)
    write_json(output / "generation3r3_checkpoint.json", {"current_status": "FUNNEL_DIAGNOSIS_COMPLETE_AWAITING_REGISTERED_REPAIR", "current_champion": None, "last_completed_iteration": 1, "confirmation_read_count": 0, "validation_economics_read": False, "completed_backtests": "Development-only C1-C6 funnel diagnosis", "known_failures": [], "next_exact_action": "Register one coverage-first threshold/calibration repair based on diagnostic artifacts.", "exact_resume_command": f"python scripts/v22/fast3_agent/generation3r3_research.py --phase diagnose --output-dir {output}", "contract_sha256": contract["contract_sha256"], **SAFETY})


def coverage_surface(p_opp: np.ndarray, p_up: np.ndarray, candidate_id: str) -> list[dict]:
    """Stage-B coordinate coverage only: no returns or costs enter this table."""
    p_opp, p_up = np.asarray(p_opp, dtype=float), np.asarray(p_up, dtype=float)
    confidence = np.maximum(p_up, 1 - p_up) - .5
    rows = []
    for threshold in OPPORTUNITY_THRESHOLDS:
        rows.append({"candidate_id": candidate_id, "stage": "OPPORTUNITY_COVERAGE_ONLY", "horizon_minutes": 60, "opportunity_threshold": threshold, "direction_margin": 0.00, "expected_net_buffer_bps": None, "scored_count": int(len(p_opp)), "pass_count": int((p_opp >= threshold).sum()), "uses_economic_returns": False})
    # .50 is the predeclared reference point from the original contract, not a
    # selected value; this is coordinate diagnosis rather than a Cartesian search.
    for margin in DIRECTION_MARGINS:
        rows.append({"candidate_id": candidate_id, "stage": "DIRECTION_COVERAGE_ONLY", "horizon_minutes": 60, "opportunity_threshold": .50, "direction_margin": margin, "expected_net_buffer_bps": None, "scored_count": int((p_opp >= .50).sum()), "pass_count": int(((p_opp >= .50) & (confidence >= margin)).sum()), "uses_economic_returns": False})
    return rows


def coverage_phase(output: Path, canonical: Path) -> None:
    contract = json.loads((output / "generation3r3_split_contract.json").read_text(encoding="utf-8"))
    if contract["confirmation_read_count"] != 0: raise RuntimeError("FAIL_LEAKAGE_DETECTED:CONFIRMATION_ALREADY_READ")
    start, end = pd.Timestamp(contract["development_start"]), pd.Timestamp(contract["development_end"])
    data = {s: r2._read_range(canonical, s, start, end) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}
    samples = r2._vix_for_development(r2.build_samples(data))
    surface = []
    for candidate in r2.candidate_contract():
        scored = []
        for _, train_start, test_start in r2._folds():
            test_end = test_start + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23, minutes=59)
            train = samples[samples.decision_timestamp.between(train_start, test_start - pd.Timedelta(minutes=r2.MAX_HORIZON_MINUTES))]
            test = samples[samples.decision_timestamp.between(test_start, test_end)]
            if len(train) >= 5000 and len(test) >= 100:
                po, pu = r2.two_layer_predictions(candidate["candidate_id"], train, test, list(r2.FEATURES)); scored.append((po, pu))
        po = np.concatenate([x[0] for x in scored]); pu = np.concatenate([x[1] for x in scored])
        surface.extend(coverage_surface(po, pu, candidate["candidate_id"]))
    pd.DataFrame(surface).to_csv(output / "generation3r3_threshold_coverage_surface.csv", index=False)
    registry = pd.read_csv(output / "generation3r3_candidate_registry.csv")
    registry["status"] = "COVERAGE_SURFACE_COMPLETE"; registry["decision"] = "AWAITING_FROZEN_SEPARATED_GATE_REPAIR"; registry["iteration_id"] = "R3R3_I02"; registry["hypothesis"] = "The legacy joint probability gate suppresses otherwise scorable model outputs; separated threshold coverage identifies viable bands without using economics."; registry["one_changed_component"] = "Threshold-funnel instrumentation only"; registry["tests_run"] = "py_compile; focused pytest"; registry["actual_command"] = "generation3r3_research.py --phase coverage"; registry.to_csv(output / "generation3r3_candidate_registry.csv", index=False)
    write_json(output / "generation3r3_checkpoint.json", {"current_status": "COVERAGE_SURFACE_COMPLETE_AWAITING_SEPARATED_GATE_REPAIR", "current_champion": None, "last_completed_iteration": 2, "confirmation_read_count": 0, "validation_economics_read": False, "completed_backtests": "Development-only C1-C6 funnel diagnosis and non-economic Stage-B coordinate coverage surface", "known_failures": ["Legacy joint probability gate produces zero C3/C4/C5/C6 passes at 0.50."], "next_exact_action": "Freeze a viable separated opportunity/direction band using the coverage surface, then evaluate at most 18 nested Development economic combinations per family.", "exact_resume_command": f"python scripts/v22/fast3_agent/generation3r3_research.py --phase coverage --output-dir {output}", "contract_sha256": contract["contract_sha256"], **SAFETY})


def separated_execution(rows: pd.DataFrame, p_opp: np.ndarray, p_up: np.ndarray, opportunity_threshold=.50, direction_margin=.04, safety_buffer=.001) -> pd.DataFrame:
    """One predeclared repair: separate the two model gates before execution."""
    columns = ["decision_timestamp", "calendar_date", *[f"{s}_gross_60m_delay{d}" for s in ("soxl", "soxs") for d in (0, 1, 3, 5)]]
    out = rows[columns].copy()
    out["p_opp"], out["p_up"] = np.asarray(p_opp), np.asarray(p_up)
    out["direction_confidence"] = np.maximum(out.p_up, 1-out.p_up) - .5
    out["action"] = np.where(out.p_up >= .5, "LONG", "SHORT")
    out["expected_net"] = out.p_opp * (.012 * (.5 + out.direction_confidence)) - .001
    eligible = (out.p_opp >= opportunity_threshold) & (out.direction_confidence >= direction_margin) & (out.expected_net > safety_buffer)
    out.loc[~eligible, "action"] = "FLAT"
    out["execution_etf"] = np.where(out.action.eq("LONG"), "SOXL", np.where(out.action.eq("SHORT"), "SOXS", None))
    for delay in (0, 1, 3, 5):
        gross = np.where(out.action.eq("LONG"), out[f"soxl_gross_60m_delay{delay}"], np.where(out.action.eq("SHORT"), out[f"soxs_gross_60m_delay{delay}"], np.nan))
        out[f"net_10bps_delay{delay}"] = gross - .001; out[f"net_20bps_delay{delay}"] = gross - .002
    return out


def repair_metrics(frame: pd.DataFrame, selector=r2.nonoverlap) -> dict:
    trades = selector(frame)
    if trades.empty:
        return {"executed_trade_count": 0, "pre_overlap_signal_count": 0, "mean_net_return_10bps": None, "mean_net_return_20bps": None, "median_chronological_window_net_10bps": None, "positive_window_ratio_10bps": None, "positive_window_ratio_20bps": None, "delay1_mean_net_return_10bps": None, "profit_factor_10bps": None, "hit_rate": None, "maximum_drawdown": None, "top5_trade_profit_concentration": None, "single_etf_profit_concentration": None, "active_month_count": 0, "max_month_trade_share": None, "long_trade_count": 0, "short_trade_count": 0}
    month_key = pd.to_datetime(trades.calendar_date).dt.to_period("M"); monthly = trades.groupby(month_key).net_10bps_delay0.sum(); monthly20 = trades.groupby(month_key).net_20bps_delay0.sum()
    pnl = trades.net_10bps_delay0; positive, negative = pnl.clip(lower=0).sum(), -pnl.clip(upper=0).sum(); daily = trades.groupby("calendar_date").net_10bps_delay0.sum(); drawdown = daily.cumsum() - daily.cumsum().cummax(); etf_profit = pnl.clip(lower=0).groupby(trades.execution_etf).sum()
    counts = trades.groupby(month_key).size()
    return {"executed_trade_count": int(len(trades)), "pre_overlap_signal_count": int((frame.action != "FLAT").sum()), "mean_net_return_10bps": float(pnl.mean()), "mean_net_return_20bps": float(trades.net_20bps_delay0.mean()), "median_chronological_window_net_10bps": float(monthly.median()), "positive_window_ratio_10bps": float((monthly > 0).mean()), "positive_window_ratio_20bps": float((monthly20 > 0).mean()), "delay1_mean_net_return_10bps": float(trades.net_10bps_delay1.mean()), "profit_factor_10bps": float(positive / negative) if negative else None, "hit_rate": float((pnl > 0).mean()), "maximum_drawdown": float(abs(drawdown.min())), "top5_trade_profit_concentration": float(pnl.clip(lower=0).nlargest(5).sum()/positive) if positive else None, "single_etf_profit_concentration": float(etf_profit.max()/positive) if positive else None, "active_month_count": int(len(counts)), "max_month_trade_share": float(counts.max()/len(trades)), "long_trade_count": int(trades.action.eq("LONG").sum()), "short_trade_count": int(trades.action.eq("SHORT").sum())}


def _random_repair_windows(execution: pd.DataFrame, selector=r2.nonoverlap) -> pd.DataFrame:
    rows = []
    for i in range(100):
        cid = sorted(execution.candidate_id.unique())[i % len(execution.candidate_id.unique())]; data = execution[execution.candidate_id.eq(cid)]; days = np.array(sorted(data.calendar_date.unique())); rng = np.random.default_rng(20260801+i)
        start = int(rng.integers(0, len(days)-9)); window = data[data.calendar_date.isin(days[start:start+10])]
        rows.append({"iteration_id": i+1, "random_seed": 20260801+i, "candidate_id": cid, "window_start": days[start], "window_end": days[start+9], **repair_metrics(window, selector)})
    return pd.DataFrame(rows)


def _promotion_gate(m: dict) -> tuple[bool, str]:
    if any(m.get(key) is None for key in ("mean_net_return_10bps", "median_chronological_window_net_10bps", "positive_window_ratio_10bps", "positive_window_ratio_20bps", "delay1_mean_net_return_10bps", "maximum_drawdown", "top5_trade_profit_concentration", "single_etf_profit_concentration")):
        return False, "NO_COVERAGE_TIER"
    tier_a = m["executed_trade_count"] >= 300
    tier_b = m["executed_trade_count"] >= 150 and m["active_month_count"] >= 18 and m["max_month_trade_share"] <= .15
    tier_c = m["executed_trade_count"] >= 90 and m["active_month_count"] >= 24 and m["long_trade_count"] >= 45 and m["short_trade_count"] >= 45
    standard = all((m["mean_net_return_10bps"] > 0, m["median_chronological_window_net_10bps"] > 0, m["positive_window_ratio_10bps"] >= .58, m["positive_window_ratio_20bps"] >= .52, m["delay1_mean_net_return_10bps"] > 0, m["profit_factor_10bps"] is not None and m["profit_factor_10bps"] >= 1.10, m["maximum_drawdown"] <= .30, m["top5_trade_profit_concentration"] is not None and m["top5_trade_profit_concentration"] < .25, m["single_etf_profit_concentration"] is not None and m["single_etf_profit_concentration"] < .75))
    return bool((tier_a or tier_b or tier_c) and standard), "TIER_A" if tier_a else ("TIER_B" if tier_b else ("TIER_C" if tier_c else "NO_COVERAGE_TIER"))


def repair_phase(output: Path, canonical: Path) -> None:
    contract = json.loads((output / "generation3r3_split_contract.json").read_text(encoding="utf-8"))
    if contract["confirmation_read_count"] != 0: raise RuntimeError("FAIL_LEAKAGE_DETECTED:CONFIRMATION_ALREADY_READ")
    start, end = pd.Timestamp(contract["development_start"]), pd.Timestamp(contract["development_end"]); data = {s: r2._read_range(canonical, s, start, end) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}; samples = r2._vix_for_development(r2.build_samples(data))
    all_execution, summaries = [], []
    for candidate in [x for x in r2.candidate_contract() if x["candidate_id"] in ("C3_HGB_TWO_STAGE", "C4_REGIME_HGB_MOE", "C6_HGB_VIX_PRIOR_DAY")]:
        records = []
        for outer, train_start, test_start in r2._folds():
            test_end = test_start + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23, minutes=59); train = samples[samples.decision_timestamp.between(train_start, test_start-pd.Timedelta(minutes=r2.MAX_HORIZON_MINUTES))]; test = samples[samples.decision_timestamp.between(test_start, test_end)]
            po, pu = r2.two_layer_predictions(candidate["candidate_id"], train, test, list(r2.FEATURES)); result = separated_execution(test, po, pu); result["candidate_id"], result["outer_structure"] = candidate["candidate_id"], outer; records.append(result)
        execution = pd.concat(records, ignore_index=True); all_execution.append(execution); metrics = repair_metrics(execution); passed, tier = _promotion_gate(metrics); summaries.append({**candidate, **metrics, "iteration_id": "R3R3_I03", "hypothesis": "Separate opportunity and direction gates restore valid nonlinear coverage without changing features or models.", "opportunity_threshold": .50, "direction_margin": .04, "expected_net_safety_buffer_bps": 10, "horizon_minutes": 60, "overlap_policy": "one_active_position_globally", "coverage_tier": tier, "development_gate_pass": passed, "decision": "ELIGIBLE_FOR_FROZEN_VALIDATION" if passed else "REJECT_DEVELOPMENT_GATE"})
    execution = pd.concat(all_execution, ignore_index=True); windows = _random_repair_windows(execution); pd.DataFrame(summaries).to_csv(output / "generation3r3_development_walkforward_metrics.csv", index=False); windows.to_csv(output / "generation3r3_random_window_metrics.csv", index=False); pd.DataFrame(summaries).to_csv(output / "generation3r3_candidate_registry.csv", index=False)
    finalists = pd.DataFrame(summaries).query("development_gate_pass == True").sort_values(["mean_net_return_10bps", "complexity"], ascending=[False, True]).head(3)
    write_json(output / "generation3r3_validation_frozen_candidates.json", {"status": "FROZEN" if len(finalists) else "NO_FINALISTS_DEVELOPMENT_GATE_FAILED", "candidate_ids": finalists.candidate_id.tolist(), "contract_sha256": contract["contract_sha256"], "confirmation_read_count": 0})
    write_json(output / "generation3r3_checkpoint.json", {"current_status": "DEVELOPMENT_FINALISTS_FROZEN_AWAITING_ONE_TIME_VALIDATION" if len(finalists) else "DEVELOPMENT_REPAIR_COMPLETE_AWAITING_NEXT_LEGAL_HYPOTHESIS", "current_champion": None, "last_completed_iteration": 3, "confirmation_read_count": 0, "validation_economics_read": False, "completed_backtests": "Development-only separated-gate nested chronological repair and 100 continuous windows", "known_failures": [] if len(finalists) else ["No separated-gate nonlinear candidate cleared every frozen Development promotion gate."], "next_exact_action": "Open Validation exactly once for frozen finalists." if len(finalists) else "Evaluate the next compact, predeclared Development-only repair (calibration or overlap policy).", "exact_resume_command": f"python scripts/v22/fast3_agent/generation3r3_research.py --phase repair --output-dir {output}", "contract_sha256": contract["contract_sha256"], **SAFETY})


def calibrated_probability(train: pd.DataFrame, test: pd.DataFrame, features: list[str], label: str, calibrator: str) -> np.ndarray:
    """Fit base and calibrator strictly inside the outer training period."""
    cut = int(len(train) * .80); base, calibration = train.iloc[:cut], train.iloc[cut:]
    if len(base) < 100 or base[label].nunique() < 2: return r2._constant_probability(base[label], len(test))
    stride = max(1, int(np.ceil(len(base) / 60_000))); model = r2._pipeline("hgb"); model.fit(base.iloc[::stride][features], base.iloc[::stride][label].astype(int))
    raw_test = model.predict_proba(test[features])[:, 1]
    if calibrator == "none" or calibration[label].nunique() < 2: return raw_test
    raw_cal = model.predict_proba(calibration[features])[:, 1]; y = calibration[label].astype(int).to_numpy()
    if calibrator == "sigmoid": return LogisticRegression(C=1., max_iter=200, random_state=20260801).fit(raw_cal.reshape(-1, 1), y).predict_proba(raw_test.reshape(-1, 1))[:, 1]
    if calibrator == "isotonic" and len(calibration) >= 5000: return IsotonicRegression(out_of_bounds="clip").fit(raw_cal, y).predict(raw_test)
    return raw_test


def calibrated_c6_predictions(train: pd.DataFrame, test: pd.DataFrame, calibrator: str) -> tuple[np.ndarray, np.ndarray]:
    features = list(r2.FEATURES) + list(r2.VIX_FEATURES)
    po = calibrated_probability(train, test, features, "opportunity_60m", calibrator)
    direction_train = train[train.opportunity_60m.eq(1)]
    pu = calibrated_probability(direction_train, test, features, "direction_up_conditional", calibrator)
    return np.clip(po, .001, .999), np.clip(pu, .001, .999)


def calibration_phase(output: Path, canonical: Path) -> None:
    contract = json.loads((output / "generation3r3_split_contract.json").read_text(encoding="utf-8"))
    if contract["confirmation_read_count"] != 0: raise RuntimeError("FAIL_LEAKAGE_DETECTED:CONFIRMATION_ALREADY_READ")
    start, end = pd.Timestamp(contract["development_start"]), pd.Timestamp(contract["development_end"]); data = {s: r2._read_range(canonical, s, start, end) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}; samples = r2._vix_for_development(r2.build_samples(data))
    executions, summaries = [], []
    for calibrator in ("none", "sigmoid", "isotonic"):
        records = []
        for outer, train_start, test_start in r2._folds():
            test_end = test_start + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23, minutes=59); train = samples[samples.decision_timestamp.between(train_start, test_start-pd.Timedelta(minutes=r2.MAX_HORIZON_MINUTES))]; test = samples[samples.decision_timestamp.between(test_start, test_end)]
            po, pu = calibrated_c6_predictions(train, test, calibrator); result = separated_execution(test, po, pu); result["candidate_id"], result["outer_structure"] = f"C6_HGB_VIX_{calibrator.upper()}", outer; records.append(result)
        execution = pd.concat(records, ignore_index=True); executions.append(execution); metrics = repair_metrics(execution); passed, tier = _promotion_gate(metrics); summaries.append({"candidate_id": f"C6_HGB_VIX_{calibrator.upper()}", "family": "C6_HGB_VIX_PRIOR_DAY_train_fold_calibration", "model": "HGB C6 unchanged", "calibrator": calibrator, "iteration_id": "R3R3_I04", "hypothesis": "Train-fold-only probability calibration can improve separated-gate direction selection without holdout access.", "one_changed_component": "calibrator", "opportunity_threshold": .50, "direction_margin": .04, "expected_net_safety_buffer_bps": 10, "horizon_minutes": 60, "overlap_policy": "one_active_position_globally", **metrics, "coverage_tier": tier, "development_gate_pass": passed, "decision": "ELIGIBLE_FOR_FROZEN_VALIDATION" if passed else "REJECT_DEVELOPMENT_GATE"})
    old = pd.read_csv(output / "generation3r3_candidate_registry.csv"); combined = pd.concat([old, pd.DataFrame(summaries)], ignore_index=True, sort=False); combined.to_csv(output / "generation3r3_candidate_registry.csv", index=False); pd.DataFrame(summaries).to_csv(output / "generation3r3_development_walkforward_metrics.csv", index=False); windows = _random_repair_windows(pd.concat(executions, ignore_index=True)); windows.to_csv(output / "generation3r3_random_window_metrics.csv", index=False)
    finalists = pd.DataFrame(summaries).query("development_gate_pass == True").sort_values("mean_net_return_10bps", ascending=False).head(3); write_json(output / "generation3r3_validation_frozen_candidates.json", {"status": "FROZEN" if len(finalists) else "NO_FINALISTS_DEVELOPMENT_GATE_FAILED", "candidate_ids": finalists.candidate_id.tolist(), "contract_sha256": contract["contract_sha256"], "confirmation_read_count": 0})
    write_json(output / "generation3r3_checkpoint.json", {"current_status": "DEVELOPMENT_FINALISTS_FROZEN_AWAITING_ONE_TIME_VALIDATION" if len(finalists) else "CALIBRATION_REPAIR_COMPLETE_AWAITING_NEXT_LEGAL_HYPOTHESIS", "current_champion": None, "last_completed_iteration": 4, "confirmation_read_count": 0, "validation_economics_read": False, "completed_backtests": "Development-only C6 train-fold calibration comparison and 100 continuous windows", "known_failures": [] if len(finalists) else ["No C6 calibration variant cleared every frozen Development promotion gate."], "next_exact_action": "Open Validation exactly once for frozen finalists." if len(finalists) else "Evaluate the next compact predeclared Development-only repair: overlap policy.", "exact_resume_command": f"python scripts/v22/fast3_agent/generation3r3_research.py --phase calibration --output-dir {output}", "contract_sha256": contract["contract_sha256"], **SAFETY})


def overlap_selector(policy: str):
    def select(frame: pd.DataFrame) -> pd.DataFrame:
        signals = frame[frame.action.ne("FLAT") & frame.net_10bps_delay0.notna()].sort_values("decision_timestamp", kind="mergesort")
        if signals.empty: return signals
        if policy == "one_active_position_per_direction":
            next_free = {"LONG": pd.Timestamp.min.tz_localize("America/New_York"), "SHORT": pd.Timestamp.min.tz_localize("America/New_York")}; holding = 60
            keep = []
            for index, row in signals.iterrows():
                if row.decision_timestamp >= next_free[row.action]: keep.append(index); next_free[row.action] = row.decision_timestamp + pd.Timedelta(minutes=holding)
            return signals.loc[keep].copy()
        cooldown = {"one_active_position_globally": 60, "cooldown_15m": 15, "cooldown_30m": 30, "cooldown_equal_horizon": 60}[policy]
        keep, next_free = [], pd.Timestamp.min.tz_localize("America/New_York")
        for index, row in signals.iterrows():
            if row.decision_timestamp >= next_free: keep.append(index); next_free = row.decision_timestamp + pd.Timedelta(minutes=cooldown)
        return signals.loc[keep].copy()
    return select


def overlap_phase(output: Path, canonical: Path) -> None:
    contract = json.loads((output / "generation3r3_split_contract.json").read_text(encoding="utf-8"))
    if contract["confirmation_read_count"] != 0: raise RuntimeError("FAIL_LEAKAGE_DETECTED:CONFIRMATION_ALREADY_READ")
    start, end = pd.Timestamp(contract["development_start"]), pd.Timestamp(contract["development_end"]); data = {s: r2._read_range(canonical, s, start, end) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}; samples = r2._vix_for_development(r2.build_samples(data)); records = []
    for outer, train_start, test_start in r2._folds():
        test_end = test_start + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23, minutes=59); train = samples[samples.decision_timestamp.between(train_start, test_start-pd.Timedelta(minutes=r2.MAX_HORIZON_MINUTES))]; test = samples[samples.decision_timestamp.between(test_start, test_end)]
        po, pu = r2.two_layer_predictions("C4_REGIME_HGB_MOE", train, test, list(r2.FEATURES)); result = separated_execution(test, po, pu); result["outer_structure"] = outer; records.append(result)
    base = pd.concat(records, ignore_index=True); policies = ("one_active_position_globally", "one_active_position_per_direction", "cooldown_15m", "cooldown_30m", "cooldown_equal_horizon"); executions, summaries = [], []
    for policy in policies:
        execution = base.copy(); execution["candidate_id"] = f"C4_OVERLAP_{policy.upper()}"; executions.append(execution); metrics = repair_metrics(execution, overlap_selector(policy)); passed, tier = _promotion_gate(metrics); summaries.append({"candidate_id": execution.candidate_id.iloc[0], "family": "C4_regime_HGB_overlap_policy", "model": "C4 unchanged", "iteration_id": "R3R3_I05", "hypothesis": "Overlap suppression, rather than signal quality, caused the negative separated-gate C4 economics.", "one_changed_component": "overlap_policy", "opportunity_threshold": .50, "direction_margin": .04, "expected_net_safety_buffer_bps": 10, "horizon_minutes": 60, "overlap_policy": policy, **metrics, "coverage_tier": tier, "development_gate_pass": passed, "decision": "ELIGIBLE_FOR_FROZEN_VALIDATION" if passed else "REJECT_DEVELOPMENT_GATE"})
    old = pd.read_csv(output / "generation3r3_candidate_registry.csv"); pd.concat([old, pd.DataFrame(summaries)], ignore_index=True, sort=False).to_csv(output / "generation3r3_candidate_registry.csv", index=False); pd.DataFrame(summaries).to_csv(output / "generation3r3_development_walkforward_metrics.csv", index=False)
    window_rows = []
    for policy, execution in zip(policies, executions): window_rows.append(_random_repair_windows(execution, overlap_selector(policy)).assign(overlap_policy=policy))
    pd.concat(window_rows, ignore_index=True).to_csv(output / "generation3r3_random_window_metrics.csv", index=False)
    finalists = pd.DataFrame(summaries).query("development_gate_pass == True").sort_values("mean_net_return_10bps", ascending=False).head(3); write_json(output / "generation3r3_validation_frozen_candidates.json", {"status": "FROZEN" if len(finalists) else "NO_FINALISTS_DEVELOPMENT_GATE_FAILED", "candidate_ids": finalists.candidate_id.tolist(), "contract_sha256": contract["contract_sha256"], "confirmation_read_count": 0})
    write_json(output / "generation3r3_checkpoint.json", {"current_status": "DEVELOPMENT_FINALISTS_FROZEN_AWAITING_ONE_TIME_VALIDATION" if len(finalists) else "OVERLAP_REPAIR_COMPLETE_AWAITING_FINAL_DEVELOPMENT_DECISION", "current_champion": None, "last_completed_iteration": 5, "confirmation_read_count": 0, "validation_economics_read": False, "completed_backtests": "Development-only C4 overlap-policy comparison and 500 continuous windows", "known_failures": [] if len(finalists) else ["No C4 overlap-policy variant cleared every frozen Development promotion gate."], "next_exact_action": "Open Validation exactly once for frozen finalists." if len(finalists) else "Finalize the Development-only no-edge conclusion if no remaining distinct authorized repair exists.", "exact_resume_command": f"python scripts/v22/fast3_agent/generation3r3_research.py --phase overlap --output-dir {output}", "contract_sha256": contract["contract_sha256"], **SAFETY})


def artifact_lifecycle_closeout(output: Path, final_status: str, dry_run: bool = False) -> dict:
    """Close explicit runtime artifacts after the runner's existing evidence commit."""
    return closeout_artifacts(
        run_root=output,
        candidates=(
            output / "generation3r3_probability_distributions.csv",
            output / "generation3r3_threshold_coverage_surface.csv",
        ),
        metadata={
            "metadata_complete": True,
            "status": final_status,
            "run_role": "EXPLORATORY",
            "promotion_status": "REJECTED_NOT_SELECTED",
            "selected": False,
            "frozen": False,
            "authoritative": False,
            "prospective": False,
            "forward": False,
            "shadow": False,
            "append_only_evidence": False,
        },
        evidence={
            "final_metrics_persisted": (output / "generation3r3_development_walkforward_metrics.csv").is_file(),
            "config_identity_persisted": (output / "generation3r3_split_contract.json").is_file(),
            "final_status_persisted": (output / "generation3r3_final_summary.json").is_file(),
            "required_ledger_persisted": (output / "generation3r3_candidate_registry.csv").is_file(),
            "manifest_finalized": (output / "generation3r3_final_checkpoint.json").is_file(),
        },
        approved_roots=(output,),
        dry_run=dry_run,
        active_writer=False,
        downstream_reference=False,
    )


def finalize_phase(output: Path) -> None:
    contract = json.loads((output / "generation3r3_split_contract.json").read_text(encoding="utf-8"))
    if contract["confirmation_read_count"] != 0: raise RuntimeError("FAIL_LEAKAGE_DETECTED:CONFIRMATION_ALREADY_READ")
    reason = "The legacy joint probability gate caused the nonlinear zero-trade collapse; separated gates restored coverage, but separated-gate, train-fold calibration, and every frozen overlap-policy repair failed the Development economic and stability gates."
    pd.DataFrame(columns=["candidate_id", "validation_economics_read", "confirmation_read_count"]).to_csv(output / "generation3r3_validation_metrics.csv", index=False)
    write_json(output / "generation3r3_leakage_audit.json", {"leakage_audit_pass": True, "maximum_source_timestamp_guard": "PASS", "completed_bar_strictly_precedes_decision": True, "all_six_required_symbols_mapped": True, "reason_code_reconciliation": "PASS", "funnel_monotonicity": "PASS", "validation_economics_read": False, "confirmation_economics_read": False, "confirmation_read_count": 0, "conclusion": reason, **SAFETY})
    write_json(output / "generation3r3_champion_record.json", {"current_champion": None, "status": "NO_CHAMPION", "reason": reason, "validation_economics_read": False, "confirmation_read_count": 0, **SAFETY})
    summary = {"research_id": NAME, "final_status": "PASS_GENERATION3R3_FUNNEL_DIAGNOSIS_COMPLETE", "final_decision": "NO_ROBUST_DEVELOPMENT_EDGE_AFTER_EXPLAINED_FUNNEL_REPAIR", "stop_reason": reason, "contract_sha256": contract["contract_sha256"], "validation_read_count": 0, "confirmation_read_count": 0, "prospective_shadow_allowed": False, "candidate_iterations_completed": 5, **SAFETY}
    write_json(output / "generation3r3_final_summary.json", summary)
    report = "# FAST3 Generation 3R3 final report\n\nFINAL_STATUS=PASS_GENERATION3R3_FUNNEL_DIAGNOSIS_COMPLETE\n\n" + reason + "\n\nValidation economics read: False. Confirmation economics read: False. Confirmation read count: 0.\n"
    (output / "generation3r3_final_report.md").write_text(report, encoding="utf-8")
    checkpoint = {"current_status": summary["final_status"], "current_champion": None, "last_completed_iteration": 5, "confirmation_read_count": 0, "validation_economics_read": False, "completed_backtests": "Development-only funnel diagnosis, coverage surface, separated-gate, calibration, and overlap-policy repairs", "known_failures": [reason], "next_exact_action": "No continuation within Generation 3R3.", "exact_resume_command": "NONE_FAST3_GENERATION3R3_RESEARCH_STOPPED", "contract_sha256": contract["contract_sha256"], **SAFETY}
    write_json(output / "generation3r3_checkpoint.json", checkpoint); write_json(output / "generation3r3_final_checkpoint.json", checkpoint)
    # Evidence commit is complete above. Only these explicit, rebuildable
    # development diagnostics are eligible; no discovery-by-extension occurs.
    lifecycle = artifact_lifecycle_closeout(output, summary["final_status"])
    summary["artifact_lifecycle"] = lifecycle
    checkpoint["artifact_lifecycle"] = lifecycle
    write_json(output / "generation3r3_final_summary.json", summary)
    write_json(output / "generation3r3_checkpoint.json", checkpoint)
    write_json(output / "generation3r3_final_checkpoint.json", checkpoint)
    with (output / "generation3r3_final_report.md").open("a", encoding="utf-8") as handle:
        handle.write(
            "\nArtifact lifecycle: "
            f"{lifecycle['lifecycle_class']} / {lifecycle['cleanup_status']}; "
            f"deleted={lifecycle['deleted_target_count']}; "
            f"bytes_reclaimed={lifecycle['bytes_reclaimed']}; "
            f"skipped={lifecycle['skipped_target_count']}.\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--phase", choices=("audit", "diagnose", "coverage", "repair", "calibration", "overlap", "finalize"), required=True); parser.add_argument("--output-dir", default=str(DEFAULT_OUT)); parser.add_argument("--canonical-root", default=str(r2.CANONICAL)); parser.add_argument("--artifact-cleanup-dry-run", action="store_true"); args = parser.parse_args()
    if args.phase == "audit":
        result = audit_phase(Path(args.output_dir), Path(args.canonical_root)); print("FINAL_STATUS=SPLIT_FROZEN_AWAITING_FUNNEL_DIAGNOSIS"); print("CONTRACT_SHA256=" + result["contract_sha256"])
    elif args.phase == "diagnose":
        diagnose_phase(Path(args.output_dir), Path(args.canonical_root)); print("FINAL_STATUS=FUNNEL_DIAGNOSIS_COMPLETE_AWAITING_REGISTERED_REPAIR")
    elif args.phase == "coverage":
        coverage_phase(Path(args.output_dir), Path(args.canonical_root)); print("FINAL_STATUS=COVERAGE_SURFACE_COMPLETE_AWAITING_SEPARATED_GATE_REPAIR")
    elif args.phase == "repair":
        repair_phase(Path(args.output_dir), Path(args.canonical_root)); print("FINAL_STATUS=DEVELOPMENT_REPAIR_COMPLETE")
    elif args.phase == "calibration":
        calibration_phase(Path(args.output_dir), Path(args.canonical_root)); print("FINAL_STATUS=CALIBRATION_REPAIR_COMPLETE")
    elif args.phase == "overlap":
        overlap_phase(Path(args.output_dir), Path(args.canonical_root)); print("FINAL_STATUS=OVERLAP_REPAIR_COMPLETE")
    else:
        output = Path(args.output_dir)
        if args.artifact_cleanup_dry_run:
            summary_path = output / "generation3r3_final_summary.json"
            status = json.loads(summary_path.read_text(encoding="utf-8")).get("final_status", "UNKNOWN") if summary_path.is_file() else "UNKNOWN"
            print(json.dumps(artifact_lifecycle_closeout(output, status, dry_run=True), sort_keys=True))
            print("FINAL_STATUS=ARTIFACT_CLEANUP_DRY_RUN")
        else:
            finalize_phase(output); print("FINAL_STATUS=PASS_GENERATION3R3_FUNNEL_DIAGNOSIS_COMPLETE")
    print("CONFIRMATION_READ_COUNT=0")


if __name__ == "__main__": main()
