"""Causal, feasible-account OOF panel; inference only for frozen experts.

No old experiment file is written. 2024 behavior is fixed before outcomes are
inspected: early HGB, original discrete allocator, original holding-aware ledger.
2025 account states come from the already sealed equal-weight/stack ledgers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
WS = ROOT.parent
FROZEN = WS / "a2_multimodel_joint_20260928"
sys.path.insert(0, str(FROZEN))

import numpy as np
import pandas as pd
import torch
from threadpoolctl import threadpool_limits
import ensemble as e
import values as v
from engine_v2 import HoldingAwareDecision, run_replay
from evaluate import forbid_fitting
from train_values import quota

OUT = ROOT / "panel_artifacts"
BEHAVIOR = ROOT / "behavior_2024"
SOURCE = WS / "a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet"
PRICE = WS / "a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet"
PATHS = {2024: ["fixed_early_hgb"], 2025: ["ensemble_equal_weight", "ensemble_stacked"]}
STAGES = {2024: "early", 2025: "validation"}
BUDGET = 10000
EXPERT_ORDER = e.META_FEATURES[:12]
BASIS_ORDER = e.META_FEATURES[14:]
STATE_ORDER = ["cash_weight", "current_weight", "available_slots", "realized_vol_20d"]
LEDGERS = ["daily", "trades", "positions", "target_decisions", "diagnostics",
           "valuation_intervals", "raw_model_outputs", "signal_contexts",
           "operational_actions", "execution_results"]


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                   allow_nan=False, default=str), encoding="utf-8")


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def checked(condition, message):
    if not bool(condition):
        raise RuntimeError(message)


def clocks_2024(calendar):
    # Original ledger uses explicit close information time. These are the
    # existing US equity half-session dates, not a new trading clock policy.
    half = {"2024-07-03", "2024-11-29", "2024-12-24"}
    return {d: (d + pd.Timedelta(hours=13 if str(d.date()) in half else 16))
            .tz_localize("America/New_York").tz_convert("UTC") for d in calendar}


class FixedEarlyHGB:
    """Frozen early expert and unchanged original allocator, no meta fit."""
    def __init__(self, base):
        checked(base.stage == "early", "2024_BEHAVIOR_REQUIRES_EARLY_EXPERT")
        self.base, self.age, self.calls = base, {}, 0

    def __call__(self, day, ctx):
        self.age = {t: self.age.get(t, 0) + 1 for t, w in ctx.current_weights.items() if w > 0}
        self.calls += 1
        day = day.loc[day.new_buy_eligible.astype(bool) |
                      day.ticker.map(ctx.current_weights).fillna(0).gt(0)]
        day = day.sort_values("ticker", kind="stable").reset_index(drop=True)
        names, n = day.ticker.tolist(), len(day)
        if not n:
            return HoldingAwareDecision(model_decisions={}, raw_model_outputs={})
        current = np.array([ctx.current_weights.get(t, 0.) for t in names])
        age = np.array([self.age.get(t, 0.) for t in names])
        features = v.mapped_features(np.repeat(day[v.FEATURES].to_numpy(float), 5, axis=0),
            np.repeat(current, 5), np.full(n * 5, ctx.cash_weight), np.repeat(age, 5),
            np.tile(v.ACTIONS, n))
        scores = v.predict_values(self.base.models["hgb"], "hgb", features).reshape(n, 5)
        eligible = day.new_buy_eligible.to_numpy(bool) & ~day.ticker.isin(ctx.buy_restricted_tickers).to_numpy()
        allowed = eligible[:, None] | (v.ACTIONS[None, :] <= current[:, None] + 1e-10)
        _, selected = v.allocate_joint_scores(scores, names, max_names=ctx.available_slots,
            max_units=min(38, int(np.floor((ctx.available_weight + 1e-12) / .025))), allowed=allowed)
        decisions = {t: float(v.ACTIONS[a]) for t, a in zip(names, selected)}
        raw = {t: {"action_values": scores[i].tolist(), "chosen_weight": decisions[t]}
               for i, t in enumerate(names)}
        return HoldingAwareDecision(model_decisions=decisions, raw_model_outputs=raw)


def behavior_2024(frame, prices, base, contract_hash):
    receipt_path = BEHAVIOR / "BEHAVIOR_RECEIPT.json"
    if receipt_path.exists():
        saved = json.loads(receipt_path.read_text(encoding="utf-8"))
        checked(saved["pre_panel_contract_sha256"] == contract_hash, "BEHAVIOR_CONTRACT_DRIFT")
        checked(all(sha(p) == h for p, h in saved["output_sha256"].items()), "BEHAVIOR_OUTPUT_DRIFT")
        return BEHAVIOR
    checked(not BEHAVIOR.exists(), "PRESERVE_INCOMPLETE_2024_BEHAVIOR")
    BEHAVIOR.mkdir()
    cal = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ") &
        prices.trade_date.dt.year.eq(2024), "trade_date"].unique()))
    mature = frame.signal_date.dt.year.eq(2024) & frame.label_available & frame.label_end_date.lt("2025-01-01")
    last = frame.loc[mature, "signal_date"].max()
    features = frame.loc[frame.signal_date.dt.year.eq(2024) & frame.signal_date.le(last),
                         ["signal_date", "ticker", "new_buy_eligible", *v.FEATURES]].copy()
    actor = FixedEarlyHGB(base)
    started = time.monotonic()
    result = run_replay(prices.loc[prices.trade_date.dt.year.eq(2024)].copy(), cal,
        features, actor, candidate="fixed_early_hgb", cost_bps=10., capacity_fraction=.01,
        signal_start="2024-01-01", signal_end=str(last.date()), signal_asof=clocks_2024(cal))
    for name in LEDGERS:
        getattr(result, name).to_parquet(BEHAVIOR / f"{name}.parquet", index=False)
    write(BEHAVIOR / "metadata.json", result.metadata)
    checked(result.daily.nav.notna().all(), "BEHAVIOR_UNKNOWN_NAV")
    checks = {name: float(result.daily[name].abs().max()) for name in
              ["nav_identity_error", "cash_flow_identity_error", "cost_identity_error", "open_self_finance_error"]}
    checked(max(checks.values()) < 1e-6, "BEHAVIOR_ACCOUNTING_IDENTITY")
    checked(result.daily.actual_name_count.le(20).all() & result.daily.cash.ge(-1e-7).all(), "BEHAVIOR_CONSTRAINT")
    outputs = [BEHAVIOR / f"{name}.parquet" for name in LEDGERS] + [BEHAVIOR / "metadata.json"]
    receipt = dict(status="PASS", behavior="PREDECLARED_EARLY_HGB_ORIGINAL_ALLOCATOR",
        original_engine=str(FROZEN / "engine_v2.py"), pre_panel_contract_sha256=contract_hash,
        expert_stage="early", actual_loaded_expert_sha256=base.hashes,
        expert_predictor_clocks=base.predictor_clocks, fit_calls=0,
        signal_start=str(features.signal_date.min().date()), signal_end=str(last.date()),
        signal_calls=actor.calls, calendar_days=len(cal), seconds=time.monotonic() - started,
        half_session_close_local_hours=13, half_sessions=["2024-07-03", "2024-11-29", "2024-12-24"],
        state_generation_reads_2025_prices=False, cost_bps=10., capacity_fraction=.01,
        max_positions=20, max_weight=.10, max_invested=.95, accounting_checks=checks,
        uncertified_valuation_days=int(result.daily.certified_nav.isna().sum()),
        output_sha256={str(p): sha(p) for p in outputs},
        note="Behavior chosen structurally before panel generation; its realized performance was not used to select a state path.")
    write(receipt_path, receipt)
    return BEHAVIOR


def account_keys(frame, prices, year, path, folder):
    """Reconstruct the exact pre-call account/age semantics from saved ledgers."""
    context_path, raw_path = folder / "signal_contexts.parquet", folder / "raw_model_outputs.parquet"
    contexts = pd.read_parquet(context_path).sort_values("signal_date", kind="stable")
    raw = pd.read_parquet(raw_path).set_index("signal_date", verify_integrity=True)
    checked(not contexts.signal_date.duplicated().any(), "DUPLICATE_SIGNAL_CONTEXT")
    checked(contexts.policy_called.all() & contexts.signal_date.dt.year.eq(year).all(), "INVALID_SIGNAL_CONTEXT")
    by_date = {d: g.set_index("ticker", verify_integrity=True) for d, g in
               frame.loc[frame.signal_date.dt.year.eq(year)].groupby("signal_date", sort=False)}
    quote = {(r.trade_date, r.ticker): (r.close, bool(r.price_quality_warning)) for r in
             prices.loc[prices.trade_date.dt.year.eq(year), ["trade_date", "ticker", "close", "price_quality_warning"]].itertuples()}
    age, rows = {}, []
    counts = dict(signal_days=len(contexts), candidate_rows=0, mature_candidates=0,
        label_missing_or_after_boundary=0, invalid_feature_rows=0, held_candidate_rows=0,
        reserved_held_rows=0, account_checks=0, candidate_input_qualification_checks=0,
        quarter_timing_checks=0, price_qualification_checks=0)
    for ctx in contexts.itertuples():
        date = pd.Timestamp(ctx.signal_date)
        current = json.loads(ctx.current_weights_json)
        units = json.loads(ctx.current_units_json)
        reserved = set(json.loads(ctx.reserved_tickers_json))
        age = {t: age.get(t, 0) + 1 for t, w in current.items() if w > 0}
        checked(len(current) <= 20 and len(units) <= 20 and all(w >= 0 for w in current.values()), "INVALID_ACCOUNT_HOLDINGS")
        checked(abs(float(ctx.cash_weight) + sum(current.values()) - 1.) < 1e-7 and ctx.cash >= -1e-7,
                "ACCOUNT_CASH_HOLDING_IDENTITY")
        checked(ctx.available_slots == 20 - len(reserved) and ctx.reserved_slots == len(reserved), "ACCOUNT_SLOT_IDENTITY")
        checked(abs(ctx.reserved_weight - sum(current.get(t, 0.) for t in reserved)) < 1e-7,
                "ACCOUNT_RESERVED_WEIGHT_IDENTITY")
        checked(abs(ctx.available_weight - max(0., .95 - ctx.reserved_weight)) < 1e-7, "ACCOUNT_AVAILABLE_WEIGHT_IDENTITY")
        counts["account_checks"] += 1
        r = raw.loc[date]
        decisions = json.loads(r.model_decisions_json)
        decision_names = set(json.loads(r.decision_input_tickers_json))
        source_names = set(json.loads(r.original_input_tickers_json))
        day = by_date[date]
        checked(source_names == set(day.index), "SAVED_SOURCE_CANDIDATES_DO_NOT_MATCH")
        checked(set(decisions).issubset(decision_names - reserved), "SAVED_DECISION_HAS_RESERVED_OR_ABSENT_NAME")
        counts["reserved_held_rows"] += len(reserved)
        for ticker in sorted(decisions):
            f = day.loc[ticker]
            c = float(current.get(ticker, 0.))
            eligible = bool(f.new_buy_eligible)
            checked(eligible or c > 0, "NEW_CANDIDATE_INELIGIBLE")
            counts["candidate_rows"] += 1
            counts["candidate_input_qualification_checks"] += 1
            counts["held_candidate_rows"] += int(c > 0)
            checked(pd.Timestamp(f.quarter_effective_date) <= date and
                    (pd.isna(f.next_quarter_effective_date) or date < pd.Timestamp(f.next_quarter_effective_date)),
                    "13F_QUARTER_NOT_EFFECTIVE_AT_SIGNAL")
            checked(pd.Timestamp(f.latest_filing_date) <= date, "13F_FILING_AFTER_SIGNAL")
            counts["quarter_timing_checks"] += 1
            close, warning = quote.get((date, ticker), (np.nan, True))
            buy_restricted = not (np.isfinite(close) and close > 0 and not warning)
            checked(not buy_restricted, "ACTIONABLE_SAVED_NAME_WITH_INVALID_SIGNAL_CLOSE")
            counts["price_qualification_checks"] += 1
            if not bool(f.label_available) or pd.isna(f.label_end_date) or f.label_end_date >= pd.Timestamp(f"{year+1}-01-01"):
                counts["label_missing_or_after_boundary"] += 1
                continue
            checked(f.label_end_date > date and f.execution_date > date and f.label_end_date > f.execution_date,
                    "INVALID_LABEL_MATURITY")
            if not np.isfinite(f[["y_next_open", *v.FEATURES]].to_numpy(float)).all() or f.avg_dollar_volume_20d <= 0:
                counts["invalid_feature_rows"] += 1
                continue
            counts["mature_candidates"] += 1
            rows.append(dict(year=year, behavior_path=path, expert_stage=STAGES[year], signal_date=date,
                ticker=ticker, label_end_date=f.label_end_date, execution_date=f.execution_date,
                new_buy_eligible=eligible, buy_restricted=buy_restricted, current_weight=c,
                cash_weight=float(ctx.cash_weight), age=int(age.get(ticker, 0)),
                available_slots=int(ctx.available_slots), available_weight=float(ctx.available_weight),
                reserved_slots=int(ctx.reserved_slots), reserved_weight=float(ctx.reserved_weight),
                realized_vol_20d=float(f.realized_vol_20d), avg_dollar_volume_20d=float(f.avg_dollar_volume_20d),
                nav=float(ctx.nav), source_row_id=int(f.source_row_id), active_13f_quarter=str(f.active_13f_quarter),
                quarter_effective_date=f.quarter_effective_date, latest_filing_date=f.latest_filing_date,
                y_next_open=float(f.y_next_open), held=c > 0,
                **{name: float(f[name]) for name in v.FEATURES if name not in ("realized_vol_20d", "avg_dollar_volume_20d")}))
    all_keys = pd.DataFrame(rows).sort_values(["signal_date", "ticker"], kind="stable").reset_index(drop=True)
    checked(len(all_keys) > 0, "NO_MATURE_ACCOUNT_ROWS")
    checked(not all_keys.duplicated(["behavior_path", "signal_date", "ticker"]).any(), "DUPLICATE_ACCOUNT_PANEL_KEY")
    counts["mature_dates"] = int(all_keys.signal_date.nunique())
    counts["input_sha256"] = {str(p): sha(p) for p in [context_path, raw_path]}
    return all_keys, counts


def sample_path(frame):
    counts = frame.groupby("signal_date", sort=True).size()
    allocation = quota(counts.to_numpy(), BUDGET)
    quotas = dict(zip(counts.index, allocation))
    held_counts = frame.groupby("signal_date", sort=True).held.sum()
    checked((held_counts.to_numpy() <= allocation).all(), "SAMPLING_BUDGET_CANNOT_KEEP_LEGAL_HELD")
    ranked = frame.copy()
    ranked["sample_hash"] = [hashlib.sha256(f"A2_CONTEXTUAL_STACKING_R1|{v.SEED}|{p}|{d.date()}|{t}".encode()).hexdigest()
        for p, d, t in zip(ranked.behavior_path, ranked.signal_date, ranked.ticker)]
    ranked = ranked.sort_values(["signal_date", "held", "sample_hash", "ticker"],
                               ascending=[True, False, True, True], kind="stable")
    picked = ranked.loc[ranked.groupby("signal_date", sort=False).cumcount().to_numpy() <
                        ranked.signal_date.map(quotas).to_numpy()]
    picked = picked.sort_values(["signal_date", "ticker"], kind="stable").reset_index(drop=True)
    checked(len(picked) == min(BUDGET, len(frame)), "SAMPLE_BUDGET_NOT_EXACT")
    checked(picked.signal_date.nunique() == frame.signal_date.nunique(), "MATURE_DATE_COVERAGE_LOST")
    checked(picked.held.sum() == frame.held.sum(), "HELD_SAMPLING_PRIORITY_LOST")
    return picked, dict(eligible_stock_dates=len(frame), sampled_stock_dates=len(picked),
        mature_dates=len(counts), quota_min=int(allocation.min()), quota_max=int(allocation.max()),
        eligible_held_rows=int(frame.held.sum()), sampled_held_rows=int(picked.held.sum()),
        held_priority_verified=True, all_mature_dates_preserved=True,
        first_signal=str(picked.signal_date.min().date()), last_signal=str(picked.signal_date.max().date()),
        label_end_max=str(picked.label_end_date.max().date()))


def build_matrix(keys, base):
    checked(keys.expert_stage.eq(base.stage).all(), "EXPERT_STAGE_MISMATCH")
    checked(pd.Timestamp(base.boundary) <= keys.signal_date.min(), "EXPERT_AFTER_OOF_SIGNAL")
    x = np.repeat(keys[v.FEATURES].to_numpy(float), 5, axis=0)
    current, cash, age = [np.repeat(keys[column].to_numpy(float), 5) for column in
                         ["current_weight", "cash_weight", "age"]]
    action = np.tile(v.ACTIONS, len(keys))
    with threadpool_limits(limits=2), torch.no_grad():
        matrix = base.matrix(x, current, cash, age, action)
    slots = np.repeat(keys.available_slots.to_numpy(float), 5)
    vol = np.repeat(keys.realized_vol_20d.to_numpy(float), 5)
    weight_budget = np.repeat(keys.available_weight.to_numpy(float), 5)
    new = np.repeat((keys.new_buy_eligible & ~keys.buy_restricted).to_numpy(bool), 5)
    allowed = (new | (action <= current + 1e-10)) & ((slots > 0) | (action == 0)) & (action <= weight_budget + 1e-10)
    checked(allowed.reshape(-1, 5)[:, 0].all(), "ZERO_ACTION_MUST_BE_ALLOWED")
    actual = current.copy()
    adv = np.repeat(keys.avg_dollar_volume_20d.to_numpy(float), 5)
    for a in v.ACTIONS:
        loc = action == a
        buy = loc & (a > current)
        sell = loc & ~buy
        actual[buy] = current[buy] + np.minimum(a - current[buy], v.CAPACITY_FRACTION * adv[buy] / v.NOMINAL_CASH)
        actual[sell] = a
    # This exactly preserves the old single-stock label, including fixed nominal
    # capital; real dynamic NAV/cash/capacity is evaluated separately in ledgers.
    forward = np.repeat(keys.y_next_open.to_numpy(float), 5)
    common = -v.COST * np.abs(actual - current) - .5 * v.RISK_AVERSION * vol**2 * actual**2
    target_clip = actual * np.clip(forward, -.2, .2) + common
    target_unclipped = actual * forward + common
    row_dates = np.repeat(keys.signal_date.to_numpy(dtype="datetime64[D]"), 5)
    row_paths = np.repeat(keys.behavior_path.to_numpy(str), 5)
    grouping = pd.DataFrame({"date": row_dates, "path": row_paths, "allowed": allowed.astype(float)})
    path_allowed_count = grouping.groupby(["date", "path"])["allowed"].transform("sum").to_numpy()
    paths_per_date = grouping.groupby("date")["path"].transform("nunique").to_numpy()
    weights = allowed.astype(float) / path_allowed_count / paths_per_date
    checked(np.isfinite(matrix).all() and np.isfinite(target_clip).all() and np.isfinite(target_unclipped).all(), "NONFINITE_PANEL_MATRIX")
    checked(np.allclose(pd.Series(weights).groupby(pd.Series(row_dates)).sum().to_numpy(), 1.), "DATE_WEIGHT_NOT_EQUAL")
    audit = dict(action_rows=len(action), allowed_rows=int(allowed.sum()),
        disallowed_rows=int((~allowed).sum()), capacity_limited_buy_rows=int(((action > current) & (actual < action - 1e-12)).sum()),
        clip_affected_rows=int((target_clip != target_unclipped).sum()),
        min_daily_total_weight=float(pd.Series(weights).groupby(pd.Series(row_dates)).sum().min()),
        max_daily_total_weight=float(pd.Series(weights).groupby(pd.Series(row_dates)).sum().max()))
    arrays = dict(p=matrix[:, :12], basis=matrix[:, 14:], z=np.column_stack([cash, current, slots, vol]),
        target_clip=target_clip, target_unclipped=target_unclipped, allowed=allowed,
        row_dates=row_dates, weights=weights, expert_order=np.asarray(EXPERT_ORDER, str),
        basis_order=np.asarray(BASIS_ORDER, str), state_order=np.asarray(STATE_ORDER, str), actions=v.ACTIONS)
    return arrays, audit


def support(keys):
    z = keys[STATE_ORDER].to_numpy(float)
    std = z.std(axis=0)
    normalized = (z - z.mean(axis=0)) / np.where(std > 0, std, 1.)
    affine_rank = int(np.linalg.matrix_rank(np.column_stack([np.ones(len(z)), normalized])))
    # Old grid relation was cash = .95 - 9*current. Measure its direct departure.
    relation_error = keys.cash_weight.to_numpy() - (.95 - 9 * keys.current_weight.to_numpy())
    cash_current = float(np.corrcoef(keys.cash_weight, keys.current_weight)[0, 1])
    return dict(stock_dates=len(keys), dates=int(keys.signal_date.nunique()),
        state_order=STATE_ORDER, min=dict(zip(STATE_ORDER, z.min(axis=0).tolist())),
        max=dict(zip(STATE_ORDER, z.max(axis=0).tolist())),
        mean=dict(zip(STATE_ORDER, z.mean(axis=0).tolist())),
        standard_deviation=dict(zip(STATE_ORDER, std.tolist())),
        quantiles={name: keys[name].quantile([0., .01, .05, .5, .95, .99, 1.]).to_dict() for name in STATE_ORDER},
        affine_state_rank=affine_rank, full_affine_state_rank=5,
        cash_current_correlation=cash_current, old_cash_current_relation_max_abs_error=float(np.abs(relation_error).max()),
        old_cash_current_relation_rmse=float(np.sqrt(np.mean(relation_error**2))),
        unique_cash_current_pairs=int(keys[["cash_weight", "current_weight"]].drop_duplicates().shape[0]),
        held_fraction=float(keys.held.mean()),
        cash_on_unheld_min=float(keys.loc[~keys.held, "cash_weight"].min()),
        cash_on_unheld_max=float(keys.loc[~keys.held, "cash_weight"].max()),
        expert_grid_outside_rows=int((keys.cash_weight.gt(.95) | keys.cash_weight.lt(.05) |
                                    keys.current_weight.gt(.1) | keys.age.gt(40)).sum()),
        limitation="Actual account states are feasible and noncollinear. Frozen experts still extrapolate outside their old three-state training grid; state coverage does not remove that limitation.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    checked(not (OUT / "PANEL_RECEIPT.json").exists(), "COMPLETED_PANEL_MUST_REMAIN_FROZEN")
    guard = forbid_fitting()
    torch.set_num_threads(2)
    bases = {year: e.BaseBundle(STAGES[year]) for year in [2024, 2025]}
    paths = [SOURCE, PRICE, OUT / "schema.json", Path(__file__), FROZEN / "ensemble.py",
             FROZEN / "values.py", FROZEN / "train_values.py", FROZEN / "neural.py", FROZEN / "engine_v2.py"]
    for path in PATHS[2025]:
        folder = FROZEN / "evaluation_2025/cost_10" / path
        paths += [folder / "signal_contexts.parquet", folder / "raw_model_outputs.parquet"]
    input_hashes = {str(p): sha(p) for p in paths}
    for base in bases.values():
        input_hashes.update(base.hashes)
    contract = dict(status="PRE_PANEL_LOCKED", experiment="A2_CONTEXTUAL_STACKING_R1",
        account_paths=PATHS, expert_stages=STAGES, budget_stock_dates_per_path_year=BUDGET,
        sampling="date count-only waterfill, all legal matured held prioritized, stable SHA256 supplement",
        label="original nominal 1000000 single-stock capacity/cost/risk, clip +/-0.20 train, raw evaluation",
        individual_allowed="new eligible or no increase; zero slots forbids positive targets; target<=available_weight",
        date_weight="each path has equal weight within a signal day; legal actions equal within path; each calendar signal day sums to one",
        new_expert_fit_calls=0, source_sha256=input_hashes,
        actual_loaded_experts={str(y): dict(stage=b.stage, hashes=b.hashes, clocks=b.predictor_clocks) for y,b in bases.items()},
        forbidden="all estimator fitting, 2026 data, outcome-based behavior selection, changes to old files",
        planned_output_schema_sha256=sha(OUT / "schema.json"))
    pre_contract = OUT / "PRE_PANEL_CONTRACT.json"
    if pre_contract.exists():
        checked(args.resume, "PANEL_RESTART_REQUIRES_EXPLICIT_RESUME")
        checked(json.loads(pre_contract.read_text(encoding="utf-8")) == json.loads(json.dumps(contract)), "PANEL_CONTRACT_DRIFT")
    else:
        write(pre_contract, contract)
    contract_hash = sha(pre_contract)
    columns = list(dict.fromkeys(["signal_date", "ticker", "label_end_date", "label_available",
        "execution_date", "new_buy_eligible", "y_next_open", "active_13f_quarter", "quarter_effective_date",
        "latest_filing_date", "next_quarter_effective_date", *v.FEATURES]))
    frame = pd.read_parquet(SOURCE, columns=columns)
    frame["source_row_id"] = np.arange(len(frame))
    checked(frame.signal_date.lt("2026-01-01").all(), "PHYSICAL_SOURCE_AFTER_BOUNDARY")
    checked(not frame.duplicated(["signal_date", "ticker"]).any(), "SOURCE_DUPLICATE_KEY")
    # Predicate filtering ensures the 2024 generator receives no 2025 price
    # rows. Later years are loaded separately only for their own saved states.
    prices_2024 = pd.read_parquet(PRICE, filters=[("trade_date", ">=", pd.Timestamp("2024-01-01")),
                                                ("trade_date", "<", pd.Timestamp("2025-01-01"))])
    if "price_quality_warning" not in prices_2024:
        prices_2024["price_quality_warning"] = False
    else:
        prices_2024["price_quality_warning"] = prices_2024.price_quality_warning.fillna(True).astype(bool)
    checked(prices_2024.trade_date.dt.year.eq(2024).all(), "2024_BEHAVIOR_RECEIVED_LATER_PRICES")
    behavior_folder = behavior_2024(frame, prices_2024, bases[2024], contract_hash)
    audits, samplings, states, artifacts = {}, {}, {}, {}
    for year in [2024, 2025]:
        prices = prices_2024 if year == 2024 else pd.read_parquet(PRICE,
            filters=[("trade_date", ">=", pd.Timestamp("2025-01-01")),
                     ("trade_date", "<", pd.Timestamp("2026-01-01"))])
        if "price_quality_warning" not in prices:
            prices["price_quality_warning"] = False
        else:
            prices["price_quality_warning"] = prices.price_quality_warning.fillna(True).astype(bool)
        checked(prices.trade_date.dt.year.eq(year).all(), "YEAR_PRICE_FILTER_FAILED")
        pieces = []
        audits[str(year)], samplings[str(year)] = {}, {}
        for path in PATHS[year]:
            folder = behavior_folder if year == 2024 else FROZEN / "evaluation_2025/cost_10" / path
            all_keys, audit = account_keys(frame, prices, year, path, folder)
            picked, sampling = sample_path(all_keys)
            pieces.append(picked)
            audits[str(year)][path], samplings[str(year)][path] = audit, sampling
        keys = pd.concat(pieces, ignore_index=True).sort_values(["behavior_path", "signal_date", "ticker"], kind="stable").reset_index(drop=True)
        keys["key_id"] = np.arange(len(keys))
        print(json.dumps(dict(status="BUILDING_FROZEN_EXPERT_OOF", year=year,
                             stock_dates=len(keys), expert_stage=bases[year].stage)), flush=True)
        arrays, label_audit = build_matrix(keys, bases[year])
        matrix_path, keys_path = OUT / f"panel_{year}.npz", OUT / f"panel_keys_{year}.parquet"
        np.savez_compressed(matrix_path, **arrays)
        keys.to_parquet(keys_path, index=False)
        states[str(year)] = support(keys)
        checked(states[str(year)]["affine_state_rank"] == 5, "REAL_STATES_STILL_AFFINE_COLLINEAR")
        write(OUT / f"state_support_{year}.json", states[str(year)])
        artifacts[str(year)] = dict(matrix_path=str(matrix_path), matrix_sha256=sha(matrix_path),
            keys_path=str(keys_path), keys_sha256=sha(keys_path), row_count=len(arrays["p"]),
            stock_date_count=len(keys), dates=int(keys.signal_date.nunique()),
            label_end_max=str(keys.label_end_date.max().date()), label_audit=label_audit)
        print(json.dumps(dict(status="PANEL_YEAR_COMPLETE", year=year,
                             stock_dates=len(keys), rows=len(arrays["p"]), allowed=label_audit["allowed_rows"])), flush=True)
    checked(guard["attempts"] == 0, "FROZEN_EXPERT_FIT_ATTEMPT")
    checked(all(sha(p) == h for p, h in input_hashes.items()), "INPUT_CHANGED_DURING_PANEL")
    receipt = dict(status="PASS", experiment="A2_CONTEXTUAL_STACKING_R1", created_utc=pd.Timestamp.now(tz="UTC").isoformat(),
        pre_panel_contract_sha256=contract_hash, source_sha256=input_hashes,
        actual_loaded_experts=contract["actual_loaded_experts"], account_validation=audits,
        sampling=samplings, state_support=states, artifacts=artifacts,
        expert_fit_attempts=guard["attempts"], fit_2026_rows=0, read_2026_rows=0,
        date_weighted=True, all_source_hashes_unchanged=True,
        row_semantics="Stock-date-action rows share dates, accounts and market information; they are not independent trials.")
    write(OUT / "PANEL_RECEIPT.json", receipt)
    report = ["# A2_CONTEXTUAL_STACKING_R1 可行账户样本外面板", "",
        "专家只推理；2024使用2023年截止工件，2025使用2024年截止工件。2024行为路径预先固定为早期HGB和原分配器/账本；2025直接复用已冻结等权与堆叠账户。", "",
        "每条路径每年10000股票日，按日期计数分配额度，保留全部合法且标签成熟的持仓，再用稳定哈希补样。五个动作共享股票日，训练只用合法动作，日期内各行为路径等权、路径内合法动作等权，每个日期总权重等于1。", "",
        "| 年份 | 路径 | 股票日 | 日期 | 动作行 | 合法动作 | 标签成熟末日 |", "|---|---|---:|---:|---:|---:|---|"]
    for year in [2024, 2025]:
        a = artifacts[str(year)]
        report.append(f"| {year} | {', '.join(PATHS[year])} | {a['stock_date_count']} | {a['dates']} | {a['row_count']} | {a['label_audit']['allowed_rows']} | {a['label_end_max']} |")
    report += ["", "状态直接来自原生产定义：现金比例、当前该股仓位、可用名额（20减保留持仓）、realized_vol_20d。各年的标准化增广状态矩阵均满秩5，现金与仓位不再满足旧三状态现金=.95−9×仓位关系。", "",
        "标签保留旧100万美元名义本金、单股1% ADV容量、单边10bp和风险系数4的一步效用。训练截断远期收益为±20%，评价保存原始收益。真实账户现金和动态本金属于完整账本评价；这里不增加第二套成本、风险或容量规则。", "",
        "这改善融合层状态覆盖，但冻结专家原来的三状态训练外推限制仍存在。详细范围、网格外样本和样本资格检查在PANEL_RECEIPT.json及state_support文件；所有实际加载专家hash、标签截止和源文件hash均保留。"]
    (OUT / "PANEL_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(dict(status="PASS", expert_fit_attempts=0, years=[2024, 2025])), flush=True)


if __name__ == "__main__":
    main()
