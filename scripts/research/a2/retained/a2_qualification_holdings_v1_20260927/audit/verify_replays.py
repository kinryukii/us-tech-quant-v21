"""Read-only, independent audit of completed holding-aware replay artifacts.

No engine, policy, training package or prediction function is imported. The
only ledger reconstruction accumulates saved fills; it does not replay orders.
Partial mode never reads a scenario until its COMPLETE.json exists.
"""
from pathlib import Path
import argparse
import hashlib
import json
import traceback

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / "a2_latest_effective_joint_20260927"
OUT = ROOT / "audit"
EPS = 1e-5
WEPS = 1e-7
NAMES = ["joint_ridge", "joint_elastic_net", "joint_logistic", "joint_hgb", "joint_q10",
         "joint_q50", "joint_q90", "joint_quantile_risk", "joint_mlp", "joint_rl_ensemble",
         "joint_rl_zero_control", "hgb_return_baseline"]
TEST_NAMES = NAMES + ["joint_hgb_lw", "joint_hgb_pca"]
SCENARIOS = [(2025, 10), (2026, 10), (2026, 5), (2026, 25)]
SOURCE_HASHES = {}


def require(ok, message):
    if not bool(ok):
        raise AssertionError(message)


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def remember(path, expected=None):
    path = Path(path).resolve()
    value = sha(path)
    require(expected is None or value == expected, f"source hash drift: {path}")
    if str(path) in SOURCE_HASHES:
        require(value == SOURCE_HASHES[str(path)], f"source changed during audit: {path}")
    SOURCE_HASHES[str(path)] = value
    return value


def read(path):
    remember(path)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def frame(path, **kwargs):
    remember(path)
    return pd.read_parquet(path, **kwargs)


def decode(value, default=None):
    return default if value is None or (isinstance(value, float) and np.isnan(value)) else json.loads(value)


