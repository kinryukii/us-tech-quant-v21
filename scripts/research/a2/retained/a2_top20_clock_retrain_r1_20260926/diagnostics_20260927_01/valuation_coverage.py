"""Read-only coverage diagnostic for sealed pre-2026 R1 holding marks.

This does not replay or alter an account and never estimates shareholder total
return. Run with the sealed training output at /bundle, its seal at /seal.json,
and a private writable /out in the fixed offline Linux image.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path("/bundle")
OUT = Path("/out")
SEAL = Path("/seal.json")
EXPECTED_SEAL_SHA256 = "1607b78294b88fea5bb565b9b22c99fccf3bb1817d1cacce2b9126336263ee3d"
CUTOFF = pd.Timestamp("2026-01-01")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sealed_paths() -> list[tuple[str, str, str, str]]:
    if sha(SEAL) != EXPECTED_SEAL_SHA256:
        raise RuntimeError("TRAINING_SEAL_IDENTITY_CHANGED")
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    if seal.get("output_root") != "restricted_run_20260926_01/run":
        raise RuntimeError("WRONG_TRAINING_OUTPUT")
    bound = {r["path"]: r for r in seal["files"]}
    policies = []
    for name in sorted(bound):
        if name.startswith("opt_artifacts/") and name.endswith("_daily.parquet"):
            stem = name.removesuffix("_daily.parquet")
            policies.append((stem.rsplit("/", 1)[-1], name,
                             stem + "_decisions.parquet", "feasible_target_weight"))
        elif name.startswith("rl_artifacts/") and name.endswith("_outer_daily.parquet"):
            stem = name.removesuffix("_daily.parquet")
            policies.append((stem.rsplit("/", 1)[-1], name,
                             stem + "_targets.parquet", "target_weight"))
    if len(policies) != 16:
        raise RuntimeError(f"SEALED_POLICY_COUNT:{len(policies)}")
    consumed = {"data/prices.parquet"}
    consumed.update(p for _, d, t, _ in policies for p in (d, t))
    for rel in sorted(consumed):
        item = bound.get(rel)
        path = ROOT / rel
        if item is None or not path.is_file() or path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise RuntimeError(f"SEALED_INPUT_CHANGED:{rel}")
    return policies


def load_holdings(policies: list[tuple[str, str, str, str]]) -> tuple[pd.DataFrame, list[dict]]:
    held_frames = []
    policy_info = []
    for name, daily_rel, targets_rel, _ in policies:
        daily = pd.read_parquet(ROOT / daily_rel,
                                columns=["signal_date", "execution_date", "pretrade_nav",
                                         "actual_name_count", "blocked_sell_count"])
        targets = pd.read_parquet(ROOT / targets_rel,
                                  columns=["signal_date", "ticker", "shares_before"])
        daily["signal_date"] = pd.to_datetime(daily.signal_date)
        daily["execution_date"] = pd.to_datetime(daily.execution_date)
        targets["signal_date"] = pd.to_datetime(targets.signal_date)
        if daily.empty or targets.empty or daily.execution_date.max() >= CUTOFF:
            raise RuntimeError(f"POLICY_DATE_OR_EMPTY:{name}")
        if targets.signal_date.max() >= CUTOFF or targets.duplicated(["signal_date", "ticker"]).any():
            raise RuntimeError(f"TARGET_DATE_OR_KEY:{name}")
        if daily.signal_date.notna().sum() != daily.signal_date.nunique():
            raise RuntimeError(f"DAILY_SIGNAL_KEY:{name}")
        held = targets.loc[targets.shares_before.gt(1e-14)].merge(
            daily[["signal_date", "execution_date", "pretrade_nav"]],
            on="signal_date", how="left", validate="many_to_one")
        if held.execution_date.isna().any() or not np.isfinite(held.shares_before).all() or (held.shares_before <= 0).any():
            raise RuntimeError(f"HOLDING_STATE_INVALID:{name}")
        if not np.isfinite(held.pretrade_nav).all() or (held.pretrade_nav <= 0).any():
            raise RuntimeError(f"PRETRADE_NAV_INVALID:{name}")
        counts = held.groupby("execution_date").size().reindex(daily.execution_date, fill_value=0).to_numpy()
        previous_count = daily.actual_name_count.shift(fill_value=0).to_numpy()
        if not np.array_equal(counts, previous_count):
            raise RuntimeError(f"HOLDING_ROSTER_INCOMPLETE:{name}")
        held.insert(0, "policy", name)
        held_frames.append(held)
        policy_info.append({"policy": name, "execution_days": len(daily),
                            "held_position_days": len(held),
                            "blocked_sells": int(daily.blocked_sell_count.sum())})
    return pd.concat(held_frames, ignore_index=True), policy_info


def load_prices(held: pd.DataFrame) -> tuple[dict, dict, np.ndarray, list[str]]:
    parquet = pq.ParquetFile(ROOT / "data/prices.parquet")
    names = parquet.schema_arrow.names
    if names != ["ticker", "trade_date", "open", "close"]:
        raise RuntimeError(f"PRICE_SCHEMA_CHANGED:{names}")
    tickers = set(held.ticker.astype(str)) | {"QQQ"}
    frames = []
    for batch in parquet.iter_batches(batch_size=65_536, columns=names):
        chunk = batch.to_pandas()
        chunk["trade_date"] = pd.to_datetime(chunk.trade_date)
        if chunk.trade_date.max() >= CUTOFF:
            raise RuntimeError("POST_CUTOFF_PRICE_IN_SEALED_INPUT")
        selected = chunk.loc[chunk.ticker.isin(tickers)]
        if not selected.empty:
            frames.append(selected)
    prices = pd.concat(frames, ignore_index=True)
    if prices.duplicated(["trade_date", "ticker"]).any():
        raise RuntimeError("DUPLICATE_PRICE_KEY")
    prices = prices.sort_values(["ticker", "trade_date"])
    opens = {}
    closes = {}
    for ticker, group in prices.groupby("ticker", sort=False):
        opens.update(((pd.Timestamp(row.trade_date), ticker), float(row.open))
                     for row in group.itertuples(index=False))
        valid = group.loc[np.isfinite(group.close.to_numpy(float)) & group.close.gt(0)]
        closes[ticker] = (valid.trade_date.to_numpy(dtype="datetime64[ns]"),
                          valid.close.to_numpy(float))
    sessions = prices.loc[prices.ticker.eq("QQQ"), "trade_date"].to_numpy(dtype="datetime64[ns]")
    if len(sessions) == 0 or len(held) == 0:
        raise RuntimeError("NO_SESSIONS_OR_HOLDINGS")
    return opens, closes, sessions, names


def last_close(closes: dict, ticker: str, date: pd.Timestamp, include_day: bool) -> tuple[pd.Timestamp, float]:
    dates, values = closes.get(ticker, (np.array([], dtype="datetime64[ns]"), np.array([], dtype=float)))
    pos = np.searchsorted(dates, date.to_datetime64(), side="right" if include_day else "left") - 1
    if pos < 0:
        raise RuntimeError(f"NO_PRIOR_HOLDING_CLOSE:{ticker}:{date.date()}")
    return pd.Timestamp(dates[pos]), float(values[pos])


def main() -> None:
    OUT.mkdir(exist_ok=True)
    policies = sealed_paths()
    held, policy_info = load_holdings(policies)
    opens, closes, sessions, price_columns = load_prices(held)
    anomaly_rows = []
    all_summary = []
    for policy, group in held.groupby("policy", sort=False):
        stale_count = stale_decision_count = 0
        stale_exposure_days = 0.0
        max_stale_exposure = 0.0
        max_calendar_age = max_session_age = 0
        affected_dates = set()
        by_day_exposure = {}
        for row in group.itertuples(index=False):
            ticker, signal, execution = str(row.ticker), pd.Timestamp(row.signal_date), pd.Timestamp(row.execution_date)
            signal_mark_date, _ = last_close(closes, ticker, signal, include_day=True)
            decision_stale = signal_mark_date < signal
            stale_decision_count += int(decision_stale)
            opening = opens.get((execution, ticker), float("nan"))
            if np.isfinite(opening) and opening > 0:
                continue
            source_date, source_close = last_close(closes, ticker, execution, include_day=False)
            calendar_age = int((execution - source_date).days)
            session_age = int(np.searchsorted(sessions, execution.to_datetime64()) -
                              np.searchsorted(sessions, source_date.to_datetime64()))
            exposure = float(row.shares_before * source_close / row.pretrade_nav)
            if not np.isfinite(exposure) or exposure < 0:
                raise RuntimeError("INVALID_STALE_EXPOSURE")
            anomaly_rows.append({"policy": policy, "signal_date": signal, "execution_date": execution,
                                 "ticker": ticker, "shares_before": float(row.shares_before),
                                 "prior_close_date": source_date, "prior_close": source_close,
                                 "calendar_days_since_close": calendar_age,
                                 "sessions_since_close": session_age,
                                 "stale_value_over_pretrade_nav": exposure,
                                 "decision_close_stale": decision_stale})
            stale_count += 1
            affected_dates.add(execution)
            by_day_exposure[execution] = by_day_exposure.get(execution, 0.0) + exposure
            stale_exposure_days += exposure
            max_calendar_age = max(max_calendar_age, calendar_age)
            max_session_age = max(max_session_age, session_age)
        if by_day_exposure:
            max_stale_exposure = max(by_day_exposure.values())
        all_summary.append({"policy": policy, "held_position_days": len(group),
                            "stale_execution_mark_position_days": stale_count,
                            "stale_decision_close_position_days": stale_decision_count,
                            "execution_days_with_stale_mark": len(affected_dates),
                            "sum_stale_weight_days": stale_exposure_days,
                            "max_stale_weight_one_day": max_stale_exposure,
                            "max_stale_calendar_days": max_calendar_age,
                            "max_stale_trading_sessions": max_session_age})
    details = pd.DataFrame(anomaly_rows)
    if not details.empty:
        details.to_parquet(OUT / "stale_holding_marks.parquet", index=False)
    totals = {"held_position_days": int(sum(r["held_position_days"] for r in all_summary)),
              "stale_execution_mark_position_days": int(sum(r["stale_execution_mark_position_days"] for r in all_summary)),
              "stale_decision_close_position_days": int(sum(r["stale_decision_close_position_days"] for r in all_summary)),
              "affected_policy_days": int(sum(r["execution_days_with_stale_mark"] for r in all_summary)),
              "max_stale_weight_one_policy_day": max(r["max_stale_weight_one_day"] for r in all_summary),
              "max_stale_calendar_days": max(r["max_stale_calendar_days"] for r in all_summary),
              "max_stale_trading_sessions": max(r["max_stale_trading_sessions"] for r in all_summary)}
    result = {"status": "SEALED_PRE2026_HOLDING_VALUATION_COVERAGE_DIAGNOSED",
              "training_output_seal_sha256": EXPECTED_SEAL_SHA256,
              "scope": "16 sealed pre-2026 policy holding paths; no fit, policy change, or 2026 read",
              "price_coordinate": "forward-rehab open/close proxy",
              "price_columns": price_columns,
              "execution_mark_rule": "current valid open, else latest valid close strictly before execution",
              "decision_mark_rule": "latest valid close on or before signal",
              "corporate_action_event_source_present": False,
              "dividend_cashflow_source_present": False,
              "shareholder_total_return_certified": False,
              "policy_inputs": policy_info,
              "totals": totals,
              "policies": all_summary,
              "stale_detail_file": "stale_holding_marks.parquet" if not details.empty else None}
    (OUT / "valuation_coverage.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "totals": totals,
                      "detail_rows": len(details)}, default=str), flush=True)


if __name__ == "__main__":
    main()
