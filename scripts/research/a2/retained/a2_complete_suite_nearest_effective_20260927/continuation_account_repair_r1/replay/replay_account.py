"""Evidence-gated continuation of the frozen R6 joint accounts.

This adapter deliberately calls the original ``engine.run_replay``.  It does
not implement fills, valuation, target selection, or policy state updates.
The full-horizon call is only a disposable probe to locate the first input
which the original engine would consume without certification.  A second call
ends before that day; only that certified prefix can be saved or reported.
Restart is deterministic replay from the original initial state with prefix
comparison, because the frozen engine has no state-injection API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from engine import run_replay  # noqa: E402  -- the actual frozen accounting function
from models.predict import predict_panel  # noqa: E402
from run_suite import Stateful, TEST_NAMES, forbid_fitting  # noqa: E402

CALENDAR_PATH = ROOT / "data/calendar.parquet"
PANEL_PATH = ROOT / "data/test_features_context.parquet"
PRICES_PATH = ROOT / "data/test_prices.parquet"
EVALUATION = ROOT / "evaluation_2026"
SIGNAL_END = pd.Timestamp("2026-09-22")
TERMINAL = pd.Timestamp("2026-09-24")
SCENARIOS = (5, 10, 25)
NEEDED_DIAGNOSTICS = {"missing_open_buy", "missing_open_sell", "execution_blocked_unknown_nav"}


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def frozen_sources() -> dict[str, str]:
    """Check each scenario's actual source seal before even loading a policy."""
    bound_engine = Path(run_replay.__code__.co_filename).resolve()
    expected_engine = (ROOT / "engine.py").resolve()
    if bound_engine != expected_engine:
        raise RuntimeError(f"actual run_replay source is not frozen engine: {bound_engine}")
    combined: dict[str, str] = {}
    for cost in SCENARIOS:
        seal_path = EVALUATION / f"cost_{cost}" / "FROZEN_BEFORE_SCORING.json"
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        if seal["roster"] != TEST_NAMES or sorted(seal["cost_bps_per_side"]) != list(SCENARIOS):
            raise RuntimeError(f"frozen roster/cost mismatch: {seal_path}")
        for rel, expected in seal["source_hashes"].items():
            if rel in combined and combined[rel] != expected:
                raise RuntimeError(f"source seals disagree for {rel}")
            combined[rel] = expected
    for rel, expected in combined.items():
        path = ROOT / rel
        if digest(path) != expected:
            raise RuntimeError(f"frozen source hash mismatch: {path}")
    if combined.get("engine.py") != digest(bound_engine):
        raise RuntimeError("actual bound run_replay source hash differs from frozen engine")
    return combined


def _bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes"}


