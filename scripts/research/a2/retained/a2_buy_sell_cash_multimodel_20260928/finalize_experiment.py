"""Read-only final audit and Chinese report for the prespecified 70 scenarios.

Run only after all frozen replays finish.  This module never imports a trainer,
fits an estimator, changes a model, reruns a portfolio, or chooses a winner.
--self-test exercises pure formatting/calculation helpers without reading data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
BASE = ["joint_ridge", "joint_elastic_net", "joint_logistic", "joint_hgb",
        "joint_q10", "joint_q50", "joint_q90", "joint_quantile_risk", "joint_mlp",
        "joint_rl_ensemble", "joint_rl_zero_control", "cash_control", "joint_hgb_lw", "joint_hgb_pca"]
ENSEMBLES = ["ensemble_equal", "ensemble_consensus_risk", "ensemble_stacked"]
MEMBERS = ["joint_ridge", "joint_elastic_net", "joint_logistic", "joint_hgb", "joint_quantile_risk", "joint_mlp"]
LEDGERS = ["daily", "trades", "positions", "target_decisions", "diagnostics", "valuation_intervals",
           "raw_model_outputs", "signal_contexts", "operational_actions", "execution_results"]
CUTOFF = {"validation": "2025-01-01", "final": "2026-01-01"}
META_CUTOFF = {"validation": "2025-07-01", "final": "2026-01-01"}
DISPLAY = {"joint_ridge": "Ridge", "joint_elastic_net": "Elastic Net", "joint_logistic": "逻辑回归",
           "joint_hgb": "HGB", "joint_q10": "Q10", "joint_q50": "Q50", "joint_q90": "Q90",
           "joint_quantile_risk": "联合分位数风险", "joint_mlp": "直接 MLP",
           "joint_rl_ensemble": "RL 双种子", "joint_rl_zero_control": "RL 零更新",
           "cash_control": "现金对照", "joint_hgb_lw": "HGB + LW", "joint_hgb_pca": "HGB + PCA",
           "ensemble_equal": "六成员等权集成", "ensemble_consensus_risk": "分歧与风险集成",
           "ensemble_stacked": "学习权重集成"}
VERIFIED_HASHES: dict[str, str] = {}


def need(condition, message):
    if not bool(condition):
        raise RuntimeError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_hash(path, expected):
    key = str(Path(path).resolve())
    if key in VERIFIED_HASHES:
        need(VERIFIED_HASHES[key] == expected, f"INCONSISTENT_FROZEN_BINDINGS:{key}")
    else:
        need(sha(key) == expected, f"HASH_CHANGED:{key}")
        VERIFIED_HASHES[key] = expected


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (Path, pd.Timestamp)):
        return str(value)
    return value


def write(path, value):
    Path(path).write_text(json.dumps(clean(value), ensure_ascii=False, indent=2,
                                   allow_nan=False), encoding="utf-8")


def near(actual, expected, message, atol=1e-6):
    need(np.allclose(np.asarray(actual, float), np.asarray(expected, float),
                     rtol=1e-10, atol=atol, equal_nan=True), message)


def scenario_groups():
    groups = []
    for year, costs in [(2025, [10]), (2026, [10, 5, 25])]:
        for cost in costs:
            groups.append(dict(family="base", year=year, cost=cost, window="full_available",
                               folder=ROOT / f"evaluation_{year}/cost_{cost}", names=BASE))
    groups.append(dict(family="ensemble", year=2025, cost=10, window="full_available",
                       folder=ROOT / "ensemble_2025/cost_10", names=ENSEMBLES[:2]))
    groups.append(dict(family="ensemble", year=2025, cost=10, window="H2",
                       folder=ROOT / "ensemble_2025_H2/cost_10", names=ENSEMBLES))
    for cost in [10, 5, 25]:
        groups.append(dict(family="ensemble", year=2026, cost=cost, window="full_available",
                           folder=ROOT / f"ensemble_2026/cost_{cost}", names=ENSEMBLES))
    need(sum(len(g["names"]) for g in groups) == 70, "BAD_EXPECTED_SCENARIO_COUNT")
    return groups


def preflight(groups):
    """Check every completion marker before reading any economic ledger."""
    missing = [str(g["folder"] / "COMPLETE.json") for g in groups
               if not (g["folder"] / "COMPLETE.json").is_file()]
    missing += [str(g["folder"] / n / "PATH_COMPLETE.json") for g in groups for n in g["names"]
                if not (g["folder"] / n / "PATH_COMPLETE.json").is_file()]
    need(not missing, "WAIT_FOR_ALL_FROZEN_REPLAYS:" + "|".join(missing))
    for g in groups:
        complete = read(g["folder"] / "COMPLETE.json")
        need(complete["status"] == "PASS" and complete["fit_attempts"] == 0
             and complete["sources_unchanged"] and complete["policies"] == len(g["names"]),
             f"INCOMPLETE_OR_REFITTED_REPLAY:{g['folder']}")
        binding = read(g["folder"] / "FROZEN_BEFORE_REPLAY.json")
        need(binding["roster"] == g["names"] and binding["year"] == g["year"], "REPLAY_ROSTER_OR_YEAR_CHANGED")
        need(binding.get("cost_bps", binding.get("cost")) == g["cost"], "REPLAY_COST_CHANGED")
        need(binding["stage"] == ("validation" if g["year"] == 2025 else "final"), "REPLAY_STAGE_CHANGED")
        need(not binding["blind_test"], "INVALID_BLIND_TEST_CLAIM")
        if g["family"] == "ensemble":
            need(binding["half"] == (g["window"] == "H2"), "REPLAY_H2_BOUNDARY_CHANGED")
        for path, digest in binding.get("source_sha256", binding.get("sources", {})).items():
            check_hash(path, digest)


def check_sources(entries):
    for value in entries.values():
        check_hash(value["path"], value["sha256"])


def training_audit():
    linear = read(ROOT / "linear_artifacts/FIT_RECEIPT.json")
    contract = read(ROOT / "linear_artifacts/PRE_FIT_CONTRACT.json")
    need(linear["status"] == "PASS" and linear["fit_calls"] == 14
         and linear["test2026_rows_read"] == linear["hyperparameter_search_count"] == 0, "LINEAR_TRAINING_RECEIPT_FAILURE")
    check_hash(ROOT / "linear_artifacts/PRE_FIT_CONTRACT.json", linear["pre_fit_contract_sha256"])
    check_sources(contract["frozen_sources"])
    names = {"ridge", "elastic_net", "logistic", "hgb", "q10", "q50", "q90"}
    need({(r["stage"], r["name"]) for r in linear["fits"]} == {(s, n) for s in CUTOFF for n in names}, "LINEAR_MODEL_GRID_INCOMPLETE")
    for stage, cutoff in CUTOFF.items():
        audit = linear["stages"][stage]
        need(audit["cutoff_exclusive"] == cutoff and audit["selected_label_end_max"] < cutoff, "LINEAR_LABEL_LEAKAGE")
        key_path = ROOT / f"linear_artifacts/sample_keys_{stage}.parquet"
        check_hash(key_path, audit["sample_keys_sha256"])
        keys = pd.read_parquet(key_path)
        need(keys.signal_date.lt(cutoff).all() and keys.label_end_date.lt(cutoff).all()
             and keys.label_end_date.gt(keys.signal_date).all()
             and not keys.duplicated(["signal_date", "ticker"]).any(), "LINEAR_SAMPLE_BOUNDARY_FAILURE")
        need(len(keys) == 13333 and keys.signal_date.nunique() == audit["eligible_dates"], "LINEAR_SAMPLE_COVERAGE_FAILURE")
    for record in linear["fits"] + linear["numerical_repairs"]:
        check_hash(record["artifact"], record["artifact_sha256"])
        need(record["train_rows"] == 199995, "LINEAR_FIXED_BUDGET_CHANGED")
    for record in linear["numerical_repairs"]:
        base = next(x for x in linear["fits"] if x["stage"] == record["stage"] and x["name"] == record["name"])
        need(record["name"] == "elastic_net" and record["converged"] and not base["converged"]
             and record["objective_and_data_unchanged"] and record["matrix_sha256"] == base["matrix_sha256"]
             and record["reward_sha256"] == base["reward_sha256"], "ELASTIC_REPAIR_CHANGED_OBJECTIVE")
    need(read(ROOT / "linear_artifacts/TEST_RECEIPT.json")["status"] == "PASS", "LINEAR_TESTS_NOT_PASS")

    neural = read(ROOT / "neural_artifacts/TRAIN_RECEIPT.json")
    need(neural["status"] == "PASS" and neural["completed_models"] == 6
         and neural["fit_2026_rows"] == 0 and neural["source_hashes_unchanged"], "NEURAL_RECEIPT_FAILURE")
    check_hash(ROOT / "neural_artifacts/PRE_FIT_CONTRACT.json", neural["pre_fit_contract_sha256"])
    check_sources(neural["specification"]["frozen_sources"])
    expected_neural = {(s, method, seed) for s in CUTOFF
                       for method, seed in [("direct", 20260928), ("rl", 20260928), ("rl", 20260929)]}
    need({(x["stage"], x["method"], x["seed"]) for x in neural["artifacts"]} == expected_neural, "NEURAL_MODEL_GRID_INCOMPLETE")
    for record in neural["artifacts"]:
        cutoff = CUTOFF[record["stage"]]
        need(record["reward_end_before"] == cutoff and record["train_signal_max"] < cutoff
             and record["updates"] > 0 and record["parameter_delta_l2"] > 0
             and record["epochs"] == (6 if record["method"] == "direct" else 4), "NEURAL_DATE_OR_FIXED_BUDGET_FAILURE")
        check_hash(record["path"], record["sha256"])
        check_hash(record["zero_path"], record["zero_sha256"])
    for stage, record in neural["normalization"].items():
        need(record["signal_max"] < CUTOFF[stage] and record["cutoff_exclusive"] == CUTOFF[stage], "NEURAL_SCALER_LEAKAGE")
        check_hash(record["path"], record["sha256"])
    need(read(ROOT / "neural_artifacts/VERIFICATION.json")["status"] == "PASS", "NEURAL_TESTS_NOT_PASS")

    risk = read(ROOT / "risk_artifacts/TRAIN_RECEIPT.json")
    need(risk["status"] == "PASS" and risk["fit_2026_rows"] == 0
         and risk["model_fit_calls"] == 6 and risk["factor_decompositions"] == 2, "RISK_RECEIPT_FAILURE")
    for stage, cutoff in CUTOFF.items():
        dest = ROOT / "risk_artifacts" / stage
        check_hash(dest / "TRAIN_RECEIPT.json", risk["stage_receipts_sha256"][stage])
        record = read(dest / "TRAIN_RECEIPT.json")
        need(record["status"] == "PASS" and record["cutoff_exclusive"] == cutoff
             and record["risk"]["return_last"] < cutoff and record["risk"]["return_rows"] == 252
             and record["diagnostics"]["sample_last"] < cutoff
             and record["diagnostics"]["sample_rows"] <= 20000 and record["fit_2026_rows"] == 0,
             "RISK_OR_DIAGNOSTIC_DATE_LEAKAGE")
        check_hash(ROOT / "risk_aux.py", record["producer_sha256"])
        for path, digest in record["source_sha256"].items():
            check_hash(path, digest)
        for filename, digest in record["artifacts_sha256"].items():
            check_hash(dest / filename, digest)

    meta = read(ROOT / "ensemble_artifacts/TRAIN_RECEIPT.json")
    meta_contract = read(ROOT / "ensemble_artifacts/PRE_FIT_CONTRACT.json")
    design = read(ROOT / "ensemble_artifacts/META_DESIGN_CONTRACT.json")
    need(meta["status"] == "PASS" and meta["fit_calls"] == 2 and meta["fit_2026_rows"] == 0
         and not meta["2026_outcomes_read"] and meta["base_stage"] == "validation", "META_RECEIPT_FAILURE")
    need(design["methods"] == MEMBERS and design["base_training_labels_before"] == "2025-01-01"
         and design["stages_cutoff_exclusive"] == META_CUTOFF and design["hyperparameter_searches"] == 0,
         "META_DESIGN_CHANGED")
    need(meta_contract["base_returns_out_of_sample"] and meta_contract["base_fit_end_exclusive"] == "2025-01-01"
         and meta_contract["fit_2026_rows"] == 0, "META_BASE_RETURNS_NOT_OOS")
    check_hash(ROOT / "ensemble_artifacts/PRE_FIT_CONTRACT.json", meta["pre_fit_contract_sha256"])
    check_hash(ROOT / "ensemble_artifacts/META_DESIGN_CONTRACT.json", meta_contract["design_sha256"])
    check_hash(ROOT / "ensemble_train.py", meta_contract["producer_sha256"])
    for path, digest in meta_contract["source_sha256"].items():
        check_hash(path, digest)
    meta_weights = {}
    for record in meta["fits"]:
        stage, cutoff = record["stage"], META_CUTOFF[record["stage"]]
        check_hash(record["artifact"], record["artifact_sha256"])
        dest = ROOT / "ensemble_artifacts"
        check_hash(dest / f"{stage}_training_returns.parquet", record["training_returns_sha256"])
        check_hash(dest / f"{stage}_date_inclusion.csv", record["date_inclusion_sha256"])
        panel = pd.read_parquet(dest / f"{stage}_training_returns.parquet")
        need(panel.columns.tolist() == MEMBERS and panel.index.min() >= pd.Timestamp("2025-01-01")
             and panel.index.max() < pd.Timestamp(cutoff) and len(panel) == record["rows"]
             and np.isfinite(panel.to_numpy(float)).all(), "META_TRAINING_DATA_BOUNDARY_FAILURE")
        artifact = read(record["artifact"])
        need(artifact["methods"] == MEMBERS and artifact["base_stage"] == "validation"
             and artifact["training_cutoff_exclusive"] == cutoff, "META_MODEL_STAGE_FAILURE")
        w = np.array([artifact["weights"][n] for n in MEMBERS])
        need(np.isfinite(w).all() and abs(w.sum()-1) < 1e-8
             and w.min() >= .05-1e-8 and w.max() <= .35+1e-8, "META_WEIGHT_CONSTRAINT_FAILURE")
        near(panel.mean().to_numpy(), artifact["solver"]["mean_daily_net_returns"], "META_MEAN_MISMATCH", atol=1e-12)
        near(panel.cov().to_numpy(), artifact["solver"]["return_covariance"], "META_COVARIANCE_MISMATCH", atol=1e-12)
        meta_weights[stage] = dict(weights=artifact["weights"], rows=len(panel),
                                   first=str(panel.index.min().date()), last=str(panel.index.max().date()),
                                   cutoff_exclusive=cutoff)
    need(set(meta_weights) == set(META_CUTOFF), "META_MISSING_STAGE")
    return dict(status="PASS", linear_primary_fits=14, elastic_numerical_repairs=len(linear["numerical_repairs"]),
                neural_trained_models=6, neural_parameter_updates=neural["actual_parameter_updates"],
                risk_model_fits=6, factor_decompositions=2, diagnostic_scaler_fits=2,
                meta_fits=2, fit_2026_rows=0, hyperparameter_searches=0, meta_weights=meta_weights)


def audit_ledger(tables, year, cost, window):
    """Independent reconstruction from saved fills, rather than stored metrics."""
    daily = tables["daily"].sort_values("date").reset_index(drop=True)
    trades, positions, targets, contexts = [tables[n] for n in ["trades", "positions", "target_decisions", "signal_contexts"]]
    need(not daily.date.duplicated().any() and daily.date.dt.year.eq(year).all(), "DAILY_DATE_BOUNDARY_FAILURE")
    need(daily.date.min() >= pd.Timestamp("2025-07-01" if window == "H2" else f"{year}-01-01"), "REPLAY_WINDOW_START_FAILURE")
    signal_end = pd.Timestamp("2026-09-22" if year == 2026 else "2025-12-29")
    value_end = pd.Timestamp("2026-09-24" if year == 2026 else "2025-12-31")
    need(daily.date.max() == value_end and contexts.signal_date.max() == signal_end, "REPLAY_WINDOW_END_FAILURE")
    need(contexts.signal_date.dt.year.eq(year).all(), "SIGNAL_YEAR_FAILURE")
    if len(targets):
        need(targets.signal_date.le(signal_end).all() and targets.execution_date.gt(targets.signal_date).all(), "TARGET_EXECUTION_CLOCK_FAILURE")
        need(targets.raw_model_weight.dropna().between(0, .1+1e-7).all(), "MODEL_SINGLE_NAME_CAP_FAILURE")
    need(daily.cash.ge(-1e-6).all() and daily.actual_name_count.le(20).all(), "ACCOUNT_CONSTRAINT_FAILURE")
    need((contexts.active_target_weight <= contexts.final_available_weight+1e-7).all()
         and (contexts.active_target_count <= contexts.final_available_slots).all(), "RESERVATION_BUDGET_FAILURE")
    cash_flow = pd.Series(0., index=pd.DatetimeIndex(daily.date))
    if len(trades):
        need(trades.execution_date.gt(trades.signal_date).all() and trades.signal_date.le(signal_end).all(), "TRADE_CLOCK_FAILURE")
        if year == 2026:
            need(trades.execution_date.le("2026-09-23").all(), "TRADE_AFTER_FINAL_EXECUTION_SESSION")
        need(trades.notional.ge(0).all() and trades.index_units.ge(0).all(), "NEGATIVE_TRADE")
        near(trades.notional, trades.index_units*trades.price, "TRADE_NOTIONAL_IDENTITY")
        near(trades.transaction_cost, trades.notional*cost/10000, "TRADE_FEE_IDENTITY")
        signed = np.where(trades.side.eq("BUY"), -trades.notional, trades.notional)-trades.transaction_cost.to_numpy()
        cash_flow = pd.Series(signed, index=pd.DatetimeIndex(trades.execution_date)).groupby(level=0).sum().reindex(daily.date, fill_value=0)
        buys = trades.loc[trades.side.eq("BUY")].merge(targets[["order_id", "signal_day_adv"]], on="order_id", validate="one_to_one")
        need(buys.signal_day_adv.notna().all() and (buys.notional <= .01*buys.signal_day_adv+1e-6).all(), "BUY_CAPACITY_FAILURE")
        need(not trades.decision_semantic.eq("MODEL_NO_DECISION").any(), "OMISSION_WAS_TRADED")
    reconstructed_cash = 1e6 + cash_flow.to_numpy().cumsum()
    near(daily.cash, reconstructed_cash, "INDEPENDENT_CASH_RECONSTRUCTION", atol=1e-5)
    maximum_cash_error = float(np.max(np.abs(daily.cash.to_numpy()-reconstructed_cash)))
    if len(positions):
        need(not positions.duplicated(["date", "ticker"]).any(), "DUPLICATE_POSITION_KEY")
        actual = positions.pivot(index="date", columns="ticker", values="index_units").reindex(daily.date).fillna(0.)
    else:
        actual = pd.DataFrame(index=pd.DatetimeIndex(daily.date))
    if len(trades):
        delta = trades.assign(_units=np.where(trades.side.eq("BUY"), trades.index_units, -trades.index_units))
        accumulated = delta.pivot_table(index="execution_date", columns="ticker", values="_units", aggfunc="sum")
        accumulated = accumulated.reindex(daily.date, fill_value=0.).fillna(0.).cumsum()
    else:
        accumulated = pd.DataFrame(index=pd.DatetimeIndex(daily.date))
    securities = sorted(set(actual.columns) | set(accumulated.columns))
    near(actual.reindex(columns=securities, fill_value=0), accumulated.reindex(columns=securities, fill_value=0), "INDEPENDENT_POSITION_RECONSTRUCTION", atol=1e-7)
    value = positions.groupby("date").market_value.sum().reindex(daily.date, fill_value=0.).to_numpy() if len(positions) else np.zeros(len(daily))
    expected_nav = reconstructed_cash+value
    expected_nav[daily.unknown_count.to_numpy() > 0] = np.nan
    near(daily.nav, expected_nav, "INDEPENDENT_NAV_RECONSTRUCTION", atol=1e-5)
    expected_certified = expected_nav.copy()
    expected_certified[(daily.stale_count.to_numpy() > 0) | (daily.unknown_count.to_numpy() > 0)] = np.nan
    near(daily.certified_nav, expected_certified, "FALSE_CERTIFIED_NAV", atol=1e-5)
    expected_return = pd.Series(expected_certified).pct_change(fill_method=None).to_numpy(copy=True)
    expected_return[0] = np.nan
    near(daily.net_return.iloc[1:], expected_return[1:], "RETURN_BRIDGED_UNCERTIFIED_INTERVAL", atol=1e-10)
    daily_fees = trades.groupby("execution_date").transaction_cost.sum().reindex(daily.date, fill_value=0).to_numpy() if len(trades) else np.zeros(len(daily))
    near(daily.transaction_cost_amount, daily_fees, "DAILY_COST_IDENTITY")
    certified = bool(daily.certified_nav.notna().all())
    nav = daily.nav.to_numpy(float)
    drawdown = float(np.min(np.r_[1e6, nav]/np.maximum.accumulate(np.r_[1e6, nav])-1)) if year == 2025 and certified else None
    return dict(status="PASS", days=len(daily), trades=len(trades), independent_cash_error_max=maximum_cash_error,
                indicative_return=float(nav[-1]/1e6-1) if np.isfinite(nav[-1]) else None,
                certified_return_2025=float(nav[-1]/1e6-1) if year == 2025 and certified else None,
                max_drawdown_2025_certified=drawdown, mean_cash=float(daily.cash_weight.mean()),
                last_cash=float(daily.cash_weight.iloc[-1]), fees=float(daily_fees.sum()),
                uncertified_days=int(daily.certified_nav.isna().sum()),
                cash_weight_unknown_days=int(daily.cash_weight.isna().sum()),
                stale_days=int(daily.stale_count.gt(0).sum()), unknown_days=int(daily.unknown_count.gt(0).sum()),
                actual_names_max=int(daily.actual_name_count.max()),
                signal_start=str(contexts.signal_date.min().date()), signal_end=str(contexts.signal_date.max().date()),
                valuation_start=str(daily.date.min().date()), valuation_end=str(daily.date.max().date()))


def latest_outputs(tables, name, cost, folder):
    date = pd.Timestamp("2026-09-22")
    targets = tables["target_decisions"]
    targets = targets.loc[targets.signal_date.eq(date)].copy()
    raw = tables["raw_model_outputs"].loc[lambda x: x.signal_date.eq(date)]
    contexts = tables["signal_contexts"].loc[lambda x: x.signal_date.eq(date)]
    need(len(raw) == len(contexts) == 1, "LAST_SIGNAL_CONTEXT_MISSING")
    raw_cell = raw.iloc[0].raw_model_outputs_json
    opinions = json.loads(raw_cell) if isinstance(raw_cell, str) else {}
    opinions = opinions or {}
    fills = tables["trades"].loc[lambda x: x.signal_date.eq(date)]
    events = tables["execution_results"].loc[lambda x: x.signal_date.eq(date)]
    decisions = []
    for target in targets.to_dict("records"):
        detail = opinions.get(target["ticker"], {})
        actual_fills = fills.loc[fills.order_id.eq(target["order_id"])]
        actual_events = events.loc[events.order_id.eq(target["order_id"])]
        difference = target["target_weight"]-target["current_weight"]
        intent = "保留原份额" if target["order_type"] == "HOLD_UNITS" else "买入或加仓" if difference > 1e-10 else "卖出或减仓" if difference < -1e-10 else "持有或零配置"
        row = dict(policy=name, cost_bps=cost, **target, intent=intent,
                   filled_buy_notional=float(actual_fills.loc[actual_fills.side.eq("BUY"), "notional"].sum()),
                   filled_sell_notional=float(actual_fills.loc[actual_fills.side.eq("SELL"), "notional"].sum()),
                   filled_fees=float(actual_fills.transaction_cost.sum()),
                   execution_statuses="|".join(map(str, actual_events.status.tolist())),
                   execution_reasons="|".join(map(str, actual_events.reason.tolist())),
                   member_opinions_json=json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
                   ledger_path=str(folder / "target_decisions.parquet"),
                   raw_opinions_path=str(folder / "raw_model_outputs.parquet"))
        if name in ENSEMBLES and detail:
            need(detail["member_names"] == MEMBERS and len(detail["member_targets"]) == 6, "ENSEMBLE_MEMBER_TRACE_FAILURE")
            for member, weight, coefficient in zip(MEMBERS, detail["member_targets"], detail["coefficients"]):
                row[f"member_target__{member}"] = weight
                row[f"member_coefficient__{member}"] = coefficient
            row.update(ensemble_mean_target=detail["mean_target"], ensemble_disagreement=detail["disagreement"],
                       ensemble_risk_scale=detail["risk_scale"], ensemble_pre_execution_target=detail["ensemble_target"])
            near(target["raw_model_weight"], detail["ensemble_target"], "ENSEMBLE_OPINION_TARGET_MISMATCH", atol=1e-10)
        decisions.append(row)
    context = contexts.iloc[0]
    daily = tables["daily"].sort_values("date")
    execution = daily.loc[daily.date.eq("2026-09-23")]
    need(len(execution) == 1 and daily.date.iloc[-1] == pd.Timestamp("2026-09-24"), "LATEST_CASH_CLOCK_FAILURE")
    total_target = context.final_reserved_weight+context.active_target_weight
    last = daily.iloc[-1]
    cash_row = dict(policy=name, cost_bps=cost, signal_date=str(date.date()), signal_cash_amount=context.cash,
                    signal_cash_weight=context.cash_weight, signal_nav=context.nav,
                    signal_policy_called=bool(context.policy_called),
                    signal_target_cash_weight=1-total_target if np.isfinite(total_target) else None,
                    signal_active_target_weight=context.active_target_weight,
                    signal_reserved_weight=context.final_reserved_weight,
                    signal_active_target_names=context.active_target_count,
                    signal_reserved_names=context.final_reserved_slots,
                    execution_date="2026-09-23", execution_cash_amount=execution.iloc[0].cash,
                    execution_cash_weight=execution.iloc[0].cash_weight,
                    execution_valuation_status=execution.iloc[0].valuation_status,
                    valuation_date="2026-09-24", cash_amount=last.cash, indicative_cash_weight=last.cash_weight,
                    indicative_nav=last.nav, certified_nav=last.certified_nav,
                    valuation_status=last.valuation_status, actual_names=int(last.actual_name_count),
                    stale_count=int(last.stale_count), unknown_count=int(last.unknown_count),
                    last_actual_trade_date=str(tables["trades"].execution_date.max().date()) if len(tables["trades"]) else None,
                    daily_ledger_path=str(folder / "daily.parquet"))
    return decisions, cash_row


def fmt(value, percent=False):
    if value is None or (isinstance(value, (float, np.floating)) and not np.isfinite(value)):
        return "—"
    return f"{value:.2%}" if percent else f"{value:,.2f}"


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"]*len(headers)) + " |",
                       *["| " + " | ".join(str(v).replace("|", "/") for v in row) + " |" for row in rows]])


def report_text(all_rows, cash, training, limits):
    frame = pd.DataFrame(all_rows)
    lines = ["# A2 多模型协同：买卖目标、现金与冻结回放", "",
             "本批已完成新模型训练、六成员目标融合、两次集成权重学习及全部 70 个预定场景。结果通过文件哈希、时间边界和独立账本重算核对；这证明本批实验执行完整，不等于收益通过正式全池认证，也不据 2026 结果挑选冠军。", "",
             "**协同方式。** Ridge、Elastic Net、逻辑回归、HGB、联合分位数风险与直接 MLP 共六个决策器，在同一账户当前持仓、现金和可用名额上分别提出目标仓位，再融合为一个共同账户的买卖目标。融合的是同单位的目标权重，未直接混加收益预测、概率和神经网络 logit。RL 双种子、零更新、风险变体、单模型及现金账户保留为对照。", "",
             "固定方案为六成员等权、分歧加现金并限制风险，以及学习非负权重的 stacked 集成。最多 20 只、单票主动目标 10%、主动加保留仓位目标 95%；锁定旧仓可能随价格漂移超过目标上限。截掉的权重留作现金，不放大剩余仓位来凑满仓。信号在收盘生成，下一交易日开盘执行；本任务没有分钟级进出场标签。", "",
             "**训练与泄漏边界。** 七种线性/树模型各训练 validation/final 两阶段，共 14 次主拟合；Elastic Net 两次同样本同目标的数值收敛修复没有追加超参数搜索。每阶段 199,995 反事实行，分别覆盖 500/750 个成熟交易日。MLP 六轮，RL 两个预定种子各四轮；另重新拟合阶段专属风险、标准化、聚类和异常检测。基础 validation 标签在 2025 年前成熟，final 标签在 2026 年前成熟；全部模型与风险估计的 2026 拟合行数为零。", "",
             "stacked 的六个基础成员均使用截至 2024 年的模型生成 2025 样本外、已扣成本日收益。validation 权重只学习 2025 上半年，再在下半年从 100 万美元现金开始冻结验证；final 权重学习全年 2025，只用于 2026。学习目标是成员独立账户收益的凸组合代理；融合后的非线性约束、实际成交和现金已另用共同账本重算。2025/2026 历史结果此前已被观察，本次固定配方不能恢复原始盲测。", "",
             "**学习型集成的冻结权重。**", ""]
    weight_rows = [[DISPLAY[n], fmt(training["meta_weights"]["validation"]["weights"][n], True),
                    fmt(training["meta_weights"]["final"]["weights"][n], True)] for n in MEMBERS]
    lines += [table(["成员", "H1 学习 → H2 验证", "全年 2025 学习 → 2026"], weight_rows), ""]
    for stage in ["validation", "final"]:
        m = training["meta_weights"][stage]
        lines += [f"{stage} 权重学习使用 {m['rows']} 个完整合格收益日：{m['first']}—{m['last']}；未填补不合格日期。", ""]
    for year in [2025, 2026]:
        subset = frame.loc[frame.year.eq(year) & frame.cost_bps.eq(10) & frame.window.eq("full_available")]
        rows = []
        for name in BASE+ENSEMBLES:
            found = subset.loc[subset.policy.eq(name)]
            if found.empty:
                continue
            r = found.iloc[0]
            rows.append([DISPLAY[name], fmt(r.certified_return_2025 if year == 2025 else r.indicative_return, True),
                         fmt(r.max_drawdown_2025_certified, True) if year == 2025 else "不计算",
                         fmt(r.mean_cash, True), fmt(r.fees), int(r.uncertified_days)])
        lines += [f"**{year} 固定 10bp 单边成本。** " + ("仅完整 certified 账本计算回报与最大回撤。" if year == 2025 else "以下只列 indicative 账面终值变化，不是可认证收益；不计算 2026 回撤、排名或冠军。"), "",
                  table(["固定顺序的方案", "合格研究指数回报" if year == 2025 else "indicative 终值变化",
                         "最大回撤", "平均现金比重" if year == 2025 else "平均指示性现金比重", "累计费用/美元", "未认证日"], rows), ""]
        if year == 2026:
            lines += ["现金美元余额可由成交现金流独立重建；2026 现金比例的 NAV 分母可能陈旧或未认证，因此均值与期末比例均只作指示性数值。均值仅统计分母可计算的日期，未知分母不补零；ALL_SCENARIOS.csv 同时保留 cash_weight_unknown_days。", ""]
    subset = frame.loc[frame.year.eq(2025) & frame.window.eq("H2")]
    rows = [[DISPLAY[r.policy], fmt(r.certified_return_2025, True), fmt(r.max_drawdown_2025_certified, True),
             fmt(r.mean_cash, True), fmt(r.fees), int(r.uncertified_days)] for r in subset.itertuples()]
    lines += ["**2025 下半年同窗集成验证。** 三方案均从 2025-07-01 的 100 万美元现金开始。学习权重方案没有使用这段收益训练 validation meta 权重；全年 2025 的最终 meta 权重不用于此表。", "",
              table(["方案", "合格研究指数回报", "最大回撤", "平均现金", "费用/美元", "未认证日"], rows), "",
              "**2026 成本压力回放。** 下表与 10bp 使用完全相同的冻结模型和输入；5/25bp 不是新增独立样本，不据此重训或选择成本。费用会改变后续账户状态，因此它们是独立账本重放。完整现金、成交和资格列保存在 ALL_SCENARIOS.csv。", ""]
    rows = []
    for name in BASE+ENSEMBLES:
        pair = []
        for cost in [5, 25]:
            r = frame.loc[frame.year.eq(2026) & frame.policy.eq(name) & frame.cost_bps.eq(cost)].iloc[0]
            pair += [fmt(r.indicative_return, True), fmt(r.fees), int(r.uncertified_days)]
        rows.append([DISPLAY[name], *pair])
    lines += [table(["方案", "5bp indicative", "5bp 费用", "5bp 未认证日", "25bp indicative", "25bp 费用", "25bp 未认证日"], rows), "",
              "**最近信号和现金。** 最末信号为 2026-09-22，计划下一开盘执行日为 09-23，末次估值为 09-24。下列为集成方案 10bp 的目标现金和实际现金；比例以当日研究指数 NAV 为分母，若该 NAV 未认证则比例也仅为指示性值。目标与实际可因买入容量、费用、缺价和保留旧仓不同。", ""]
    rows = []
    for name in ENSEMBLES:
        r = next(x for x in cash if x["policy"] == name and x["cost_bps"] == 10)
        rows.append([DISPLAY[name], fmt(r["signal_target_cash_weight"], True), fmt(r["execution_cash_weight"], True),
                     fmt(r["indicative_cash_weight"], True), fmt(r["cash_amount"]), r["actual_names"], r["valuation_status"]])
    lines += [table(["方案", "09-22 目标现金", "09-23 执行后现金", "09-24 现金比", "现金金额/美元", "实际持仓数", "末日资格"], rows), "",
              "LAST_SIGNAL_DECISIONS.csv 保存全部 17 个方案 × 3 档成本的末信号股票目标、买卖/保留语义、实际成交、阻塞原因、六成员意见及原账本路径。显式零目标与无模型决策分开记录；无决策的旧仓保留原份额、名额和资金，不伪装为卖出。现金对照可能没有股票目标行，仍在 LATEST_CASH.csv 中完整列出。", "",
              "**尚未解决的数据资格。** 2026 只覆盖既有事后核验子池；原候选中仍有 " + f"{limits['unknown_rows']:,}" + " 行资格未知，完整候选池合格交易日为 0。最近公开 13F 沿用披露后第 5 个交易日生效的保守约定，不能称为即时逐机构到达。GLW 的 2026-02-26 事件日期与调整特征冲突尚未解决；历史供应商真实到达时间和全原池幸存者偏差也未获证明。保留未认证持仓和日期，未通过删掉坏日期或换区间修饰结果。", "",
              "2026 窗口为 2026-01-02—09-24，并非全年。价格和持仓单位是调整研究指数坐标，不是原始可交易股数或正式股东总收益。费用为单边比例代理，买入容量为信号日 ADV 的 1%；实盘撮合、税费和完整市场冲击未获认证。聚类和异常检测仅作诊断，未直接当成买卖信号。", "",
              "**可追查交付。** REPORT.md 为本文；ALL_SCENARIOS.csv 为全部 70 场景；LAST_SIGNAL_DECISIONS.csv 为末信号目标及成员意见；LATEST_CASH.csv 为信号、成交与期末现金；VERIFICATION.json 保存训练/回放审计、账本哈希、输出哈希和明确限制。所有表按事前方案顺序展示，没有按 2026 表现重排或选择模型。", ""]
    return "\n".join(lines)


def finalize():
    started = time.monotonic()
    groups = scenario_groups()
    preflight(groups)
    training = training_audit()
    qa_path = ROOT / "audit/QA_RECEIPT.json"
    qa = read(qa_path)
    need(qa["status"] == "PASS" and qa["unique_behavior_tests_passed"] >= 56, "BEHAVIOR_QA_NOT_COMPLETE")
    inherited = read(ROOT / "audit/INHERITED_INPUT_AUDIT.json")
    need(inherited["test2026"]["unknown_candidate_rows"] == 47271
         and inherited["test2026"]["complete_signal_days"] == 0
         and not inherited["test2026"]["formal_full_pool_test_allowed"], "INPUT_LIMITATIONS_CHANGED")
    for path, digest in inherited["input_sha256"].items():
        check_hash(path, digest)
    rows, latest, cash, checks = [], [], [], []
    for group in groups:
        for name in group["names"]:
            folder = group["folder"] / name
            receipt = read(folder / "PATH_COMPLETE.json")
            need(receipt["audit"]["status"] == "PASS" and set(receipt["ledger_sha256"]) == set(LEDGERS), "PATH_AUDIT_NOT_PASS")
            for key, digest in receipt["ledger_sha256"].items():
                check_hash(folder / f"{key}.parquet", digest)
            tables = {key: pd.read_parquet(folder / f"{key}.parquet") for key in LEDGERS}
            audit = audit_ledger(tables, group["year"], group["cost"], group["window"])
            saved = receipt["metrics"]
            need(saved["policy"] == name and saved["year"] == group["year"] and saved["cost_bps"] == group["cost"], "METRIC_IDENTITY_MISMATCH")
            for key in ["indicative_return", "max_drawdown_2025_certified", "mean_cash", "last_cash", "fees"]:
                near(np.nan if saved[key] is None else saved[key], np.nan if audit[key] is None else audit[key], f"SAVED_METRIC_MISMATCH:{name}:{key}", atol=1e-7)
            need(saved["uncertified_days"] == audit["uncertified_days"] and saved["trades"] == audit["trades"], "SAVED_COUNT_MISMATCH")
            row = dict(policy=name, label=DISPLAY[name], family=group["family"], year=group["year"],
                       cost_bps=group["cost"], window=group["window"], **audit,
                       blind_test=False, complete_original_pool=False if group["year"] == 2026 else None,
                       economic_evidence="indicative_only_not_model_selection" if group["year"] == 2026 else "certified_research_index" if not audit["uncertified_days"] else "uncertified",
                       path=str(folder), path_complete_sha256=sha(folder / "PATH_COMPLETE.json"))
            rows.append(row)
            checks.append(dict(policy=name, year=group["year"], cost_bps=group["cost"], window=group["window"],
                               status="PASS", independent_cash_error_max=audit["independent_cash_error_max"],
                               path_complete_sha256=row["path_complete_sha256"], ledger_sha256=receipt["ledger_sha256"]))
            if group["year"] == 2026:
                last_decisions, last_cash = latest_outputs(tables, name, group["cost"], folder)
                latest.extend(last_decisions)
                cash.append(last_cash)
            print(json.dumps(dict(audited=len(rows), expected=70, policy=name, year=group["year"], cost=group["cost"])), flush=True)
    need(len(rows) == 70 and len(cash) == 51, "FINAL_SCENARIO_OR_CASH_COUNT_FAILURE")
    # Bypass hash cache once at the end: no input or model may change during audit.
    for path, digest in VERIFIED_HASHES.items():
        need(sha(path) == digest, f"SOURCE_CHANGED_DURING_FINAL_AUDIT:{path}")
    limits = dict(unknown_rows=47271, full_pool_days=0, full_original_pool=False, blind_test=False,
                  complete_2026_year=False, glw_event_conflict_unresolved=True,
                  price_coordinate="adjusted_research_index_not_certified_shareholder_total_return",
                  prior_observation_not_erased=True, model_selection_on_2026_performed=False)
    # No output is written unless all expected scenarios and every audit pass.
    pd.DataFrame(rows).to_csv(ROOT / "ALL_SCENARIOS.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(latest).to_csv(ROOT / "LAST_SIGNAL_DECISIONS.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(cash).to_csv(ROOT / "LATEST_CASH.csv", index=False, encoding="utf-8-sig")
    (ROOT / "REPORT.md").write_text(report_text(rows, cash, training, limits), encoding="utf-8")
    outputs = ["REPORT.md", "ALL_SCENARIOS.csv", "LAST_SIGNAL_DECISIONS.csv", "LATEST_CASH.csv"]
    verification = dict(status="PASS_WITH_EXPLICIT_DATA_LIMITATIONS", generated_utc=datetime.now(timezone.utc).isoformat(),
                        expected_scenarios=70, audited_scenarios=len(rows), base_scenarios=56, ensemble_scenarios=14,
                        latest_cash_scenarios=len(cash), final_signal="2026-09-22", final_execution_session="2026-09-23",
                        final_valuation="2026-09-24", replay_fit_attempts=0, training=training,
                        behavior_qa=dict(status=qa["status"], unique_tests=qa["unique_behavior_tests_passed"],
                                         receipt_sha256=sha(qa_path), test_files=qa["test_files"]),
                        independent_reconstruction="cash, cumulative index units, NAV, certified NAV, fee, buy capacity, reservation budget, timing and no-decision semantics",
                        scenario_checks=checks, verified_source_and_ledger_count=len(VERIFIED_HASHES),
                        frozen_source_and_ledger_sha256=VERIFIED_HASHES,
                        all_sources_unchanged_after_audit=True, limitations=limits,
                        economic_rank_or_model_selection_performed=False,
                        producer_sha256=sha(Path(__file__)),
                        output_sha256={n: sha(ROOT / n) for n in outputs}, seconds=time.monotonic()-started)
    write(ROOT / "VERIFICATION.json", verification)
    print(json.dumps({"status": verification["status"], "scenarios": len(rows), "outputs": outputs+["VERIFICATION.json"]}), flush=True)


def self_test():
    need(len(scenario_groups()) == 9, "SCENARIO_GROUP_TEST_FAILED")
    need(sum(len(g["names"]) for g in scenario_groups() if g["family"] == "ensemble") == 14, "ENSEMBLE_COUNT_TEST_FAILED")
    need(fmt(None) == "—" and fmt(float("nan")) == "—" and fmt(.25, True) == "25.00%", "FORMATTING_TEST_FAILED")
    near([1., np.nan], [1., np.nan], "NAN_COMPARISON_TEST_FAILED")
    need(len(MEMBERS) == 6 and len(set(MEMBERS)) == 6, "HETEROGENEOUS_ROSTER_TEST_FAILED")
    need(clean({"bad": float("nan"), "n": np.int64(2)}) == {"bad": None, "n": 2}, "SERIALIZATION_TEST_FAILED")
    # A small fabricated ledger catches pandas index alignment errors in cash reconstruction.
    dates = pd.to_datetime(["2025-12-30", "2025-12-31"])
    signal = pd.Timestamp("2025-12-29")
    synthetic = {
        "daily": pd.DataFrame(dict(date=dates, cash=[999799.8]*2, nav=[999999.8]*2,
                                   certified_nav=[999999.8]*2, actual_name_count=[1]*2,
                                   unknown_count=[0]*2, stale_count=[0]*2,
                                   net_return=[np.nan, 0.], transaction_cost_amount=[.2, 0.],
                                   cash_weight=[999799.8/999999.8]*2)),
        "trades": pd.DataFrame([dict(signal_date=signal, execution_date=dates[0], ticker="A",
                                     side="BUY", notional=200., index_units=2., price=100.,
                                     transaction_cost=.2, order_id="test|A", decision_semantic="MODEL_TARGET_WEIGHT")]),
        "positions": pd.DataFrame([dict(date=d, ticker="A", index_units=2., market_value=200.) for d in dates]),
        "target_decisions": pd.DataFrame([dict(signal_date=signal, execution_date=dates[0],
                                               raw_model_weight=.0002, order_id="test|A", signal_day_adv=100000.)]),
        "signal_contexts": pd.DataFrame([dict(signal_date=signal, active_target_weight=.0002,
                                              final_available_weight=.95, active_target_count=1, final_available_slots=20)])}
    result = audit_ledger(synthetic, 2025, 10, "full_available")
    need(result["status"] == "PASS" and result["trades"] == 1, "SYNTHETIC_LEDGER_TEST_FAILURE")
    print("PASS: seven pure self-tests; no dataset, model, replay, or economic output read")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    self_test() if args.self_test else finalize()