def maxerr(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    require(a.shape == b.shape, "numeric comparison shape mismatch")
    require(not np.isinf(a).any() and not np.isinf(b).any(), "infinite value")
    require(np.array_equal(np.isnan(a), np.isnan(b)), "numeric comparison NaN mismatch")
    good = np.isfinite(a) & np.isfinite(b)
    return float(np.max(np.abs(a[good] - b[good]))) if good.any() else 0.


def same(a, b, message, tolerance=EPS):
    error = maxerr(a, b)
    require(error <= tolerance, f"{message}: {error:.12g}")
    return error


def group_sum(table, column, calendar, date="execution_date"):
    return table.groupby(date)[column].sum().reindex(calendar, fill_value=0.) if len(table) else pd.Series(0., index=calendar)


def training_audit():
    receipt = read(ROOT / "neural_artifacts/TRAIN_RECEIPT.json")
    spec = receipt["specification"]
    require(receipt["status"] == "JOINT_TRAINING_COMPLETE", "neural fits incomplete")
    require(receipt["fit_2026_rows"] == 0, "neural fit consumed test rows")
    for key in ["training_signal_max", "training_label_end_max", "max_consumed_price_date"]:
        require(pd.Timestamp(receipt[key]) < pd.Timestamp("2026-01-01"), f"neural cutoff: {key}")
    remember(ROOT / "joint_neural_v2.py", spec["source_code_sha256"])
    remember(ROOT / "VERSION_CONTRACT.md", spec["version_contract_sha256"])
    remember(spec["source"], spec["source_sha256"])
    remember(ROOT.parent / "a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet",
             spec["price_source_sha256"])
    require(len(receipt["artifacts"]) == 6, "expected six retrained neural artifacts")
    for r in receipt["artifacts"]:
        remember(r["path"], r["sha256"])
    for r in receipt["logs"]:
        cutoff = "2025-01-01" if r["stage"] == "validation" else "2026-01-01"
        require(pd.Timestamp(r["max_reward_signal"]) < pd.Timestamp(cutoff), "neural reward cutoff")
        require(r["max_actual_names"] <= 20, "training actual name limit")
    require(receipt["actual_parameter_updates"] > 0, "neural had no parameter updates")
    old_seal = read(ROOT / "OLD_FROZEN_PRESERVATION.json")
    require(old_seal["status"] == "PASS" and not old_seal["mismatches"], "old preservation failed")
    for relative, digest in old_seal["source_sha256"].items():
        remember(ROOT.parent / relative, digest)
    linear = read(OLD / "joint_linear_tree_artifacts/FIT_RECEIPT.json")
    require(linear["test_rows_read"] == 0, "reused value models consumed test rows")
    for r in linear["fits"]:
        cutoff = "2025-01-01" if r["stage"] == "validation" else "2026-01-01"
        for key in ["train_signal_max", "train_label_end_max"]:
            require(pd.Timestamp(r[key]) < pd.Timestamp(cutoff), f"value-model cutoff: {key}")
        remember(r["artifact"], r["artifact_sha256"])
    for r in linear.get("numerical_repairs", []):
        remember(r["artifact"], r["artifact_sha256"])
    risk = read(OLD / "risk/TRAIN_RECEIPT.json")
    require(risk["fit_2026_rows"] == 0 and pd.Timestamp(risk["train_last"]) < pd.Timestamp("2026-01-01"), "risk cutoff")
    remember(OLD / "risk/frozen_covariance.npz", risk["artifact_sha256"])
    return {"status": "PASS", "neural_fits": 6, "actual_parameter_updates": receipt["actual_parameter_updates"],
            "fit_2026_rows": 0, "retrained_source_code_hash_matches": True,
            "old_preservation_hashes": len(old_seal["source_sha256"]), "all_final_training_dates_before": "2026-01-01"}


def load_inputs(year):
    if year == 2025:
        panel = frame(OLD / "data/pre2026_joint_context.parquet")
        panel = panel.loc[panel.signal_date.between("2025-01-01", "2025-12-29")].copy()
        px = frame(ROOT.parent / "a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet")
        calendar = pd.DatetimeIndex(sorted(px.loc[px.ticker.eq("QQQ") & px.trade_date.ge("2025-01-01"), "trade_date"].unique()))
    else:
        panel = frame(ROOT / "data/test_features_context.parquet")
        panel = panel.loc[panel.signal_date.le("2026-09-22")].copy()
        px = frame(ROOT / "data/test_prices.parquet")
        calendar = pd.DatetimeIndex(frame(OLD / "data/calendar.parquet").query("is_test").trade_date)
    require(not panel.duplicated(["signal_date", "ticker"]).any(), "duplicate input key")
    require(not px.duplicated(["trade_date", "ticker"]).any(), "duplicate price key")
    require(panel.signal_date.isin(calendar).all(), "input outside calendar")
    px = px.copy()
    if "price_quality_warning" not in px:
        px["price_quality_warning"] = False
    px["price_quality_warning"] = px.price_quality_warning.fillna(True).astype(bool)
    for col in ["open", "close"]:
        px[col] = pd.to_numeric(px[col], errors="coerce")
        good = ~px.price_quality_warning & np.isfinite(px[col]) & px[col].gt(0)
        px.loc[~good, col] = np.nan
    return panel, px, calendar


def reuse_audit():
    receipt=read(ROOT/"MODEL_REUSE.json")
    require(receipt["status"]=="PASS" and receipt["supervised_fit_in_this_version"] is False,
            "supervised reuse receipt is not frozen reuse")
    require(receipt["risk_and_auxiliary_fit_in_this_version"] is False,"risk/auxiliary unexpectedly refitted")
    prior=read(OLD/"evaluation_2026/cost_10/FROZEN_BEFORE_SCORING.json")
    expected={str((OLD/p).resolve()):h for p,h in prior["source_hashes"].items()}
    inherited={str(Path(p).resolve()):h for p,h in receipt["all_old_frozen_source_sha256"].items()}
    require(inherited==expected,"MODEL_REUSE not bound to original frozen hashes")
    for path,digest in inherited.items():remember(path,digest)
    linear=read(OLD/"joint_linear_tree_artifacts/FIT_RECEIPT.json")
    require(len(receipt["used_supervised_models"])==14,"model reuse stage/name coverage")
    seen=set()
    for row in receipt["used_supervised_models"]:
        key=(row["stage"],row["name"])
        require(key not in seen and row["fit_in_this_version"] is False,"duplicate/refitted reused model")
        seen.add(key)
        fit=next(r for r in linear["fits"] if (r["stage"],r["name"])==key)
        repaired=[r for r in linear.get("numerical_repairs",[]) if (r["stage"],r["name"])==key and r.get("used_for_policy")]
        fit=repaired[-1] if repaired else fit
        require(Path(row["path"]).resolve()==Path(fit["artifact"]).resolve() and row["sha256"]==fit["artifact_sha256"],"reuse lost selected numerical repair")
        require(inherited.get(str(Path(row["path"]).resolve()))==row["sha256"],"reuse artifact absent from old seal")
        remember(row["path"],row["sha256"])
    require(seen=={(s,n) for s in ["validation","final"] for n in ["ridge","elastic_net","logistic","hgb","q10","q50","q90"]},"incomplete reused family roster")
    return dict(status="PASS",used_supervised_models=len(seen),old_frozen_sources=len(inherited),fit_in_this_version=False)


def supplemental_audit(folder):
    seal=read(ROOT/"ADDITIONAL_CONSUMED_INPUT_SEAL.json")
    require(seal["status"]=="FROZEN_BEFORE_2026_REPLAY","supplementary seal status")
    for path,digest in seal["source_sha256"].items():remember(path,digest)
    needed=[ROOT/"data/operational_exit_evidence.csv",ROOT/"data/DATA_RECEIPT.json",ROOT/"MODEL_REUSE.json"]
    covered={str(Path(p).resolve()) for p in seal["source_sha256"]}
    require(all(str(p.resolve()) in covered for p in needed),"operational/data/reuse evidence not supplementary sealed")
    created=pd.Timestamp(seal["created_at_utc"])
    replay_start=pd.Timestamp((folder/"FROZEN_BEFORE_REPLAY.json").stat().st_mtime,unit="s",tz="UTC")
    require(created<=replay_start,"supplementary binding created after replay seal")
    return seal


def check_run(folder, panel, px, calendar, year, cost):
    tables = {k: frame(folder / f"{k}.parquet") for k in ["daily", "trades", "positions", "target_decisions",
        "diagnostics", "valuation_intervals", "raw_model_outputs", "signal_contexts", "operational_actions", "execution_results"]}
    meta = read(folder / "metadata.json")
    daily, trades, positions, targets = [tables[k] for k in ["daily", "trades", "positions", "target_decisions"]]
    raw, contexts, ops, events = [tables[k] for k in ["raw_model_outputs", "signal_contexts", "operational_actions", "execution_results"]]
    daily = daily.sort_values("date").reset_index(drop=True)
    require(pd.DatetimeIndex(daily.date).equals(calendar), "daily calendar mismatch")
    require(meta["version"] == "HOLDING_AWARE_EXECUTION_V2", "wrong ledger semantics version")
    require(meta["terminal_liquidation"] is False and meta["shareholder_total_return_certified"] is False, "valuation boundary upgraded")
    require(float(meta["cost_bps_one_way"]) == cost, "wrong scenario cost")
    require(np.isfinite(daily.cash).all() and daily.cash.ge(-EPS).all(), "invalid cash")
    require(daily.actual_name_count.between(0, meta["max_positions"]).all(), "actual holding limit")
    next_day = dict(zip(calendar[:-1], calendar[1:]))
    pxidx = px.set_index(["ticker", "trade_date"])
    pidx = panel.set_index(["signal_date", "ticker"])
    rate = cost / 10000.
    initial = meta["initial_positions"]
    price_error = fee_error = units_error = 0.
    intra_cash=float(meta["initial_cash"]);minimum_intra_cash=intra_cash;max_intra_names=len(initial)
    fill_name_counts={}
    if len(trades):
        require(trades.execution_date.eq(trades.signal_date.map(next_day)).all(), "fill not next session")
        require(trades.side.isin(["BUY", "SELL"]).all(), "unknown fill side")
        require(trades.notional.gt(0).all() and trades.index_units.gt(0).all(), "nonpositive fill")
        require(not trades.duplicated(["order_id", "side"]).any(), "duplicate side fill for order")
        expected = pxidx.open.reindex(pd.MultiIndex.from_frame(trades[["ticker", "execution_date"]])).to_numpy()
        price_error = same(trades.price, expected, "consumed missing/uncertified/wrong execution open")
        fee_error = same(trades.transaction_cost, trades.notional * rate, "one-way costs")
        same(trades.notional, trades.index_units * trades.price, "fill notional")
        holdings = dict(initial)
        require(trades.execution_date.is_monotonic_increasing,"fill ledger is not chronological")
        for r in trades.itertuples(index=False):
            before = holdings.get(r.ticker, 0.)
            after = before + r.index_units * (1 if r.side == "BUY" else -1)
            units_error = max(units_error, abs(before-r.index_units_before), abs(after-r.index_units_after))
            require(after >= -EPS, "sold unowned units")
            if after>1e-10:holdings[r.ticker]=after
            else:holdings.pop(r.ticker,None)
            intra_cash += r.notional*(1 if r.side=="SELL" else -1)-r.transaction_cost
            minimum_intra_cash=min(minimum_intra_cash,intra_cash)
            max_intra_names=max(max_intra_names,len(holdings))
            require(intra_cash>=-EPS,"intraday fill spent unavailable cash")
            require(len(holdings)<=meta["max_positions"],"intraday fill exceeded actual holding cap")
            fill_name_counts[(r.order_id,r.side)]=len(holdings)
        require(units_error < EPS, "fill unit continuity")
        fill_events=events.loc[events.status.eq("FILLED")]
        require(all(r.actual_names_at_event==fill_name_counts.get((r.order_id,r.side)) for r in fill_events.itertuples(index=False)),"fill event count differs from independently accumulated holdings")
        buys = trades.loc[trades.side.eq("BUY")]
        keys = pd.MultiIndex.from_frame(buys[["signal_date", "ticker"]])
        allowed = pidx.new_buy_eligible.reindex(keys).fillna(False)
        require(allowed.all(), "buy/increase without signal pool eligibility")
        signal_close = pxidx.close.reindex(pd.MultiIndex.from_frame(buys[["ticker", "signal_date"]]))
        require(np.isfinite(signal_close).all(), "buy despite signal-close known price restriction")
        if meta["capacity_fraction"] is not None:
            require(buys.capacity_enforced.all() and buys.capacity_adv_source_date.eq(buys.signal_date).all(), "buy capacity/clock bypass")
            require((buys.notional <= buys.capacity_adv * meta["capacity_fraction"] + EPS).all(), "buy ADV limit")
            same(buys.capacity_adv, pidx.avg_dollar_volume_20d.reindex(keys), "signal ADV mismatch")
        signed = trades.assign(cash_flow=np.where(trades.side.eq("BUY"), -trades.notional, trades.notional)-trades.transaction_cost,
                               unit_flow=np.where(trades.side.eq("BUY"), trades.index_units, -trades.index_units))
        flows = group_sum(signed, "cash_flow", calendar)
        expected_units = signed.pivot_table(index="execution_date", columns="ticker", values="unit_flow", aggfunc="sum", fill_value=0.).reindex(calendar, fill_value=0.).cumsum()
    else:
        buys = trades
        flows = pd.Series(0., index=calendar)
        expected_units = pd.DataFrame(index=calendar)
    for t, q in initial.items():
        expected_units[t] = expected_units.get(t, 0.) + q
    fees = group_sum(trades, "transaction_cost", calendar)
    cash_error = same(daily.cash, meta["initial_cash"] + flows.cumsum().to_numpy(), "independent cash reconstruction")
    same(daily.transaction_cost_amount, fees, "daily fee aggregation")
    same(daily.buy_notional, group_sum(trades.loc[trades.side.eq("BUY")], "notional", calendar), "daily buys")
    same(daily.sell_notional, group_sum(trades.loc[trades.side.eq("SELL")], "notional", calendar), "daily sells")
    same(daily.open_posttrade_nav, daily.open_pretrade_nav-daily.transaction_cost_amount, "open self-finance")
    actual_units = positions.pivot(index="date", columns="ticker", values="index_units") if len(positions) else pd.DataFrame(index=calendar)
    names = expected_units.columns.union(actual_units.columns)
    actual_units = actual_units.reindex(index=calendar, columns=names, fill_value=0.).fillna(0.)
    expected_units = expected_units.reindex(index=calendar, columns=names, fill_value=0.).fillna(0.)
    daily_units_error = same(actual_units, expected_units, "independent position reconstruction")
    if len(positions):
        require(not positions.duplicated(["date", "ticker"]).any() and positions.index_units.gt(0).all(), "invalid position keys/units")
        require((positions.unknown | positions.mark_date.le(positions.date)).all(), "future mark consumed")
        known = positions.loc[~positions.unknown]
        for source, group in known.groupby("mark_source"):
            require(source in ["open", "close"], "unrecognized mark source")
            expected = pxidx[source].reindex(pd.MultiIndex.from_frame(group[["ticker", "mark_date"]])).to_numpy()
            same(group.mark, expected, "mark from invalid/uncertified source quote")
        fresh = positions.loc[~positions.stale & ~positions.unknown]
        same(fresh.mark, pxidx.close.reindex(pd.MultiIndex.from_frame(fresh[["ticker", "date"]])), "fresh close mark")
        same(known.market_value, known.index_units*known.mark, "known position value")
        count = positions.groupby("date").size().reindex(calendar, fill_value=0)
        known_value = group_sum(known, "market_value", calendar, "date")
        unknown = group_sum(positions, "unknown", calendar, "date")
        stale = group_sum(positions, "stale", calendar, "date")
    else:
        count = known_value = unknown = stale = pd.Series(0., index=calendar)
    same(daily.actual_name_count, count, "actual name count")
    same(daily.unknown_count, unknown, "unknown valuation count")
    same(daily.stale_count, stale, "stale valuation count")
    same(daily.known_position_value, known_value, "known position sum")
    nav = daily.cash.to_numpy() + known_value.to_numpy()
    nav[unknown.to_numpy()>0] = np.nan
    nav_error = same(daily.nav, nav, "NAV accounting")
    bad = (unknown.to_numpy()>0) | (stale.to_numpy()>0)
    certified = nav.copy(); certified[bad] = np.nan
    same(daily.certified_nav, certified, "false certified NAV")
    require(daily.valuation_status.eq(np.where(unknown.gt(0), "unknown", np.where(stale.gt(0), "stale", "certified"))).all(), "valuation status")
    expected_return = pd.Series(certified).div(pd.Series(certified).shift()).sub(1)
    same(daily.net_return, expected_return, "certified return bridged unknown interval")
    # The remainder checks saved decisions and exact units, not order execution.
    semantic = check_decisions(folder.name, meta, tables, panel, pxidx, calendar, actual_units)
    return dict(status="PASS", policy=folder.name, year=year, cost_bps=cost, days=len(daily), trades=len(trades),
        buys=len(buys), target_rows=len(targets), raw_signals=len(raw), max_actual_names=int(count.max()),
        uncertified_days=int(bad.sum()), max_cash_error=cash_error, max_fee_error=fee_error,
        max_nav_error=nav_error, max_trade_price_error=price_error, max_units_error=units_error,
        max_daily_units_error=daily_units_error,minimum_intraday_cash=minimum_intra_cash,
        max_independent_intraday_names=max_intra_names, **semantic)


def check_decisions(candidate, meta, tables, panel, pxidx, calendar, actual_units):
    raw, ctx, targets, ops, events, trades, daily = [tables[k] for k in ["raw_model_outputs", "signal_contexts",
        "target_decisions", "operational_actions", "execution_results", "trades", "daily"]]
    next_day = dict(zip(calendar[:-1], calendar[1:]))
    signal_days = calendar[(calendar >= pd.Timestamp(meta["signal_start"])) & (calendar <= pd.Timestamp(meta["signal_end"]))]
    require(pd.DatetimeIndex(raw.signal_date).equals(signal_days), "raw signal clock/window")
    require(pd.DatetimeIndex(ctx.signal_date).equals(signal_days), "context signal clock/window")
    require(not raw.decision_id.duplicated().any() and not ctx.decision_id.duplicated().any(), "duplicate raw/context decision")
    require(not targets.order_id.duplicated().any(), "duplicate target order")
    require(set(raw.decision_id) == set(ctx.decision_id), "raw/context association")
    require(targets.decision_id.isin(raw.decision_id).all(), "orphan target decision")
    require(targets.order_id.eq(targets.decision_id+"|"+targets.ticker).all(), "invalid order correlation id")
    require(targets.execution_date.eq(targets.signal_date.map(next_day)).all(), "target execution clock")
    rawidx = raw.set_index("decision_id")
    target_groups = {k:g.set_index("ticker") for k,g in targets.groupby("decision_id")}
    op_groups = {k:g.set_index("ticker") for k,g in ops.groupby("decision_id")}
    sources = {d:g.set_index("ticker") for d,g in panel.groupby("signal_date")}
    eligible_names = {d:set(g.loc[g.new_buy_eligible.fillna(False).astype(bool),"ticker"]) for d,g in panel.groupby("signal_date")}
    price_rows=pxidx[["close"]].reset_index()
    price_rows=price_rows.loc[price_rows.trade_date.isin(signal_days)&np.isfinite(price_rows.close)]
    usable_close_names={d:set(g.ticker) for d,g in price_rows.groupby("trade_date")}
    position_weights={d:dict(zip(g.ticker,g.weight)) for d,g in tables["positions"].groupby("date")}
    dailyidx = daily.set_index("date")
    evidence=pd.DataFrame()
    if signal_days[0].year==2026:
        evidence_path=ROOT/"data/operational_exit_evidence.csv"
        remember(evidence_path)
        evidence=pd.read_csv(evidence_path)
        if len(evidence):
            evidence["known_at"]=pd.to_datetime(evidence.known_at,utc=True)
            evidence["effective_date"]=pd.to_datetime(evidence.effective_date)
    model_omissions = reserved_days = reserved_positions = ops_checked = 0
    restricted_sources = {"PRICE_QUALITY_UNCERTIFIED", "MISSING_PRICE_ROW", "MISSING_OR_INVALID_CLOSE"}
    early = {"2025-07-03", "2025-11-28", "2025-12-24", "2026-11-27", "2026-12-24"}
    for c in ctx.itertuples(index=False):
        label = f"{candidate}/{c.signal_date.date()}"
        require(c.decision_id == f"{candidate}|{c.signal_date.date()}", f"decision identifier: {label}")
        expected_asof = (c.signal_date+pd.Timedelta(hours=13 if str(c.signal_date.date()) in early else 16)).tz_localize("America/New_York").tz_convert("UTC")
        require(pd.Timestamp(c.signal_asof) == expected_asof, f"actual signal-close UTC clock: {label}")
        r = rawidx.loc[c.decision_id]
        model = decode(r.model_decisions_json, {})
        scores = decode(r.raw_model_outputs_json, {}) or {}
        original = set(decode(r.original_input_tickers_json, []))
        decision_names = set(decode(r.decision_input_tickers_json, []))
        operation = decode(r.operational_exits_json, {})
        units = decode(c.current_units_json, {})
        weights = decode(c.current_weights_json, {}) or {}
        reserve = set(decode(c.reserved_tickers_json, []))
        final_reserve = set(decode(c.final_reserved_tickers_json, []))
        source = sources.get(c.signal_date, panel.iloc[:0].set_index("ticker"))
        require(original == set(source.index), f"input row keys: {label}")
        require(c.input_count == len(original) and c.decision_input_count == len(decision_names), f"input count: {label}")
        require(set(model).issubset(decision_names), f"model saw non-decision input: {label}")
        require(isinstance(scores, dict) and set(scores) == set(model), f"raw scores/model decisions correspondence: {label}")
        require(bool(c.policy_called) == bool(r.policy_called) == bool(np.isfinite(c.nav) and c.nav>0), f"unknown NAV policy invocation: {label}")
        account = actual_units.loc[c.signal_date]; held = account[account>1e-10].to_dict()
        require(set(units) == set(held), f"account units disappeared before policy: {label}")
        same(list(units.values()), [held[t] for t in units], f"signal units: {label}")
        ledger = dailyidx.loc[c.signal_date]
        same([c.cash,c.nav,c.cash_weight], [ledger.cash,ledger.nav,ledger.cash_weight], f"signal account context: {label}")
        wp = position_weights.get(c.signal_date,{})
        if np.isfinite(c.nav):
            require(set(weights) == set(held), f"missing held weight: {label}")
            same(list(weights.values()), [wp[t] for t in weights], f"signal weights: {label}")
        else:
            require(not weights and c.available_weight == c.final_available_weight == 0 and not model, f"invented capital for unknown NAV: {label}")
        known_bad = (set(held)|original)-usable_close_names.get(c.signal_date,set())
        expected_reserve = (set(held)-original) | (set(held)&known_bad)
        expected_reserve -= set(operation)-known_bad
        if not np.isfinite(c.nav): expected_reserve = set(held)
        require(reserve == expected_reserve, f"signal known reservation mismatch: {label}")
        expected_decision = original-reserve-set(operation)-(known_bad-set(held))
        require(decision_names == expected_decision, f"signal decision rows not derived from known state: {label}")
        eligible_today=eligible_names.get(c.signal_date,set())
        expected_model=decision_names&(eligible_today|set(held))
        require(set(model)==(expected_model if c.policy_called else set()),f"adapter missing explicit per-input zero/positive decision: {label}")
        expected_final = reserve | (set(held)-set(model)-set(operation))
        expected_final -= set(operation)-known_bad
        require(final_reserve == expected_final, f"post-model omission reservation: {label}")
        for prefix, reserved in [("",reserve),("final_",final_reserve)]:
            weight = sum(weights[t] for t in reserved) if np.isfinite(c.nav) else np.nan
            require(getattr(c,prefix+"reserved_slots") == len(reserved), f"reserved slots: {label}")
            same([getattr(c,prefix+"reserved_weight")], [weight], f"reserved capital: {label}")
            require(getattr(c,prefix+"available_slots") == max(0,meta["max_positions"]-len(reserved)), f"free slots: {label}")
            same([getattr(c,prefix+"available_weight")], [max(0,meta["max_target_invested"]-weight) if np.isfinite(c.nav) else 0], f"free capital: {label}")
        group = target_groups.get(c.decision_id, targets.iloc[:0].set_index("ticker"))
        require(set(group.index) == set(held)|set(model)|set(operation), f"target universe drops held units/raw/ops: {label}")
        active = group.loc[group.order_type.eq("TARGET_WEIGHT")]
        require(active.target_weight.between(0,meta["max_target_weight"]+WEPS).all(), f"active single-name target cap: {label}")
        positive_count = int(active.target_weight.gt(0).sum())
        require(c.active_target_count == positive_count and positive_count+len(final_reserve)<=meta["max_positions"], f"known held + active slot budget: {label}")
        total = float(active.target_weight.sum())
        same([c.active_target_weight],[total], f"active target sum: {label}")
        require(total <= c.final_available_weight+WEPS, f"known held + active capital budget: {label}")
        adapted={t:min(float(w),meta["max_target_weight"]) for t,w in model.items() if t not in operation and t not in final_reserve}
        for t,w in model.items():require(np.isfinite(w) and 0<=w<=meta["max_target_weight"]+WEPS,f"raw model invalid weight: {label}/{t}")
        for t in adapted:
            eligible=t in eligible_today and t not in known_bad
            if not eligible:adapted[t]=min(adapted[t],max(0.,weights.get(t,0.)))
        priority=sorted([t for t,w in adapted.items() if w>0],key=lambda t:(t not in held,-adapted[t],t))
        for t in priority[c.final_available_slots:]:adapted[t]=0.
        proposed_sum=sum(adapted.values())
        if proposed_sum>c.final_available_weight and proposed_sum>0:
            adapted={t:w*c.final_available_weight/proposed_sum for t,w in adapted.items()}
        require(set(active.index)==set(adapted),f"adapted target coverage: {label}")
        same(active.target_weight,[adapted[t] for t in active.index],f"signal-only target adaptation: {label}",WEPS)
        same(group.raw_model_weight,[model.get(t,np.nan) for t in group.index],f"raw model weights preserved: {label}")
        same(group.current_units,[held.get(t,0.) for t in group.index],f"target account units: {label}")
        same(group.current_weight,[wp.get(t,0.) for t in group.index],f"target account weights: {label}")
        same(group.hold_units,[held.get(t,0.) if t in final_reserve else 0. for t in group.index],f"retained-unit targets: {label}")
        same(group.adapted_target_weight,group.target_weight,f"target aliases: {label}")
        for col,value in [("reserved_weight",c.final_reserved_weight),("active_target_sum",total),("total_signal_committed_weight",c.final_reserved_weight+total)]:
            same(group[col],np.repeat(value,len(group)),f"target signal budget {col}: {label}")
        held_targets=group.loc[group.order_type.eq("HOLD_UNITS")]
        same(held_targets.target_weight,[wp[t] for t in held_targets.index],f"hold indicative weights: {label}")
        for row in group.itertuples():
            t=row.Index
            explicit = t in model
            require(bool(row.explicit_model_decision)==explicit and bool(row.model_input_row_present)==(t in original)
                    and bool(row.decision_input_row_present)==(t in decision_names), f"explicit/input flags: {label}/{t}")
            require(bool(row.signal_reserved)==(t in final_reserve), f"target reservation: {label}/{t}")
            semantic = "OPERATIONAL_EXIT_REQUIRED" if t in operation else (
                "MODEL_ACTIVE_EXIT" if explicit and model[t]==0 and t in held else
                "MODEL_ZERO_ALLOCATION" if explicit and model[t]==0 else
                "MODEL_TARGET_WEIGHT" if explicit else "MODEL_NO_DECISION")
            require(row.decision_semantic==semantic, f"decision semantic mislabel: {label}/{t}")
            kind = "EXIT" if t in operation else "HOLD_UNITS" if t in final_reserve else "TARGET_WEIGHT"
            require(row.order_type == kind, f"implicit liquidation order: {label}/{t}")
            if kind=="EXIT": require(row.target_weight==0, f"operational target not zero: {label}/{t}")
            if not explicit and t in held and t not in operation: model_omissions += 1
        op_group = op_groups.get(c.decision_id, ops.iloc[:0].set_index("ticker"))
        require(set(op_group.index)==set(operation), f"raw/action operational association: {label}")
        expected_ops={}
        if len(evidence):
            eligible_evidence=evidence.loc[evidence.known_at.le(c.signal_asof)&evidence.effective_date.le(c.signal_date)]
            expected_ops={str(e.ticker):e for e in eligible_evidence.itertuples(index=False)}
        require(set(operation)==set(expected_ops),f"operational schedule differs from signal-known evidence: {label}")
        for t, action in operation.items():
            saved=op_group.loc[t]
            require(bool(str(action["reason"]).strip()) and bool(str(action["source_id"]).strip()), "unproven operational action")
            require(pd.Timestamp(action["known_at"]) <= pd.Timestamp(c.signal_asof), f"future operational evidence: {label}/{t}")
            require(pd.Timestamp(saved.known_at)==pd.Timestamp(action["known_at"]) and saved.reason==action["reason"] and saved.source_id==action["source_id"], "operational output differs from raw action")
            ref=expected_ops[t]
            require(pd.Timestamp(saved.known_at)==ref.known_at and saved.reason==ref.reason and saved.source_id==ref.source_id,"operational output not bound to evidence CSV")
            require(bool(saved.had_position)==(t in held) and bool(saved.signal_sell_restricted)==(t in held and t in known_bad), "operational held/restriction flags")
            ops_checked += 1
        reserved_days += bool(final_reserve); reserved_positions += len(final_reserve)
    # Every actual fill and execution outcome must belong to the saved order.
    order = targets.set_index("order_id")
    require(events.order_id.isin(order.index).all() and trades.order_id.isin(order.index).all(), "orphan execution/fill")
    if len(events):
        linked = order.reindex(events.order_id)
        for col in ["decision_id", "ticker", "signal_date", "execution_date", "order_type", "decision_semantic"]:
            require(np.array_equal(events[col].to_numpy(), linked[col].to_numpy()), f"execution/order correlation: {col}")
        require(events.actual_names_at_event.between(0,meta["max_positions"]).all(), "intraday actual name cap")
        submitted=set(targets.loc[targets.status.eq("submitted"),"order_id"])
        require(set(events.order_id)==submitted, "submitted order lacks execution outcome")
        filled=events.loc[events.status.eq("FILLED")].set_index(["order_id","side"])
        saved=trades.set_index(["order_id","side"])
        require(not filled.index.duplicated().any() and set(filled.index)==set(saved.index), "fill receipt/trade one-to-one")
        for col in ["notional","index_units","transaction_cost"]:
            same(filled[col],saved[col].reindex(filled.index),f"fill receipt {col}")
        zero=events.loc[~events.status.eq("FILLED")]
        for col in ["notional","index_units","transaction_cost"]: same(zero[col],np.zeros(len(zero)),f"nonfill pretends {col}")
    else:
        require(trades.empty and targets.loc[targets.status.eq("submitted")].empty,"missing execution log")
    hold = targets.loc[targets.order_type.eq("HOLD_UNITS") & targets.status.eq("submitted")]
    preserve_ids=set(events.loc[events.status.eq("PRESERVED_UNITS"),"order_id"])
    require(set(hold.order_id)==preserve_ids,"HOLD_UNITS lacks exact preservation outcome")
    require(not trades.order_id.isin(hold.order_id).any(),"traded an implicit no-decision reservation")
    for r in hold.itertuples(index=False):
        same([actual_units.loc[r.execution_date,r.ticker]],[r.current_units],"HOLD_UNITS changed at next open")
    rejected=events.loc[events.status.eq("REJECTED")]
    require(rejected.execution_semantic.eq("EXECUTION_REJECTED").all(),"rejection mislabel")
    require(not trades.order_id.isin(rejected.order_id).any(),"rejected order also filled")
    sell_rejected=rejected.loc[rejected.side.eq("SELL")]
    for r in sell_rejected.itertuples(index=False):
        same([actual_units.loc[r.execution_date,r.ticker]],[order.loc[r.order_id,"current_units"]],"failed sell lost units")
    for r in rejected.loc[rejected.reason.isin(["MISSING_PRICE_ROW","PRICE_QUALITY_UNCERTIFIED","MISSING_OR_INVALID_OPEN"])].itertuples(index=False):
        value=pxidx.open.get((r.ticker,r.execution_date),np.nan)
        require(not np.isfinite(value),"price rejection contradicts certified saved open")
    if len(rejected):
        diagnostic=tables["diagnostics"].loc[tables["diagnostics"].get("phase",pd.Series(index=tables["diagnostics"].index,dtype=str)).eq("EXECUTION")]
        require(len(diagnostic)==len(rejected),"rejection/diagnostic count")
        require(set(zip(diagnostic.decision_id,diagnostic.ticker,diagnostic.rejection_reason))==set(zip(rejected.decision_id,rejected.ticker,rejected.reason)),"rejection diagnostic association")
    return dict(model_no_decision_held=model_omissions,preserved_unit_orders=len(hold),reserved_signal_days=reserved_days,
        reserved_position_days=reserved_positions,operational_actions=ops_checked,rejected_orders=len(rejected),
        failed_sells_units_preserved=len(sell_rejected),live_position_limit_blocks=int(rejected.reason.eq("LIVE_POSITION_LIMIT").sum()))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-partial",action="store_true")
    args=parser.parse_args()
    remember(Path(__file__))
    result={"status":"PENDING","allow_partial":args.allow_partial,"expected_runs":54,"training":None,"model_reuse":None,
            "scenarios":{},"pending":[],"material_issues":[],"scope":"saved decision/ledger/frozen-artifact audit; no model inference, fit or replay; not full-pool or shareholder-return certification",
            "verification_limits":"Original scores are linked to decisions, not recomputed. Source hashes and signal input/time/account fields are checked; execution quotes are used only for auditing actual fills and valuation."}
    def check(scope, callback):
        try:return callback()
        except FileNotFoundError as exc:
            result["pending"].append({"scope":scope,"missing":str(exc.filename)})
        except Exception as exc:
            result["material_issues"].append({"scope":scope,"error":f"{type(exc).__name__}: {exc}","traceback":traceback.format_exc()[-2200:]})
        return None
    result["training"]=check("training",training_audit)
    result["model_reuse"]=check("model_reuse",reuse_audit)
    inputs={}
    for year,cost in SCENARIOS:
        folder=ROOT/f"evaluation_{year}"/f"cost_{cost}"
        key=f"{year}/cost_{cost}"
        if not (folder/"COMPLETE.json").exists():
            result["pending"].append({"scope":key,"missing":"COMPLETE.json; no scenario outputs read"})
            continue
        def scenario():
            complete=read(folder/"COMPLETE.json");seal=read(folder/"FROZEN_BEFORE_REPLAY.json")
            roster=NAMES if year==2025 else TEST_NAMES
            require(complete["fit_attempts"]==0 and seal["fit_2026_rows"]==0,"fit during replay")
            require(complete["sources_unchanged"] and not complete["full_pool_complete"] and not seal["full_pool_complete"],"invalid completion scope")
            require(set(seal["roster"])==set(roster) and complete["policies"]==len(roster),"scenario roster")
            require(seal["year"]==year and float(seal["cost_bps"])==cost,"seal year/cost")
            for path,digest in seal["source_sha256"].items():remember(path,digest)
            if year==2026:supplemental_audit(folder)
            remember(folder/"comparison.csv");comparison=pd.read_csv(folder/"comparison.csv")
            require(set(comparison.policy)==set(roster) and len(comparison)==len(roster),"comparison roster")
            if year not in inputs:inputs[year]=load_inputs(year)
            panel,px,calendar=inputs[year]
            runs=[]
            for name in roster:
                row=check(f"{key}/{name}",lambda name=name:check_run(folder/name,panel,px,calendar,year,cost))
                if row:
                    reported=comparison.loc[comparison.policy.eq(name)].iloc[0]
                    for metric in ["days","trades","uncertified_days","max_actual_names"]:
                        require(int(reported[metric])==row[metric],f"comparison mismatch: {name}/{metric}")
                    runs.append(row)
                    print(json.dumps(dict(scope=f"{key}/{name}",status="PASS",trades=row["trades"],targets=row["target_rows"])),flush=True)
            return {"status":"PASS" if len(runs)==len(roster) else "FAIL","frozen_hashes_checked":len(seal["source_sha256"]),"runs":runs}
        result["scenarios"][key]=check(key,scenario)
    runs=[r for s in result["scenarios"].values() if s for r in s["runs"]]
    result["totals"]={"runs_checked":len(runs),"trades":sum(r["trades"] for r in runs),"buys":sum(r["buys"] for r in runs),
        "target_rows":sum(r["target_rows"] for r in runs),"raw_signals":sum(r["raw_signals"] for r in runs),
        "uncertified_scenarios":sum(r["uncertified_days"]>0 for r in runs),"uncertified_days":sum(r["uncertified_days"] for r in runs),
        "preserved_unit_orders":sum(r["preserved_unit_orders"] for r in runs),"failed_sells_units_preserved":sum(r["failed_sells_units_preserved"] for r in runs),
        "live_position_limit_blocks":sum(r["live_position_limit_blocks"] for r in runs),"unique_source_hashes_checked":len(SOURCE_HASHES)}
    for path,digest in list(SOURCE_HASHES.items()):check(f"unchanged/{path}",lambda path=path,digest=digest:require(sha(path)==digest,"source changed while auditing"))
    result["source_sha256"]=SOURCE_HASHES
    result["status"]="FAIL" if result["material_issues"] else "PASS" if not result["pending"] and len(runs)==54 else "PARTIAL_PASS" if args.allow_partial and runs else "PENDING"
    OUT.mkdir(exist_ok=True)
    (OUT/"VERIFICATION.json").write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    issues={"status":result["status"],"material_issues":result["material_issues"],"pending":result["pending"]}
    (OUT/"MATERIAL_ISSUES.json").write_text(json.dumps(issues,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({k:result[k] for k in ["status","totals","pending","material_issues"]},indent=2,ensure_ascii=False))
    return 1 if result["material_issues"] else 0 if result["status"] in ["PASS","PARTIAL_PASS"] else 2


if __name__=="__main__":raise SystemExit(main())
