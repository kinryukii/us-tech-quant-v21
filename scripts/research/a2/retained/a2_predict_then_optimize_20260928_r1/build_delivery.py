"""Build the complete diagnostic delivery after frozen, full two-window replay.

This module does not read evaluation outcomes on import.  Only --run opens real
results, after validate_global_freeze and both 5,053-route completion gates.
--self-test uses synthetic temporary ledgers and never opens 2026 inputs/results.
All result signs, failures, numerical warnings and provenance are retained.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import tempfile
import time

from common import (ROOT, PROVIDERS, COALITIONS, FUSIONS, RISKS, OPTIMIZERS,
                    forecasts, strategies, sha, read, write, clean)
import numpy as np
import pandas as pd


YEARS = (2025, 2026)
CONTROLS = ("cash", "reinforce", "reinforce_zero", "ppo", "ppo_zero")
PILOT_IDS = {"single__ridge__diag__mv", "single__ridge__diag__robust",
             "single__ridge__none__equal_top20"}
LEDGERS = ("daily", "trades", "positions", "target_decisions", "diagnostics",
           "valuation_intervals", "raw_model_outputs", "signal_contexts",
           "operational_actions", "execution_results")
IDENTITY_COLUMNS = ("nav_identity_error", "cash_flow_identity_error",
                    "cost_identity_error", "open_self_finance_error")
META_COLUMNS = ("strategy_id", "forecast_id", "coalition", "fusion", "risk",
                "optimizer", "route", "target_fusion")
FAIL_COLUMNS = ("category", "year", "strategy_id", "stage", "member", "status",
                "reason", "source", "numeric_days", "gap_bound", "mapping", "resolved", "strategy_route_failure")


def _need(condition, reason):
    if not bool(condition):
        raise ValueError(reason)


def _csv(path):
    return pd.read_csv(path, low_memory=False)


def _parquet(path, columns=None):
    return pd.read_parquet(path, columns=columns, use_threads=False)


def _max_error(left, right):
    a, b = np.broadcast_arrays(np.asarray(left, float), np.asarray(right, float))
    _need(np.array_equal(np.isfinite(a), np.isfinite(b)), "FINITE_IDENTITY_MASK_MISMATCH")
    valid = np.isfinite(a) & np.isfinite(b)
    return float(np.abs(a[valid] - b[valid]).max()) if valid.any() else 0.


def _local(root, relative):
    path = (root / str(relative).replace("\\", "/")).resolve()
    _need(path.is_relative_to(root.resolve()), "DELIVERY_REFERENCE_OUTSIDE_EXPERIMENT")
    return path


def gate_inputs(root=ROOT):
    """No outcome is opened until the real frozen-artifact validator succeeds."""
    _need(root.resolve() == ROOT.resolve(), "REAL_DELIVERY_ROOT_MUST_BE_CURRENT_EXPERIMENT")
    from freeze_batch import validate_global_freeze
    freeze = validate_global_freeze()
    contract, lock = read(root / "contract.json"), read(root / "DESIGN_LOCK.json")
    _need(sha(root / "contract.json") == lock["contract_sha256"] == freeze["contract_sha256"], "DESIGN_CONTRACT_DRIFT")
    _need(contract["models"] == PROVIDERS and contract["coalitions"] == COALITIONS
          and contract["fusions"] == FUSIONS and contract["risks"] == RISKS
          and contract["optimizers"] == OPTIMIZERS, "FINITE_ROSTER_DRIFT")
    roster = pd.DataFrame(strategies())
    _need(len(forecasts()) == 152 and len(roster) == 5053 and not roster.strategy_id.duplicated().any(), "EXPECTED_152_FORECAST_5053_ROUTE_CONTRACT")
    tables, controls = {}, {}
    for year in YEARS:
        marker = read(root / f"evaluation_{year}/COMPLETE.json")
        _need(marker.get("expected") == 5053 and not marker.get("partial_diagnostic_run", False)
              and marker.get("completed", 0) + marker.get("failed", 0) == 5053,
              f"FULL_{year}_ROSTER_NOT_READY")
        table = _csv(root / f"evaluation_{year}/comparison.csv")
        _need(len(table) == 5053 and not table.strategy_id.duplicated().any()
              and set(table.strategy_id) == set(roster.strategy_id), f"{year}_MISSING_OR_EXTRA_STRATEGY")
        _need(table.status.isin(["REPLAY_COMPLETE", "FAILED"]).all(), f"{year}_UNFINISHED_STRATEGY")
        for col in [c for c in META_COLUMNS if c != "strategy_id"]:
            wanted = roster.set_index("strategy_id")[col].fillna("none").astype(str)
            actual = table.set_index("strategy_id")[col].fillna("none").astype(str)
            _need(actual.reindex(wanted.index).equals(wanted), f"{year}_FACTOR_CELL_DRIFT:{col}")
        table["year"] = year
        tables[year] = table
        control_marker = read(root / f"evaluation_controls_{year}/COMPLETE.json")
        control_table = _csv(root / f"evaluation_controls_{year}/COMPARISON.csv")
        _need(set(control_marker["controls"]) == set(CONTROLS) and len(control_table) == 5
              and set(control_table.strategy_id) == set(CONTROLS)
              and control_table.status.isin(["REPLAY_COMPLETE", "FAILED"]).all(), f"{year}_FIVE_CONTROLS_NOT_READY")
        control_table["year"] = year
        controls[year] = control_table
    analysis = _csv(root / "report/ALL_PTO_RESULTS.csv")
    _need(len(analysis) == 10106 and not analysis.duplicated(["year", "strategy_id"]).any(), "ANALYSIS_FULL_TWO_WINDOW_TABLE_REQUIRED")
    _need(set(zip(analysis.year, analysis.strategy_id)) == {(year, sid) for year in YEARS for sid in roster.strategy_id}, "ANALYSIS_ROSTER_MISMATCH")
    return freeze, contract, roster, tables, controls


def forecast_provenance(year, freeze, root=ROOT):
    directory = root / f"diagnostics/forecast_metrics/{year}"
    receipt = read(directory / "RECEIPT.json")
    _need(receipt["forecasts_reported"] == 152 and receipt["forecasts_expected"] == 152
          and receipt["no_parameter_fitting"] and receipt["no_model_selection"], "FORECAST_METRIC_SCOPE_DRIFT")
    if year == 2026:
        _need(receipt["global_freeze_sha256"] == sha(root / "GLOBAL_FREEZE.json"), "2026_METRIC_FREEZE_MISMATCH")
    for relative, digest in {**receipt["prediction_sha256"], **receipt["output_sha256"], **receipt["label_source_sha256"]}.items():
        _need(sha(_local(root, relative)) == digest, f"METRIC_ARTIFACT_HASH_MISMATCH:{relative}")
    from pyarrow.parquet import read_schema
    feature_path = root / f"input/eval_{year}/features.parquet"
    has_buy_gate = "new_buy_eligible" in read_schema(feature_path).names
    _need(year != 2026 or has_buy_gate, "2026_NEW_BUY_ELIGIBILITY_FIELD_REQUIRED")
    features = _parquet(feature_path, ["signal_date", "ticker"] + (["new_buy_eligible"] if has_buy_gate else []))
    keys = set(zip(features.signal_date.dt.strftime("%Y-%m-%d"), features.ticker.astype(str)))
    _need(len(keys) == len(features), "DUPLICATE_FROZEN_POOL_KEYS")
    eligible = features.new_buy_eligible.eq(True) if has_buy_gate else pd.Series(True, index=features.index)
    eligible_keys = set(zip(features.loc[eligible, "signal_date"].dt.strftime("%Y-%m-%d"), features.loc[eligible, "ticker"].astype(str)))
    forecast_status = {}
    for spec in forecasts():
        relative = f'predictions/forecasts/{year}/{spec["forecast_id"]}.parquet'
        path = root / relative
        if not path.exists():
            forecast_status[spec["forecast_id"]] = "MISSING_FORECAST"
            continue
        digest = sha(path)
        if year == 2025:
            _need(freeze["artifact_sha256"].get(relative) == digest, "2025_FORECAST_NOT_BOUND_BY_LATER_GLOBAL_FREEZE:" + relative)
        _need(receipt["prediction_sha256"].get(relative, receipt["prediction_sha256"].get(relative.replace("/", "\\"))) == digest,
              "FORECAST_NOT_BOUND_BY_METRIC_RECEIPT:" + relative)
        frame = _parquet(path, ["signal_date", "ticker", "prediction_id", "mu"])
        actual = set(zip(frame.signal_date.dt.strftime("%Y-%m-%d"), frame.ticker.astype(str)))
        expected_ids = [spec["forecast_id"] + "|" + d + "|" + t for d, t in zip(frame.signal_date.dt.strftime("%Y-%m-%d"), frame.ticker.astype(str))]
        good = len(frame) == len(keys) and actual == keys and not frame.duplicated(["signal_date", "ticker"]).any()
        good = good and np.isfinite(frame.mu).all() and frame.prediction_id.astype(str).to_list() == expected_ids
        forecast_status[spec["forecast_id"]] = "PASS" if good else "FORECAST_KEY_OR_VALUE_FAILURE"
    metrics = _csv(directory / "FORECAST_METRICS.csv")
    _need(len(metrics) == 152 and not metrics.forecast_id.duplicated().any(), "FORECAST_METRIC_ROSTER_INCOMPLETE")
    probabilities = _csv(directory / "NATIVE_PROBABILITY_METRICS.csv")
    return dict(receipt=receipt, keys=keys, buy_eligible_keys=eligible_keys, buy_blocked_keys=keys - eligible_keys,
                buy_gate_source="explicit frozen new_buy_eligible" if has_buy_gate else "2025 engine initialization defaults every provided key to True",
                forecast_status=forecast_status,
                metrics=metrics, probabilities=probabilities)


def audit_account(folder, done, *, year, spec, freeze_sha, calendar, pool_keys,
                  buy_eligible_keys, forecast_status, control=False):
    """Independent ledger algebra, quantities, clocks, costs and order links."""
    hashes = done.get("ledger_sha256", {})
    required = {name + ".parquet" for name in LEDGERS}
    if not control:
        required |= {"optimization_diagnostics.parquet", "prediction_order_links.parquet"}
    _need(required <= set(hashes), "REQUIRED_LEDGER_HASHES_MISSING")
    _need(set(hashes) == {p.name for p in folder.glob("*.parquet")}, "UNDECLARED_OR_MISSING_LEDGER")
    for relative, digest in hashes.items():
        _need(sha(_local(folder, relative)) == digest, "LEDGER_SHA256_MISMATCH:" + relative)
    if control:
        provenance = read(folder / "FROZEN_BEFORE_REPLAY.json")
        values = [value for key, value in provenance["source_sha256"].items() if Path(key).name == "GLOBAL_FREEZE.json"]
        binding = values[0] if values else None
    else:
        binding = done.get("model_batch_freeze_sha256")
    if year == 2026:
        _need(binding == freeze_sha, "2026_REPLAY_NOT_BOUND_TO_EXACT_GLOBAL_FREEZE")
        freeze_state = "GLOBAL_FREEZE_MATCH"
    else:
        _need(binding in [None, freeze_sha], "2025_REPLAY_BOUND_TO_DIFFERENT_GLOBAL_BATCH")
        freeze_state = "PRE_GLOBAL_2025_DESIGN_LOCKED_ARTIFACTS_MATCH_LATER_FREEZE" if binding is None else "2025_GLOBAL_FREEZE_MATCH"
    d, t, pos, target, execution = [_parquet(folder / (name + ".parquet")) for name in
                                  ["daily", "trades", "positions", "target_decisions", "execution_results"]]
    _need(d.date.is_unique and d.date.is_monotonic_increasing and len(d) == len(calendar), "DAILY_CALENDAR_INCOMPLETE")
    _need(list(pd.to_datetime(d.date)) == list(calendar), "DAILY_CALENDAR_MISMATCH")
    _need(np.isfinite(d.cash).all() and d.cash.min() >= -1e-6 and d.actual_name_count.max() <= 20, "ACTUAL_ACCOUNT_CONSTRAINT")
    _need(not target.order_id.duplicated().any(), "DUPLICATE_ORDER_ID")
    order_ids = set(target.order_id)
    _need(set(t.order_id) <= order_ids and set(execution.order_id) <= order_ids, "BROKEN_ORDER_EXECUTION_LINK")
    next_dates = dict(zip(calendar[:-1], calendar[1:]))
    if len(t):
        _need(t.execution_date.is_monotonic_increasing and t.side.isin(["BUY", "SELL"]).all(), "TRADE_ORDER_OR_SIDE_INVALID")
        _need((t.execution_date == t.signal_date.map(next_dates)).all(), "TRADE_NOT_NEXT_SESSION_OPEN_CLOCK")
        _need((t.cost_bps == 10).all(), "REALIZED_COST_RULE_DRIFT")
    fee_error = _max_error(t.transaction_cost, t.notional * .001)
    notional_error = _max_error(t.notional, t.index_units * t.price)
    _need(fee_error <= 1e-7 and notional_error <= 1e-6, "TRADE_FEE_OR_NOTIONAL_IDENTITY")
    buy = t.side.eq("BUY")
    _need(buy_eligible_keys <= pool_keys, "BUY_ELIGIBILITY_KEYS_OUTSIDE_INPUT")
    actual_buy_keys = list(zip(pd.to_datetime(t.loc[buy, "signal_date"]).dt.strftime("%Y-%m-%d"), t.loc[buy, "ticker"].astype(str)))
    ineligible_buy_rows = sum(key not in buy_eligible_keys for key in actual_buy_keys)
    blocked_context_buy_rows = sum(key in pool_keys and key not in buy_eligible_keys for key in actual_buy_keys)
    _need(ineligible_buy_rows == 0, "ACTUAL_BUY_OUTSIDE_SIGNAL_NEW_BUY_ELIGIBILITY")
    if buy.any():
        _need((t.loc[buy, "notional"] <= .01 * t.loc[buy, "capacity_adv"] + 1e-5).all()
              and (t.loc[buy, "capacity_adv_source_date"] <= t.loc[buy, "signal_date"]).all(), "BUY_CAPACITY_OR_ASOF_FAILED")
    delta = t.index_units.to_numpy(float) * np.where(buy, 1., -1.)
    independent_units = pd.Series(delta, index=t.index).groupby(t.ticker, sort=False).cumsum()
    units_error = max(_max_error(independent_units, t.index_units_after),
                      _max_error(independent_units - delta, t.index_units_before))
    _need(units_error <= 1e-6 and (independent_units >= -1e-6).all(), "TRADE_UNITS_RECURSION_FAILED")
    totals = t.assign(buy_notional=np.where(buy, t.notional, 0.), sell_notional=np.where(buy, 0., t.notional),
                      cash_delta=-delta * t.price.to_numpy(float) - t.transaction_cost.to_numpy(float))
    totals = totals.groupby("execution_date", sort=True)[["buy_notional", "sell_notional", "transaction_cost", "cash_delta"]].sum().reindex(d.date, fill_value=0.)
    cash = 1_000_000. + totals.cash_delta.cumsum().to_numpy(float)
    cash_error = _max_error(cash, d.cash)
    daily_fee_error = _max_error(totals.transaction_cost, d.transaction_cost_amount)
    daily_flow_error = max(_max_error(totals.buy_notional, d.buy_notional), _max_error(totals.sell_notional, d.sell_notional))
    _need(max(cash_error, daily_fee_error, daily_flow_error) <= 1e-5, "INDEPENDENT_CASH_OR_DAILY_TOTAL_FAILED")
    active_delta = (t.index_units_after.gt(1e-10).astype(int) - t.index_units_before.gt(1e-10).astype(int))
    active_names = active_delta.groupby(t.execution_date).sum().reindex(d.date, fill_value=0).cumsum()
    _need(np.array_equal(active_names.to_numpy(), d.actual_name_count.to_numpy()), "INDEPENDENT_NAME_COUNT_FAILED")
    position_units_error = 0.
    if len(pos):
        _need(not pos.duplicated(["date", "ticker"]).any(), "DUPLICATE_POSITION")
        history = t.assign(independent_units=independent_units)[["execution_date", "ticker", "independent_units"]].rename(columns={"execution_date": "date"})
        history = history.drop_duplicates(["date", "ticker"], keep="last")
        left, right = pos[["date", "ticker", "index_units"]].copy(), history.copy()
        left["date"], right["date"] = pd.to_datetime(left.date).astype("datetime64[ns]"), pd.to_datetime(right.date).astype("datetime64[ns]")
        reconciled = pd.merge_asof(left.sort_values("date"), right.sort_values("date"), on="date", by="ticker", direction="backward")
        position_units_error = _max_error(reconciled.index_units, reconciled.independent_units)
        _need(position_units_error <= 1e-6, "POSITION_UNITS_NOT_INDEPENDENT_TRADE_HISTORY")
        _need(np.array_equal(pos.groupby("date").size().reindex(d.date, fill_value=0).to_numpy(), d.actual_name_count.to_numpy()), "POSITION_NAME_COUNT_FAILED")
    else:
        _need(d.actual_name_count.eq(0).all(), "MISSING_ALL_POSITIONS")
    position_value_error = _max_error(pos.market_value, pos.index_units * pos.mark)
    known = pos.groupby("date").market_value.sum().reindex(d.date, fill_value=0.)
    nav_mask = np.isfinite(d.nav.to_numpy(float))
    nav_error = _max_error((cash + known.to_numpy())[nav_mask], d.nav.to_numpy(float)[nav_mask])
    _need(position_value_error <= 1e-5 and nav_error <= 1e-5, "INDEPENDENT_POSITION_VALUE_NAV_FAILED")
    identity_errors = {column: float(d[column].abs().max()) for column in IDENTITY_COLUMNS}
    _need(all(value <= 1e-5 for value in identity_errors.values()), "ENGINE_IDENTITY_FIELD_FAILED")
    if len(target):
        raw = target.raw_model_weight.dropna()
        _need(raw.between(0., .10000001).all(), "RAW_TARGET_CAP_FAILED")
        allowed = np.maximum(0., .95 - target.reserved_weight.fillna(0.).to_numpy(float))
        _need((target.active_target_sum.fillna(0.).to_numpy(float) <= allowed + 1e-8).all(), "TARGET_ACTIVE_BUDGET_FAILED")
        context_units = pos[["date", "ticker", "index_units"]].rename(columns={"date": "signal_date", "index_units": "observed_signal_units"})
        joined = target[["signal_date", "ticker", "current_units"]].merge(context_units, on=["signal_date", "ticker"], how="left", validate="many_to_one")
        _need(_max_error(joined.current_units.fillna(0.), joined.observed_signal_units.fillna(0.)) <= 1e-6, "TARGET_NOT_OWN_CURRENT_HOLDINGS")
    prediction_links = 0
    risk_audit = dict(risk_metadata_path_days=0, risk_unknown_path_days=0, risk_unknown_support_occurrences=0,
        scenario_metadata_path_days=0, scenario_unknown_path_days=0, scenario_unknown_support_occurrences=0,
        scenario_rank_deficient_path_days=0, scenario_correlation_max_error=None, scenario_mean_matching_max_error=None)
    if not control:
        links = _parquet(folder / "prediction_order_links.parquet")
        _need(not links.order_id.duplicated().any() and set(links.order_id) == order_ids, "PREDICTION_ORDER_LINK_SET_FAILED")
        joined = links.merge(target[["order_id", "adapted_target_weight"]], on="order_id", suffixes=("_link", "_target"), validate="one_to_one")
        _need(_max_error(joined.adapted_target_weight_link, joined.adapted_target_weight_target) <= 1e-10, "PREDICTION_LINK_TARGET_WEIGHT_FAILED")
        fids = [spec["forecast_id"]] if spec["route"] == "prediction_fusion" else ["single__" + m for m in spec["members"]]
        _need(all(forecast_status.get(fid) == "PASS" for fid in fids), "LINKED_FORECAST_NOT_COMPLETE")
        for row in links.itertuples():
            _need(json.loads(row.forecast_ids_json) == fids, "LINKED_FORECAST_IDS_DRIFT")
            if row.model_input_row_present:
                key = (str(row.signal_date.date()), str(row.ticker))
                suffix = key[0] + "|" + key[1]
                _need(key in pool_keys and row.prediction_key_suffix == suffix, "PREDICTION_KEY_NOT_FROZEN_POOL")
                if len(fids) == 1:
                    _need(row.prediction_id == fids[0] + "|" + suffix, "EXACT_PREDICTION_ID_MISMATCH")
                prediction_links += len(fids)
            else:
                _need(pd.isna(row.prediction_key_suffix), "ABSENT_MODEL_INPUT_GOT_FAKE_PREDICTION")
        member_path = folder / "member_targets.parquet"
        if member_path.exists():
            members = _parquet(member_path)
            expected_ids = ["single__" + str(m) + "|" + str(date.date()) + "|" + str(ticker)
                            for m, date, ticker in zip(members.member, members.signal_date, members.ticker)]
            _need(members.prediction_id.to_list() == expected_ids, "MEMBER_PREDICTION_TARGET_LINK_FAILED")
            _need(_max_error(members.weighted_target, members.member_target * members.blend_weight) <= 1e-10, "MEMBER_TARGET_BLEND_ARITHMETIC_FAILED")
        diag = _parquet(folder / "optimization_diagnostics.parquet")
        if "risk_coverage_json" in diag:
            for text in diag.risk_coverage_json.dropna():
                meta = json.loads(text)
                unknown = len(meta.get("unknown_tickers", []))
                risk_audit["risk_metadata_path_days"] += 1
                risk_audit["risk_unknown_path_days"] += int(unknown > 0)
                risk_audit["risk_unknown_support_occurrences"] += unknown
                scenario = meta.get("scenarios")
                if scenario:
                    _need(scenario["scenario_count"] == 64 and scenario["independent_scenarios"] is False, "SCENARIO_SHARED_CALENDAR_CONTRACT_DRIFT")
                    risk_audit["scenario_metadata_path_days"] += 1
                    risk_audit["scenario_unknown_path_days"] += int(bool(scenario.get("unknown_tickers")))
                    risk_audit["scenario_unknown_support_occurrences"] += len(scenario.get("unknown_tickers", []))
                    risk_audit["scenario_rank_deficient_path_days"] += int(scenario.get("rank_deficient", False))
                    for key, source_key in [("scenario_correlation_max_error", "pre_subsample_correlation_max_error"),
                                            ("scenario_mean_matching_max_error", "mean_matching_error")]:
                        value = scenario.get(source_key)
                        if value is not None:
                            previous = risk_audit[key]
                            risk_audit[key] = float(value) if previous is None else max(previous, float(value))
        risk_audit["risk_metadata_scope"] = "prediction_route_selected_plus_reserved_support" if spec["route"] == "prediction_fusion" else "target_blend_member_risk_detail_not_persisted; member residuals and frozen recipes retained"
        if "iterations" in diag:
            nonempty = diag.iterations.gt(0)
            _need(diag.loc[nonempty, "iterations"].eq(80).all(), "OPTIMIZER_FIXED_80_BUDGET_DRIFT")
            if {"status", "optimality_gap_bound", "gradient_mapping_inf"} <= set(diag):
                usable = diag.optimality_gap_bound.notna() & diag.gradient_mapping_inf.notna()
                expected_status = np.where((diag.loc[usable, "optimality_gap_bound"] <= 1e-6)
                                           & (diag.loc[usable, "gradient_mapping_inf"] <= 1e-5),
                                           "approx_converged", "approx_unconverged")
                _need(list(expected_status) == diag.loc[usable, "status"].to_list(), "CONVERGENCE_STATUS_SUPPRESSED_OR_CHANGED")
            if {"feasible", "constraint_violation"} <= set(diag):
                usable = diag.constraint_violation.notna()
                _need(list(diag.loc[usable, "constraint_violation"].le(1e-8)) == diag.loc[usable, "feasible"].to_list(), "FEASIBILITY_STATUS_SUPPRESSED_OR_CHANGED")
    _need(int(done.get("guard_fit_attempts", done.get("fit_attempts_during_replay", 0))) == 0, "REPLAY_ATTEMPTED_FIT")
    for key, value in {"total_fees": float(t.transaction_cost.sum()), "terminal_nav": float(d.nav.iloc[-1]),
                       "mean_gross_exposure": float(d.gross_exposure.mean()), "trades": len(t)}.items():
        if done.get(key) is not None:
            _need(_max_error(value, done[key]) <= 1e-5, "DONE_SUMMARY_NOT_LEDGER:" + key)
    return dict(status="PASS", ledger_files=len(hashes), prediction_links_verified=prediction_links,
                cash_recursive_max_error=cash_error, units_recursive_max_error=units_error,
                position_units_max_error=position_units_error, nav_recursive_max_error=nav_error,
                fee_max_error=fee_error, daily_fee_max_error=daily_fee_error, notional_max_error=notional_error,
                engine_identity_max_error=max(identity_errors.values()), freeze_provenance=freeze_state,
                buy_eligibility_status="PASS", actual_buy_rows_checked=len(actual_buy_keys),
                ineligible_actual_buy_rows=ineligible_buy_rows, buy_blocked_context_buy_rows=blocked_context_buy_rows,
                buy_blocked_input_keys=len(pool_keys) - len(buy_eligible_keys),
                early_test_vs_full_run="early_pilot_same_ledger_exact_verified" if year == 2025 and spec["strategy_id"] in PILOT_IDS else "full_prespecified_run",
                source_done_sha256=sha(folder / "DONE.json"), certified_price_index_days=int(d.certified_nav.notna().sum()),
                uncertified_price_index_days=int(d.certified_nav.isna().sum()),
                unknown_valuation_days=int(d.unknown_count.gt(0).sum()), stale_valuation_days=int(d.stale_count.gt(0).sum()), **risk_audit)


def collect_training(root=ROOT):
    counts, issues = {}, []
    native = []
    for stage, cutoff in [("early", "2024-01-01"), ("validation", "2025-01-01"), ("final", "2026-01-01")]:
        for provider in PROVIDERS:
            source = root / "models" / stage / (provider + "_FIT_RECEIPT.json")
            row = read(source)
            _need(row["status"] == "PASS" and row["train_label_end_max"] < cutoff and row["no_2026_training"], "NATIVE_TRAIN_TIME_OR_STATUS_FAILURE")
            native.append(row)
            for warning in row.get("fit_details", {}).get("warnings", []):
                issues.append(dict(category="TRAIN_WARNING", stage=stage, member=provider, status="WARNING_FIXED_BUDGET_PRESERVED",
                                   reason=json.dumps(warning, ensure_ascii=False), source=str(source.relative_to(root))))
            if row.get("initial_restore_failure_preserved"):
                issues.append(dict(category="INITIAL_RESTORE_FAILURE", stage=stage, member=provider,
                    status="RESTORED_WITHOUT_RETRAINING", reason="initial numerical restoration failure preserved; saved native forest deterministic inference audit passed",
                    source=str(Path(row["initial_restore_failure_preserved"]).relative_to(root))))
    counts["native"] = dict(bundles=len(native), predictive_fit_calls=sum(x["predictive_fit_calls"] for x in native),
        statistical_target_heads=sum(x["statistical_target_heads"] for x in native),
        scaler_fit_calls=sum(x.get("scaler_fit_calls", 0) for x in native), adapter_fit_calls=sum(x.get("adapter_fit_calls", 0) for x in native),
        probability_amplitude_statistic_sets=sum(x["native_kind"] == "probability" for x in native),
        quantile_mean_offset_estimates=sum(x["native_kind"] == "quantile" for x in native),
        huber_mean_offset_estimates=sum(x["model_id"] == "huber" for x in native),
        point_rank_residual_scale_estimates=sum(x["native_kind"] in ["point", "rank"] for x in native))
    fusion_rows = []
    for stage, cutoff in [("validation", "2025-01-01"), ("final", "2026-01-01")]:
        for group in COALITIONS:
            for method in FUSIONS:
                source = root / "fusion_artifacts" / stage / (group + "__" + method + ".json")
                row = read(source)
                _need(row["label_end_max"] < cutoff and row["stage"] == stage, "FUSION_TRAIN_TIME_FAILURE")
                fusion_rows.append(row)
                for warning in row.get("warnings", []):
                    issues.append(dict(category="FUSION_WARNING", stage=stage, member=group + "__" + method,
                                       status="WARNING_FIXED_BUDGET_PRESERVED", reason=str(warning), source=str(source.relative_to(root))))
    counts["fusion"] = dict(objects=len(fusion_rows), learned_mean_objects=sum(x["fitted"] for x in fusion_rows),
        regression_estimator_fit_calls=sum(x["method"].startswith(("stack_", "residual_")) for x in fusion_rows),
        convex_weight_optimization_objects=sum(x["method"] == "convex" for x in fusion_rows),
        gate_training_objects=sum(x["method"].startswith("gate_") for x in fusion_rows),
        gate_parameter_update_steps=80 * sum(x["method"].startswith("gate_") for x in fusion_rows),
        scaler_fit_calls=sum(x["method"].startswith(("stack_", "residual_", "gate_")) for x in fusion_rows),
        residual_scale_estimates=len(fusion_rows), equal_median_mean_estimator_fit_calls=0)
    risk_rows = []
    for stage in ["validation", "final"]:
        source = root / "risk_artifacts" / stage / "TRAIN_RECEIPT.json"
        row = read(source)
        _need(row["status"] == "PASS" and row["fit_2026_rows"] == 0, "RISK_FIT_TIME_FAILURE")
        risk_rows.append(row)
        for fit in row.get("supervised_fits", []):
            for warning in fit.get("warnings", []):
                issues.append(dict(category="RISK_TRAIN_WARNING", stage=stage, member=fit["name"], status="WARNING_FIXED_BUDGET_PRESERVED",
                                   reason=json.dumps(warning, ensure_ascii=False), source=str(source.relative_to(root))))
    keys = set().union(*(r["fit_operation_counts"] for r in risk_rows))
    counts["risk"] = dict(stages=2, risk_recipes_per_stage=10,
        actual_operations={key: sum(row["fit_operation_counts"].get(key, 0) for row in risk_rows) for key in sorted(keys)})
    rl_rows = []
    for stage in ["validation", "final"]:
        for method in ["reinforce", "ppo"]:
            source = root / "rl_artifacts" / (stage + "_" + method) / "TRAIN_RECEIPT.json"
            row = read(source)
            _need(row["fit_2026_rows"] == 0 and row["zero_parameter_updates"] == 0 and row["matched_initial_state_immutable"], "PAIRED_RL_TIME_OR_ZERO_FAILURE")
            prefit = read(source.with_name("PRE_FIT.json"))
            _need(prefit["normalization_keys"] == 30000 and prefit["fit_2026_rows"] == 0, "RL_NORMALIZATION_TIME_OR_KEY_BUDGET_DRIFT")
            rl_rows.append(row)
            for epoch in row["epoch_receipts"]:
                if epoch["invalid_reward_steps"]:
                    issues.append(dict(category="RL_ACCOUNT_STATE_LIMITATION", stage=stage, member=method,
                        status="INVALID_REWARD_SKIPPED_FIXED_BUDGET", numeric_days=epoch["invalid_reward_steps"],
                        reason="epoch " + str(epoch["epoch"]) + ": uncertified reward states skipped; prior actor/account transitions retained",
                        source=str(source.relative_to(root))))
    counts["rl"] = dict(trained_actor_objects=len(rl_rows), matched_zero_actor_objects=len(rl_rows),
        parameter_update_steps=sum(row["parameter_update_steps"] for row in rl_rows), zero_parameter_update_steps=0,
        feature_normalization_estimates=len(rl_rows),
        invalid_reward_steps=sum(ep["invalid_reward_steps"] for row in rl_rows for ep in row["epoch_receipts"]),
        zero_controls_independent_seeds=False)
    counts["warnings_and_preserved_initial_failures"] = len(issues)
    return counts, issues


def verify_control_document_bindings(controls, freeze, root=ROOT):
    """Report document provenance separately from direct global artifact binding."""
    digest = sha(root / "INPUT_AUDIT.json")
    bindings = []
    for year in YEARS:
        for row in controls[year].to_dict("records"):
            if row["status"] != "REPLAY_COMPLETE":
                continue
            source = root / f"evaluation_controls_{year}" / row["strategy_id"] / "FROZEN_BEFORE_REPLAY.json"
            record = read(source)
            values = [value for key, value in record["source_sha256"].items() if Path(key).name == "INPUT_AUDIT.json"]
            _need(len(values) == 1 and values[0] == digest, "CONTROL_INPUT_AUDIT_DOCUMENT_SHA_MISMATCH:" + str(source.relative_to(root)))
            bindings.append(dict(year=year, strategy_id=row["strategy_id"], source_sha256=sha(source)))
    return dict(document="INPUT_AUDIT.json", current_sha256=digest,
        directly_bound_by_global=freeze["artifact_sha256"].get("INPUT_AUDIT.json") == digest,
        successful_control_source_matches=len(bindings), control_bindings=bindings,
        scope="current document hash checked against preserved control provenance; not promoted to direct global artifact")


def verify_held_only_counts(input_audit, root=ROOT):
    source = root / "diagnostics/HELD_ONLY_INPUT_KEY_RECONCILIATION.json"
    record = read(source)
    original = int(record["original_candidate_gate_rows"])
    current = int(record["input_current_pool_qualified_new_buy_rows"])
    held = int(record["input_held_only_rows"])
    replay = int(record["replay_input_rows"])
    audit = input_audit["evaluation_2026"]
    _need(original == int(audit["original_candidate_rows"]) and replay == int(audit["candidate_rows"]), "HELD_ONLY_INPUT_AUDIT_COUNT_MISMATCH")
    _need(sum(record["gate_category_counts"].values()) == original and current + held == replay
          and current + int(audit["unknown_candidate_rows"]) + int(audit["proven_ineligible_rows"]) == original,
          "HELD_ONLY_ORIGINAL_INPUT_COUNT_IDENTITIES_FAILED")
    for col in ["held_only_keys_in_gate", "held_only_unknown_overlap", "held_only_proven_ineligible_overlap", "held_only_qualified_overlap"]:
        _need(record[col] == 0, "HELD_ONLY_GATE_CATEGORY_OVERLAP:" + col)
    tickers = record["held_only_by_ticker"]
    _need(sum(row["rows"] for row in tickers) == held
          and all(row["new_buy_eligible"] is False and row["all_keys_outside_original_candidate_gate"] is True for row in tickers),
          "HELD_ONLY_MUST_BE_OUTSIDE_GATE_AND_INELIGIBLE_FOR_NEW_BUY")
    return dict(record, source_sha256=sha(source), independently_rechecked_count_identities=True)


def held_only_count_explanation(record, input_audit):
    original, current, held = [int(record[col]) for col in ["original_candidate_gate_rows", "input_current_pool_qualified_new_buy_rows", "input_held_only_rows"]]
    unknown = int(input_audit["evaluation_2026"]["unknown_candidate_rows"])
    ineligible = int(input_audit["evaluation_2026"]["proven_ineligible_rows"])
    ticker_rows = "、".join(str(row["ticker"]) + " " + str(row["rows"]) for row in record["held_only_by_ticker"])
    return (f"已核验计数关系：原 gate {original:,} = {current:,} 合格当期候选 + {unknown:,} UNKNOWN + {ineligible:,} 已证不合格；"
            f"输入 {record['replay_input_rows']:,} = {current:,} 当期候选 + {held:,} held-only 额外上下文。"
            f"{held:,} 行（{ticker_rows}）全部在原 gate 之外，new_buy_eligible 全 False，不属于上述 gate 资格分类，也不属于 UNKNOWN。"
            f"{original + held:,} 是 gate∪input 混合键总数，不能写成原候选池总数。通用 forecast TOP20 可以包含这些原池之外的上下文，进一步限制其标签收益诊断的解释。"
            "键级核对见 [held-only 对账收据](../diagnostics/HELD_ONLY_INPUT_KEY_RECONCILIATION.json)。\n")


def report_statistics_history(root=ROOT):
    directory = root / "diagnostics/statistics_2025_preflight"
    failed_path = directory / "PREFLIGHT_RECEIPT_FAILED_LEFT_RIGHT_ARGUMENTS.json"
    passed_path = directory / "PREFLIGHT_RECEIPT.json"
    failed, passed = read(failed_path), read(passed_path)
    _need(failed["status"] == "FAIL_2025_REAL_STATISTICAL_INTEGRATION"
          and passed["status"] == "PASS_2025_REAL_STATISTICAL_INTEGRATION", "STATISTICS_PREFLIGHT_HISTORY_STATUS_MISMATCH")
    for receipt in [failed, passed]:
        _need(receipt["fit_calls"] == 0 and not receipt["frozen_artifacts_modified"]
              and receipt["unfinished_2026_account_reads"] == 0, "STATISTICS_PREFLIGHT_LEARNING_OR_SCOPE_DRIFT")
        _need(receipt["global_freeze_sha256"] == sha(root / "GLOBAL_FREEZE.json"), "STATISTICS_PREFLIGHT_GLOBAL_FREEZE_MISMATCH")
    prior = passed["prior_failed_preflight"]
    _need(_local(root, prior["path"]) == failed_path.resolve() and prior["sha256"] == sha(failed_path),
          "STATISTICS_PREFLIGHT_FAILURE_RECEIPT_SHA_MISMATCH")
    for relative, digest in passed["source_sha256"].items():
        _need(sha(_local(root, relative)) == digest, "STATISTICS_PREFLIGHT_SOURCE_CHANGED:" + relative)
    budget = passed["optimization_vs_budget_control"]
    forecast_count = len(forecasts())
    _need(budget["prediction_route_rows"] == forecast_count * len(RISKS) * len(OPTIMIZERS)
          and budget["target_route_rows"] == len(COALITIONS) * len(RISKS) * len(OPTIMIZERS)
          and budget["rows"] == budget["prediction_route_rows"] + budget["target_route_rows"]
          and budget["distinct_budget_controls"] == forecast_count + len(COALITIONS),
          "STATISTICS_OPTIMIZATION_BUDGET_PAIR_COUNT_MISMATCH")
    _need(set(passed["factor_decompositions"]) == {"net_return", "max_drawdown", "mean_gross_exposure", "mean_daily_log_return"}
          and all(row["rows"] == forecast_count * len(RISKS) * len(OPTIMIZERS) for row in passed["factor_decompositions"].values()),
          "STATISTICS_PREFLIGHT_FACTOR_COVERAGE_MISMATCH")
    issue = dict(category="REPORT_STATISTICS_INITIAL_INTEGRATION_FAILURE", year=2025,
        status="RESOLVED_NONFROZEN_REPORT_LAYER", reason=failed["error"] + "; " + prior["statistics_fix"],
        source=str(failed_path.relative_to(root)), resolved=True, strategy_route_failure=False)
    summary = dict(failed_receipt_sha256=sha(failed_path), passed_receipt_sha256=sha(passed_path), resolved=True,
        strategy_route_failure=False, source_sha256=passed["source_sha256"],
        current_statistics_test_sha256=sha(root / "test_comparison_analysis.py"),
        fit_calls=0, frozen_learning_execution_modified=False,
        daily_returns=passed["daily_returns"], matched_comparisons=passed["matched_comparisons"],
        conditional_fusion_comparisons=passed["conditional_fusion_comparisons"],
        factor_decompositions=passed["factor_decompositions"], optimization_vs_budget_control=budget)
    return summary, [issue]


def helper_orchestration_provenance(freeze, root=ROOT):
    """Terminal orchestration metadata, read only after both full-grid gates."""
    directory = root / "diagnostics"
    prefix = "TARGET_ALL_OUTPUTS_HELPER_2026"
    receipt_path = directory / (prefix + "_RECEIPT.json")
    _need(receipt_path.exists(), "PARALLEL_HELPER_TERMINAL_RECEIPT_NOT_READY")
    receipt = read(receipt_path)
    _need(receipt["status"] == "FINISHED_ORIGINAL_PUBLIC_CHUNK", "PARALLEL_HELPER_NOT_TERMINALLY_FINISHED")
    specs = [spec for spec in strategies() if spec["route"] == "target_fusion" and spec["coalition"] == "all_outputs"]
    ids = {spec["strategy_id"] for spec in specs}
    _need(len(ids) == 31 and len(receipt["strategy_ids"]) == 31 and set(receipt["strategy_ids"]) == ids
          and receipt["expected"] == 31 and receipt["year"] == 2026
          and receipt["route"] == "target_fusion" and receipt["coalition"] == "all_outputs",
          "PARALLEL_HELPER_NOT_EXACT_ORIGINAL_31_SPECS")
    caller = _local(root, receipt["helper_source"])
    _need(sha(caller) == receipt["helper_source_sha256"], "PARALLEL_HELPER_CALLER_SOURCE_SHA_CHANGED")
    _need(str(caller.relative_to(root)).replace("\\", "/") not in freeze["artifact_sha256"],
          "PARALLEL_HELPER_DIRECT_GLOBAL_MEMBERSHIP_UNEXPECTED")
    _need(receipt["global_freeze_sha256"] == sha(root / "GLOBAL_FREEZE.json")
          and receipt["original_frozen_sha256"] == freeze["artifact_sha256"]
          and receipt["all_frozen_sha256_unchanged"], "PARALLEL_HELPER_FROZEN_CORE_CHANGED")
    expected_guards = {"native", "pipeline", "scaler", "adam", "sgd", "hgbvol", "mlpvol"}
    _need(not receipt["global_comparison_or_complete_writes"] and not receipt["fitting_allowed"]
          and receipt["guard_fit_attempts"] == 0 and receipt["resume"] is True
          and set(receipt["installed_fit_guards"]) == expected_guards and all(receipt["installed_fit_guards"].values()),
          "PARALLEL_HELPER_FIT_OR_GLOBAL_SUMMARY_SCOPE_DRIFT")
    _need(receipt["completed"] + receipt["failed"] == 31
          and set(receipt["output_receipts"]) == ids and receipt["all_completed_leaf_ledgers_hash_verified"],
          "PARALLEL_HELPER_TERMINAL_LEAF_COVERAGE_MISMATCH")
    _need(receipt["all_forecast_sha256_unchanged"], "PARALLEL_HELPER_FORECAST_CHANGED")
    expected_forecasts = {"predictions/forecasts/2026/single__" + member + ".parquet" for member in specs[0]["members"]}
    _need({str(key).replace("\\", "/") for key in receipt["forecast_sha256"]} == expected_forecasts,
          "PARALLEL_HELPER_SINGLE_FORECAST_SOURCE_ROSTER_MISMATCH")
    for relative, digest in receipt["forecast_sha256"].items():
        _need(sha(_local(root, relative)) == digest, "PARALLEL_HELPER_FORECAST_SHA_CHANGED:" + relative)
    failure_ids = {row["strategy_id"] for row in receipt.get("failures", [])}
    _need(failure_ids <= ids and len(failure_ids) == receipt["failed"], "PARALLEL_HELPER_FAILURE_LEAF_COUNT_MISMATCH")
    output_matches = {}
    for sid, digest in receipt["output_receipts"].items():
        folder = root / "evaluation_2026" / sid
        name = "FAILURE.json" if sid in failure_ids else "DONE.json"
        candidates = [folder / name] + list(folder.glob("attempts/*/" + name))
        matched = [path for path in candidates if path.exists() and sha(path) == digest]
        _need(bool(matched), "PARALLEL_HELPER_OUTPUT_RECEIPT_NOT_PRESERVED:" + sid)
        output_matches[sid] = str(matched[0].relative_to(root))
    progress_path = directory / (prefix + "_PROGRESS.json")
    progress = read(progress_path)
    _need(progress["status"] == receipt["status"] and set(progress["strategy_ids"]) == ids
          and progress["helper_source_sha256"] == receipt["helper_source_sha256"]
          and progress["completed"] == receipt["completed"] and progress["failed"] == receipt["failed"],
          "PARALLEL_HELPER_PROGRESS_NOT_TERMINAL_RECEIPT_STATE")
    artifacts = sorted(directory.glob(prefix + "*.json"))
    issues = []
    for source in artifacts:
        if "FAIL" in source.name.upper():
            record = read(source)
            issues.append(dict(category="PARALLEL_HELPER_ORCHESTRATION_FAILURE_HISTORY", year=2026,
                status=record.get("status", "PRESERVED_HELPER_FAILURE"), reason=record.get("reason", record.get("error", "see original helper failure record")),
                source=str(source.relative_to(root)), resolved=bool(record.get("resolved", receipt["completed"] == 31)), strategy_route_failure=False))
    for row in receipt.get("failures", []):
        issues.append(dict(category="PARALLEL_HELPER_ORIGINAL_ROUTE_FAILURE", year=2026, strategy_id=row["strategy_id"],
            status="FAILED_HELPER_LEAF_ATTEMPT_PRESERVED", reason=row.get("reason", "see preserved original leaf failure"),
            source=str(receipt_path.relative_to(root)), resolved=False, strategy_route_failure=True))
    for message in receipt.get("monitor_errors", []):
        issues.append(dict(category="PARALLEL_HELPER_MONITOR_WARNING", year=2026, status="PRESERVED_ORCHESTRATION_WARNING",
            reason=str(message), source=str(receipt_path.relative_to(root)), strategy_route_failure=False))
    summary = dict(caller=str(caller.relative_to(root)), caller_sha256=receipt["helper_source_sha256"], directly_bound_by_global=False,
        caller_binding="separate terminal receipt SHA; original core/global contract hashes unchanged",
        global_freeze_sha256=receipt["global_freeze_sha256"], frozen_core_files=len(freeze["artifact_sha256"]),
        status=receipt["status"], strategy_ids=receipt["strategy_ids"], expected_original_specs=31,
        completed=receipt["completed"], failed=receipt["failed"], fitting_allowed=False, guard_fit_attempts=0,
        installed_fit_guards=receipt["installed_fit_guards"], all_frozen_sha256_unchanged=True,
        all_forecast_sha256_unchanged=True, global_comparison_or_complete_writes=False,
        output_receipts_verified=len(output_matches), output_receipt_paths=output_matches,
        main_full_grid_required_per_window=5053, additional_strategy_variants_created=False,
        diagnostic_artifact_sha256={str(path.relative_to(root)): sha(path) for path in artifacts},
        alerts=receipt.get("alerts", []), monitor_errors=receipt.get("monitor_errors", []))
    return summary, issues


def source_preservation_provenance(root=ROOT):
    source = root / "diagnostics/FINAL_SOURCE_PRESERVATION_RECHECK.json"
    receipt = read(source)
    _need(receipt["status"] == "PASS" and receipt["historic_receipt_unchanged"]
          and receipt["fit_calls"] == receipt["strategy_outcomes_read"] == receipt["source_files_modified"]
          == receipt["prepared_snapshots_modified"] == receipt["frozen_files_modified"] == 0,
          "FINAL_SOURCE_PRESERVATION_SCOPE_OR_STATUS_FAILURE")
    _need(receipt["old_source_files_checked"] == 15 and receipt["prepared_snapshots_checked"] == 20,
          "FINAL_SOURCE_PRESERVATION_EXPECTED_FILE_COUNTS_CHANGED")
    for group, expected in [("old_source", 15), ("prepared_snapshot", 20)]:
        counts = receipt["counts"][group]
        _need(counts["MATCH"] == counts["expected"] == expected
              and all(counts[name] == 0 for name in ["MISSING", "CHANGED", "CHANGED_DURING_READ", "READ_ERROR"]),
              "FINAL_SOURCE_PRESERVATION_NONMATCH:" + group)
    _need(len(receipt["file_checks"]) == 35 and all(row["status"] == "MATCH" and row["stable_during_read"]
          and row["expected_sha256"] == row["actual_sha256"] for row in receipt["file_checks"]),
          "FINAL_SOURCE_PRESERVATION_FILE_CHECK_RECORDS_INCONSISTENT")
    baseline = receipt["expected_baseline"]
    _need(not baseline["expected_sha256_replaced"], "SOURCE_PRESERVATION_ORIGINAL_EXPECTED_HASHES_REPLACED")
    for name in ["input_audit", "pause_snapshot"]:
        path = _local(root, baseline[name + "_path"])
        _need(sha(path) == baseline[name + "_expected_sha256"] == baseline[name + "_actual_sha256"],
              "SOURCE_PRESERVATION_BASELINE_ANCHOR_CHANGED:" + name)
    resume = _local(root, baseline["resume_verification_path"])
    _need(sha(resume) == baseline["resume_verification_sha256"], "SOURCE_PRESERVATION_RESUME_ANCHOR_CHANGED")
    history = receipt["historic_receipt"]
    _need(sha(_local(root, history["path"])) == history["sha256"], "SOURCE_PRESERVATION_HISTORIC_RECEIPT_CHANGED")
    return dict(status="PASS", source=str(source.relative_to(root)), source_sha256=sha(source),
        old_source_matches=15, prepared_snapshot_matches=20, missing=0, changed=0, read_errors=0, concurrent_changes=0,
        original_expected_hashes_replaced=False, baseline=baseline, historic_receipt=history,
        fit_calls=0, strategy_outcomes_read=0, scope="latest preserved source audit receipt and baseline anchors; no source table values re-read")


def audit_all(tables, controls, roster, forecasts_by_year, freeze, *, workers=2, root=ROOT):
    freeze_sha = sha(root / "GLOBAL_FREEZE.json")
    specs = {r["strategy_id"]: r for r in roster.to_dict("records")}
    calendars = {year: pd.DatetimeIndex(_parquet(root / f"input/eval_{year}/calendar.parquet").trade_date) for year in YEARS}
    tasks = [(year, row, False) for year in YEARS for row in tables[year].to_dict("records")]
    tasks += [(year, row, True) for year in YEARS for row in controls[year].to_dict("records")]
    def one(task):
        year, row, control = task
        sid = row["strategy_id"]
        folder = root / (f"evaluation_controls_{year}" if control else f"evaluation_{year}") / sid
        label = dict(year=year, strategy_id=sid, control=control)
        if row["status"] == "FAILED":
            failure = read(folder / "FAILURE.json")
            _need(failure["status"] == "FAILED", "FAILURE_MARKER_INVALID")
            return {**label, "status": "NOT_AUDITED_FAILED_REPLAY", "reason": failure["reason"], "failure_type": failure["failure_type"]}
        try:
            done = read(folder / "DONE.json")
            _need(done["status"] == "REPLAY_COMPLETE" and done["strategy_id"] == sid and done["year"] == year, "DONE_IDENTITY_MISMATCH")
            for key in ["net_return", "max_drawdown", "mean_gross_exposure", "total_fees", "trades", "terminal_nav"]:
                _need(_max_error(row.get(key, np.nan), done.get(key, np.nan)) <= 1e-8, "COMPARISON_DIFFERS_FROM_DONE:" + key)
            spec = specs[sid] if not control else {"strategy_id": sid}
            details = audit_account(folder, done, year=year, spec=spec, freeze_sha=freeze_sha,
                calendar=calendars[year], pool_keys=forecasts_by_year[year]["keys"],
                buy_eligible_keys=forecasts_by_year[year]["buy_eligible_keys"],
                forecast_status=forecasts_by_year[year]["forecast_status"], control=control)
            return {**label, **details}
        except Exception as exc:
            return {**label, "status": "AUDIT_FAILED", "reason": type(exc).__name__ + ": " + str(exc)}
    rows = []
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 4))) as pool:
        for result in pool.map(one, tasks):
            rows.append(result)
            if len(rows) % 250 == 0:
                print(json.dumps(dict(event="DELIVERY_AUDIT_PROGRESS", audited=len(rows), expected=len(tasks),
                      audit_failures=sum(r["status"] == "AUDIT_FAILED" for r in rows))), flush=True)
    return pd.DataFrame(rows)


def build_coverage(roster, tables, audited):
    blocks = []
    for year in YEARS:
        design = roster.copy()
        design["members"] = design.members.map(lambda x: json.dumps(x, ensure_ascii=False))
        results = tables[year].copy()
        blocks.append(design.merge(results.drop(columns=[c for c in META_COLUMNS if c != "strategy_id"], errors="ignore"), on="strategy_id", validate="one_to_one"))
    coverage = pd.concat(blocks, ignore_index=True)
    audit = audited.loc[~audited.control].drop(columns="control").rename(columns={"status": "independent_audit_status", "reason": "independent_audit_reason"})
    coverage = coverage.merge(audit, on=["year", "strategy_id"], validate="one_to_one")
    coverage["legal_by_frozen_design"] = True
    coverage["diagnostic_execution"] = np.where(coverage.status.eq("REPLAY_COMPLETE"), "COMPLETE", "FAILED_ATTEMPT_RETAINED")
    coverage["formal_full_pool"] = "BLOCKED"
    coverage["formal_full_pool_reason"] = np.where(coverage.year.eq(2026), "UNKNOWN_ORIGINAL_INPUTS_RETROSPECTIVE_QUALIFIED_SUBSET", "UPSTREAM_IDENTITY_RESOLUTION_POOL_GAPS")
    coverage["blind_test"] = False
    coverage["shareholder_total_return_certified"] = False
    coverage["return_sign"] = np.select([coverage.status.ne("REPLAY_COMPLETE"), coverage.net_return.gt(0), coverage.net_return.lt(0)], ["FAILED", "POSITIVE", "NEGATIVE"], default="ZERO_OR_UNAVAILABLE")
    return coverage


def collect_failures(coverage, controls, audited, training_issues, forecast_info, input_audit, contract, statistics_issues=(), helper_issues=()):
    rows = list(training_issues) + list(statistics_issues) + list(helper_issues)
    for record in coverage.to_dict("records"):
        base = dict(year=record["year"], strategy_id=record["strategy_id"], source=f'evaluation_{record["year"]}/{record["strategy_id"]}')
        if record["status"] == "FAILED":
            rows.append(dict(**base, category="PTO_REPLAY_FAILURE", status="FAILED", reason=record.get("reason", record.get("independent_audit_reason", "see FAILURE.json"))))
        for field, category in [("optimizer_approx_unconverged_days", "NUMERICAL_UNCONVERGED"),
                                ("target_blend_unconverged_member_days", "TARGET_BLEND_MEMBER_UNCONVERGED")]:
            if float(record.get(field, 0) or 0) > 0:
                rows.append(dict(**base, category=category, status="FIXED_BUDGET_APPROXIMATION_RETAINED", numeric_days=record[field],
                                 gap_bound=record.get("max_optimality_gap_bound"), mapping=record.get("max_gradient_mapping_inf"),
                                 reason="fixed 80 iterations; numerical approximation is separate from a model conclusion"))
        if float(record.get("optimizer_infeasible_days", 0) or 0) > 0:
            rows.append(dict(**base, category="NUMERICAL_INFEASIBLE", status="INFEASIBLE_TARGET_ACCOUNT_ADAPTATION_RETAINED",
                             numeric_days=record["optimizer_infeasible_days"], reason="solver feasibility and actual account adaptation must be reported separately"))
    for record in audited.loc[audited.status.eq("AUDIT_FAILED")].to_dict("records"):
        rows.append(dict(category="INDEPENDENT_LEDGER_AUDIT_FAILURE", year=record["year"], strategy_id=record["strategy_id"], status="AUDIT_FAILED", reason=record["reason"]))
    for year in YEARS:
        for record in controls[year].loc[controls[year].status.eq("FAILED")].to_dict("records"):
            rows.append(dict(category="DECISION_CONTROL_FAILURE", year=year, strategy_id=record["strategy_id"], status="FAILED", reason=record.get("reason", "see FAILURE.json")))
        info = forecast_info[year]
        for record in info["metrics"].loc[info["metrics"].status.ne("PASS")].to_dict("records"):
            rows.append(dict(category="FORECAST_DIAGNOSTIC_FAILURE", year=year, member=record["forecast_id"], status=record["status"], reason=record.get("error", record["status"])))
        for record in info["probabilities"].loc[info["probabilities"].status.ne("PASS")].to_dict("records"):
            rows.append(dict(category="NATIVE_PROBABILITY_NOT_APPLICABLE" if record["status"] == "NO_NATIVE_PROBABILITY" else "NATIVE_PROBABILITY_FAILURE",
                             year=year, member=record["provider"], status=record["status"], reason=record.get("error", record.get("probability_semantics", record["status"]))))
    for member, reason in contract["excluded"].items():
        rows.append(dict(category="OUTSIDE_FINITE_REGISTERED_SCOPE", member=member, status="NOT_A_REGISTERED_LEGAL_ROUTE", reason=reason))
    matrix_path = ROOT / "INPUT_OUTPUT_COMPATIBILITY.csv"
    if matrix_path.exists():
        matrix = _csv(matrix_path)
        invalid = matrix.loc[~matrix.legal.astype(str).str.lower().eq("true")]
        for record in invalid.to_dict("records"):
            rows.append(dict(category="INPUT_OUTPUT_INCOMPATIBILITY", member=record["provider"], status="NOT_A_REGISTERED_LEGAL_ROUTE",
                reason="fusion=" + str(record["fusion"]) + ", risk=" + str(record["risk"]) + ", optimizer=" + str(record["optimizer"]) + ": " + str(record["reason"]),
                source="INPUT_OUTPUT_COMPATIBILITY.csv"))
    for year in YEARS:
        for source in (ROOT / f"evaluation_{year}").glob("*/attempts/*/FAILURE.json"):
            record = read(source)
            rows.append(dict(category="PRESERVED_PREVIOUS_REPLAY_FAILURE", year=year, strategy_id=record.get("strategy_id"),
                             status="FAILED_ATTEMPT_PRESERVED", reason=record.get("reason"), source=str(source.relative_to(ROOT))))
        for source in (ROOT / f"evaluation_{year}").glob("*/attempts/*/INTERRUPTED_ATTEMPT.json"):
            rows.append(dict(category="PRESERVED_INTERRUPTED_ATTEMPT", year=year, strategy_id=source.parents[2].name,
                             status="INTERRUPTED_ATTEMPT_PRESERVED", reason="retry retained the interrupted directory; no old ledger silently overwritten", source=str(source.relative_to(ROOT))))
    rows.extend([
        dict(category="FORMAL_FULL_POOL_INCOMPATIBILITY", year=2026, status="BLOCKED_UNKNOWN_INPUTS",
             numeric_days=input_audit["evaluation_2026"]["unknown_candidate_rows"], reason="UNKNOWN rows are not proven ineligible; qualified subset does not certify original full pool", source="INPUT_AUDIT.json"),
        dict(category="OLD_LEARNING_ARTIFACT_INCOMPATIBILITY", status="NOT_REUSED_FOR_LEARNING", reason=contract["old_reuse"], source="contract.json"),
        dict(category="RISK_NONE_CANONICALIZATION", status="DUPLICATE_ROUTES_NOT_REGISTERED", reason="equal_top20 has canonical risk none; risk model permutations of the fixed rule are not separate learned evidence"),
    ])
    result = pd.DataFrame(rows)
    for col in FAIL_COLUMNS:
        if col not in result:
            result[col] = None
    return result[list(FAIL_COLUMNS)]


def md_table(frame, columns=None, formats=None):
    if frame.empty:
        return "无可用记录。\n"
    if columns is not None:
        frame = frame[[c for c in columns if c in frame]].copy()
    formats = formats or {}
    def cell(value, column):
        if pd.isna(value):
            return "—"
        if column in formats:
            return formats[column].format(value)
        if isinstance(value, (float, np.floating)):
            return f"{value:.6g}"
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(frame.columns) + " |", "| " + " | ".join(["---"] * len(frame.columns)) + " |"]
    lines += ["| " + " | ".join(cell(value, col) for col, value in zip(frame.columns, row)) + " |" for row in frame.itertuples(index=False, name=None)]
    return "\n".join(lines) + "\n"


def fusion_comparison_summary(fusion):
    columns = [col for col in ["delta_net_return", "delta_max_drawdown", "delta_mean_gross_exposure", "delta_total_fees"] if col in fusion]
    table = fusion.groupby("left")[columns].mean().reset_index()
    table["fixed_coalitions"] = table.left.map(fusion.groupby("left").size())
    for col in ["expected_cells", "matched_cells", "left_only_success_cells", "right_only_success_cells", "both_missing_cells"]:
        if col in fusion:
            table[col + "_sum"] = table.left.map(fusion.groupby("left")[col].sum())
    if "matched_cells" in fusion:
        table["zero_match_coalitions"] = table.left.map(fusion.assign(zero=fusion.matched_cells.eq(0)).groupby("left").zero.sum())
    return table


def evaluation_window_metadata(root=ROOT):
    """Read frozen calendar columns only; dates are not annualized returns."""
    windows = {}
    for year in YEARS:
        calendar = pd.read_parquet(root / f"input/eval_{year}/calendar.parquet")
        signals = pd.read_parquet(root / f"input/eval_{year}/features.parquet", columns=["signal_date"])
        dates = pd.to_datetime(calendar.trade_date)
        signal_dates = pd.to_datetime(signals.signal_date).drop_duplicates().sort_values()
        _need(dates.is_monotonic_increasing and not dates.duplicated().any()
              and signal_dates.isin(dates).all()
              and len(signal_dates) == int(calendar.is_signal.sum()), "REPORT_WINDOW_CALENDAR_MISMATCH")
        windows[str(year)] = dict(year=year, nav_first=dates.min().date().isoformat(),
            nav_last=dates.max().date().isoformat(), nav_days=len(dates),
            signal_first=signal_dates.min().date().isoformat(), signal_last=signal_dates.max().date().isoformat(),
            signal_days=len(signal_dates), terminal_non_signal_nav_days=int((~calendar.is_signal).sum()),
            reported_return_is_window_return=True, full_calendar_year=(year == 2025),
            scope="upstream available input pool" if year == 2025 else "retrospective qualified subset, nonblind")
    return windows


def descriptive_route_extrema(coverage):
    """Describe registered complete-route extrema without selecting a model."""
    rows = []
    for year in YEARS:
        frame = coverage.loc[coverage.year.eq(year) & coverage.status.eq("REPLAY_COMPLETE")
                             & np.isfinite(coverage.net_return)]
        if frame.empty:
            continue
        for label, value in [("highest", frame.net_return.max()), ("lowest", frame.net_return.min())]:
            tied = frame.loc[frame.net_return.eq(value)].sort_values("strategy_id", kind="stable")
            selected = tied.iloc[0]
            rows.append(dict(year=year, observed_extreme=label, strategy_id=selected.strategy_id,
                net_return=float(selected.net_return), max_drawdown=float(selected.max_drawdown),
                mean_gross_exposure=float(selected.mean_gross_exposure), total_fees=float(selected.total_fees),
                exact_tie_count=len(tied), registered_route_count=len(frame)))
    return rows


def write_markdown(coverage, controls, training, failures, verification, forecast_info, input_audit, exposure, root=ROOT):
    report = root / "report"
    parts = ["# Predict-then-Optimize 冻结组合实验\n",
             f"生成时间：{verification['created_utc']}。本交付按事前有限清单保留两年全部 10,106 条 PTO 路径及 10 条独立决策控制；不根据 2026 结果选择部署模型。\n",
             f"诊断执行状态：**{verification['diagnostic_execution']}**；独立账本校验：**{verification['verification_status']}**；原规则完整池评估：**BLOCKED**；盲测及认证股东总收益：**未成立**。\n",
             "## 覆盖与全部结果\n",
             "31 个单预测器加 11 个成员联盟×11 个预测融合方法，共 152 个预测接口；各 31 种合法 risk/optimizer 配置给出 4,712 条预测路线，11 个独立目标融合联盟×31 配置给出 341 条目标路线，每窗口 5,053 条。固定等权 TOP20 只登记 risk=none 一种控制。\n"]
    if "evaluation_windows" in verification:
        parts += [md_table(pd.DataFrame(verification["evaluation_windows"].values()),
                    ["year", "nav_first", "nav_last", "nav_days", "signal_first", "signal_last", "signal_days", "terminal_non_signal_nav_days"]),
            "收益为各自实际窗口的累计账户收益。2026 只截至 2026-09-24，并非全年；两个窗口长短不同，不能把跨窗口收益高低直接解释成年度模型能力变化。末两个 NAV 日只处理账户收尾，不产生新信号。\n"]
    summary = []
    for year in YEARS:
        f = coverage.loc[coverage.year.eq(year)]
        summary.append(dict(year=year, attempted=len(f), complete=int(f.status.eq("REPLAY_COMPLETE").sum()), failed=int(f.status.eq("FAILED").sum()),
             positive=int(f.return_sign.eq("POSITIVE").sum()), negative=int(f.return_sign.eq("NEGATIVE").sum()), zero_or_unavailable=int(f.return_sign.eq("ZERO_OR_UNAVAILABLE").sum()),
             unconverged_path_days=int(f.optimizer_approx_unconverged_days.fillna(0).sum()),
             target_member_unconverged_path_days=int(f.target_blend_unconverged_member_days.fillna(0).sum())))
    parts += [md_table(pd.DataFrame(summary)),
        "上述 path-days 是共享日期上多策略的数值状态计数，不是独立统计样本数。全部正负结果见 [ALL_PTO_RESULTS.csv](ALL_PTO_RESULTS.csv) 和 [可筛选本地结果](RESULTS.html)；覆盖状态见 [完整覆盖表](COMBINATION_COVERAGE_FINAL.csv)，失败、未收敛、警告及不兼容原因见 [记录表](FAILURE_AND_INCOMPATIBILITY.csv)。\n",
        "## 训练、复用与固定预算\n",
        "复用的是公共输入与账户执行实现；旧学习工件因目标或接口合同不匹配而重新训练，新目录没有覆盖 Raw A2 或旧冻结批次。所有学习、标准化、校准和尺度估计的样本及标签日期都在 2026 年前；实际运行训练的墙钟时间为 2026 年 9 月，不能将其改写成此前已实际训练。融合均值学习使用按时间成熟的基模型 OOF；融合残差尺度来自同一基模型 OOF 训练表上的融合拟合残差，没有再对融合器 cross-fit，不能称为融合输出完整折外概率校准。rank 的 isotonic score-to-return 适配、点预测残差尺度以及 equal/median 的固定统计也不是独立完整分布校准。\n",
        md_table(pd.DataFrame([dict(layer=k, **v) for k, v in training.items() if isinstance(v, dict) and k != "risk"])),
        "风险实际操作：`" + json.dumps(training["risk"], ensure_ascii=False) + "`。预测 fit calls、输出头数、标准化、校准与统计尺度分开计数；242 个融合工件中 equal/median 无均值估计器拟合，但仍产生训练残差尺度估计。\n",
        "[原生模型/预测完成覆盖](../diagnostics/NATIVE_COMPLETED_COVERAGE.csv) 保留各阶段实物工件状态；最终计数来自实际训练收据，不按算法名称推测 fit 次数。\n",
        f"本批拟合警告、初次恢复失败及 RL 无有效认证奖励的状态记录共 {training['warnings_and_preserved_initial_failures']} 条，详见原因表；不通过追加预算、候选或种子挽救结果。\n",
        "## 预测器与预测合作\n",
        "下表是单预测器在十风险×三优化的条件平均，以及对应 provided input keys 的预测诊断。MSE 不作为账户模型选择的唯一依据；Normal NLL/分位数 proxy 与原生分布的语义分别在预测诊断文件保留。所有 152 个预测接口的诊断均交付。通用预测 TOP20 在完整提供输入行上按 mu 排序，包含 held-only 行；它没有逐账户可新买 gate、保留槽位、成交与费用约束，不等于账户可买 TOP20 的选股表现或原完整 13F 池表现。TOP20−输入池均值只使用该输入池标签和预测全部可用的日期，并在表中保留 complete day 数。\n",
        "合作覆盖为 11 个预登记联盟×11 个统一 mu 融合方法，没有展开成员幂集，也没有原生概率/log-pool 融合。equal/convex/gate 使用 sigma 的混合矩；median/stack/residual 使用同一基模型 OOF 训练表上的融合拟合残差尺度，融合均为 Normal proxy。只有 single 的六种 quantile 以原生 piecewise 分位数进入 CVaR，三种 distribution 使用 Native Normal；没有原生字段的预测器不伪造 native 输出。\n",
        "[INPUT_OUTPUT_COMPATIBILITY.csv](../INPUT_OUTPUT_COMPATIBILITY.csv) 的 16,368 行、11,532 个 legal 单元是 31 个 provider 进入 12 个 fusion 类型（含 identity）及风险/优化接口的类型矩阵，不能当作 11,532 条独立实验。实际执行合法性以固定 11 个成员联盟、152 个预测接口和每窗口 5,053 条覆盖表为准；identity 只用于单预测器，risk=none/equal_top20 去重后仅登记一次。\n"]
    if "training_sample_boundaries" in verification:
        boundaries = verification["training_sample_boundaries"]
        parts += ["### 实际训练样本边界\n", md_table(pd.DataFrame(boundaries["native"]),
            ["stage", "models", "sample_rows_each", "features", "train_signal_min", "train_signal_max", "train_label_end_max", "cutoff_exclusive"]),
            md_table(pd.DataFrame(boundaries["fusion"]).assign(base_prediction_cutoffs=lambda frame: frame.base_prediction_cutoffs.map(lambda values: ", ".join(values))), ["stage", "objects", "base_oof_signal_years", "rows_max", "dates_max", "signal_max", "label_end_max", "cutoff", "base_prediction_cutoffs"]),
            "原始 FIT_LOG.csv 保留 84 PASS 和 9 个首次恢复 FAILED；这 9 个 forest 数值恢复问题随后通过保存的 RESTORE_NUMERIC_AUDIT 解决，恢复阶段新增 fit=0。最终 93 个模型阶段完成依据是 models/TRAIN_RECEIPT.json 与 93 个最终 FIT_RECEIPT，不覆盖初始失败历史。训练信号均从 2023-01-03 起；较早价格历史不等于模型训练样本从 2018 年起。\n",
            "[2026 未参与学习的日期及调用边界核对](../diagnostics/NO_2026_LEARNING_BOUNDARY_RECHECK.json) 另外检查原生、融合、风险、RL 及两年回放 guard；它不认证上游 knowledge-time、原完整池或此前曝光后的盲测。\n"]
    for year in YEARS:
        f = coverage.loc[coverage.year.eq(year) & coverage.coalition.eq("single") & coverage.optimizer.isin(OPTIMIZERS) & coverage.status.eq("REPLAY_COMPLETE")]
        table = f.groupby("forecast_id", sort=False).agg(cells=("strategy_id", "size"), net_return_mean=("net_return", "mean"), drawdown_mean=("max_drawdown", "mean"), gross_mean=("mean_gross_exposure", "mean"), fees_mean=("total_fees", "mean")).reset_index()
        diagnostics = forecast_info[year]["metrics"]
        table = table.merge(diagnostics[[c for c in ["forecast_id", "mse", "day_spearman_ic", "top20_minus_whole_input_pool", "top20_complete_input_pool_days", "missing_label_rows", "normal_nll_semantics"] if c in diagnostics]], on="forecast_id", how="left", validate="one_to_one")
        negative_ic = int(diagnostics.day_spearman_ic.lt(0).sum()) if "day_spearman_ic" in diagnostics else None
        below_pool = int(diagnostics.top20_minus_whole_input_pool.lt(0).sum()) if "top20_minus_whole_input_pool" in diagnostics else None
        parts += [f"### {year}\n", f"全部预测诊断中，负日均 rank IC 的接口数为 {negative_ic}，TOP20 标签收益低于同一 provided 输入池平均的接口数为 {below_pool}。这些负诊断、完整标签日期数与标签缺失均保留；标签收益诊断不是含成本账户收益。\n",
                  md_table(table), f"[全部预测诊断](../diagnostics/forecast_metrics/{year}/FORECAST_METRICS.csv)、[原生概率诊断](../diagnostics/forecast_metrics/{year}/NATIVE_PROBABILITY_METRICS.csv)、[标签可用性](../diagnostics/forecast_metrics/{year}/LABEL_AVAILABILITY.csv)。\n"]
        matched = _csv(report / f"matched_dimension_comparisons_{year}.csv")
        fusion = matched.loc[matched.comparison.eq("fusion_within_fixed_members")].copy()
        if len(fusion):
            table = fusion_comparison_summary(fusion)
            parts += ["固定联盟内相对 equal 预测融合的描述性变化；联盟之间共享成员，表中联盟数不是独立样本量。配对只使用成功交集，预期/匹配/仅一方成功/双方缺失及零匹配联盟数同时保留；空收益不填零。\n", md_table(table)]
    parts += ["## 风险、优化与交互\n",
        "风险比较按十风险×三优化登记网格组织；失败时均值明确条件于成功路径，三层因子分解要求共同完整 Cartesian 网格，equal_top20 预算规则对照单列。静态协方差来自阶段截止日前同一 252 日窗口：validation 为 2024-01-02 至 2024-12-31，final 为 2024-12-30 至 2025-12-31；2026 没有滚动重新估计这些历史、收缩或因子参数。HGB/MLPvol 信号样本从 2023-01-03 至各阶段信号末日，学的是截尾收益条件二阶矩，并非已去均值的无偏方差；评估日特征只用于冻结模型前向预测风险幅度，不能叫重新拟合。MV/robust 使用适配后的 mu 与风险 Sigma；预测 sigma/原生 q 主要进入 CVaR 联合场景。共同历史 rank-copula 后，场景中心匹配 provider mu，幅度乘 selectedRiskSigma/historicalSigma，因此不声称保持原生分位位置、精确校准或预测器完整原生分布。\n"]
    for year in YEARS:
        f = coverage.loc[coverage.year.eq(year) & coverage.route.eq("prediction_fusion") & coverage.optimizer.isin(OPTIMIZERS) & coverage.status.eq("REPLAY_COMPLETE")]
        parts.append(f"### {year}\n")
        for dimension in ["risk", "optimizer"]:
            table = f.groupby(dimension).agg(cells=("strategy_id", "size"), return_mean=("net_return", "mean"), drawdown_mean=("max_drawdown", "mean"), gross_mean=("mean_gross_exposure", "mean"), fees_mean=("total_fees", "mean"), unconverged_path_days=("optimizer_approx_unconverged_days", "sum")).reset_index()
            parts.append(md_table(table))
        diagnostics = coverage.loc[coverage.year.eq(year) & coverage.route.eq("prediction_fusion") & coverage.independent_audit_status.eq("PASS")]
        if "scenario_metadata_path_days" in diagnostics:
            scenario = diagnostics.loc[diagnostics.scenario_metadata_path_days.gt(0)]
            if len(scenario):
                table = scenario.groupby("risk").agg(recorded_scenario_path_days=("scenario_metadata_path_days", "sum"),
                    unknown_path_days=("scenario_unknown_path_days", "sum"), unknown_support_occurrences=("scenario_unknown_support_occurrences", "sum"),
                    rank_deficient_path_days=("scenario_rank_deficient_path_days", "sum"),
                    max_pre_subsample_correlation_error=("scenario_correlation_max_error", "max"),
                    max_mean_matching_error=("scenario_mean_matching_max_error", "max")).reset_index()
                parts += ["CVaR 预测路线的已保存场景诊断（path-days 与 support occurrences 可能重复共享输入，非独立 N；相关误差是 252 日秩变换在 64 行抽取前的值）：\n", md_table(table)]
        parts.append("未知股票协方差按固定规则保留，场景共享市场秩可能降秩；不能把对角未知协方差解释成尾部精确独立。目标融合保存成员目标与聚合残差，未逐成员保存完整 risk/correlation 元信息，因此上述相关误差汇总范围明确限于预测路线。\n")
        pair = _csv(report / f"matched_dimension_comparisons_{year}.csv")
        parts += ["同日匹配风险/优化比较（共享日差先平均成功匹配单元，再 HAC5；matched_cells 不是独立 N）。HAC5 是五个保留的共同有效收益日；内部缺日可跨更多原交易日。预期和缺失配对数量、共同有效日及删去日数均保留；零匹配行不填零。\n",
                  md_table(pair.loc[pair.comparison.isin(["risk", "optimizer"])], ["comparison", "left", "right", "expected_cells", "matched_cells", "left_only_success_cells", "right_only_success_cells", "both_missing_cells", "common_valid_return_days", "omitted_return_days", "mean_daily_log_difference", "hac_se_lag5", "delta_net_return", "delta_mean_gross_exposure", "delta_total_fees"])]
        path = report / f"factor_interactions_{year}_net_return.csv"
        if path.exists():
            interaction = _csv(path).groupby(["risk", "optimizer"]).risk_optimizer_interaction.mean().unstack("optimizer").reset_index()
            parts += ["收益的风险×优化描述性交互：\n", md_table(interaction)]
        else:
            parts.append("存在失败或不完整可用网格，未填零制造完整因子分解。\n")
        parts.append(f"[主效应](main_effect_summaries_{year}.csv)、[同日匹配差](matched_dimension_comparisons_{year}.csv)、[优化相对 equal 预算规则](optimization_vs_fixed_gross_{year}.csv)、[融合×风险条件比较](fusion_risk_conditional_comparisons_{year}.csv)。文件名 fixed_gross 为兼容保留：同 forecast/route 的 risk=none/equal_top20 对照采用≤0.95账户预算上限及相同资格/单股约束，实际 gross 并不恒定；比较不识别纯敞口因果效果。全部 forecast×risk、forecast×optimizer 和三阶交互见对应 factor_interactions CSV；mean_daily_log_return 因子表是各账户可用日均值的代数分解，缺日集合不同则不是共享日期的交互推断。\n")
    parts += ["## 全结果静态图\n",
        "所有有限且可用的完成路径均进入图中；失败和无有限指标路径的数量写在图注，不将其收益填零。颜色是平均实际 gross，配对变化使用实际账户与成本，不另造倍仓路径。交互热图依原设计顺序显示全部 152 个预测接口；没有按结果筛选成员。\n"]
    for year in YEARS:
        parts += [f"### {year}\n", f"![全部净收益、最大回撤及实际敞口](figures/all_results_return_drawdown_{year}.png)\n",
                  f"![优化相对 equal 预算规则的配对变化](figures/paired_return_gross_delta_{year}.png)\n"]
        if (report / f"figures/forecast_risk_optimizer_interaction_{year}.png").exists():
            parts.append(f"![预测、风险、优化三层描述性交互](figures/forecast_risk_optimizer_interaction_{year}.png)\n")
        else:
            parts.append("未生成三层交互热图：该年完整平衡可用网格未成立，失败原因及全部结果仍保留。\n")
    parts += ["## 目标仓位融合与独立控制\n",
        "目标仓位融合与预测融合是独立路线；每个成员收到融合策略自身实际当前仓位和现金。target_vs_prediction_fusion 按同联盟、同 OOF convex 系数、risk 和 optimizer 配对，两边独立推进自己的账户；支持、槽位、现金及费用都会变化。CVaR 目标融合使用单成员原生 quantile/Normal 或明确 proxy，预测融合使用 Normal proxy，场景语义也可能不同，差异不能全部归为纯融合顺序因果效果。全部配对及缺失情况见同日匹配比较 CSV。\n",
        md_table(pd.concat([controls[y] for y in YEARS], ignore_index=True), ["year", "strategy_id", "status", "net_return", "certified_terminal_nav", "entire_valuation_path_certified", "max_drawdown", "mean_gross_exposure", "total_fees", "trades", "uncertified_valuation_days"]),
        "cash、REINFORCE/PPO 和各自同初始状态 zero 控制只作独立决策比较，不计入 5,053 条 PTO 清单。两个 zero 共享初始状态，不能当作两个独立种子的学习证据；低敞口或跳过无认证奖励状态的效果不自动证明学习能力提高。\n",
        "上表 net_return 是公共引擎研究价格指数上的 indicative 收益；certified_terminal_nav 缺失时，终值没有完整认证报价支持，不能将 indicative 终值改写成 certified 收益。即使报价净值存在，AFFINE 指数坐标仍不是已认证的完整股东 total return。未认证/陈旧估值日期与具体原因保留在原账本和独立核验中。\n",
        *control_valuation_notes(root=root),
        "## 统计报告层的真实集成核验\n",
        "2025 首次真实统计集成曾因 comparison 的 DataFrame 形参 left/right 与同名输出标签冲突而中止；非冻结统计代码改为 left_frame/right_frame 后完整重跑通过。首次失败收据与修复后收据均保留，分类为 REPORT_STATISTICS_INITIAL_INTEGRATION_FAILURE、resolved=True、strategy_route_failure=False；它不是策略路线回放失败，未改冻结学习或执行工件、未重新训练。\n",
        f"修复后 2025 收据记录 {verification['statistics_report_history']['matched_comparisons']['rows']} 条匹配比较、{verification['statistics_report_history']['conditional_fusion_comparisons']['rows']} 条条件融合比较，以及四种指标各 4,560 个完整交互单元。优化对照 {verification['statistics_report_history']['optimization_vs_budget_control']['rows']:,} = {verification['statistics_report_history']['optimization_vs_budget_control']['prediction_route_rows']:,} 预测路线 + {verification['statistics_report_history']['optimization_vs_budget_control']['target_route_rows']:,} 目标路线，对应 {verification['statistics_report_history']['optimization_vs_budget_control']['distinct_budget_controls']} 条 equal 预算规则；冻结 roster 为每年 5,053。2025 NAV 日历 {verification['statistics_report_history']['daily_returns']['calendar_rows']} 日，共同有效收益 {verification['statistics_report_history']['daily_returns']['whole_roster_common_valid_days']} 日，内部非有限收益数 {verification['statistics_report_history']['daily_returns']['internal_nonfinite_returns']}，首行收益缺失为预期时钟结果。\n",
        "[首次统计集成失败](../diagnostics/statistics_2025_preflight/PREFLIGHT_RECEIPT_FAILED_LEFT_RIGHT_ARGUMENTS.json)、[修复后真实统计核验](../diagnostics/statistics_2025_preflight/PREFLIGHT_RECEIPT.json)。当前统计源码与测试源码 SHA、两份收据 SHA 和失败关联保存在 FINAL_VERIFICATION；先前失败属于报告层历史，不计入策略失败数量。\n",
        "## 账户、预测与冻结核验\n",
        f"本交付逐 DONE 复验 {verification['ledger_files_verified']} 个账本哈希，并对全部成功路径独立递推现金、数量、持仓与净值、费用、容量证据和下一交易日时钟，核验预测→目标→订单→执行及成员目标链接。预测链接核验数 {verification['prediction_links_verified']}；账户最大误差：`{json.dumps(verification['account_max_errors'], ensure_ascii=False)}`。失败路径保留原失败记录，未伪造账户。\n",
        "实际成交 BUY 另按 (signal_date,ticker) 核验属于该年冻结输入的 new_buy_eligible=True 键，不只检查目标权重。2025 无该字段时遵循原初始化全 True；2026 对额外 held-only 上下文实证 BUY=0，允许保留/卖出。此检查也覆盖下一开盘价格 gap 导致潜在数量增加的情况；计数范围是全部成功 DONE 账本。\n",
        "2025 在事前 DESIGN_LOCK 后执行；pre-global provenance 保留，预测和模型工件与后续 GLOBAL 冻结哈希一致。早期三条 ridge 验证路径标为 early pilot，已有全部十表完全一致测试；速度层修改具有等价核审计。2026 每条 DONE 必须匹配当前完整 GLOBAL 冻结哈希。不能表述为两年都在 GLOBAL 冻结后才观察。\n",
        "GLOBAL 的直接冻结工件清单与报告引用文件的来源哈希分开记录；INPUT_AUDIT.json 等解释文档不自动属于直接 GLOBAL 工件。本交付另外核对 INPUT_AUDIT 内容哈希与各成功控制的 FROZEN_BEFORE_REPLAY 记录，保留此文档 provenance，不能声称所有文档均被直接冻结。\n",
        f"2026 的 all_outputs 目标融合原 31 条规格由单进程 helper 提前调用原 initialize/chunk_worker，随后主全批按原 resume 规则复用并核验账本。helper 完成 {verification['parallel_helper_orchestration']['completed']}、失败 {verification['parallel_helper_orchestration']['failed']}，0 拟合，核心 {verification['parallel_helper_orchestration']['frozen_core_files']} 项哈希前后相同；没有新增模型、种子、期限、权重或策略变体。新 caller 不属于原 GLOBAL 直接冻结成员，其单独源码 SHA、进度/完成/失败历史由 [helper 完成收据](../diagnostics/TARGET_ALL_OUTPUTS_HELPER_2026_RECEIPT.json) 和 FINAL_VERIFICATION 绑定；声明不写全局 comparison/COMPLETE 的范围结合 caller 源码审查与收据核验。最终覆盖仍核验主批每年全部 5,053 条，不能由 helper 的 31 条代替。\n",
        f"最新源文件保全：原旧源 {verification['source_preservation']['old_source_matches']}/15、prepared 快照 {verification['source_preservation']['prepared_snapshot_matches']}/20 全部 MATCH，missing/changed/read_error/concurrent_change 均为零。初始 INPUT_AUDIT 的预期 SHA 仍由暂停快照和原恢复收据锚定，没有替换 expected；原保全历史收据也未覆盖。最新 [源文件保全实核验](../diagnostics/FINAL_SOURCE_PRESERVATION_RECHECK.json) 及其 SHA/锚定来源纳入 FINAL_VERIFICATION，本交付不重读旧表收益。\n",
        "数据/公共账户验证引用原已保存验证：POOL_POLICY_CLARIFICATION、risk_artifacts/IMPLEMENTATION_VERIFICATION、REPLAY_INTEGRATION_VERIFICATION、INDEPENDENT_IMPLEMENTATION_AUDIT 与 RL 验证文件。完整清单及源码哈希见 FINAL_VERIFICATION.json；本脚本不重新执行拟合或扩预算。\n",
        "## 证据边界\n",
        f"13F 原规则固定 24 家机构，排除 Situational Awareness；每季符合条件的经营公司权益按披露 USD value/CUSIP 排名前 100 后取并集。共享季度 cohort 按 24 家中最晚公开时间之后第 5 个 QQQ 交易日共同生效，不是各经理单独切季。新季度已经公开但尚未生效，仍沿用最近已生效季度；确实尚未公开时可沿旧池，已经公开但本地缺失必须记 UNKNOWN，不能用 stale 旧池掩盖。\n",
        f"2026 保存的 legacy 映射 gate 为 {input_audit['evaluation_2026']['original_candidate_rows']:,} 个 (date,ticker) 键，其中合格新买 62,393、UNKNOWN {input_audit['evaluation_2026']['unknown_candidate_rows']:,}、已证明不合格 {input_audit['evaluation_2026']['proven_ineligible_rows']:,}；回放输入 {input_audit['evaluation_2026']['candidate_rows']:,} 键，原完整池覆盖日为 {input_audit['evaluation_2026']['complete_original_pool_signal_days']}。这一 gate 已经过上游身份映射和静态验证筛选，不是未过滤的原始 eligible CUSIP 经济全池，其缺口不能由 111,868 这个分母恢复。UNKNOWN 未重新编码成不合格，也不能把上游可用池认证为无生存偏差原完整池。\n",
        held_only_count_explanation(verification["held_only_input_reconciliation"], input_audit).replace("原候选 gate", "保存的 legacy 映射 gate").replace("原 gate", "保存的 legacy 映射 gate").replace("原候选池", "该 legacy 映射 gate"),
        "2026 为事后 qualified 子池诊断，不认证全原池完成或盲测。此前 2025/2026 曝光及输入依赖文档中的意外旧策略摘要曝光完整保留于 EXPOSURE_HISTORY.json；当前冻结只能防止新的结果回流，不能恢复已失去的盲测。价格为 AFFINE 研究指数坐标，认证报价净值不等于认证股东 total return；GLW 事件日期冲突及未知估值继续披露。\n",
        "5,053 条策略共享日期、股票、基础预测和成员，不是 5,053 个独立样本。HAC5 作用于保留的共同有效日期上的配对日对数收益差；缺日后五个有效日可能跨更多原交易日，未作多重比较校正，不应解读为部署选择或因果证明。各层作用均条件于当前有限合同；回撤必须与实际 gross、现金、换手及费用并看，降低敞口不等于学习能力提升。\n",
        "详细解释见 [分层比较口径](../DIMENSION_ANALYSIS_INTERPRETATION.md)、[独立实现审计](../INDEPENDENT_IMPLEMENTATION_AUDIT.md)、[冻结验证](FINAL_VERIFICATION.json)。本批到此停止，不追加搜索或部署选择。\n"]
    if "diagnostics/COMPARISON_FINDINGS.md" in {key.replace("\\", "/") for key in verification["source_sha256"]}:
        parts.append("[独立完整结果解读](../diagnostics/COMPARISON_FINDINGS.md) 按全部冻结结果组织，保留日期依赖、敞口、数值近似与数据覆盖限制；它不构成部署选择。\n")
    extrema = descriptive_route_extrema(coverage)
    parts += ["## 登记完整组合的描述性极值\n",
        "下表只从已完成的固定 5,053 条完整组合中描述每窗口最高、最低累计净收益。单位是独立推进的完整策略账户，收益坐标仍为 AFFINE 研究价格指数，2026 仍限 qualified 子池及截至 09-24 的非全年窗口。并列值按登记 ID 稳定取一例并报告 exact_tie_count；这里没有新搜索、模型选择或部署推荐。\n",
        md_table(pd.DataFrame(extrema), formats={"net_return": "{:.3%}", "max_drawdown": "{:.3%}", "mean_gross_exposure": "{:.3%}", "total_fees": "{:.2f}"})]
    if "rendering_revision" in verification:
        parts += ["报告展示修订复用已完整通过的 10,116 条账户核验，未重新读取账本、训练或回放。初始报告、核验及原核验源码已先行归档；覆盖 CSV 和失败 CSV 与原实核验输出哈希完全相同。\n",
            "[原完整核验归档](../diagnostics/DELIVERY_INITIAL_FULL_AUDIT/report/FINAL_VERIFICATION.json)、[归档清单](../diagnostics/DELIVERY_INITIAL_FULL_AUDIT/MANIFEST.json)、[原审计 stdout 与终态历史](../diagnostics/DELIVERY_THREAD_AUDIT_HISTORY.json)、[展示修订收据](../diagnostics/DELIVERY_REPORT_REFRESH_RECEIPT.json)。独立比较表覆盖及完整结果解读收据作为后置来源分别绑定，不替代全账本核验。\n"]
    if "presentation_render_failure_history" in verification:
        parts.append("第一次缓存展示修订因训练截止日列表直接传入 Markdown 标量单元函数而中止；仅将展示列转为文本后修复，未改通用账本审计或统计数据。该 [实际展示失败收据](../diagnostics/REPORT_REFRESH_INITIAL_TABLE_RENDER_FAILURE.json) 及失败当时源码保留；resolved=True、strategy_route_failure=False，不计入策略失败数量，覆盖及失败 CSV 哈希保持原值。\n")
    (report / "EXPERIMENT_REPORT.md").write_text("\n".join(parts), encoding="utf-8")


def control_valuation_notes(root=ROOT):
    """Executed during delivery only; keep certified gaps next to controls."""
    source = root / "diagnostics/CONTROLS_2026_VERIFICATION.json"
    if not source.exists():
        return ["控制报价质量原因收据尚缺失；原逐日持仓账本仍交付，不推测认证缺失原因。\n"]
    receipt = read(source)
    rows = []
    for account in receipt.get("account_audits", []):
        for ticker in account.get("bad_mark_tickers", []):
            rows.append(dict(control=account["control"], ticker=ticker["ticker"], bad_mark_rows=ticker["bad_mark_rows"],
                first_bad_mark=ticker.get("first_bad_mark"), last_bad_mark=ticker.get("last_bad_mark"),
                reasons=json.dumps(ticker.get("reasons", {}), ensure_ascii=False)))
    return ["2026 控制的报价质量缺口按全部 ticker/原因保留；bad_mark_rows 是股票×日期计数，同日多股会重复，不是独立日期数。stale 导致 certified 终值缺失时，即使 unknown NAV 为零且现金/数量/净值算术通过，也不代表终值已认证。\n",
            md_table(pd.DataFrame(rows)) if rows else "收据未记录 bad-mark 股票行。\n",
            "[2026 控制独立核验](../diagnostics/CONTROLS_2026_VERIFICATION.json)。\n"]


def write_html(coverage, controls, verification, root=ROOT):
    columns = ["year", "strategy_id", "route", "forecast_id", "risk", "optimizer", "status", "return_sign",
               "net_return", "max_drawdown", "mean_gross_exposure", "total_fees", "trades",
               "optimizer_approx_unconverged_days", "optimizer_infeasible_days", "target_blend_unconverged_member_days", "independent_audit_status",
               "formal_full_pool", "early_test_vs_full_run"]
    all_rows = coverage.copy()
    control_rows = pd.concat([controls[y] for y in YEARS], ignore_index=True)
    control_rows["return_sign"] = np.select([control_rows.status.ne("REPLAY_COMPLETE"), control_rows.net_return.gt(0), control_rows.net_return.lt(0)], ["FAILED", "POSITIVE", "NEGATIVE"], default="ZERO_OR_UNAVAILABLE")
    all_rows = pd.concat([all_rows, control_rows], ignore_index=True)
    for col in columns:
        if col not in all_rows:
            all_rows[col] = None
    data = json.dumps(clean(all_rows[columns].replace({np.nan: None}).to_dict("records")), ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    headers = "".join("<th>" + html.escape(c) + "</th>" for c in columns)
    document = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>PTO 全部冻结结果</title>
<style>body{font:14px system-ui,sans-serif;margin:24px;background:#f8fafc;color:#172033}h1{font-size:24px}.notice{padding:16px;background:#fff3cd;border-left:4px solid #947400;line-height:1.7}.filters{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}select,input,button{padding:8px;border:1px solid #bac4d1;border-radius:4px;background:white}.tablewrap{overflow:auto;max-height:72vh;border:1px solid #d5dde7}table{border-collapse:collapse;background:white;font-size:12px;width:100%}th,td{border-bottom:1px solid #e4e9ef;padding:7px;text-align:left;white-space:nowrap}th{position:sticky;top:0;background:#e8eef5;cursor:pointer}.negative{color:#9f2330}.positive{color:#16683d}a{color:#1555a0}#count{margin:12px 0}</style>
<h1>Predict-then-Optimize 全部结果</h1><div class="notice">诊断执行：__EXECUTION__；独立核验：__VERIFICATION__。原完整池评估 BLOCKED，2026 是 qualified 子池历史诊断；此前曝光保留，非盲测、非认证股东 total return。__WINDOWS__ 所有正负结果和失败均展示，排序仅用于查阅，不作部署选择。</div>
<p><a href="EXPERIMENT_REPORT.md">实验报告</a> · <a href="ALL_PTO_RESULTS.csv">全部 PTO CSV</a> · <a href="COMBINATION_COVERAGE_FINAL.csv">覆盖 CSV</a> · <a href="FAILURE_AND_INCOMPATIBILITY.csv">失败/警告/不兼容</a> · <a href="FINAL_VERIFICATION.json">核验 JSON</a> · <a href="../diagnostics/COMPARISON_FINDINGS.md">完整分层解读</a></p>
<div class="filters" id="filters"></div><div id="count"></div><div class="tablewrap"><table><thead><tr>__HEADERS__</tr></thead><tbody id="rows"></tbody></table></div><p>多路径共享日期和预测，不是独立 N；风险/优化比较需同时观察实际敞口和费用。CSV 保留所有行，本页每页 200 行。</p><button id="prev">上一页</button> <button id="next">下一页</button>
<script>const data=__DATA__;const cols=__COLUMNS__;const dimensions=['year','return_sign','route','risk','optimizer','forecast_id','status'];let page=0,sortKey=null,sortDirection=1;const box=document.getElementById('filters');const controls={};for(const k of dimensions){const select=document.createElement('select');select.setAttribute('aria-label',k);const all=document.createElement('option');all.value='';all.textContent=k+'：全部';select.appendChild(all);for(const v of [...new Set(data.map(r=>r[k]).filter(v=>v!==null&&v!==undefined))].sort()){const o=document.createElement('option');o.value=String(v);o.textContent=String(v);select.appendChild(o)}select.addEventListener('change',()=>{page=0;render()});box.appendChild(select);controls[k]=select}const search=document.createElement('input');search.placeholder='策略 ID 搜索';search.setAttribute('aria-label','策略 ID 搜索');search.addEventListener('input',()=>{page=0;render()});box.appendChild(search);function filtered(){let result=data.filter(r=>dimensions.every(k=>!controls[k].value||String(r[k])===controls[k].value)&&String(r.strategy_id).toLowerCase().includes(search.value.toLowerCase()));if(sortKey)result.sort((a,b)=>{const x=a[sortKey],y=b[sortKey];if(x===null)return 1;if(y===null)return -1;return sortDirection*(typeof x==='number'&&typeof y==='number'?x-y:String(x).localeCompare(String(y)))});return result}function render(){const selected=filtered();const total=Math.max(1,Math.ceil(selected.length/200));page=Math.max(0,Math.min(page,total-1));document.getElementById('count').textContent=`显示 ${selected.length} / ${data.length} 行；第 ${page+1} / ${total} 页（包含10条独立控制）`;const body=document.getElementById('rows');body.replaceChildren();for(const r of selected.slice(page*200,(page+1)*200)){const tr=document.createElement('tr');for(const k of cols){const td=document.createElement('td');const v=r[k];td.textContent=v===null||v===undefined?'—':typeof v==='number'?(k==='net_return'||k==='max_drawdown'||k==='mean_gross_exposure'?(v*100).toFixed(3)+'%':Number.isInteger(v)?String(v):v.toFixed(6)):String(v);if(k==='net_return')td.className=v<0?'negative':v>0?'positive':'';tr.appendChild(td)}body.appendChild(tr)}document.getElementById('prev').disabled=page===0;document.getElementById('next').disabled=page>=total-1}document.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{const k=cols[i];sortDirection=sortKey===k?-sortDirection:1;sortKey=k;render()}));document.getElementById('prev').onclick=()=>{page--;render()};document.getElementById('next').onclick=()=>{page++;render()};render();</script></html>"""
    document = document.replace("__DATA__", data).replace("__COLUMNS__", json.dumps(columns))
    document = document.replace("__HEADERS__", headers).replace("__EXECUTION__", html.escape(verification["diagnostic_execution"]))
    document = document.replace("（包含10条独立控制）", "（总数据含10条独立控制）")
    window_text = ""
    if "evaluation_windows" in verification:
        window_text = "；".join(f"{y} NAV {verification['evaluation_windows'][str(y)]['nav_first']} 至 {verification['evaluation_windows'][str(y)]['nav_last']}，{verification['evaluation_windows'][str(y)]['nav_days']} 日、{verification['evaluation_windows'][str(y)]['signal_days']} 信号日" for y in YEARS)
        window_text += "。2026 不是全年，表中为窗口累计收益，不能直接按不同长度窗口评判跨年高低。"
    document = document.replace("__WINDOWS__", html.escape(window_text))
    document = document.replace("__VERIFICATION__", html.escape(verification["verification_status"]))
    (root / "report/RESULTS.html").write_text(document, encoding="utf-8")


