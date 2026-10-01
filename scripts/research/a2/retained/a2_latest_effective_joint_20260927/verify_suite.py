"""Independent latest-effective-pool, training-boundary and ledger audit.

This module never fits a model, selects a winner or rewrites an evaluation.
It writes only VERIFICATION.json. Missing receipts remain PENDING.
"""
from pathlib import Path
import ast
import hashlib
import json
import traceback

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
EPS = 1e-5
CUTOFF = pd.Timestamp("2026-01-01")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(value, message):
    if not bool(value):
        raise AssertionError(message)


def maxerr(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    require(a.shape == b.shape, "shape mismatch")
    require(not np.isinf(a).any() and not np.isinf(b).any(), "infinite ledger value")
    require(np.array_equal(np.isnan(a), np.isnan(b)), "NaN mismatch")
    good = np.isfinite(a) & np.isfinite(b)
    return float(np.max(np.abs(a[good] - b[good]))) if good.any() else 0.


def latest_effective_eligibility(panel, timing, quarter_column):
    """Independently rederive a row's quarter eligibility using an as-of join.

    The caller supplies reference membership rows in panel. No calendar-quarter
    arithmetic decides eligibility. A quarter remains active until the next
    already-public quarter reaches its effective session. A date-only filing
    timestamp is treated conservatively as requiring a later signal day.
    """
    required = {"quarter", "quarter_effective_date", "latest_filing_date"}
    require(required.issubset(timing), "timing reference columns missing")
    q = timing[list(required)].copy()
    q["quarter"] = q.quarter.astype(str)
    q["quarter_effective_date"] = pd.to_datetime(q.quarter_effective_date)
    q["latest_filing_date"] = pd.to_datetime(q.latest_filing_date)
    require(not q.quarter.duplicated().any(), "duplicate quarter in timing reference")
    require(not q.quarter_effective_date.duplicated().any(), "ambiguous simultaneous effective quarters")
    require(q.quarter_effective_date.notna().all() and q.latest_filing_date.notna().all(), "missing quarter timing")
    require(q.quarter_effective_date.gt(q.latest_filing_date).all(), "effective quarter predates public filing clock")
    q = q.sort_values("quarter_effective_date").rename(columns={
        "quarter": "expected_active_quarter", "quarter_effective_date": "expected_effective_date",
        "latest_filing_date": "expected_latest_filing_date",
    })
    dates = pd.DataFrame({"signal_date": pd.to_datetime(panel.signal_date).drop_duplicates().sort_values()})
    active = pd.merge_asof(dates, q, left_on="signal_date", right_on="expected_effective_date", direction="backward")
    rows = panel[["signal_date", quarter_column]].copy()
    rows["_row"] = np.arange(len(rows))
    rows = rows.merge(active, on="signal_date", how="left", validate="many_to_one").sort_values("_row")
    rows["expected_new_buy_eligible"] = (
        rows[quarter_column].astype(str).eq(rows.expected_active_quarter)
        & rows.signal_date.ge(rows.expected_effective_date)
        & rows.signal_date.gt(rows.expected_latest_filing_date)
    )
    return rows.drop(columns="_row").reset_index(drop=True)


def _verify_hashes(records, path_key="artifact", hash_key="artifact_sha256"):
    count = 0
    for record in records:
        require(sha(record[path_key]) == record[hash_key], f"artifact changed: {record[path_key]}")
        count += 1
    return count


def training_audit():
    linear = read(ROOT / "joint_linear_tree_artifacts/FIT_RECEIPT.json")
    require(linear["test_rows_read"] == 0, "linear/tree consumed test rows")
    require(sha(ROOT / "data/pre2026_joint.parquet") == linear["source_sha256"], "linear/tree training source changed")
    for fit in linear["fits"]:
        cutoff = pd.Timestamp("2025-01-01") if fit["stage"] == "validation" else CUTOFF
        require(pd.Timestamp(fit["train_label_end_max"]) < cutoff, "linear/tree label cutoff")
        require(pd.Timestamp(fit["train_signal_max"]) < cutoff, "linear/tree feature cutoff")
    linear_count = _verify_hashes(linear["fits"])
    linear_count += _verify_hashes(linear.get("numerical_repairs", []))
    neural = read(ROOT / "joint_neural_artifacts/TRAIN_RECEIPT.json")
    require(neural["fit_2026_rows"] == 0, "neural consumed test rows")
    for key in ["training_label_end_max", "max_consumed_price_date", "training_signal_max"]:
        require(pd.Timestamp(neural[key]) < CUTOFF, f"neural cutoff: {key}")
    require(sha(neural["specification"]["source"]) == neural["specification"]["source_sha256"], "neural training source changed")
    neural_count = _verify_hashes(neural["artifacts"], "path", "sha256")
    for log in neural["logs"]:
        if log.get("stage") == "validation":
            require(pd.Timestamp(log["max_reward_signal"]) < pd.Timestamp("2025-01-01"), "neural validation fit crossed cutoff")
        if log.get("stage") == "2025_validation":
            require(log["updates"] == 0, "neural updated during validation evaluation")
    risk = read(ROOT / "risk/TRAIN_RECEIPT.json")
    require(risk["fit_2026_rows"] == 0 and pd.Timestamp(risk["train_last"]) < CUTOFF, "risk training cutoff")
    require(sha(ROOT / "risk/frozen_covariance.npz") == risk["artifact_sha256"], "risk artifact changed")
    require(sha(risk["source"]) == risk["source_sha256"], "risk training source changed")
    registry = read(ROOT / "models/model_registry.json")
    for name, record in registry["models"].items():
        require(sha(record["path"]) == record["sha256"], f"model registry hash mismatch: {name}")
        if "training_cutoff_exclusive" in record:
            require(pd.Timestamp(record["training_cutoff_exclusive"]) <= CUTOFF, f"registry cutoff: {name}")
    auxiliary = read(ROOT / "models/AUXILIARY_TRAIN_RECEIPT.json")
    require(auxiliary["test_rows_read"] == 0, "auxiliary models consumed test rows")
    require(pd.Timestamp(auxiliary["train_signal_max"]) < CUTOFF, "auxiliary training cutoff")
    require(sha(auxiliary["source_path"]) == auxiliary["source_sha256"], "auxiliary training source changed")
    require(sha(auxiliary["artifact"]) == auxiliary["artifact_sha256"], "anomaly artifact changed")
    require(sha(auxiliary["cluster_artifact"]) == auxiliary["cluster_artifact_sha256"], "clustering artifact changed")
    frame = pd.read_parquet(ROOT / "data/pre2026_joint_context.parquet")
    require(pd.to_datetime(frame.signal_date).lt(CUTOFF).all(), "joint feature data crossed cutoff")
    require(pd.to_datetime(frame.loc[frame.label_available, "label_end_date"]).lt(CUTOFF).all(), "joint available labels crossed cutoff")
    if "target_context_available" in frame:
        require(pd.to_datetime(frame.loc[frame.target_context_available, "target_end_date"]).lt(CUTOFF).all(), "auxiliary targets crossed cutoff")
    return {"status": "PASS", "linear_artifact_hashes_checked": linear_count,
            "neural_artifact_hashes_checked": neural_count, "registry_hashes_checked": len(registry["models"]),
            "all_final_training_labels_before": "2026-01-01", "test_rows_in_training": 0,
            "neural_2025_validation_updates": 0, "auxiliary_models_refitted": True}


def pool_audit():
    # Timing references are independent source manifests copied by the input
    # builder, not inferred from the already-computed eligibility boolean.
    source = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
    original = pd.read_parquet(source / "universe/quarterly_universe_manifest.parquet")
    timing = original[["quarter", "effective_date", "latest_actual_filing_timestamp"]].rename(columns={
        "effective_date": "quarter_effective_date", "latest_actual_filing_timestamp": "latest_filing_date"})
    q2source = pd.read_csv(ROOT.parent / "a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1/Q2_ORIGINAL24_SOURCE_MAP.csv")
    initial = q2source.loc[~q2source.source_scope.str.contains("RESTAT")]
    latest_q2 = pd.to_datetime(initial.accepted_at, utc=True).max().tz_convert(None).normalize()
    binding = read(ROOT.parent / "a2_strict_method_retrain_20260926/test2026_stage/fixed_window_binding/Q2_SOURCE_BINDING.json")
    timing = pd.concat([timing, pd.DataFrame([{"quarter": "2026Q2", "quarter_effective_date": pd.Timestamp(binding["initial_effective_date"]),
                                             "latest_filing_date": latest_q2}])], ignore_index=True)
    for column in ["quarter_effective_date", "latest_filing_date"]:
        timing[column] = pd.to_datetime(timing[column])
    copied = pd.read_csv(ROOT / "data/quarter_timing.csv", parse_dates=["quarter_effective_date", "latest_filing_date"])
    reference_columns = ["quarter", "quarter_effective_date", "latest_filing_date"]
    pd.testing.assert_frame_equal(timing[reference_columns].sort_values("quarter").reset_index(drop=True),
                                  copied[reference_columns].sort_values("quarter").reset_index(drop=True), check_dtype=False)
    result = {}
    for name, quarter in [("pre2026_joint_context.parquet", "active_13f_quarter"),
                          ("test_features_context.parquet", "quarter")]:
        panel = pd.read_parquet(ROOT / "data" / name)
        require(not panel.duplicated(["signal_date", "ticker"]).any(), f"duplicate context rows: {name}")
        expected = latest_effective_eligibility(panel, timing, quarter)
        require(np.array_equal(panel.new_buy_eligible.to_numpy(bool), expected.expected_new_buy_eligible.to_numpy(bool)),
                f"latest-effective eligibility mismatch: {name}")
        require(panel.new_buy_eligible.notna().all(), "missing new-buy eligibility")
        require(pd.to_datetime(panel.quarter_effective_date).eq(expected.expected_effective_date.to_numpy()).all(),
                f"row effective date differs from independent as-of reference: {name}")
        require("required_report_quarter" not in panel, "obsolete natural-quarter gating field remains")
        if name.startswith("pre2026"):
            keys = ["signal_date", "ticker", "active_13f_quarter", "cusip"]
            membership = pd.read_parquet(source / "universe/daily_eligible_universe_membership.parquet", columns=keys)
            require(len(panel[keys].merge(membership, on=keys, validate="one_to_one")) == len(panel), "pretraining pool differs from original membership keys")
        else:
            keys = ["signal_date", "quarter", "ticker", "cusip", "title_of_class"]
            gate = pd.read_parquet(ROOT.parent / "a2_strict_method_retrain_20260926/test2026_stage/r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet")
            verified = gate.loc[gate.final_input_gate.str.startswith("INPUT_VERIFIED"), keys]
            require(len(verified) == len(panel) and len(panel[keys].merge(verified, on=keys, validate="one_to_one")) == len(panel),
                    "test pool differs from original verified candidate keys")
        # Old-calendar-quarter rows are the precise regression case: when that
        # report is still the active effective pool, it remains buy eligible.
        natural_previous = (panel.signal_date.dt.to_period("Q") - 1).astype(str)
        carried = panel[quarter].astype(str).ne(natural_previous) & expected.expected_new_buy_eligible.to_numpy(bool)
        require(panel.loc[carried, "new_buy_eligible"].all(), "calendar boundary incorrectly revoked effective pool")
        active = expected[["signal_date", "expected_active_quarter"]].drop_duplicates().sort_values("signal_date")
        switches = active.loc[active.expected_active_quarter.ne(active.expected_active_quarter.shift())]
        result[name] = {"rows": len(panel), "days": panel.signal_date.nunique(),
                        "eligible_rows": int(panel.new_buy_eligible.sum()), "natural_quarter_mismatch_still_eligible_rows": int(carried.sum()),
                        "active_pool_switches": [{"signal_date": str(r.signal_date.date()), "quarter": r.expected_active_quarter}
                                                 for r in switches.itertuples(index=False)]}
    return {"status": "PASS", "rule": "latest actually public and effective 13F pool; carry forward until a later pool becomes effective",
            "calendar_quarter_forced_exclusion": False, "panels": result}


def check_run(directory, panel, prices, calendar, year):
    daily = pd.read_parquet(directory / "daily.parquet").sort_values("date").reset_index(drop=True)
    trades = pd.read_parquet(directory / "trades.parquet")
    positions = pd.read_parquet(directory / "positions.parquet")
    decisions = pd.read_parquet(directory / "target_decisions.parquet")
    meta = read(directory / "metadata.json")
    cost = float(meta["cost_bps_one_way"]) / 1e4
    require(pd.DatetimeIndex(daily.date).equals(calendar), "daily calendar missing/reordered")
    require(np.isfinite(daily.cash).all() and daily.cash.ge(-EPS).all(), "invalid or negative cash")
    require(daily.actual_name_count.between(0, meta["max_positions"]).all(), "invalid actual position count")
    require(not daily.date.duplicated().any(), "duplicate ledger dates")
    price_index = prices.set_index(["ticker", "trade_date"])
    require(not price_index.index.duplicated().any(), "duplicate source price keys")
    next_day = pd.Series(calendar[1:], index=calendar[:-1])
    price_error = fee_error = units_error = 0.
    eligibility_checked = 0
    if len(trades):
        require(trades.execution_date.eq(trades.signal_date.map(next_day)).all(), "non-next-session fill")
        require(trades.signal_date.lt(trades.execution_date).all(), "same-day trade")
        require(trades.execution_date.dt.year.eq(year).all(), "trade outside evaluation year")
        require(trades.notional.gt(0).all() and trades.price.gt(0).all(), "nonpositive fill")
        require(trades.side.isin(["BUY", "SELL"]).all(), "unknown fill side")
        expected = price_index.open.reindex(pd.MultiIndex.from_frame(trades[["ticker", "execution_date"]])).to_numpy()
        require(np.isfinite(expected).all(), "traded missing or flagged open")
        price_error = maxerr(trades.price, expected)
        fee_error = maxerr(trades.transaction_cost, trades.notional * cost)
        require(price_error < EPS and fee_error < EPS, "fill price or full one-way cost mismatch")
        require(maxerr(trades.notional, trades.index_units * trades.price) < EPS, "notional/units mismatch")
        buys = trades.loc[trades.side.eq("BUY")]
        allowed = panel.set_index(["signal_date", "ticker"]).new_buy_eligible.reindex(
            pd.MultiIndex.from_frame(buys[["signal_date", "ticker"]])).fillna(False)
        require(allowed.all(), "new entry or increase outside signal-day effective pool")
        eligibility_checked = len(buys)
        if len(buys) and meta["capacity_fraction"] is not None:
            require(buys.capacity_enforced.all(), "buy capacity proxy unexpectedly bypassed")
            require(buys.capacity_adv_source_date.eq(buys.signal_date).all(), "buy ADV not from signal day")
            require((buys.notional <= buys.capacity_adv * meta["capacity_fraction"] + EPS).all(), "buy exceeds capacity proxy")
        holdings = {}
        for row in trades.itertuples(index=False):
            old = holdings.get(row.ticker, 0.)
            units_error = max(units_error, abs(old - row.index_units_before))
            new = old + row.index_units * (1 if row.side == "BUY" else -1)
            require(new >= -EPS, "sold nonexistent units")
            units_error = max(units_error, abs(new - row.index_units_after))
            holdings[row.ticker] = max(0., new)
        require(units_error < EPS, "unit continuity error")
    if len(trades):
        signed = trades.assign(cash_flow=np.where(trades.side.eq("BUY"), -trades.notional, trades.notional) - trades.transaction_cost,
                               unit_flow=np.where(trades.side.eq("BUY"), trades.index_units, -trades.index_units))
        flows = signed.groupby("execution_date").cash_flow.sum().reindex(calendar, fill_value=0.)
        fees = trades.groupby("execution_date").transaction_cost.sum().reindex(calendar, fill_value=0.)
        expected_units = signed.pivot_table(index="execution_date", columns="ticker", values="unit_flow", aggfunc="sum", fill_value=0.)
        expected_units = expected_units.reindex(calendar, fill_value=0.).cumsum()
    else:
        flows = fees = pd.Series(0., index=calendar)
        expected_units = pd.DataFrame(index=calendar)
    cash_error = maxerr(daily.cash, meta["initial_cash"] + flows.cumsum().to_numpy())
    require(cash_error < EPS, "cash differs from independently reconstructed net fills")
    require(maxerr(daily.transaction_cost_amount, fees) < EPS, "daily fees differ from actual trades")
    actual_units = positions.pivot(index="date", columns="ticker", values="index_units") if len(positions) else pd.DataFrame(index=calendar)
    unit_names = expected_units.columns.union(actual_units.columns)
    daily_units_error = maxerr(expected_units.reindex(index=calendar, columns=unit_names, fill_value=0.).fillna(0.),
                               actual_units.reindex(index=calendar, columns=unit_names, fill_value=0.).fillna(0.))
    require(daily_units_error < EPS, "position ledger differs from accumulated actual trade units")
    if len(positions):
        require(not positions.duplicated(["date", "ticker"]).any(), "duplicate position key")
        require(positions.index_units.gt(0).all(), "nonpositive retained units")
        require((positions.unknown | positions.mark_date.le(positions.date)).all(), "future valuation mark")
        fresh = positions.loc[~positions.stale & ~positions.unknown]
        expected = price_index.close.reindex(pd.MultiIndex.from_frame(fresh[["ticker", "date"]])).to_numpy()
        require(np.isfinite(expected).all(), "fresh position uses unavailable close")
        require(maxerr(fresh.mark, expected) < EPS, "fresh mark differs from contemporaneous close")
        known = positions.loc[~positions.unknown]
        require(maxerr(known.market_value, known.index_units * known.mark) < EPS, "position value mismatch")
        count = positions.groupby("date").size().reindex(calendar, fill_value=0)
        known_value = known.groupby("date").market_value.sum().reindex(calendar, fill_value=0.)
        unknown_count = positions.groupby("date").unknown.sum().reindex(calendar, fill_value=0)
        stale_count = positions.groupby("date").stale.sum().reindex(calendar, fill_value=0)
    else:
        count = unknown_count = stale_count = pd.Series(0, index=calendar)
        known_value = pd.Series(0., index=calendar)
    require(np.array_equal(count.to_numpy(), daily.actual_name_count.to_numpy()), "position count mismatch")
    require(np.array_equal(unknown_count.to_numpy(), daily.unknown_count.to_numpy()), "unknown count mismatch")
    require(np.array_equal(stale_count.to_numpy(), daily.stale_count.to_numpy()), "stale count mismatch")
    require(maxerr(daily.known_position_value, known_value) < EPS, "known NAV components mismatch")
    expected_nav = daily.cash.to_numpy() + known_value.to_numpy()
    expected_nav[unknown_count.to_numpy() > 0] = np.nan
    nav_error = maxerr(daily.nav, expected_nav)
    require(nav_error < EPS, "NAV differs from cash plus retained positions")
    bad = (unknown_count.to_numpy() > 0) | (stale_count.to_numpy() > 0)
    certified_nav = expected_nav.copy()
    certified_nav[bad] = np.nan
    require(maxerr(daily.certified_nav, certified_nav) < EPS, "uncertified value published as certified NAV")
    if len(decisions):
        submitted = decisions.loc[decisions.status.eq("submitted")]
        require(submitted.execution_date.eq(submitted.signal_date.map(next_day)).all(), "decision execution clock mismatch")
        require(not submitted.duplicated(["signal_date", "ticker"]).any(), "duplicate target row")
        require(submitted.target_weight.fillna(0).between(0, meta["max_target_weight"] + 1e-7).all(), "target stock cap exceeded")
        require(submitted.target_sum.le(meta["max_target_invested"] + 1e-7).all(), "target investment cap exceeded")
        positive = submitted.loc[submitted.target_weight.gt(1e-10)]
        require(positive.groupby("signal_date").size().le(meta["max_positions"]).all(), "target position count exceeded")
        totals = submitted.groupby("signal_date").target_weight.sum()
        require(maxerr(totals, submitted.groupby("signal_date").target_sum.first().reindex(totals.index)) < 1e-7, "target total does not match target rows")
    require(meta["terminal_liquidation"] is False, "unrequested terminal liquidation assumption")
    return {"status": "PASS", "directory": directory.name, "year": year, "days": len(daily), "trades": len(trades),
            "buys_and_increases_eligibility_checked": eligibility_checked, "max_actual_names": int(daily.actual_name_count.max()),
            "uncertified_days": int(bad.sum()), "max_independent_cash_error": cash_error, "max_fee_error": fee_error,
            "max_nav_error": nav_error, "max_trade_price_error": price_error, "max_units_continuity_error": units_error,
            "max_daily_units_reconstruction_error": daily_units_error, "minimum_cash": float(daily.cash.min())}


def _source_roster(year):
    values = {}
    tree = ast.parse((ROOT / "run_suite.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {"NAMES", "TEST_NAMES"} for t in node.targets):
            name = next(t.id for t in node.targets if isinstance(t, ast.Name))
            if isinstance(node.value, ast.List):
                values[name] = ast.literal_eval(node.value)
            elif isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add) and isinstance(node.value.left, ast.Name):
                values[name] = values[node.value.left.id] + ast.literal_eval(node.value.right)
    return values["TEST_NAMES" if year == 2026 else "NAMES"]


def main():
    result = {"status": "PENDING", "training": None, "pool": None, "evaluations": {}, "failures": [], "pending": [],
              "scope": "Independent latest-effective pool, ledger, date and frozen-hash audit; not certification of complete universe or shareholder total return."}

    def audit(scope, callback):
        try:
            return callback()
        except FileNotFoundError as exc:
            result["pending"].append(f"{scope}: {exc.filename}")
        except Exception as exc:
            result["failures"].append({"scope": scope, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-1800:]})
        return None

    result["training"] = audit("training", training_audit)
    result["pool"] = audit("pool", pool_audit)
    shards = sorted((ROOT / "evaluation_2026").glob("cost_*"))
    scenarios = [(2025, ROOT / "evaluation_2025")] + ([(2026, p) for p in shards] if shards else [(2026, ROOT / "evaluation_2026")])
    for year, folder in scenarios:
        scope = str(folder.relative_to(ROOT))

        def evaluate(year=year, folder=folder):
            complete = read(folder / "COMPLETE.json")
            require(complete["fit_guard_attempts"] == 0 and complete["training_2026_rows"] == 0, "fit attempted during evaluation")
            require(complete["full_pool_formal_result"] is False, "partial pool upgraded to formal result")
            seal = None
            if year == 2026:
                seal = read(folder / "FROZEN_BEFORE_SCORING.json")
                require(seal["inference_only"] and not seal["full_pool"], "invalid test seal")
                for relative, digest in seal["source_hashes"].items():
                    require(sha(ROOT / relative) == digest, f"frozen source drift: {relative}")
                panel = pd.read_parquet(ROOT / "data/test_features_context.parquet")
                prices = pd.read_parquet(ROOT / "data/test_prices.parquet")
                prices.loc[prices.price_quality_warning.astype(bool), ["open", "close"]] = np.nan
                calendar = pd.DatetimeIndex(pd.read_parquet(ROOT / "data/calendar.parquet").query("is_test").trade_date)
                roster = seal["roster"]
            else:
                panel = pd.read_parquet(ROOT / "data/pre2026_joint_context.parquet").query('signal_date >= "2025-01-01"')
                prices = pd.read_parquet(ROOT.parent / "a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet")
                prices["trade_date"] = pd.to_datetime(prices.trade_date)
                calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ") & prices.trade_date.ge("2025-01-01"), "trade_date"].unique()))
                roster = _source_roster(year)
            comparison = pd.read_csv(folder / "comparison.csv")
            require(len(comparison) == complete["evaluations"], "comparison incomplete")
            require(not comparison.duplicated(["policy", "cost_bps_per_side"]).any(), "duplicate evaluation combination")
            require(complete["policies"] == len(roster), "receipt roster count differs from frozen roster")
            for _, group in comparison.groupby("cost_bps_per_side"):
                require(set(group.policy) == set(roster), "frozen policy missing from cost scenario")
            require(comparison.formal_full_pool_return.isna().all(), "incomplete pool has formal reported return")
            rows = [check_run(folder / f"{row.policy}_{row.cost_bps_per_side:g}bps", panel, prices, calendar, year)
                    for row in comparison.itertuples(index=False)]
            return {"status": "PASS", "fit_guard_attempts": 0,
                    "frozen_source_hashes_checked": len(seal["source_hashes"]) if seal else 0, "runs": rows}

        checked = audit(scope, evaluate)
        if checked is not None:
            result["evaluations"][scope] = checked
    if shards:
        def aggregate():
            complete = read(ROOT / "evaluation_2026/COMPLETE.json")
            comparison = pd.read_csv(ROOT / "evaluation_2026/comparison.csv")
            seals = [read(p / "FROZEN_BEFORE_SCORING.json") for p in shards]
            roster = set(seals[0]["roster"])
            costs = set(seals[0]["cost_bps_per_side"])
            require(all(set(s["roster"]) == roster and set(s["cost_bps_per_side"]) == costs for s in seals), "inconsistent frozen scenarios")
            require(len(comparison) == len(roster) * len(costs), "aggregate scenario count differs from frozen contract")
            require(not comparison.duplicated(["policy", "cost_bps_per_side"]).any(), "duplicate combined scenario")
            require(set(comparison.cost_bps_per_side) == costs, "aggregate missing cost scenario")
            for _, group in comparison.groupby("cost_bps_per_side"):
                require(set(group.policy) == roster, "aggregate missing frozen policy")
            require(comparison.formal_full_pool_return.isna().all(), "aggregate upgrades incomplete pool return")
            if "evaluations" in complete:
                require(complete["evaluations"] == len(comparison), "aggregate receipt count mismatch")
            return {"status": "PASS", "evaluations": len(comparison), "cost_bps": sorted(costs), "policies": len(roster)}
        result["aggregate_2026"] = audit("aggregate_2026", aggregate)
    result["status"] = "FAIL" if result["failures"] else "PENDING" if result["pending"] else "PASS"
    (ROOT / "VERIFICATION.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": result["status"], "pending": result["pending"], "failures": result["failures"],
                      "verified_runs": sum(len(v["runs"]) for v in result["evaluations"].values())}, indent=2, ensure_ascii=False))
    if result["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
