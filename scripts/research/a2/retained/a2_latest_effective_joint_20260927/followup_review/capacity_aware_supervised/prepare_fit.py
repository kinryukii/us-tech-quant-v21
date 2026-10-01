"""Pre-2026, versioned capacity-aware HGB labels and two fixed fits.

Only the original engine creates durable behavior accounts.  The one-step
label calculator is separately checked trade-for-trade against that engine.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.metrics import mean_squared_error
from threadpoolctl import threadpool_limits

ROOT = Path("/joint")
HERE = ROOT / "followup_review" / "capacity_aware_supervised"
OUT = Path("/out")
SOURCE = ROOT / "data" / "pre2026_joint_context.parquet"
PRICE = Path("/external/pre2026_original_price_coordinate.parquet")
OOF = Path("/external/pre2026_oof.parquet")
OOF_LOG = Path("/external/fit_log.json")
V2_KEYS = ROOT / "joint_linear_tree_coverage_v2" / "out"
STAGES = {"validation": pd.Timestamp("2025-01-01"),
          "final": pd.Timestamp("2026-01-01"),
          "validation_metrics": pd.Timestamp("2026-01-01")}
REGIMES = (1, 10, 19)

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import joint_linear_tree as original  # noqa: E402
from engine import _validate_targets, run_replay  # noqa: E402
from one_step_label import CloseState, UnknownMark, settle  # noqa: E402


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False,
                               default=str, allow_nan=False), encoding="utf-8")


def source_boundary(path: Path, column: str) -> dict:
    parquet = pq.ParquetFile(path)
    col = parquet.schema.names.index(column)
    minima, maxima = [], []
    for i in range(parquet.metadata.num_row_groups):
        stats = parquet.metadata.row_group(i).column(col).statistics
        if stats is None or not stats.has_min_max:
            raise RuntimeError(f"MISSING_DATE_ROW_GROUP_STATS:{path.name}:{i}")
        low, high = pd.Timestamp(stats.min), pd.Timestamp(stats.max)
        if high >= pd.Timestamp("2026-01-01"):
            raise RuntimeError(f"POST2025_SOURCE:{path.name}:{i}")
        minima.append(low)
        maxima.append(high)
    return dict(rows=parquet.metadata.num_rows, row_groups=len(minima),
                min=str(min(minima)), max=str(max(maxima)))


def validate_oof_log() -> list[dict]:
    log = json.loads(OOF_LOG.read_text(encoding="utf-8"))
    expected = {
        2023: ("DEVELOPMENT", "2022-12-30"),
        2024: ("CONFIRMATION", "2023-12-29"),
        2025: ("FINAL", "2024-12-31"),
    }
    records = []
    for year, (stage, max_end) in expected.items():
        found = [r for r in log if r.get("year") == year and r.get("stage") == stage and r.get("method") == "hgb"]
        if len(found) != 1 or found[0]["train_target_end_max"] != max_end:
            raise RuntimeError(f"OOF_LINEAGE_INVALID:{year}")
        if pd.Timestamp(max_end) >= pd.Timestamp(f"{year}-01-01"):
            raise RuntimeError(f"OOF_TRAIN_TARGET_OVERLAP:{year}")
        records.append(dict(year=year, stage=stage, train_target_end_max=max_end,
                            model_sha256=found[0]["model_sha256"]))
    return records


def load_sources() -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex, dict]:
    boundaries = {
        "joint": source_boundary(SOURCE, "signal_date"),
        "price": source_boundary(PRICE, "trade_date"),
        "oof": source_boundary(OOF, "signal_date"),
    }
    if any(item["rows"] == 0 for item in boundaries.values()):
        raise RuntimeError("EMPTY_PRE2026_SOURCE")
    required = ["signal_date", "ticker", "label_end_date", "label_available",
                "new_buy_eligible", "y_next_open", *original.FEATURES]
    panel = pd.read_parquet(SOURCE, columns=required)
    score = pd.read_parquet(OOF, columns=["signal_date", "ticker", "stage", "prediction"])
    assert len(panel) == len(score) == 313668, "UNEXPECTED_PRE2026_KEY_COUNT"
    if panel.duplicated(["signal_date", "ticker"]).any() or score.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("DUPLICATE_PRE2026_KEY")
    panel = panel.merge(score, on=["signal_date", "ticker"], how="left",
                        validate="one_to_one", indicator=True)
    if not panel._merge.eq("both").all() or panel.prediction.isna().any():
        raise RuntimeError("OOF_KEY_OR_SCORE_MISSING")
    panel = panel.drop(columns="_merge")
    correct_stage = {2023: "DEVELOPMENT", 2024: "CONFIRMATION", 2025: "FINAL"}
    if not panel.stage.eq(panel.signal_date.dt.year.map(correct_stage)).all():
        raise RuntimeError("OOF_STAGE_DATE_MISMATCH")
    if not panel.new_buy_eligible.all():
        raise RuntimeError("UNEXPECTED_INELIGIBLE_PRE2026_BEHAVIOR_POOL")
    if not np.isfinite(panel[[*original.FEATURES, "prediction"]].to_numpy(float)).all():
        raise RuntimeError("NONFINITE_BEHAVIOR_OBSERVATION")
    prices = pd.read_parquet(PRICE, columns=["ticker", "trade_date", "open", "close"])
    if prices.duplicated(["trade_date", "ticker"]).any():
        raise RuntimeError("DUPLICATE_PRICE_KEY")
    if panel.signal_date.max() >= pd.Timestamp("2026-01-01") or prices.trade_date.max() >= pd.Timestamp("2026-01-01"):
        raise RuntimeError("TEST_YEAR_LOADED")
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    if calendar.empty or calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise RuntimeError("BAD_PRE2026_CALENDAR")
    return panel, prices, calendar, boundaries


def behavior_targets(day: pd.DataFrame, top_n: int) -> dict[str, float]:
    eligible = day.loc[day.new_buy_eligible].sort_values(
        ["prediction", "ticker"], ascending=[False, True], kind="mergesort")
    result = {str(t): .05 for t in eligible.head(top_n).ticker}
    assert len(result) <= top_n and sum(result.values()) <= .95 + 1e-10
    return result


def behavior_paths(panel: pd.DataFrame, prices: pd.DataFrame,
                   calendar: pd.DatetimeIndex) -> tuple[dict, list[dict]]:
    """Run exactly 3 account regimes x 3 annual pre-2026 episodes."""
    states: dict[tuple[pd.Timestamp, int], tuple[CloseState, dict[str, float], dict[str, int], bool]] = {}
    audits = []
    for year in (2023, 2024, 2025):
        year_panel = panel.loc[panel.signal_date.dt.year.eq(year),
                               ["signal_date", "ticker", "new_buy_eligible",
                                "prediction", "avg_dollar_volume_20d"]].copy()
        dates = calendar[calendar.year == year]
        if year_panel.signal_date.nunique() != len(dates):
            raise RuntimeError(f"INCOMPLETE_BEHAVIOR_SIGNAL_DATES:{year}")
        after = calendar[calendar > dates[-1]][:2]
        annual_calendar = dates.append(after)
        annual_prices = prices.loc[prices.trade_date.isin(annual_calendar)].copy()
        for top_n in REGIMES:
            def policy(day, _weights, _cash, *, n=top_n):
                return behavior_targets(day, n)
            with threadpool_limits(limits=2):
                replay = run_replay(
                    annual_prices, annual_calendar, year_panel, policy,
                    candidate=f"behavior_top{top_n}_{year}", initial_cash=1_000_000.,
                    cost_bps=10., capacity_fraction=.01, max_weight=.1,
                    max_positions=20, max_invested=.95, missing_signal_policy="cash",
                    signal_start=dates[0], signal_end=dates[-1],
                )
            daily = replay.daily.set_index("date")
            pos = {d: group for d, group in replay.positions.groupby("date", sort=False)}
            ages: dict[str, int] = {}
            for date in dates:
                row = daily.loc[date]
                group = pos.get(date)
                units = {} if group is None else dict(zip(group.ticker, group.index_units))
                weights = {} if group is None else dict(zip(group.ticker, group.weight))
                ages = {t: ages.get(t, 0) + 1 for t, q in units.items() if q > 0}
                state = CloseState(float(row.cash), float(row.nav), units)
                states[(date, top_n)] = (state, weights, ages.copy(),
                                          row.valuation_status == "certified")
            account_cols = ("cash_flow_identity_error", "cost_identity_error",
                            "open_self_finance_error", "nav_identity_error")
            errors = {c: float(replay.daily[c].abs().max()) for c in account_cols}
            if any(not np.isfinite(v) or v >= 1e-6 for v in errors.values()):
                raise RuntimeError(f"BEHAVIOR_ACCOUNT_IDENTITY:{year}:{top_n}:{errors}")
            audits.append(dict(year=year, top_n=top_n, dates=len(dates),
                               account_days=len(replay.daily), trades=len(replay.trades),
                               capacity_limited_events=int(replay.diagnostics.code.eq("capacity_limited").sum())
                                  if not replay.diagnostics.empty else 0,
                               uncertified_days=int(replay.daily.valuation_status.ne("certified").sum()),
                               max_abs_account_error=max(errors.values()),
                               terminal_nav=float(replay.daily.nav.iloc[-1])))
            del replay, daily, pos
            gc.collect()
    return states, audits


def sample_keys(stage: str, panel: pd.DataFrame, calendar_next2: dict) -> pd.DataFrame:
    keys = pd.read_parquet(V2_KEYS / f"sample_keys_{stage}.parquet")
    if keys.duplicated(["signal_date", "ticker"]).any() or keys.empty:
        raise RuntimeError(f"BAD_V2_KEYS:{stage}")
    if stage == "validation_metrics" and not keys.signal_date.dt.year.eq(2025).all():
        raise RuntimeError("VALIDATION_METRICS_NOT_2025")
    cutoff = STAGES[stage]
    if not keys.signal_date.lt(cutoff).all() or not keys.label_end_date.lt(cutoff).all():
        raise RuntimeError(f"IMMATURE_V2_KEYS:{stage}")
    x = keys.merge(panel[["signal_date", "ticker", "label_end_date", "label_available",
                          "y_next_open", *original.FEATURES]], on=["signal_date", "ticker"],
                   how="left", validate="one_to_one", suffixes=("_key", "_source"), indicator=True)
    if not x._merge.eq("both").all() or not x.label_available.all():
        raise RuntimeError(f"V2_KEY_MISSING_MATURE_SOURCE:{stage}")
    if not x.label_end_date_key.eq(x.label_end_date_source).all():
        raise RuntimeError(f"V2_KEY_LABEL_END_CHANGED:{stage}")
    if not x.label_end_date_key.eq(x.signal_date.map(calendar_next2)).all():
        raise RuntimeError(f"V2_KEY_NOT_NEXT_TWO_SESSIONS:{stage}")
    if not np.isfinite(x[["y_next_open", *original.FEATURES]].to_numpy(float)).all():
        raise RuntimeError(f"V2_KEY_NONFINITE_LABEL_OR_FEATURE:{stage}")
    return x[["signal_date", "ticker", "label_end_date_key"]].rename(
        columns={"label_end_date_key": "label_end_date"})


def labels_for_stage(stage: str, keys: pd.DataFrame, panel: pd.DataFrame,
                     states: dict, calendar_next: dict, calendar_next2: dict,
                     opens: dict) -> tuple[pd.DataFrame, dict]:
    by_date = {d: group.set_index("ticker") for d, group in panel.groupby("signal_date", sort=False)}
    counts = Counter()
    records: list[dict] = []
    robust = stage != "validation_metrics"
    for row in keys.itertuples(index=False):
        date, ticker = row.signal_date, row.ticker
        day = by_date[date]
        adv = day.avg_dollar_volume_20d.to_dict()
        eligibility = day.new_buy_eligible.to_dict()
        next_date, last_date = calendar_next[date], calendar_next2[date]
        open1, open2 = opens.get(next_date, {}), opens.get(last_date, {})
        signal_vol = float(day.loc[ticker, "realized_vol_20d"])
        ticker_adv = float(day.loc[ticker, "avg_dollar_volume_20d"])
        for regime in REGIMES:
            state, current_weights, ages, certified = states[(date, regime)]
            counts["attempted_regime_keys"] += 1
            if not certified or not np.isfinite(state.nav) or state.nav <= 0:
                counts["uncertified_signal_account"] += 1
                continue
            targets_base = behavior_targets(day.reset_index(), regime)
            zero_target = dict(targets_base)
            zero_target.pop(ticker, None)
            zero_target = _validate_targets(zero_target, .1, 20, .95)
            try:
                zero = settle(state, zero_target, open1, open2, adv, eligibility,
                              clipped_following_return=robust)
            except UnknownMark as exc:
                counts[str(exc)] += 1
                continue
            current = float(current_weights.get(ticker, 0.))
            cash_weight = float(state.cash / state.nav)
            age = int(ages.get(ticker, 0))
            capacity_weight = max(0., .01 * ticker_adv / state.nav) if np.isfinite(ticker_adv) else 0.
            for action in original.ACTIONS:
                counts["attempted_actions"] += 1
                target = dict(targets_base)
                if action <= 0:
                    target.pop(ticker, None)
                else:
                    target[ticker] = float(action)
                try:
                    target = _validate_targets(target, .1, 20, .95)
                except ValueError:
                    counts["target_infeasible"] += 1
                    continue
                if action <= 0:
                    result = zero
                else:
                    try:
                        result = settle(state, target, open1, open2, adv, eligibility,
                                        clipped_following_return=robust)
                    except UnknownMark as exc:
                        counts[str(exc)] += 1
                        continue
                if not np.isclose(result.pretrade_nav, zero.pretrade_nav, rtol=1e-11, atol=1e-5):
                    raise RuntimeError("COUNTERFACTUAL_PRETRADE_NAV_CHANGED")
                weight = (result.units.get(ticker, 0.) * float(open1[ticker]) / result.posttrade_nav
                          if ticker in result.units else 0.)
                zero_weight = (zero.units.get(ticker, 0.) * float(open1[ticker]) / zero.posttrade_nav
                               if ticker in zero.units else 0.)
                risk = .5 * original.RISK_AVERSION * signal_vol**2 * (weight**2 - zero_weight**2)
                value = (result.following_open_nav - zero.following_open_nav) / zero.pretrade_nav - risk
                if not np.isfinite(value):
                    raise RuntimeError("NONFINITE_CAPACITY_ACTION_LABEL")
                records.append(dict(signal_date=date, ticker=ticker, label_end_date=last_date,
                                    regime=regime, current_weight=current, cash_weight=cash_weight,
                                    held_age=age, capacity_weight=capacity_weight,
                                    action=float(action), value=float(value),
                                    actual_filled_weight=float(weight),
                                    actual_buy_cash_scale=float(result.buy_cash_scale),
                                    capacity_limited_buys=result.capacity_limited_buys))
                counts["valid_actions"] += 1
    labels = pd.DataFrame.from_records(records)
    if labels.empty or labels.duplicated(["signal_date", "ticker", "regime", "action"]).any():
        raise RuntimeError(f"EMPTY_OR_DUPLICATE_CAPACITY_LABELS:{stage}")
    if labels.signal_date.max() >= STAGES[stage] or labels.label_end_date.max() >= STAGES[stage]:
        raise RuntimeError(f"CAPACITY_LABEL_CROSSES_FOLD:{stage}")
    if not set(keys.signal_date).issubset(set(labels.signal_date)):
        raise RuntimeError(f"ORIGINAL_SAMPLE_DATE_LOST:{stage}")
    audit = dict(stage=stage, original_sample_keys=len(keys),
                 original_sample_dates=keys.signal_date.nunique(),
                 kept_sample_dates=labels.signal_date.nunique(),
                 kept_sample_keys=labels[["signal_date", "ticker"]].drop_duplicates().shape[0],
                 output_rows=len(labels), label_end_max=str(labels.label_end_date.max().date()),
                 counts=dict(counts), clipped_training=robust)
    return labels, audit


def verify_real_engine_steps(panel: pd.DataFrame, prices: pd.DataFrame,
                             states: dict, calendar_next: dict,
                             calendar_next2: dict, opens: dict) -> dict:
    """Check actual pre-2026 behavior states before creating any fit labels."""
    keys = pd.concat([pd.read_parquet(V2_KEYS / f"sample_keys_{stage}.parquet")
                      for stage in STAGES], ignore_index=True)
    keys = keys.drop_duplicates(["signal_date", "ticker"]).sort_values(
        ["signal_date", "ticker"], kind="mergesort")
    dates = {d: g.copy() for d, g in panel.groupby("signal_date", sort=False)}
    cases: list[dict] = []
    for year in (2023, 2024, 2025):
        year_keys = keys.loc[keys.signal_date.dt.year.eq(year), ["signal_date", "ticker"]]
        for regime in REGIMES:
            for action in (0., .05):
                chosen = None
                for key in year_keys.itertuples(index=False):
                    date, ticker = key.signal_date, key.ticker
                    state, _, _, certified = states[(date, regime)]
                    if not certified:
                        continue
                    day = dates[date]
                    base = behavior_targets(day, regime)
                    target = dict(base)
                    if action == 0:
                        target.pop(ticker, None)
                    else:
                        target[ticker] = action
                    try:
                        target = _validate_targets(target, .1, 20, .95)
                    except ValueError:
                        continue
                    d1, d2 = calendar_next[date], calendar_next2[date]
                    adv = dict(zip(day.ticker, day.avg_dollar_volume_20d))
                    eligible = dict(zip(day.ticker, day.new_buy_eligible))
                    try:
                        expected = settle(state, target, opens[d1], opens[d2], adv, eligible)
                    except UnknownMark:
                        continue
                    chosen = (date, ticker, state, day, target, d1, d2, expected)
                    break
                if chosen is None:
                    raise RuntimeError(f"NO_VALID_REAL_ENGINE_CHECK:{year}:{regime}:{action}")
                date, ticker, state, day, target, d1, d2, expected = chosen
                subset_prices = prices.loc[prices.trade_date.isin((date, d1, d2))]
                subset_features = day[["signal_date", "ticker", "avg_dollar_volume_20d",
                                       "new_buy_eligible"]].copy()
                with threadpool_limits(limits=2):
                    actual = run_replay(
                        subset_prices, pd.DatetimeIndex([date, d1, d2]), subset_features,
                        lambda *_: target, candidate="real_capacity_label_check",
                        initial_cash=state.cash, initial_positions=state.units,
                        cost_bps=10., capacity_fraction=.01,
                        max_weight=.1, max_positions=20, max_invested=.95,
                        missing_signal_policy="hold", signal_start=date, signal_end=date,
                    )
                rows = actual.daily.set_index("date")
                values = [("signal_nav", state.nav, rows.loc[date, "nav"]),
                          ("pretrade_nav", expected.pretrade_nav, rows.loc[d1, "open_pretrade_nav"]),
                          ("posttrade_nav", expected.posttrade_nav, rows.loc[d1, "open_posttrade_nav"]),
                          ("cash", expected.cash, rows.loc[d1, "cash"]),
                          ("following_open_nav", expected.following_open_nav,
                           rows.loc[d2, "open_pretrade_nav"])]
                for name, want, got in values:
                    if not np.isclose(want, got, rtol=1e-10, atol=1e-6):
                        raise RuntimeError(f"REAL_STEP_{name}_DIFF:{year}:{regime}:{ticker}:{date}:{want}:{got}")
                trades = actual.trades.loc[actual.trades.execution_date.eq(d1)].to_dict("records")
                if len(trades) != len(expected.trades):
                    raise RuntimeError(f"REAL_STEP_TRADE_COUNT_DIFF:{year}:{regime}:{ticker}:{date}")
                for want, got in zip(expected.trades, trades):
                    if want["ticker"] != got["ticker"] or want["side"] != got["side"]:
                        raise RuntimeError("REAL_STEP_TRADE_IDENTITY_DIFF")
                    for column in ("notional", "index_units", "transaction_cost",
                                   "index_units_before", "index_units_after"):
                        if not np.isclose(want[column], got[column], rtol=1e-10, atol=1e-6):
                            raise RuntimeError(f"REAL_STEP_TRADE_{column}_DIFF")
                actual_units = actual.positions.loc[actual.positions.date.eq(d1)].set_index("ticker").index_units.to_dict()
                if set(actual_units) != set(expected.units) or any(
                    not np.isclose(q, actual_units[t], rtol=1e-10, atol=1e-8)
                    for t, q in expected.units.items()
                ):
                    raise RuntimeError("REAL_STEP_POSITION_DIFF")
                cap_events = int(actual.diagnostics.code.eq("capacity_limited").sum()) if not actual.diagnostics.empty else 0
                if cap_events != expected.capacity_limited_buys:
                    raise RuntimeError("REAL_STEP_CAP_EVENT_DIFF")
                cases.append(dict(year=year, regime=regime, action=action, signal_date=str(date.date()),
                                  ticker=ticker, trades=len(trades), cap_events=cap_events,
                                  max_abs_wealth_diff=max(abs(w-g) for _, w, g in values)))
                del actual
    return dict(status="REAL_PRE2026_STEP_ENGINE_EXACT_PASS", checked_cases=len(cases),
                trades_checked=sum(c["trades"] for c in cases),
                cap_events_checked=sum(c["cap_events"] for c in cases),
                cases=cases, fit_calls=0, test_2026_reads=0)


def prepare() -> None:
    if any(OUT.iterdir()):
        raise RuntimeError("PREPARE_REQUIRES_EMPTY_PRIVATE_OUTPUT")
    sources = [SOURCE, PRICE, OOF, OOF_LOG, HERE / "SCIENCE_CONTRACT.md",
               HERE / "one_step_label.py", HERE / "verify_one_step.py",
               HERE / "prepare_fit.py", HERE / "policy.py",
               ROOT / "engine.py", ROOT / "joint_linear_tree.py",
               ROOT / "models/model_registry.json",
               *(V2_KEYS / f"sample_keys_{stage}.parquet" for stage in STAGES)]
    source_hashes = {str(path): sha(path) for path in sources}
    expected = {
        str(SOURCE): "5895dbca36064a7ea7a9ab66fbe47c5b1dfc2ab5e6cef61d53cd23e447b09b0e",
        str(PRICE): "a8fd449887076633a816fd1ebf4ad17f27dbf5ae0948bb805e9cc6b978cb8cda",
        str(OOF): "60cd7198818f33e8a6a496666a7c775f0e4d37c1d6a7464df50b379e0fac024f",
        str(OOF_LOG): "a9feb14a82b246dcb500f5cf3ba711bd45e5e849c482310de4299ae65f1eafa9",
    }
    if any(source_hashes[p] != h for p, h in expected.items()):
        raise RuntimeError("PRE2026_SOURCE_IDENTITY_MISMATCH")
    technical = json.loads((Path("/technical") / "TECHNICAL_CHECK.json").read_text(encoding="utf-8"))
    if technical["status"] != "LABEL_SETTLEMENT_ENGINE_EXACT_SYNTHETIC_PASS" or \
       technical["engine_sha256"] != sha(ROOT / "engine.py") or \
       technical["one_step_sha256"] != sha(HERE / "one_step_label.py"):
        raise RuntimeError("TECHNICAL_SETTLEMENT_IDENTITY_MISMATCH")
    lineage = validate_oof_log()
    panel, prices, calendar, boundaries = load_sources()
    next1 = dict(zip(calendar[:-1], calendar[1:]))
    next2 = dict(zip(calendar[:-2], calendar[2:]))
    opens = {d: dict(zip(g.ticker, g.open)) for d, g in prices.groupby("trade_date", sort=False)}
    states, behavior_audit = behavior_paths(panel, prices, calendar)
    real_check = verify_real_engine_steps(panel, prices, states, next1, next2, opens)
    write(OUT / "REAL_PRE2026_TECHNICAL_CHECK.json", real_check)
    stage_audits = {}
    for stage in STAGES:
        keys = sample_keys(stage, panel, next2)
        labels, audit = labels_for_stage(stage, keys, panel, states, next1, next2, opens)
        path = OUT / f"labels_{stage}.parquet"
        labels.to_parquet(path, index=False)
        audit["label_sha256"] = sha(path)
        stage_audits[stage] = audit
        print(json.dumps({"stage": stage, "valid_rows": len(labels),
                          "infeasible": audit["counts"].get("target_infeasible", 0)}), flush=True)
        del labels, keys
        gc.collect()
    manifest = dict(status="PRE_FIT_CAPACITY_HGB_LOCKED", batch="a2_latest_effective_joint_20260927",
                    scientific_change="dynamic behavior accounts and full-account capacity-aware one-step labels",
                    fits_allowed=2, hgb_specs=original.SPECS["hgb"], seed=original.SEED,
                    original_actions=original.ACTIONS.tolist(), original_sample_dates_preserved=True,
                    sources_sha256=source_hashes, source_boundaries=boundaries,
                    oof_lineage=lineage, technical_check_sha256=sha(Path("/technical/TECHNICAL_CHECK.json")),
                    real_technical_check_sha256=sha(OUT / "REAL_PRE2026_TECHNICAL_CHECK.json"),
                    behavior_accounts=behavior_audit, stages=stage_audits,
                    tested_2026_rows=0, hyperparameter_search_count=0,
                    peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    write(OUT / "PRE_FIT_FREEZE.json", manifest)
    print(json.dumps({"status": manifest["status"], "behavior_accounts": len(behavior_audit),
                      "stage_rows": {k: v["output_rows"] for k, v in stage_audits.items()}}), flush=True)


def matrix(stage: str, panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    labels = pd.read_parquet(OUT / f"labels_{stage}.parquet")
    joined = labels.merge(panel[["signal_date", "ticker", *original.FEATURES]],
                          on=["signal_date", "ticker"], how="left", validate="many_to_one")
    if joined[original.FEATURES].isna().any().any():
        raise RuntimeError(f"MISSING_MODEL_FEATURES:{stage}")
    design = original.mapped_features(
        joined[original.FEATURES].to_numpy(float),
        joined.current_weight.to_numpy(float),
        joined.cash_weight.to_numpy(float),
        joined.held_age.to_numpy(float),
        joined.action.to_numpy(float),
    )
    design = np.column_stack((design, joined.capacity_weight.to_numpy(float)))
    target = joined.value.to_numpy(float)
    if not np.isfinite(design).all() or not np.isfinite(target).all():
        raise RuntimeError(f"NONFINITE_DESIGN_OR_LABEL:{stage}")
    return design, target, joined[["signal_date", "ticker", "label_end_date"]]


def fit() -> None:
    manifest_path = OUT / "PRE_FIT_FREEZE.json"
    if not manifest_path.is_file():
        raise RuntimeError("MISSING_PRE_FIT_FREEZE")
    frozen = json.loads(manifest_path.read_text(encoding="utf-8"))
    if frozen["status"] != "PRE_FIT_CAPACITY_HGB_LOCKED":
        raise RuntimeError("BAD_PRE_FIT_STATUS")
    if (OUT / "FIT_RECEIPT.json").exists() or (OUT / "FIT_RECEIPT.partial.json").exists():
        raise RuntimeError("PRESERVE_EXISTING_FIT_ATTEMPT")
    if any(sha(Path(path)) != expected for path, expected in frozen["sources_sha256"].items()):
        raise RuntimeError("SOURCE_CHANGED_SINCE_PREPARE")
    if sha(Path("/technical/TECHNICAL_CHECK.json")) != frozen["technical_check_sha256"]:
        raise RuntimeError("TECHNICAL_CHECK_CHANGED")
    if sha(OUT / "REAL_PRE2026_TECHNICAL_CHECK.json") != frozen["real_technical_check_sha256"]:
        raise RuntimeError("REAL_TECHNICAL_CHECK_CHANGED")
    for stage, item in frozen["stages"].items():
        if sha(OUT / f"labels_{stage}.parquet") != item["label_sha256"]:
            raise RuntimeError(f"LABEL_CHANGED_SINCE_PREPARE:{stage}")
    panel = pd.read_parquet(SOURCE, columns=["signal_date", "ticker", *original.FEATURES])
    vx, vy, vkeys = matrix("validation_metrics", panel)
    if not vkeys.signal_date.dt.year.eq(2025).all() or not vkeys.label_end_date.lt("2026-01-01").all():
        raise RuntimeError("BAD_VALIDATION_METRIC_BOUNDARY")
    del vkeys
    receipt = dict(status="RUNNING", revision="CAPACITY_AWARE_HGB_ONE_STEP_R1",
                   pre_fit_freeze_sha256=sha(manifest_path), fit_calls=0,
                   fits=[], test_2026_reads=0, hyperparameter_search_count=0,
                   validation_metrics={}, source_unchanged=False)
    for stage in ("validation", "final"):
        x, y, keys = matrix(stage, panel)
        if len(x) > original.MAX_ROWS or keys.signal_date.max() >= STAGES[stage] or \
           keys.label_end_date.max() >= STAGES[stage]:
            raise RuntimeError(f"TRAIN_BUDGET_OR_MATURITY_FAILED:{stage}")
        del keys
        start = time.monotonic()
        model = original.estimator("hgb")
        with threadpool_limits(limits=2):
            model.fit(x, y)
        path = OUT / f"{stage}_hgb.joblib"
        joblib.dump(model, path, compress=3)
        item = dict(stage=stage, name="hgb", rows=len(x), design_columns=x.shape[1],
                    fit_seconds=time.monotonic() - start, n_iter_=int(model.n_iter_),
                    artifact=str(path), artifact_sha256=sha(path))
        receipt["fits"].append(item)
        receipt["fit_calls"] = len(receipt["fits"])
        if stage == "validation":
            with threadpool_limits(limits=2):
                prediction = model.predict(vx)
            receipt["validation_metrics"] = dict(mse=float(mean_squared_error(vy, prediction)),
                                                 validation_rows=len(vy),
                                                 used_for_selection=False)
            del prediction, vx, vy
        write(OUT / "FIT_RECEIPT.partial.json", receipt)
        print(json.dumps({"fit": stage, "rows": len(x), "fit_calls": receipt["fit_calls"]}), flush=True)
        del x, y, model
        gc.collect()
    receipt["source_unchanged"] = all(sha(Path(path)) == expected
                                      for path, expected in frozen["sources_sha256"].items())
    receipt["label_unchanged"] = all(sha(OUT / f"labels_{stage}.parquet") == item["label_sha256"]
                                      for stage, item in frozen["stages"].items())
    receipt["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if not receipt["source_unchanged"] or not receipt["label_unchanged"]:
        raise RuntimeError("SOURCE_OR_LABEL_CHANGED_AFTER_FIT")
    receipt["status"] = "PASS"
    write(OUT / "FIT_RECEIPT.json", receipt)
    print(json.dumps({"status": "PASS", "fit_calls": receipt["fit_calls"],
                      "peak_rss_kib": receipt["peak_rss_kib"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "fit"))
    phase = parser.parse_args().phase
    if phase == "prepare":
        prepare()
    else:
        fit()