def write_plots(coverage, root=ROOT, windows=None):
    """Export all-results scientific PNG/SVG; no model or exposure selection."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    output = root / "report/figures"
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    scopes = {2025: "Upstream available pool; previously exposed, nonblind",
              2026: "Retrospective qualified subset; previously exposed, nonblind"}
    colors = {"mv": "#2667a5", "robust": "#cf6433", "cvar": "#29805c"}
    def save(fig, name):
        for extension in ["png", "svg"]:
            path = output / (name + "." + extension)
            fig.savefig(path, dpi=145, bbox_inches="tight")
            paths.append(path)
        plt.close(fig)
    for year in YEARS:
        date_window = windows[str(year)] if windows and str(year) in windows else None
        period_label = f"\nNAV window: {date_window['nav_first']} to {date_window['nav_last']}" if date_window else ""
        rows = coverage.loc[coverage.year.eq(year)]
        usable = rows.status.eq("REPLAY_COMPLETE") & np.isfinite(rows.net_return) & np.isfinite(rows.max_drawdown) & np.isfinite(rows.mean_gross_exposure)
        figure, ax = plt.subplots(figsize=(11, 7))
        plotted = rows.loc[usable]
        dots = ax.scatter(-100 * plotted.max_drawdown, 100 * plotted.net_return, c=plotted.mean_gross_exposure,
                          cmap="viridis", s=13, alpha=.6, linewidths=0, rasterized=True)
        figure.colorbar(dots, ax=ax, label="Mean actual gross exposure")
        ax.axhline(0, color="#777", linewidth=.8)
        ax.set(xlabel="Maximum drawdown magnitude (%)", ylabel="Net price-index return (%)",
               title=f"{year}: all fixed PTO routes\n{scopes[year]}{period_label}")
        ax.text(.01, -.18, f"Plotted {len(plotted)} / {len(rows)} routes. Failed/unavailable coordinates: {len(rows)-len(plotted)}.\n"
                "Shared dates and forecasts; routes are not independent samples. No deployment selection.", transform=ax.transAxes, fontsize=9)
        ax.grid(alpha=.18)
        save(figure, f"all_results_return_drawdown_{year}")
        paired = _csv(root / f"report/optimization_vs_fixed_gross_{year}.csv")
        valid = np.isfinite(paired.delta_mean_gross_exposure) & np.isfinite(paired.delta_net_return)
        figure, ax = plt.subplots(figsize=(11, 7))
        for method in OPTIMIZERS:
            cells = paired.loc[valid & paired.optimizer.eq(method)]
            ax.scatter(100 * cells.delta_mean_gross_exposure, 100 * cells.delta_net_return,
                       color=colors[method], label=method, s=13, alpha=.45, linewidths=0, rasterized=True)
        ax.axhline(0, color="#777", linewidth=.8)
        ax.axvline(0, color="#777", linewidth=.8)
        ax.legend(title="Optimizer")
        ax.set(xlabel="Change in mean actual gross (percentage points)", ylabel="Change in net price-index return (percentage points)",
               title=f"{year}: optimization vs same-forecast equal budget rule\n{scopes[year]}{period_label}")
        ax.text(.01, -.18, f"Plotted {int(valid.sum())} / {len(paired)} available pairs; equal rule uses risk none and <=0.95 budget.\n"
                "Realized gross is not constant; no pure exposure causal effect or rescaled replay.", transform=ax.transAxes, fontsize=9)
        ax.grid(alpha=.18)
        save(figure, f"paired_return_gross_delta_{year}")
        interaction_path = root / f"report/factor_interactions_{year}_net_return.csv"
        if not interaction_path.exists():
            continue
        frame = _csv(interaction_path)
        _need(len(frame) == 4560 and not frame.duplicated(["forecast_id", "risk", "optimizer"]).any(), "INTERACTION_HEATMAP_GRID_INCOMPLETE")
        order = [item["forecast_id"] for item in forecasts()]
        columns = [(risk, method) for risk in RISKS for method in OPTIMIZERS]
        matrix = frame.pivot(index="forecast_id", columns=["risk", "optimizer"], values="three_way_interaction").reindex(index=order, columns=pd.MultiIndex.from_tuples(columns))
        _need(np.isfinite(matrix.to_numpy()).all(), "INTERACTION_HEATMAP_NONFINITE")
        values = 100 * matrix.to_numpy(float)
        bound = max(float(np.abs(values).max()), 1e-12)
        figure, axes = plt.subplots(2, 1, figsize=(15, 27), gridspec_kw={"height_ratios": [31, 121]}, constrained_layout=True)
        image = None
        for ax, low, high, label in [(axes[0], 0, 31, "31 single predictors"), (axes[1], 31, 152, "11 fixed coalitions x 11 mu fusion methods")]:
            image = ax.imshow(values[low:high], aspect="auto", interpolation="nearest", cmap="RdBu_r", vmin=-bound, vmax=bound)
            ax.set_yticks(np.arange(high-low), order[low:high], fontsize=6)
            ax.set_xticks(np.arange(30), [r + " | " + o for r, o in columns], rotation=70, ha="right", fontsize=7)
            ax.set_title(label)
        figure.colorbar(image, ax=axes, shrink=.45, label="Three-way descriptive return interaction (percentage points)")
        figure.suptitle(f"{year}: forecast x risk x optimizer, complete fixed grid\n{scopes[year]}{period_label}\n"
                       "All cells, registered order. Algebraic decomposition; shared paths are not independent N.", fontsize=12)
        save(figure, f"forecast_risk_optimizer_interaction_{year}")
    return paths


def run(*, workers=2):
    start = time.monotonic()
    freeze, contract, roster, tables, controls = gate_inputs()
    report = ROOT / "report"
    report.mkdir(exist_ok=True)
    sources = [ROOT / "contract.json", ROOT / "DESIGN_LOCK.json", ROOT / "GLOBAL_FREEZE.json", ROOT / "INPUT_AUDIT.json", ROOT / "EXPOSURE_HISTORY.json", Path(__file__), ROOT / "comparison_analysis.py", ROOT / "test_comparison_analysis.py", ROOT / "forecast_metrics.py",
               ROOT / "diagnostics/statistics_2025_preflight/PREFLIGHT_RECEIPT_FAILED_LEFT_RIGHT_ARGUMENTS.json",
               ROOT / "diagnostics/statistics_2025_preflight/PREFLIGHT_RECEIPT.json",
               ROOT / "diagnostics/FINAL_SOURCE_PRESERVATION_RECHECK.json", ROOT / "diagnostics/SOURCE_PRESERVATION_RECHECK.json",
               ROOT / "PAUSE_FILE_SNAPSHOT.json", ROOT / "rl_artifacts/DATA_RESUME_VERIFICATION.json"]
    sources += [p for p in [ROOT / "diagnostics/NATIVE_COMPLETED_COVERAGE.csv", report / "ANALYSIS_METHOD.json",
                           ROOT / "diagnostics/HELD_ONLY_INPUT_KEY_RECONCILIATION.json",
                           ROOT / "diagnostics/CONTROLS_2026_VERIFICATION.json",
                           ROOT / "diagnostics/COMPARISON_FINDINGS.md", ROOT / "diagnostics/COMPARISON_FINDINGS.json"] if p.exists()]
    sources += [ROOT / "run_all_outputs_target_helper_2026.py"] + sorted((ROOT / "diagnostics").glob("TARGET_ALL_OUTPUTS_HELPER_2026*.json"))
    sources += list(report.glob("*.csv")) + list(report.glob("daily_log_returns_*.parquet"))
    # Delivery outputs are regenerated, never treated as upstream analysis.
    sources = [p for p in sources if p.name not in ["COMBINATION_COVERAGE_FINAL.csv", "FAILURE_AND_INCOMPATIBILITY.csv"]]
    source_hashes = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    control_document_provenance = verify_control_document_bindings(controls, freeze)
    input_audit, exposure = read(ROOT / "INPUT_AUDIT.json"), read(ROOT / "EXPOSURE_HISTORY.json")
    held_only_input_reconciliation = verify_held_only_counts(input_audit)
    statistics_report_history, statistics_issues = report_statistics_history()
    parallel_helper_orchestration, helper_issues = helper_orchestration_provenance(freeze)
    source_preservation = source_preservation_provenance()
    forecast_info = {year: forecast_provenance(year, freeze) for year in YEARS}
    blocked = forecast_info[2026]["buy_blocked_keys"]
    _need(len(blocked) == held_only_input_reconciliation["input_held_only_rows"], "2026_BUY_BLOCKED_INPUT_KEYS_NOT_HELD_CONTEXT_COUNT")
    blocked_by_ticker = pd.Series([ticker for _, ticker in blocked]).value_counts().to_dict()
    _need(blocked_by_ticker == {row["ticker"]: row["rows"] for row in held_only_input_reconciliation["held_only_by_ticker"]}, "2026_BUY_BLOCKED_TICKER_COUNTS_NOT_HELD_CONTEXT")
    training, training_issues = collect_training()
    audited = audit_all(tables, controls, roster, forecast_info, freeze, workers=workers)
    coverage = build_coverage(roster, tables, audited)
    coverage["execution_orchestration"] = "original_main_grid"
    coverage["separate_caller_sha256"] = None
    helped = coverage.year.eq(2026) & coverage.strategy_id.isin(parallel_helper_orchestration["strategy_ids"])
    coverage.loc[helped, "execution_orchestration"] = "original_31spec_public_chunk_helper_then_main_resume"
    coverage.loc[helped, "separate_caller_sha256"] = parallel_helper_orchestration["caller_sha256"]
    failures = collect_failures(coverage, controls, audited, training_issues, forecast_info, input_audit, contract, statistics_issues, helper_issues)
    coverage.to_csv(report / "COMBINATION_COVERAGE_FINAL.csv", index=False)
    failures.to_csv(report / "FAILURE_AND_INCOMPATIBILITY.csv", index=False)
    error_columns = [c for c in audited if c.endswith("max_error") and not c.startswith("scenario_")]
    successful = audited.loc[audited.status.eq("PASS")]
    verification = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        diagnostic_execution="COMPLETE" if coverage.status.eq("REPLAY_COMPLETE").all() else "COMPLETE_WITH_FAILURES",
        verification_status="PASS" if not audited.status.eq("AUDIT_FAILED").any() else "FAILED_INDEPENDENT_AUDIT",
        formal_full_pool="BLOCKED", formal_full_pool_2026=input_audit["evaluation_2026"]["full_original_pool_test_status"],
        blind_test=False, shareholder_total_return_certified=False, previous_2026_exposure_retained=exposure,
        expected_pto_routes_per_window=5053, expected_pto_path_windows=10106, delivered_pto_path_windows=len(coverage),
        forecasts=152, target_blend_coalitions=11, independent_decision_control_path_windows=10,
        root_contract_sha256=sha(ROOT / "contract.json"), global_freeze_sha256=sha(ROOT / "GLOBAL_FREEZE.json"),
        ledger_files_verified=int(successful.ledger_files.sum()) if "ledger_files" in successful else 0,
        prediction_links_verified=int(successful.prediction_links_verified.sum()) if "prediction_links_verified" in successful else 0,
        account_max_errors={c: float(successful[c].max()) for c in error_columns},
        risk_copula_summary={str(year): dict(
            recorded_scenario_path_days=int(coverage.loc[coverage.year.eq(year), "scenario_metadata_path_days"].fillna(0).sum()),
            rank_deficient_path_days=int(coverage.loc[coverage.year.eq(year), "scenario_rank_deficient_path_days"].fillna(0).sum()),
            unknown_support_occurrences=int(coverage.loc[coverage.year.eq(year), "scenario_unknown_support_occurrences"].fillna(0).sum()),
            max_pre_subsample_correlation_error=float(coverage.loc[coverage.year.eq(year), "scenario_correlation_max_error"].max()),
            scope="prediction-route saved metadata only; shared path-days/support occurrences are not independent observations") for year in YEARS},
        independent_audit_status_counts=audited.status.value_counts().to_dict(),
        actual_training=training, forecast_diagnostic_statuses={str(y): forecast_info[y]["receipt"]["status"] for y in YEARS},
        source_sha256=source_hashes, existing_validation_evidence={str(p.relative_to(ROOT)): sha(p) for p in [
            ROOT / "POOL_POLICY_CLARIFICATION.json", ROOT / "REPLAY_INTEGRATION_VERIFICATION.json",
            ROOT / "INDEPENDENT_IMPLEMENTATION_AUDIT.json", ROOT / "risk_artifacts/IMPLEMENTATION_VERIFICATION.json",
            ROOT / "models/NATIVE_TEST_RECEIPT.json", ROOT / "rl_artifacts/VERIFICATION.json",
            ROOT / "diagnostics/CONTROLS_2026_VERIFICATION.json", ROOT / "diagnostics/READONLY_STATISTICS_SYNTHETIC_RECEIPT.json",
            ROOT / "diagnostics/READONLY_STATISTICAL_REVIEW.md"] if p.exists()},
        document_provenance=control_document_provenance, held_only_input_reconciliation=held_only_input_reconciliation,
        statistics_report_history=statistics_report_history,
        parallel_helper_orchestration=parallel_helper_orchestration,
        source_preservation=source_preservation,
        actual_buy_eligibility={str(year): dict(
            audited_successful_accounts=int(successful.year.eq(year).sum()),
            actual_buy_rows_checked=int(successful.loc[successful.year.eq(year), "actual_buy_rows_checked"].sum()),
            ineligible_actual_buy_rows=int(successful.loc[successful.year.eq(year), "ineligible_actual_buy_rows"].sum()),
            buy_blocked_context_buy_rows=int(successful.loc[successful.year.eq(year), "buy_blocked_context_buy_rows"].sum()),
            buy_blocked_input_keys=len(forecast_info[year]["buy_blocked_keys"]), buy_gate_source=forecast_info[year]["buy_gate_source"],
            scope="all successful DONE paths and controls; repeated path fills are not independent samples") for year in YEARS},
        verification_scope="all DONE ledger hashes; independent cash/units/position/NAV/cost algebra and next-calendar clocks; input quote provenance covered by frozen source and prior engine tests",
        fitting_performed=False, model_selection_performed=False, candidates_expanded=False,
        matched_cells_independent_samples=False, hac_lag=5, hac_lag_basis="retained common valid return dates; internal missing dates can span more original sessions",
        fixed_gross_is_realized_constant=False, pure_exposure_causal_effect_identified=False,
        pure_target_fusion_order_causal_effect_identified=False, multiple_testing_correction=False,
        provenance_2025="DESIGN_LOCK precedes evaluation; pre-global outcomes retained; predictions and models match later complete freeze; early pilots exact-ledger audit retained",
        provenance_2026="exact GLOBAL_FREEZE before features/predictions/replay; every successful DONE must bind same freeze",
        elapsed_seconds=time.monotonic() - start, path_audits=clean(audited.replace({np.nan: None}).to_dict("records")))
    verification["evaluation_windows"] = evaluation_window_metadata()
    verification["descriptive_complete_route_extrema"] = descriptive_route_extrema(coverage)
    plot_paths = write_plots(coverage, windows=verification["evaluation_windows"])
    verification["scientific_plot_sha256"] = {str(path.relative_to(ROOT)): sha(path) for path in plot_paths}
    write_markdown(coverage, controls, training, failures, verification, forecast_info, input_audit, exposure)
    write_html(coverage, controls, verification)
    for relative, digest in source_hashes.items():
        _need(sha(ROOT / relative) == digest, "SOURCE_CHANGED_DURING_DELIVERY:" + relative)
    verification["output_sha256"] = {p.name: sha(p) for p in [report / "EXPERIMENT_REPORT.md", report / "RESULTS.html",
        report / "COMBINATION_COVERAGE_FINAL.csv", report / "FAILURE_AND_INCOMPATIBILITY.csv"]}
    write(report / "FINAL_VERIFICATION.json", verification)
    print(json.dumps(dict(event="DELIVERY_COMPLETE", status=verification["verification_status"],
        diagnostic_execution=verification["diagnostic_execution"], formal_full_pool="BLOCKED", rows=len(coverage),
        elapsed_seconds=time.monotonic() - start)), flush=True)
    return verification


def self_test():
    """Pure synthetic checks for failure retention and unsafe HTML injection."""
    example = pd.DataFrame([dict(strategy_id="a", forecast_id="a", coalition="single", fusion="identity", risk="diag", optimizer="mv", route="prediction_fusion", target_fusion="none", members=["x"])])
    tables = {year: pd.DataFrame([dict(strategy_id="a", year=year, status="REPLAY_COMPLETE" if year == 2025 else "FAILED", net_return=-.1 if year == 2025 else np.nan)]) for year in YEARS}
    audited = pd.DataFrame([dict(year=year, strategy_id="a", control=False, status="PASS" if year == 2025 else "NOT_AUDITED_FAILED_REPLAY") for year in YEARS])
    covered = build_coverage(example, tables, audited)
    assert len(covered) == 2 and covered.loc[0, "return_sign"] == "NEGATIVE" and covered.loc[1, "return_sign"] == "FAILED"
    assert covered.formal_full_pool.eq("BLOCKED").all() and not covered.blind_test.any()
    assert _max_error([1, 2], [1, 2]) == 0.
    try:
        _max_error([np.nan], [1])
    except ValueError:
        pass
    else:
        raise AssertionError("nonfinite mismatch not rejected")
    with tempfile.TemporaryDirectory(prefix="pto_delivery_synthetic_") as directory:
        root = Path(directory)
        (root / "report").mkdir()
        frame = covered.copy()
        frame.loc[0, "strategy_id"] = "</script><img src=x onerror=alert(1)>"
        controls = {year: pd.DataFrame([dict(year=year, strategy_id="cash", status="REPLAY_COMPLETE", net_return=0.)]) for year in YEARS}
        write_html(frame, controls, dict(diagnostic_execution="COMPLETE_WITH_FAILURES", verification_status="PASS"), root=root)
        content = (root / "report/RESULTS.html").read_text(encoding="utf-8")
        assert "</script><img" not in content and "\\u003c/script" in content
        assert 'return_sign' in content and 'forecast_id' in content and 'FAILED' in content
        write(root / "INPUT_AUDIT.json", dict(synthetic_document=True))
        document_controls = {year: pd.DataFrame([dict(strategy_id="cash", status="REPLAY_COMPLETE")]) for year in YEARS}
        for year in YEARS:
            write(root / f"evaluation_controls_{year}/cash/FROZEN_BEFORE_REPLAY.json",
                  dict(source_sha256={str(root / "INPUT_AUDIT.json"): sha(root / "INPUT_AUDIT.json")}))
        provenance = verify_control_document_bindings(document_controls, dict(artifact_sha256={}), root=root)
        assert not provenance["directly_bound_by_global"] and provenance["successful_control_source_matches"] == 2
        write(root / "INPUT_AUDIT.json", dict(synthetic_document="modified"))
        try:
            verify_control_document_bindings(document_controls, dict(artifact_sha256={}), root=root)
        except ValueError as exc:
            assert "CONTROL_INPUT_AUDIT_DOCUMENT_SHA_MISMATCH" in str(exc)
        else:
            raise AssertionError("modified control provenance document accepted")
        pairs = pd.DataFrame([dict(left="synthetic_fusion", delta_net_return=.1, expected_cells=30, matched_cells=30,
                                  left_only_success_cells=0, right_only_success_cells=0, both_missing_cells=0),
                              dict(left="synthetic_fusion", delta_net_return=np.nan, expected_cells=30, matched_cells=0,
                                  left_only_success_cells=0, right_only_success_cells=0, both_missing_cells=30)])
        pair_summary = fusion_comparison_summary(pairs).iloc[0]
        assert pair_summary.delta_net_return == .1 and pair_summary.expected_cells_sum == 60
        assert pair_summary.matched_cells_sum == 30 and pair_summary.both_missing_cells_sum == 30 and pair_summary.zero_match_coalitions == 1
        zero_summary = fusion_comparison_summary(pairs.iloc[1:]).iloc[0]
        assert pd.isna(zero_summary.delta_net_return) and zero_summary.matched_cells_sum == 0
        input_counts = dict(evaluation_2026=dict(original_candidate_rows=5, candidate_rows=4,
                                                unknown_candidate_rows=1, proven_ineligible_rows=1))
        held_counts = dict(original_candidate_gate_rows=5, gate_category_counts=dict(QUALIFIED=3, UNKNOWN=1, PROVEN_INELIGIBLE=1),
            replay_input_rows=4, input_current_pool_qualified_new_buy_rows=3, input_held_only_rows=1,
            held_only_keys_in_gate=0, held_only_unknown_overlap=0, held_only_proven_ineligible_overlap=0, held_only_qualified_overlap=0,
            held_only_by_ticker=[dict(ticker="SYNTHETIC", rows=1, new_buy_eligible=False, all_keys_outside_original_candidate_gate=True)])
        write(root / "diagnostics/HELD_ONLY_INPUT_KEY_RECONCILIATION.json", held_counts)
        counts_receipt = verify_held_only_counts(input_counts, root=root)
        assert counts_receipt["independently_rechecked_count_identities"] and "6 是 gate∪input" in held_only_count_explanation(counts_receipt, input_counts)
        held_counts["held_only_unknown_overlap"] = 1
        write(root / "diagnostics/HELD_ONLY_INPUT_KEY_RECONCILIATION.json", held_counts)
        try:
            verify_held_only_counts(input_counts, root=root)
        except ValueError as exc:
            assert "HELD_ONLY_GATE_CATEGORY_OVERLAP" in str(exc)
        else:
            raise AssertionError("held-only context folded into UNKNOWN")
        write(root / "diagnostics/CONTROLS_2026_VERIFICATION.json", dict(account_audits=[dict(control="synthetic", bad_mark_tickers=[
            dict(ticker="AAA", bad_mark_rows=2, reasons=dict(PRICE_QUALITY_UNCERTIFIED=2)),
            dict(ticker="BBB", bad_mark_rows=1, reasons=dict(MISSING_PRICE_ROW=1))])]))
        notes = "\n".join(control_valuation_notes(root=root))
        assert "AAA" in notes and "BBB" in notes and "PRICE_QUALITY_UNCERTIFIED" in notes and "MISSING_PRICE_ROW" in notes
        write(root / "GLOBAL_FREEZE.json", dict(synthetic_freeze=True))
        (root / "comparison_analysis.py").write_text("synthetic_source = True\n", encoding="utf-8")
        (root / "test_comparison_analysis.py").write_text("synthetic_tests = True\n", encoding="utf-8")
        statistics_directory = root / "diagnostics/statistics_2025_preflight"
        failed_statistics_path = statistics_directory / "PREFLIGHT_RECEIPT_FAILED_LEFT_RIGHT_ARGUMENTS.json"
        statistics_common = dict(fit_calls=0, frozen_artifacts_modified=False, unfinished_2026_account_reads=0,
                                 global_freeze_sha256=sha(root / "GLOBAL_FREEZE.json"))
        write(failed_statistics_path, dict(statistics_common, status="FAIL_2025_REAL_STATISTICAL_INTEGRATION",
                                           error="comparison() got multiple values for argument 'left'"))
        forecast_count = len(forecasts())
        passed_statistics = dict(statistics_common, status="PASS_2025_REAL_STATISTICAL_INTEGRATION",
            prior_failed_preflight=dict(path=str(failed_statistics_path.relative_to(root)), sha256=sha(failed_statistics_path),
                                         statistics_fix="DataFrame parameters renamed left_frame/right_frame"),
            source_sha256={"comparison_analysis.py": sha(root / "comparison_analysis.py")},
            daily_returns=dict(calendar_rows=250, whole_roster_common_valid_days=249, internal_nonfinite_returns=0),
            matched_comparisons=dict(rows=634), conditional_fusion_comparisons=dict(rows=1100),
            factor_decompositions={metric: dict(rows=forecast_count * len(RISKS) * len(OPTIMIZERS))
                                   for metric in ["net_return", "max_drawdown", "mean_gross_exposure", "mean_daily_log_return"]},
            optimization_vs_budget_control=dict(prediction_route_rows=forecast_count * len(RISKS) * len(OPTIMIZERS),
                target_route_rows=len(COALITIONS) * len(RISKS) * len(OPTIMIZERS),
                rows=(forecast_count + len(COALITIONS)) * len(RISKS) * len(OPTIMIZERS),
                distinct_budget_controls=forecast_count + len(COALITIONS)))
        write(statistics_directory / "PREFLIGHT_RECEIPT.json", passed_statistics)
        statistics_summary, statistics_issues = report_statistics_history(root=root)
        assert statistics_summary["optimization_vs_budget_control"]["rows"] == 4890
        assert statistics_issues[0]["category"] == "REPORT_STATISTICS_INITIAL_INTEGRATION_FAILURE"
        assert statistics_issues[0]["resolved"] and not statistics_issues[0]["strategy_route_failure"]
        (root / "comparison_analysis.py").write_text("synthetic_source = 'changed'\n", encoding="utf-8")
        try:
            report_statistics_history(root=root)
        except ValueError as exc:
            assert "STATISTICS_PREFLIGHT_SOURCE_CHANGED" in str(exc)
        else:
            raise AssertionError("statistics preflight source drift accepted")
        helper_specs = [item for item in strategies() if item["route"] == "target_fusion" and item["coalition"] == "all_outputs"]
        caller = root / "run_all_outputs_target_helper_2026.py"
        caller.write_text("synthetic_helper_source = True\n", encoding="utf-8")
        core = root / "synthetic_frozen_core.py"
        core.write_text("synthetic_core = True\n", encoding="utf-8")
        helper_freeze = dict(artifact_sha256={"synthetic_frozen_core.py": sha(core)})
        helper_forecasts = {}
        for member in helper_specs[0]["members"]:
            forecast = root / ("predictions/forecasts/2026/single__" + member + ".parquet")
            forecast.parent.mkdir(parents=True, exist_ok=True)
            forecast.write_bytes(b"synthetic forecast artifact; never parsed")
            helper_forecasts[str(forecast.relative_to(root))] = sha(forecast)
        outputs = {}
        for item in helper_specs:
            output = root / "evaluation_2026" / item["strategy_id"] / "DONE.json"
            write(output, dict(synthetic_helper_leaf=True))
            outputs[item["strategy_id"]] = sha(output)
        helper_receipt = dict(status="FINISHED_ORIGINAL_PUBLIC_CHUNK", expected=31, year=2026, route="target_fusion", coalition="all_outputs",
            strategy_ids=[item["strategy_id"] for item in helper_specs], helper_source=caller.name, helper_source_sha256=sha(caller),
            global_freeze_sha256=sha(root / "GLOBAL_FREEZE.json"), original_frozen_sha256=helper_freeze["artifact_sha256"],
            all_frozen_sha256_unchanged=True, global_comparison_or_complete_writes=False, fitting_allowed=False, guard_fit_attempts=0, resume=True,
            installed_fit_guards={name: True for name in ["native", "pipeline", "scaler", "adam", "sgd", "hgbvol", "mlpvol"]},
            completed=31, failed=0, output_receipts=outputs, all_completed_leaf_ledgers_hash_verified=True,
            all_forecast_sha256_unchanged=True, forecast_sha256=helper_forecasts, failures=[], monitor_errors=[], alerts=[])
        helper_receipt_path = root / "diagnostics/TARGET_ALL_OUTPUTS_HELPER_2026_RECEIPT.json"
        helper_progress_path = root / "diagnostics/TARGET_ALL_OUTPUTS_HELPER_2026_PROGRESS.json"
        write(helper_receipt_path, helper_receipt)
        write(helper_progress_path, helper_receipt)
        helper_summary, helper_issues = helper_orchestration_provenance(helper_freeze, root=root)
        assert helper_summary["output_receipts_verified"] == 31 and not helper_summary["directly_bound_by_global"]
        assert helper_summary["main_full_grid_required_per_window"] == 5053 and not helper_issues
        invalid_helper = dict(helper_receipt, strategy_ids=helper_receipt["strategy_ids"][:-1])
        write(helper_receipt_path, invalid_helper)
        try:
            helper_orchestration_provenance(helper_freeze, root=root)
        except ValueError as exc:
            assert "PARALLEL_HELPER_NOT_EXACT_ORIGINAL_31_SPECS" in str(exc)
        else:
            raise AssertionError("helper 30-leaf subset accepted as original 31")
        invalid_helper = dict(helper_receipt, global_comparison_or_complete_writes=True)
        write(helper_receipt_path, invalid_helper)
        try:
            helper_orchestration_provenance(helper_freeze, root=root)
        except ValueError as exc:
            assert "PARALLEL_HELPER_FIT_OR_GLOBAL_SUMMARY_SCOPE_DRIFT" in str(exc)
        else:
            raise AssertionError("helper allowed to write global comparison")
        folder = root / "synthetic_account"
        folder.mkdir()
        dates = pd.DatetimeIndex(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"])
        signal, execution = dates[:-1], dates[1:]
        trade = pd.DataFrame(dict(signal_date=signal, execution_date=execution, ticker=["AAA"] * 3,
            side=["BUY", "SELL", "SELL"], index_units=[100., 40., 60.], price=[10., 12., 11.],
            notional=[1000., 480., 660.], transaction_cost=[1., .48, .66], cost_bps=[10] * 3,
            index_units_before=[0., 100., 60.], index_units_after=[100., 60., 0.],
            capacity_adv=[100000.] * 3, capacity_adv_source_date=signal,
            order_id=["synthetic|" + str(d.date()) + "|AAA" for d in signal]))
        cash = np.array([1000000., 998999., 999478.52, 1000137.86])
        mv = np.array([0., 1100., 690., 0.])
        nav = cash + mv
        daily = pd.DataFrame(dict(date=dates, cash=cash, nav=nav, certified_nav=nav,
            actual_name_count=[0, 1, 1, 0], transaction_cost_amount=[0., 1., .48, .66],
            buy_notional=[0., 1000., 0., 0.], sell_notional=[0., 0., 480., 660.],
            gross_exposure=mv / nav, unknown_count=[0] * 4, stale_count=[0] * 4))
        for col in IDENTITY_COLUMNS:
            daily[col] = 0.
        position = pd.DataFrame(dict(date=dates[1:3], ticker=["AAA"] * 2, index_units=[100., 60.],
                                     mark=[11., 11.5], market_value=[1100., 690.]))
        target = pd.DataFrame(dict(order_id=trade.order_id, signal_date=signal, ticker=["AAA"] * 3,
            raw_model_weight=[.001, .0005, 0.], adapted_target_weight=[.001, .0005, 0.],
            current_units=[0., 100., 60.], reserved_weight=[0.] * 3, active_target_sum=[.001, .0005, 0.]))
        link = target[["order_id", "signal_date", "ticker", "adapted_target_weight"]].copy()
        link["model_input_row_present"] = True
        link["forecast_ids_json"] = json.dumps(["single__synthetic"])
        link["prediction_key_suffix"] = [str(d.date()) + "|AAA" for d in signal]
        link["prediction_id"] = "single__synthetic|" + link.prediction_key_suffix
        tables = {name: pd.DataFrame() for name in LEDGERS}
        tables.update(daily=daily, trades=trade, positions=position, target_decisions=target,
                      execution_results=trade[["order_id"]], prediction_order_links=link,
                      optimization_diagnostics=pd.DataFrame(dict(iterations=[80] * 3, status=["approx_converged"] * 3,
                          optimality_gap_bound=[0.] * 3, gradient_mapping_inf=[0.] * 3)))
        for name, table in tables.items():
            table.to_parquet(folder / (name + ".parquet"), index=False)
        done = dict(strategy_id="synthetic", year=2025, status="REPLAY_COMPLETE", model_batch_freeze_sha256=None,
                    ledger_sha256={p.name: sha(p) for p in folder.glob("*.parquet")}, total_fees=2.14,
                    terminal_nav=nav[-1], mean_gross_exposure=float((mv / nav).mean()), trades=3, guard_fit_attempts=0)
        write(folder / "DONE.json", done)
        spec = dict(strategy_id="synthetic", route="prediction_fusion", forecast_id="single__synthetic", members=["synthetic"])
        keys = {(str(d.date()), "AAA") for d in signal}
        eligible_keys = {(str(signal[0].date()), "AAA")}
        result = audit_account(folder, done, year=2025, spec=spec, freeze_sha="synthetic_freeze", calendar=dates,
                               pool_keys=keys, buy_eligible_keys=eligible_keys, forecast_status={"single__synthetic": "PASS"})
        assert result["status"] == "PASS" and result["prediction_links_verified"] == 3 and result["cash_recursive_max_error"] < 1e-8
        assert result["actual_buy_rows_checked"] == 1 and result["buy_blocked_context_buy_rows"] == 0 and result["buy_blocked_input_keys"] == 2
        try:
            audit_account(folder, done, year=2025, spec=spec, freeze_sha="synthetic_freeze", calendar=dates,
                          pool_keys=keys, buy_eligible_keys=set(), forecast_status={"single__synthetic": "PASS"})
        except ValueError as exc:
            assert "ACTUAL_BUY_OUTSIDE_SIGNAL_NEW_BUY_ELIGIBILITY" in str(exc)
        else:
            raise AssertionError("ineligible signal key actual BUY accepted")
        try:
            audit_account(folder, done, year=2026, spec=spec, freeze_sha="synthetic_freeze", calendar=dates,
                          pool_keys=keys, buy_eligible_keys=eligible_keys, forecast_status={"single__synthetic": "PASS"})
        except ValueError as exc:
            assert "EXACT_GLOBAL_FREEZE" in str(exc)
        else:
            raise AssertionError("2026 missing exact freeze was accepted")
        cash_folder = root / "synthetic_cash"
        cash_folder.mkdir()
        cash_daily = daily.copy()
        cash_daily[["cash", "nav", "certified_nav"]] = 1_000_000.
        cash_daily[["actual_name_count", "transaction_cost_amount", "buy_notional", "sell_notional", "gross_exposure"]] = 0
        for name in LEDGERS:
            table = cash_daily if name == "daily" else tables[name].iloc[:0].copy()
            table.to_parquet(cash_folder / (name + ".parquet"), index=False)
        write(cash_folder / "FROZEN_BEFORE_REPLAY.json", dict(source_sha256={}))
        cash_done = dict(strategy_id="cash", year=2025, status="REPLAY_COMPLETE", total_fees=0., terminal_nav=1_000_000.,
            mean_gross_exposure=0., trades=0, guard_fit_attempts=0, ledger_sha256={p.name: sha(p) for p in cash_folder.glob("*.parquet")})
        write(cash_folder / "DONE.json", cash_done)
        cash_audit = audit_account(cash_folder, cash_done, year=2025, spec=dict(strategy_id="cash"), freeze_sha="synthetic_freeze",
            calendar=dates, pool_keys=keys, buy_eligible_keys=set(), forecast_status={}, control=True)
        assert cash_audit["status"] == "PASS" and cash_audit["actual_buy_rows_checked"] == 0 and cash_audit["cash_recursive_max_error"] == 0
        broken = trade.copy()
        broken.loc[0, "transaction_cost"] = 1.1
        broken.to_parquet(folder / "trades.parquet", index=False)
        done["ledger_sha256"]["trades.parquet"] = sha(folder / "trades.parquet")
        try:
            audit_account(folder, done, year=2025, spec=spec, freeze_sha="synthetic_freeze", calendar=dates,
                          pool_keys=keys, buy_eligible_keys=eligible_keys, forecast_status={"single__synthetic": "PASS"})
        except ValueError as exc:
            assert "TRADE_FEE" in str(exc)
        else:
            raise AssertionError("fee identity error was accepted")
    print(json.dumps(dict(status="PASS_SYNTHETIC_ONLY", real_evaluation_inputs_read=0, real_evaluation_outcomes_read=0,
                          checks=["negative_and_failed_rows_retained", "formal_vs_diagnostic_scope", "nonfinite_identity_rejected", "html_json_injection_escaped",
                                  "document_control_binding_distinguished_from_direct_global_binding", "zero_match_pair_coverage_retained_without_zero_returns",
                                  "held_context_outside_original_gate_counts_and_category_guard", "all_control_bad_mark_reasons_retained",
                                  "ineligible_actual_buy_rejected_while_ineligible_sell_allowed",
                                  "empty_cash_account_and_zero_actual_buys",
                                  "resolved_statistics_failure_preserved_separately_from_strategy_failure", "statistics_preflight_current_source_and_4890_pair_count_guard",
                                  "parallel_helper_separate_caller_31_frozen_specs_and_receipts", "parallel_helper_subset_and_global_summary_scope_drift_rejected",
                                  "independent_cash_units_nav_and_prediction_order_links", "2026_exact_freeze_required", "tampered_realized_fee_rejected"])))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="requires frozen artifacts and both complete 5,053-route windows")
    parser.add_argument("--self-test", action="store_true", help="synthetic only; no real evaluation reads")
    parser.add_argument("--workers", type=int, default=2, help="bounded ledger audit IO workers, maximum 4")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.run:
        run(workers=args.workers)
    else:
        print("READY: no real results read. Run --self-test now, or --run only after frozen full-window completion.")


if __name__ == "__main__":
    main()