def load_prices(approval_path: Path | None) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply only an explicit evidence ledger to the original R6 price mask.

    An approval may certify the open, close, or both.  Existing numerical raw
    values are copied exactly; values are never invented from stale marks.
    A missing raw row (for example DTP 09-23/24 or EXAS after exit) cannot be
    restored by this adapter and needs a separate same-source/corporate-action
    resolution.  The caller's evidence review is not replaced by this schema.
    """
    raw = pd.read_parquet(PRICES_PATH)
    if raw.duplicated(["ticker", "trade_date"]).any():
        raise RuntimeError("duplicate frozen raw prices")
    prices = raw.copy()
    flagged = prices.price_quality_warning.fillna(False).astype(bool)
    prices.loc[flagged, ["open", "close"]] = np.nan
    applied: list[dict[str, Any]] = []
    if approval_path is None:
        return prices, applied
    approved = pd.read_csv(approval_path)
    required = {"ticker", "trade_date", "open_authorized", "close_authorized", "evidence_id"}
    if not required <= set(approved):
        raise ValueError(f"approval ledger missing {sorted(required - set(approved))}")
    approved["trade_date"] = pd.to_datetime(approved.trade_date)
    if approved.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("duplicate approval key")
    if "candidate_pool_version" in approved and not approved.candidate_pool_version.eq("R6_UNCHANGED").all():
        raise ValueError("approval would silently change the R6 candidate pool")
    lookup = raw.set_index(["ticker", "trade_date"])
    target = prices.set_index(["ticker", "trade_date"])
    for row in approved.itertuples(index=False):
        key = (row.ticker, row.trade_date)
        if key not in lookup.index:
            raise ValueError(f"approval lacks frozen same-source raw row: {key}")
        if not str(row.evidence_id).strip():
            raise ValueError(f"approval lacks evidence id: {key}")
        open_ok, close_ok = _bool(row.open_authorized), _bool(row.close_authorized)
        if not (open_ok or close_ok):
            raise ValueError(f"approval certifies neither field: {key}")
        for field, is_ok in (("open", open_ok), ("close", close_ok)):
            if is_ok:
                if pd.notna(target.loc[key, field]):
                    raise ValueError(f"approved {field} was not masked in original R6 replay: {key}")
                value = float(lookup.loc[key, field])
                if not np.isfinite(value) or value <= 0:
                    raise ValueError(f"approval has no positive frozen raw {field}: {key}")
                if field in approved.columns and not np.isclose(value, float(getattr(row, field)), rtol=0, atol=1e-9):
                    raise ValueError(f"approval value differs from frozen raw {field}: {key}")
                target.loc[key, field] = value
        applied.append({"ticker": row.ticker, "trade_date": row.trade_date.date().isoformat(),
                        "open_authorized": open_ok, "close_authorized": close_ok,
                        "open_value": float(lookup.loc[key, "open"]) if open_ok else None,
                        "close_value": float(lookup.loc[key, "close"]) if close_ok else None,
                        "evidence_id": str(row.evidence_id)})
    return target.reset_index(), applied


def load_policy_panel() -> pd.DataFrame:
    panel = pd.read_parquet(PANEL_PATH)
    panel = panel.loc[panel.signal_date.le(SIGNAL_END)].copy()
    baseline = predict_panel(panel)[["signal_date", "ticker", "hgb"]].rename(columns={"hgb": "baseline_hgb"})
    panel = panel.merge(baseline, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    if panel.baseline_hgb.isna().any():
        raise RuntimeError("frozen HGB baseline prediction missing")
    from joint_neural import FEATURES
    columns = ["signal_date", "ticker", "new_buy_eligible", "baseline_hgb"] + list(FEATURES)
    return panel[columns]


def call_engine(prices: pd.DataFrame, calendar: pd.DatetimeIndex,
                panel: pd.DataFrame, policy: str, cost: int):
    actor = Stateful(policy, "final")
    features = panel.loc[panel.signal_date.isin(calendar)]
    with threadpool_limits(limits=2):
        result = run_replay(prices, calendar, features, actor, candidate=policy,
                            cost_bps=cost, max_invested=.95, capacity_fraction=.01,
                            missing_signal_policy="cash", signal_start="2026-01-01",
                            signal_end=SIGNAL_END)
    return result, actor


def _necessary_failures(result, prices: pd.DataFrame) -> tuple[pd.Timestamp | None, list[dict[str, Any]]]:
    """Identify the first price requirement consumed by this actual path."""
    d = result.daily
    bad_daily = d.loc[(d.valuation_status != "certified") |
                      ((d.signal_date.notna()) & ((d.open_stale_count > 0) | (d.open_unknown_count > 0)))]
    events = result.diagnostics
    bad_events = events.loc[events.code.isin(NEEDED_DIAGNOSTICS)] if not events.empty else events
    dates = []
    if not bad_daily.empty:
        dates.append(pd.Timestamp(bad_daily.date.min()))
    if not bad_events.empty:
        dates.append(pd.Timestamp(bad_events.date.min()))
    if not dates:
        return None, []
    first = min(dates)
    details: list[dict[str, Any]] = []
    available = prices.loc[prices.trade_date.eq(first), ["ticker", "open", "close"]].set_index("ticker")
    held = result.positions.loc[result.positions.date.eq(first)]
    day_row = d.loc[d.date.eq(first)].iloc[0]
    if pd.notna(day_row.signal_date):
        for ticker in held.ticker:
            if ticker not in available.index or not np.isfinite(available.loc[ticker, "open"]):
                details.append({"ticker": ticker, "date": first.date().isoformat(), "field": "open",
                                "purpose": "held_position_pretrade_nav_or_exit",
                                "pending_signal_date": str(pd.Timestamp(day_row.signal_date).date())})
    for row in held.itertuples(index=False):
        if bool(row.stale) or bool(row.unknown):
            details.append({"ticker": row.ticker, "date": first.date().isoformat(), "field": "close",
                            "purpose": "actual_held_position_valuation"})
    for row in bad_events.loc[bad_events.date.eq(first)].itertuples(index=False):
        if row.code == "missing_open_buy":
            details.append({"ticker": row.ticker, "date": first.date().isoformat(), "field": "open",
                            "purpose": "requested_target_buy"})
        elif row.code == "missing_open_sell":
            details.append({"ticker": row.ticker, "date": first.date().isoformat(), "field": "open",
                            "purpose": "requested_position_sell"})
        else:
            details.append({"ticker": None, "date": first.date().isoformat(), "field": "open",
                            "purpose": "pending_orders_blocked_unknown_pretrade_nav"})
    unique = list({(v["ticker"], v["date"], v["field"], v["purpose"]): v for v in details}.values())
    return first, unique


def _equal_prefix(new, old_dir: Path, safe_date: pd.Timestamp,
                  historical_first_bad: pd.Timestamp | None) -> dict[str, Any]:
    """Prove the unchanged portion still follows the first saved replay."""
    compare_to = safe_date if historical_first_bad is None else min(safe_date, historical_first_bad - pd.Timedelta(days=1))
    tables = {"daily": "date", "positions": "date", "trades": "execution_date",
              "target_decisions": "signal_date", "diagnostics": "date"}
    counts = {}
    for name, date_column in tables.items():
        current = getattr(new, name)
        old = pd.read_parquet(old_dir / f"{name}.parquet")
        current = current.loc[current[date_column].le(compare_to)].reset_index(drop=True)
        old = old.loc[old[date_column].le(compare_to)].reset_index(drop=True)
        # Later diagnostics can add schema columns absent in a prefix-only run.
        # All-null columns contain no prefix evidence and may be discarded.
        current = current.dropna(axis=1, how="all")
        old = old.dropna(axis=1, how="all")
        pd.testing.assert_frame_equal(current, old, check_dtype=False, check_exact=True)
        counts[name] = len(current)
    return {"through": compare_to.date().isoformat(), "row_counts": counts,
            "method": "exact in-memory DataFrame equality, including recomputed target and fixed next execution date"}


def _restore_fixed_next_session(result, safe_date: pd.Timestamp,
                                calendar: pd.DatetimeIndex) -> None:
    """Label the sliced last decision with the unchanged real next session.

    The original engine computed this frozen-policy target.  Its clipped
    calendar alone caused ``no_next_session``/NaT.  No order size, target,
    account value, or fill is changed by restoring this schedule label.
    """
    later = calendar[calendar > safe_date]
    if not len(later):
        return
    at_end = result.target_decisions.signal_date.eq(safe_date)
    eligible = at_end & result.target_decisions.status.eq("no_next_session")
    result.target_decisions.loc[eligible, "execution_date"] = later[0]
    result.target_decisions.loc[eligible, "status"] = "submitted"


def _old_first_bad(old_dir: Path) -> pd.Timestamp | None:
    d = pd.read_parquet(old_dir / "daily.parquet", columns=["date", "signal_date", "valuation_status", "open_stale_count", "open_unknown_count"])
    e = pd.read_parquet(old_dir / "diagnostics.parquet", columns=["date", "code"])
    bad = d.loc[(d.valuation_status != "certified") |
                ((d.signal_date.notna()) & ((d.open_stale_count > 0) | (d.open_unknown_count > 0)))]
    needed = e.loc[e.code.isin(NEEDED_DIAGNOSTICS)]
    vals = []
    if not bad.empty:
        vals.append(pd.Timestamp(bad.date.min()))
    if not needed.empty:
        vals.append(pd.Timestamp(needed.date.min()))
    return min(vals) if vals else None


def _pending_from_prefix(result, panel: pd.DataFrame, actor: Stateful,
                         safe_date: pd.Timestamp) -> dict[str, Any] | None:
    if safe_date > SIGNAL_END:
        return None
    decisions = result.target_decisions.loc[result.target_decisions.signal_date.eq(safe_date)]
    if decisions.empty or decisions.status.eq("blocked_unknown_valuation").any():
        return None
    target = {str(r.ticker): float(r.target_weight) for r in decisions.itertuples(index=False)
              if isinstance(r.ticker, str) and np.isfinite(r.target_weight) and r.target_weight > 0}
    source = panel.loc[panel.signal_date.eq(safe_date)]
    adv = {str(t): float(v) for t, v in zip(source.ticker, source.avg_dollar_volume_20d)
           if np.isfinite(v) and float(v) > 0} if "avg_dollar_volume_20d" in source else {}
    return {"signal_date": safe_date.date().isoformat(), "targets_from_new_frozen_policy": target,
            "signal_day_adv": adv, "buy_eligibility": dict(zip(source.ticker.astype(str), source.new_buy_eligible.astype(bool))),
            "actor_held_age": actor.age,
            "restore_rule": "rerun original run_replay from initial state; this serialized order is evidence, not an injected order"}


def _assert_account_invariants(result) -> dict[str, float | int]:
    d = result.daily
    if (d.valuation_status != "certified").any():
        raise AssertionError("accepted prefix contains uncertified valuation")
    if d.cash.isna().any() or (d.cash < -1e-8).any():
        raise AssertionError("cash missing or negative")
    if (d.actual_name_count > 20).any():
        raise AssertionError("live position limit exceeded")
    maxima: dict[str, float | int] = {"days": len(d), "minimum_cash": float(d.cash.min()),
                                       "maximum_names": int(d.actual_name_count.max())}
    for column in ("cash_flow_identity_error", "nav_identity_error", "cost_identity_error"):
        values = d[column].to_numpy(float)
        if not np.isfinite(values).all():
            raise AssertionError(f"nonfinite {column} in accepted prefix")
        maximum = float(np.max(np.abs(values)))
        if maximum > 1e-7:
            raise AssertionError(f"{column} exceeds 1e-7: {maximum}")
        maxima[f"max_abs_{column}"] = maximum
    return maxima


def _consumed_approvals(prefix, applied: list[dict[str, Any]],
                        calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Return only approved price fields used by this accepted account prefix."""
    if prefix is None or not applied:
        return pd.DataFrame(columns=["ticker", "trade_date", "field", "value", "evidence_id", "purpose"])
    close_keys = {(str(r.ticker), pd.Timestamp(r.date).date().isoformat())
                  for r in prefix.positions.itertuples(index=False)}
    open_keys = {(str(r.ticker), pd.Timestamp(r.execution_date).date().isoformat())
                 for r in prefix.trades.itertuples(index=False)}
    positions_by_date = {date: set(g.ticker.astype(str))
                         for date, g in prefix.positions.groupby("date")}
    for row in prefix.daily.itertuples(index=False):
        if pd.isna(row.signal_date):
            continue
        date = pd.Timestamp(row.date)
        index = calendar.get_loc(date)
        if index > 0:
            for ticker in positions_by_date.get(calendar[index - 1], set()):
                open_keys.add((ticker, date.date().isoformat()))
    consumed = []
    for row in applied:
        key = (row["ticker"], row["trade_date"])
        if row["open_authorized"] and key in open_keys:
            consumed.append({"ticker": key[0], "trade_date": key[1], "field": "open",
                             "value": row["open_value"], "evidence_id": row["evidence_id"],
                             "purpose": "actual execution or held-position pretrade NAV"})
        if row["close_authorized"] and key in close_keys:
            consumed.append({"ticker": key[0], "trade_date": key[1], "field": "close",
                             "value": row["close_value"], "evidence_id": row["evidence_id"],
                             "purpose": "actual held-position valuation"})
    return pd.DataFrame(consumed, columns=["ticker", "trade_date", "field", "value", "evidence_id", "purpose"])


def run_path(policy: str, cost: int, prices: pd.DataFrame, calendar: pd.DatetimeIndex,
             panel: pd.DataFrame, output: Path, source_hashes: dict[str, str],
             approval_path: Path | None, applied: list[dict[str, Any]],
             source_manifest_hash: str, price_field_diff_hash: str) -> dict[str, Any]:
    old_dir = EVALUATION / f"cost_{cost}" / f"{policy}_{cost}bps"
    if not old_dir.is_dir():
        raise FileNotFoundError(old_dir)
    # Probe output is never persisted or described as an accepted account.
    probe, _ = call_engine(prices, calendar, panel, policy, cost)
    first_bad, needs = _necessary_failures(probe, prices)
    historical_first_bad = _old_first_bad(old_dir)
    safe_calendar = calendar if first_bad is None else calendar[calendar < first_bad]
    if len(safe_calendar):
        prefix, actor = call_engine(prices, safe_calendar, panel, policy, cost)
        safe_date = safe_calendar[-1]
        if (prefix.daily.valuation_status != "certified").any():
            raise RuntimeError("probe/prefix certification disagreement")
        if ((prefix.daily.signal_date.notna()) &
            ((prefix.daily.open_stale_count > 0) | (prefix.daily.open_unknown_count > 0))).any():
            raise RuntimeError("uncertified execution input in accepted prefix")
        if first_bad is not None:
            _restore_fixed_next_session(prefix, safe_date, calendar)
        invariants = _assert_account_invariants(prefix)
        checked = _equal_prefix(prefix, old_dir, safe_date, historical_first_bad)
        final = prefix.daily.iloc[-1]
        positions = prefix.positions.loc[prefix.positions.date.eq(safe_date)]
        holdings = {str(r.ticker): {"index_units": float(r.index_units), "mark": float(r.mark),
                                    "mark_date": pd.Timestamp(r.mark_date).date().isoformat(),
                                    "mark_source": str(r.mark_source)} for r in positions.itertuples(index=False)}
        cash = float(final.cash)
        pending = _pending_from_prefix(prefix, panel, actor, safe_date)
    else:
        prefix = None
        safe_date = None
        checked = {"through": None, "row_counts": {}}
        invariants = {"days": 0, "minimum_cash": 1_000_000.0, "maximum_names": 0}
        holdings, cash, pending = {}, 1_000_000.0, None
    run_id = f"{policy}_{cost}bps"
    folder = output / run_id
    folder.mkdir(parents=True, exist_ok=False)
    consumed = _consumed_approvals(prefix, applied, calendar)
    if not consumed.empty:
        consumed.to_csv(folder / "CONSUMED_APPROVALS.csv", index=False)
    old_hashes = {f"{name}.parquet": digest(old_dir / f"{name}.parquet")
                  for name in ("daily", "positions", "trades", "target_decisions", "diagnostics")}
    checkpoint = {"run_id": run_id, "status": "certified_to_terminal" if first_bad is None else "paused_before_uncertified_input",
                  "certified_through": None if safe_date is None else safe_date.date().isoformat(),
                  "next_date": None if first_bad is None else first_bad.date().isoformat(),
                  "next_required_inputs": needs, "cash": cash, "holdings": holdings,
                  "pending_recomputed_by_frozen_policy": pending,
                  "policy_held_age_at_checkpoint": {} if prefix is None else actor.age,
                  "restart_method": "deterministically rerun original engine from 2026 initial cash, assert previous certified prefix, then continue; no state injection or old targets",
                  "historical_first_bad": None if historical_first_bad is None else historical_first_bad.date().isoformat(),
                  "old_ledger_hashes": old_hashes,
                  "source_manifest": {"path": str(output / "SOURCE_HASHES.json"), "sha256": source_manifest_hash},
                  "input_approval_ledger": None if approval_path is None else {"path": str(approval_path), "sha256": digest(approval_path)},
                  "price_field_diff": {"path": str(output / "PRICE_FIELD_DIFF.csv"), "sha256": price_field_diff_hash},
                  "approved_fields_consumed_in_certified_prefix": {"count": len(consumed),
                      "path": None if consumed.empty else str(folder / "CONSUMED_APPROVALS.csv"),
                      "sha256": None if consumed.empty else digest(folder / "CONSUMED_APPROVALS.csv")},
                  "prefix_agrees_with_original": checked,
                  "certified_account_invariants": invariants,
                  "new_predictor_fit_attempts": 0, "new_preprocessor_fit_attempts": 0,
                  "outcome_status": "diagnostic_post_2026_evidence_repair; never a fresh blind test"}
    save_json(folder / "CHECKPOINT.json", checkpoint)
    if prefix is not None:
        # Avoid duplicating an unchanged old prefix.  The SHA-pinned source is
        # the ledger; any newly advanced certified prefix gets its own files.
        advanced = historical_first_bad is not None and safe_date >= historical_first_bad
        if advanced:
            for name in ("daily", "positions", "trades", "target_decisions", "diagnostics"):
                getattr(prefix, name).to_parquet(folder / f"{name}.parquet", index=False)
            save_json(folder / "metadata.json", prefix.metadata)
        else:
            save_json(folder / "PREFIX_LEDGER_REFERENCE.json", {"old_dir": str(old_dir),
                       "through": safe_date.date().isoformat(), "sha256": old_hashes,
                       "boundary_decision": "new frozen policy was called and target schedule was normalized to the fixed next session"})
    return {"run_id": run_id, "status": checkpoint["status"], "certified_through": checkpoint["certified_through"],
            "next_date": checkpoint["next_date"], "next_required_inputs": needs,
            "historical_first_bad": checkpoint["historical_first_bad"],
            "approved_fields_consumed_in_certified_prefix": len(consumed),
            "account_advanced_beyond_old_bad": bool(safe_date is not None and historical_first_bad is not None and safe_date >= historical_first_bad)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval-ledger", type=Path, help="separately proved ticker/date open/close authorizations")
    parser.add_argument("--paths", nargs="+", help="run ids such as joint_mlp_10bps; default all frozen 42")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError(f"output exists; preserve previous run: {output}")
    source_hashes = frozen_sources()
    fit_guard = forbid_fitting()
    prices, applied = load_prices(args.approval_ledger)
    panel = load_policy_panel()
    calendar = pd.DatetimeIndex(pd.read_parquet(CALENDAR_PATH).query("is_test").trade_date)
    if calendar[-1] != TERMINAL or max(panel.signal_date) != SIGNAL_END:
        raise RuntimeError("fixed R6 calendar or signal window changed")
    selected = args.paths or [f"{name}_{cost}bps" for cost in SCENARIOS for name in TEST_NAMES]
    roster = {f"{name}_{cost}bps": (name, cost) for cost in SCENARIOS for name in TEST_NAMES}
    if len(selected) != len(set(selected)) or any(item not in roster for item in selected):
        raise ValueError("unknown or duplicate run id")
    output.mkdir(parents=True, exist_ok=False)
    save_json(output / "SOURCE_HASHES.json", {"frozen_source_hashes": source_hashes,
              "actual_run_replay_source": {"path": str(Path(run_replay.__code__.co_filename).resolve()),
                                            "sha256": digest(Path(run_replay.__code__.co_filename))},
              "seal_files": {f"cost_{cost}": {"path": str(EVALUATION / f"cost_{cost}" / "FROZEN_BEFORE_SCORING.json"),
                  "sha256": digest(EVALUATION / f"cost_{cost}" / "FROZEN_BEFORE_SCORING.json")}
                  for cost in SCENARIOS}})
    source_manifest_hash = digest(output / "SOURCE_HASHES.json")
    diff_rows = []
    for row in applied:
        for field in ("open", "close"):
            if row[f"{field}_authorized"]:
                diff_rows.append({"ticker": row["ticker"], "trade_date": row["trade_date"],
                                  "field": field, "masked_old_value": None,
                                  "restored_same_source_raw_value": row[f"{field}_value"],
                                  "evidence_id": row["evidence_id"]})
    pd.DataFrame(diff_rows, columns=["ticker", "trade_date", "field", "masked_old_value",
                                     "restored_same_source_raw_value", "evidence_id"]).to_csv(
                                         output / "PRICE_FIELD_DIFF.csv", index=False)
    price_field_diff_hash = digest(output / "PRICE_FIELD_DIFF.csv")
    summaries = []
    for item in selected:
        name, cost = roster[item]
        summary = run_path(name, cost, prices, calendar, panel, output, source_hashes,
                           args.approval_ledger, applied, source_manifest_hash, price_field_diff_hash)
        summaries.append(summary)
        save_json(output / "PROGRESS.json", {"paths_completed": len(summaries), "paths": summaries,
                                              "fit_guard_attempts": fit_guard["attempts"]})
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    if fit_guard["attempts"]:
        raise RuntimeError("a forbidden fit was attempted")
    if frozen_sources() != source_hashes:
        raise RuntimeError("frozen sources changed during account replay")
    save_json(output / "COMPLETE.json", {"status": "EVIDENCE_GATED_PREFIXES_ONLY", "paths": summaries,
               "source_hashes_checked_before_and_after": len(source_hashes),
               "source_seals_checked_before_and_after": len(SCENARIOS),
               "approved_price_keys": len(applied),
               "fit_guard_attempts": fit_guard["attempts"], "formal_full_pool_result": False})


if __name__ == "__main__":
    main()
