#!/usr/bin/env python
"""V21.097 historical event-occurrence impact and forward observation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay


OUT = Path("outputs/v21")
MASTER_REL = Path("outputs/v21/v21_096_r6_certified_event_master_ledger.csv")
TOP20_HISTORY_REL = Path(
    "outputs/v21/manual_review/"
    "top20_past2y_certified_event_occurrence_from_v21_096_20260622.csv"
)
FORWARD_REL = Path(
    "data/events/manual_import/top20_forward/"
    "top20_forward_risk_events_manual_20260622.csv"
)
D_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
WINDOWS = (1, 3, 5, 10, 20)
CHECKPOINTS = (
    ("T-5", -5), ("T-3", -3), ("T-1", -1), ("T0", 0),
    ("T+1", 1), ("T+3", 3), ("T+5", 5), ("T+10", 10), ("T+20", 20),
)
OUTPUTS = (
    "v21_097_r1_event_input_validation.csv",
    "v21_097_r1_event_input_validation.json",
    "v21_097_r2_historical_event_occurrence_return_rows.csv",
    "v21_097_r2_historical_event_occurrence_price_join_validation.json",
    "v21_097_r3_event_type_impact_summary.csv",
    "v21_097_r4_ticker_event_vulnerability_summary.csv",
    "v21_097_r4_sector_event_vulnerability_summary.csv",
    "v21_097_r5_top20_forward_event_observation_schedule.csv",
    "v21_097_r5_top20_forward_event_observation_status.csv",
    "v21_097_r6_current_d_event_risk_dashboard.csv",
    "v21_097_r7_event_occurrence_and_forward_observation_report.md",
    "v21_097_r7_event_occurrence_and_forward_observation_summary.json",
)


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=json_default) + "\n", encoding="utf-8")


def markdown(title: str, summary: dict[str, Any]) -> str:
    lines = [f"# {title}", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in summary.items())
    lines.extend([
        "",
        "Historical results describe post-filing event-occurrence behavior only. They do not "
        "establish historical pre-event tradability or authorize ranking penalties.",
    ])
    return "\n".join(lines) + "\n"


def protected_snapshot(root: Path, output_paths: set[Path]) -> dict[str, str]:
    tokens = (
        "official", "broker", "protected", "forward_observation_ledger",
        "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
    )
    result = {}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.resolve() in output_paths:
                continue
            if any(token in path.as_posix().lower() for token in tokens):
                result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def current_rankings(root: Path) -> pd.DataFrame:
    frame = pd.read_csv(root / D_REL, low_memory=False)
    frame["final_shadow_rank"] = pd.to_numeric(frame["final_shadow_rank"], errors="coerce")
    frame = frame[frame["final_shadow_rank"].notna()].copy()
    frame["as_of_date"] = frame["as_of_date"].astype(str)
    latest = frame["as_of_date"].max()
    current = frame[frame["as_of_date"].eq(latest)].sort_values("final_shadow_rank").head(50)
    return pd.DataFrame({
        "rank": current["final_shadow_rank"].astype(int),
        "ticker": current["ticker"].astype(str).str.upper().str.strip(),
        "final_score": pd.to_numeric(current["final_shadow_score"], errors="coerce"),
        "top20_flag": current["final_shadow_rank"].le(20),
        "top50_flag": True,
        "theme": current["theme"].fillna("").astype(str),
        "momentum_state": current["momentum_state"].fillna("").astype(str),
    })


def validate_inputs(root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    specs = [
        ("V21_096_MASTER", MASTER_REL, {
            "event_id", "event_type", "event_date", "ticker",
            "known_as_of_timestamp", "historical_event_occurrence_usable",
            "historical_pre_event_calendar_usable",
        }),
        ("TOP20_HISTORY_EXTRACT", TOP20_HISTORY_REL, {
            "event_id", "event_type", "event_date", "ticker",
            "known_as_of_timestamp", "historical_event_occurrence_usable",
        }),
        ("TOP20_FORWARD_MANUAL", FORWARD_REL, {
            "ticker", "rank", "event_type", "event_name", "event_date",
            "retrieval_timestamp_utc",
        }),
        ("PRICE_HISTORY", PRICE_REL, {"symbol", "date", "adjusted_close"}),
        ("D_RANKING", D_REL, {"ticker", "final_shadow_rank", "final_shadow_score"}),
    ]
    rows = []
    loaded = {}
    for source_name, rel, required in specs:
        path = root / rel
        exists = path.is_file()
        columns = []
        row_count = 0
        if exists:
            try:
                sample = pd.read_csv(path, nrows=0)
                columns = list(sample.columns)
                if source_name != "PRICE_HISTORY":
                    row_count = len(pd.read_csv(path, low_memory=False))
            except Exception:
                exists = False
        missing = sorted(required - set(columns))
        rows.append({
            "source_name": source_name, "source_path": rel.as_posix(),
            "exists": exists, "row_count": row_count,
            "required_columns_exist": not missing,
            "missing_columns": "|".join(missing),
            "validation_status": "PASS" if exists and not missing else "FAIL",
            "research_only": True,
        })
        loaded[source_name] = exists and not missing
    forward_count = 0
    forward_certified = 0
    pit_warnings = 0
    if loaded["TOP20_FORWARD_MANUAL"]:
        forward = pd.read_csv(root / FORWARD_REL, low_memory=False)
        forward_count = len(forward)
        event_date = pd.to_datetime(forward["event_date"], errors="coerce")
        retrieval = pd.to_datetime(
            forward["retrieval_timestamp_utc"], utc=True, errors="coerce"
        )
        forward_certified = int((event_date.notna() & retrieval.notna()).sum())
        pit_warnings += int((event_date.notna() & retrieval.isna()).sum())
    if loaded["V21_096_MASTER"]:
        master = pd.read_csv(root / MASTER_REL, low_memory=False)
        certified = master["pit_certified"].map(truth)
        known = pd.to_datetime(
            master["known_as_of_timestamp"], utc=True, errors="coerce", format="mixed"
        )
        pit_warnings += int((certified & known.isna()).sum())
    summary = {
        "stage": "V21.097-R1_EVENT_INPUT_VALIDATION",
        "status": "PASS" if all(loaded.values()) and forward_certified == 20 and pit_warnings == 0 else "FAIL",
        "v21_096_master_exists": loaded["V21_096_MASTER"],
        "top20_history_extract_exists": loaded["TOP20_HISTORY_EXTRACT"],
        "top20_forward_manual_rows": forward_count,
        "top20_forward_certified_count": forward_certified,
        "pit_leakage_warnings": pit_warnings,
        "historical_pre_event_random_backtest_allowed": False,
        "research_only": True, "official_adoption_allowed": False,
    }
    return pd.DataFrame(rows), summary


def load_prices(root: Path, symbols: set[str]) -> dict[str, pd.DataFrame]:
    parts = []
    for chunk in pd.read_csv(
        root / PRICE_REL,
        usecols=["symbol", "date", "adjusted_close"],
        chunksize=250_000,
        low_memory=False,
    ):
        keep = chunk["symbol"].astype(str).str.upper().isin(symbols)
        if keep.any():
            parts.append(chunk.loc[keep].copy())
    if not parts:
        return {}
    frame = pd.concat(parts, ignore_index=True)
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame = frame.dropna(subset=["date", "adjusted_close"]).sort_values(["symbol", "date"])
    return {
        symbol: group.drop_duplicates("date").reset_index(drop=True)
        for symbol, group in frame.groupby("symbol")
    }


def price_path(
    prices: pd.DataFrame | None, event_date: pd.Timestamp
) -> tuple[pd.Timestamp | None, dict[int, float]]:
    if prices is None or prices.empty or pd.isna(event_date):
        return None, {}
    dates = prices["date"].values
    index = int(np.searchsorted(dates, np.datetime64(event_date.normalize()), side="left"))
    if index >= len(prices):
        return None, {}
    result = {}
    for offset in (0, *WINDOWS):
        position = index + offset
        result[offset] = (
            float(prices.iloc[position]["adjusted_close"])
            if position < len(prices) else np.nan
        )
    return prices.iloc[index]["date"], result


def historical_return_rows(
    master: pd.DataFrame,
    rankings: pd.DataFrame,
    price_map: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rank_map = rankings.set_index("ticker")["rank"].to_dict()
    events = master[
        master["historical_event_occurrence_usable"].map(truth)
        & master["ticker"].isin(set(rankings["ticker"]))
        & master["ticker"].ne("ALL")
    ].copy()
    rows = []
    benchmark = price_map.get("QQQ")
    for _, event in events.iterrows():
        event_date = pd.to_datetime(event["event_date"], errors="coerce")
        mapped_date, path = price_path(price_map.get(event["ticker"]), event_date)
        benchmark_date, benchmark_path = price_path(benchmark, event_date)
        record = {
            "event_id": event["event_id"], "ticker": event["ticker"],
            "rank_if_current_top50": rank_map.get(event["ticker"]),
            "event_type": event["event_type"], "event_name": event["event_name"],
            "event_date": event["event_date"],
            "price_event_date": "" if mapped_date is None else mapped_date.date().isoformat(),
            "price_t0": path.get(0, np.nan),
        }
        for window in WINDOWS:
            record[f"price_t{window}"] = path.get(window, np.nan)
            record[f"return_{window}d"] = (
                path.get(window) / path.get(0) - 1
                if path.get(0) and pd.notna(path.get(window)) else np.nan
            )
            benchmark_return = (
                benchmark_path.get(window) / benchmark_path.get(0) - 1
                if benchmark_path.get(0) and pd.notna(benchmark_path.get(window))
                else np.nan
            )
            record[f"benchmark_return_{window}d"] = benchmark_return
            record[f"excess_return_{window}d"] = (
                record[f"return_{window}d"] - benchmark_return
                if pd.notna(record[f"return_{window}d"]) and pd.notna(benchmark_return)
                else np.nan
            )
        record["price_missing_flag"] = mapped_date is None or pd.isna(record["price_t0"])
        record["benchmark_missing_flag"] = benchmark_date is None or pd.isna(
            record["benchmark_return_1d"]
        )
        record["research_only"] = True
        rows.append(record)
    return pd.DataFrame(rows)


def cvar(values: pd.Series, quantile: float = .05) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return np.nan
    cutoff = clean.quantile(quantile)
    return clean[clean.le(cutoff)].mean()


def impact_summary(rows: pd.DataFrame) -> pd.DataFrame:
    output = []
    for event_type, group in rows.groupby("event_type"):
        for window in WINDOWS:
            values = group[f"return_{window}d"].dropna()
            excess = group[f"excess_return_{window}d"].dropna()
            output.append({
                "event_type": event_type, "window": f"{window}D",
                "event_count": len(group), "usable_event_count": len(values),
                "mean_return": values.mean(), "median_return": values.median(),
                "hit_rate": values.gt(0).mean(), "p10_return": values.quantile(.10),
                "p5_return": values.quantile(.05), "cvar_5": cvar(values),
                "worst_return": values.min(),
                "severe_loss_count": int(values.le(-.10).sum()),
                "severe_gain_count": int(values.ge(.10).sum()),
                "mean_excess_vs_QQQ": excess.mean(),
                "median_excess_vs_QQQ": excess.median(),
                "negative_excess_rate": excess.lt(0).mean(),
                "research_only": True,
            })
    return pd.DataFrame(output)


def vulnerability_bucket(score: float) -> str:
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    if score > 0:
        return "LOW"
    return "INSUFFICIENT"


def vulnerability_summary(
    rows: pd.DataFrame, rankings: pd.DataFrame, sector_map: dict[str, str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rank_map = rankings.set_index("ticker")["rank"].to_dict()
    ticker_rows = []
    for ticker, group in rows.groupby("ticker"):
        ret5 = group["return_5d"].dropna()
        ret10 = group["return_10d"].dropna()
        losses = group[group["return_5d"].lt(0)]
        loss_types = (
            losses.groupby("event_type")["return_5d"].mean().sort_values().index[:3]
            if not losses.empty else []
        )
        severe = int(group["return_5d"].le(-.10).sum() + group["return_10d"].le(-.10).sum())
        score = min(100.0, severe * 8.0 + max(0.0, -cvar(ret5)) * 180 + max(0.0, -cvar(ret10)) * 120)
        ticker_rows.append({
            "ticker": ticker, "current_rank": rank_map.get(ticker),
            "event_count": len(group),
            "earnings_occurrence_count": int(group["event_type"].eq("ticker_earnings_occurrence").sum()),
            "severe_loss_count": severe,
            "worst_5d_return": ret5.min(), "worst_10d_return": ret10.min(),
            "cvar_5d": cvar(ret5), "cvar_10d": cvar(ret10),
            "event_types_most_associated_with_loss": "|".join(loss_types),
            "event_vulnerability_bucket": vulnerability_bucket(score),
            "event_vulnerability_score": score,
            "sector_or_industry": sector_map.get(ticker, "UNMAPPED"),
            "research_only": True,
        })
    ticker_summary = pd.DataFrame(ticker_rows)
    sector_rows = []
    if not ticker_summary.empty:
        merged = rows.merge(
            ticker_summary[["ticker", "sector_or_industry"]], on="ticker", how="left"
        )
        for sector, group in merged.groupby("sector_or_industry"):
            ret5, ret10 = group["return_5d"].dropna(), group["return_10d"].dropna()
            severe = int(group["return_5d"].le(-.10).sum() + group["return_10d"].le(-.10).sum())
            score = min(100.0, severe * 4.0 + max(0.0, -cvar(ret5)) * 150 + max(0.0, -cvar(ret10)) * 100)
            loss_types = (
                group[group["return_5d"].lt(0)].groupby("event_type")["return_5d"]
                .mean().sort_values().index[:3]
            )
            sector_rows.append({
                "sector_or_industry": sector, "ticker_count": group["ticker"].nunique(),
                "event_count": len(group),
                "earnings_occurrence_count": int(group["event_type"].eq("ticker_earnings_occurrence").sum()),
                "severe_loss_count": severe,
                "worst_5d_return": ret5.min(), "worst_10d_return": ret10.min(),
                "cvar_5d": cvar(ret5), "cvar_10d": cvar(ret10),
                "event_types_most_associated_with_loss": "|".join(loss_types),
                "event_vulnerability_bucket": vulnerability_bucket(score),
                "event_vulnerability_score": score, "research_only": True,
            })
    return ticker_summary, pd.DataFrame(sector_rows)


def normalize_forward(forward: pd.DataFrame) -> pd.DataFrame:
    event_date = pd.to_datetime(forward["event_date"], errors="coerce")
    retrieval = pd.to_datetime(
        forward["retrieval_timestamp_utc"], utc=True, errors="coerce"
    )
    return forward[event_date.notna() & retrieval.notna()].copy()


def observation_schedule(
    forward: pd.DataFrame,
    price_map: dict[str, pd.DataFrame],
    run_date: pd.Timestamp,
) -> pd.DataFrame:
    rows = []
    for index, event in forward.iterrows():
        event_date = pd.Timestamp(event["event_date"])
        ticker_prices = price_map.get(event["ticker"])
        price_dates = set(ticker_prices["date"].dt.date) if ticker_prices is not None else set()
        for label, offset in CHECKPOINTS:
            checkpoint = event_date + BDay(offset)
            available = checkpoint.date() in price_dates
            pending = checkpoint.normalize() > run_date.normalize() or not available
            rows.append({
                "observation_id": "V21_097_OBS_" + hashlib.sha256(
                    f"{event['ticker']}|{event['event_date']}|{label}|{index}".encode()
                ).hexdigest()[:20].upper(),
                "ticker": event["ticker"], "rank": event["rank"],
                "event_type": event["event_type"], "event_name": event["event_name"],
                "event_date": event["event_date"], "event_time": event.get("event_time", ""),
                "event_severity": event.get("event_severity", ""),
                "event_confidence": event.get("event_confidence", ""),
                "checkpoint_label": label,
                "checkpoint_date": checkpoint.date().isoformat(),
                "checkpoint_maturity_status": "PENDING" if pending else "MATURED",
                "price_required_date": checkpoint.date().isoformat(),
                "price_available": available,
                "realized_return_available": bool(
                    available and label.startswith("T+") and label != "T0"
                ),
                "scheduled_only": True, "research_only": True,
            })
    return pd.DataFrame(rows)


def dashboard(
    rankings: pd.DataFrame,
    ticker_summary: pd.DataFrame,
    forward: pd.DataFrame,
    run_date: pd.Timestamp,
) -> pd.DataFrame:
    vulnerability = ticker_summary.set_index("ticker") if not ticker_summary.empty else None
    rows = []
    for _, rank_row in rankings.iterrows():
        ticker = rank_row["ticker"]
        future = forward[
            forward["ticker"].eq(ticker)
            & pd.to_datetime(forward["event_date"]).between(
                run_date.normalize(), run_date.normalize() + pd.Timedelta(days=180)
            )
        ].sort_values("event_date")
        nearest = future.iloc[0] if not future.empty else None
        vuln = vulnerability.loc[ticker] if vulnerability is not None and ticker in vulnerability.index else None
        rows.append({
            "rank": rank_row["rank"], "ticker": ticker,
            "final_score": rank_row["final_score"],
            "top20_flag": rank_row["top20_flag"], "top50_flag": True,
            "historical_event_count": 0 if vuln is None else int(vuln["event_count"]),
            "historical_earnings_occurrence_count": 0 if vuln is None else int(vuln["earnings_occurrence_count"]),
            "historical_event_vulnerability_score": np.nan if vuln is None else vuln["event_vulnerability_score"],
            "historical_event_vulnerability_bucket": "INSUFFICIENT" if vuln is None else vuln["event_vulnerability_bucket"],
            "future_event_count_next_180d": len(future),
            "nearest_future_event_date": "" if nearest is None else nearest["event_date"],
            "nearest_future_event_type": "" if nearest is None else nearest["event_type"],
            "days_to_nearest_future_event": np.nan if nearest is None else (
                pd.Timestamp(nearest["event_date"]).date() - run_date.date()
            ).days,
            "future_event_severity": "" if nearest is None else nearest.get("event_severity", ""),
            "entry_throttle_research_allowed": bool(nearest is not None),
            "exposure_overlay_research_allowed": bool(nearest is not None or vuln is not None),
            "ranking_penalty_allowed": False, "official_adoption_allowed": False,
            "research_only": True,
        })
    return pd.DataFrame(rows)


def run(root: Path) -> dict[str, Any]:
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUTS}
    before = protected_snapshot(root, output_paths)
    d_hash_before = sha256(root / D_REL)
    master_hash_before = sha256(root / MASTER_REL)
    run_date = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)

    validation_rows, validation = validate_inputs(root)
    validation_rows.to_csv(out / OUTPUTS[0], index=False)
    write_json(out / OUTPUTS[1], validation)

    master = pd.read_csv(root / MASTER_REL, low_memory=False)
    rankings = current_rankings(root)
    top50_symbols = set(rankings["ticker"])
    price_map = load_prices(root, top50_symbols | {"QQQ", "SPY"})
    returns = historical_return_rows(master, rankings, price_map)
    returns.to_csv(out / OUTPUTS[2], index=False)
    usable = returns["return_5d"].notna() if not returns.empty else pd.Series(dtype=bool)
    price_validation = {
        "status": "PASS", "historical_event_rows_loaded": len(returns),
        "price_joined_rows": int((~returns["price_missing_flag"]).sum()),
        "usable_5d_return_rows": int(usable.sum()),
        "price_missing_rows": int(returns["price_missing_flag"].sum()),
        "benchmark_missing_rows": int(returns["benchmark_missing_flag"].sum()),
        "price_coverage_ratio": float((~returns["price_missing_flag"]).mean()) if len(returns) else 0.0,
        "next_trading_day_mapping_used": True,
        "intraday_data_used": False, "pre_event_signal_created": False,
        "research_only": True,
    }
    write_json(out / OUTPUTS[3], price_validation)

    impact = impact_summary(returns)
    impact.to_csv(out / OUTPUTS[4], index=False)
    forward_raw = pd.read_csv(root / FORWARD_REL, low_memory=False)
    forward = normalize_forward(forward_raw)
    sector_map = {
        str(row["ticker"]).upper(): str(row.get("affected_sector", "") or "UNMAPPED")
        for _, row in forward.iterrows()
    }
    ticker_vulnerability, sector_vulnerability = vulnerability_summary(
        returns, rankings, sector_map
    )
    ticker_vulnerability.to_csv(out / OUTPUTS[5], index=False)
    sector_vulnerability.to_csv(out / OUTPUTS[6], index=False)

    schedule = observation_schedule(forward, price_map, run_date)
    schedule.to_csv(out / OUTPUTS[7], index=False)
    schedule.to_csv(out / OUTPUTS[8], index=False)
    current_dashboard = dashboard(
        rankings, ticker_vulnerability, forward, run_date
    )
    current_dashboard.to_csv(out / OUTPUTS[9], index=False)

    after = protected_snapshot(root, output_paths)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d_preserved = sha256(root / D_REL) == d_hash_before
    master_preserved = sha256(root / MASTER_REL) == master_hash_before
    official_changed = [p for p in changed if "official" in p.lower() or "broker" in p.lower()]
    pit_warnings = int(validation["pit_leakage_warnings"])
    severe_loss_events = int(
        returns[[f"return_{w}d" for w in WINDOWS]].le(-.10).any(axis=1).sum()
    )
    left_tail_types = sorted(set(
        impact.loc[
            impact["window"].isin(["5D", "10D"])
            & (
                impact["p5_return"].lt(-.10)
                | impact["cvar_5"].lt(-.10)
                | impact["severe_loss_count"].gt(0)
            ),
            "event_type",
        ]
    ))
    high_tickers = int(
        ticker_vulnerability["event_vulnerability_bucket"].eq("HIGH").sum()
    ) if not ticker_vulnerability.empty else 0
    pending = int(schedule["checkpoint_maturity_status"].eq("PENDING").sum())
    matured = int(schedule["checkpoint_maturity_status"].eq("MATURED").sum())
    coverage = price_validation["price_coverage_ratio"]
    if pit_warnings:
        decision = "REJECT_EVENT_OBSERVATION_DUE_TO_PIT_LEAKAGE"
    elif changed or not d_preserved or not master_preserved:
        decision = "REJECT_EVENT_OBSERVATION_DUE_TO_PROTECTED_MUTATION"
    elif coverage < .60:
        decision = "EVENT_OCCURRENCE_ANALYSIS_INSUFFICIENT_PRICE_COVERAGE"
    elif left_tail_types and len(schedule):
        decision = "EVENT_OCCURRENCE_AND_FORWARD_OBSERVATION_READY_RESEARCH_ONLY"
    elif len(schedule):
        decision = "FORWARD_EVENT_OBSERVATION_READY_NO_HISTORICAL_LEFT_TAIL_SIGNAL"
    else:
        decision = "EVENT_OCCURRENCE_ANALYSIS_INSUFFICIENT_PRICE_COVERAGE"
    summary = {
        "FINAL_STATUS": "PASS" if not pit_warnings and not changed and d_preserved and master_preserved else "FAIL",
        "DECISION": decision,
        "HISTORICAL_EVENT_ROWS_LOADED": len(returns),
        "HISTORICAL_EVENT_ROWS_PRICE_JOINED": int((~returns["price_missing_flag"]).sum()),
        "USABLE_HISTORICAL_EVENT_RETURN_ROWS": int(usable.sum()),
        "PRICE_MISSING_ROWS": int(returns["price_missing_flag"].sum()),
        "BENCHMARK_MISSING_ROWS": int(returns["benchmark_missing_flag"].sum()),
        "EVENT_TYPES_ANALYZED": int(returns["event_type"].nunique()),
        "EARNINGS_OCCURRENCE_ROWS_ANALYZED": int(returns["event_type"].eq("ticker_earnings_occurrence").sum()),
        "SEVERE_LOSS_EVENTS": severe_loss_events,
        "EVENT_TYPES_WITH_LEFT_TAIL_RISK": left_tail_types,
        "TICKERS_WITH_HIGH_EVENT_VULNERABILITY": high_tickers,
        "TOP20_FORWARD_EVENT_ROWS_LOADED": len(forward),
        "TOP20_FORWARD_OBSERVATION_CHECKPOINTS_CREATED": len(schedule),
        "TOP20_FORWARD_PENDING_CHECKPOINTS": pending,
        "TOP20_FORWARD_MATURED_CHECKPOINTS": matured,
        "FORWARD_EVENT_OBSERVATION_ALLOWED": len(schedule) > 0,
        "HISTORICAL_EVENT_OCCURRENCE_OBSERVATION_ALLOWED": len(returns) > 0,
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED": False,
        "ENTRY_THROTTLE_RESEARCH_ALLOWED": len(schedule) > 0,
        "EXPOSURE_OVERLAY_RESEARCH_ALLOWED": len(returns) > 0 or len(schedule) > 0,
        "PIT_LEAKAGE_WARNINGS": pit_warnings,
        "PROTECTED_OUTPUTS_MODIFIED": bool(changed or not d_preserved or not master_preserved),
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True, "OFFICIAL_ADOPTION_ALLOWED": False,
        "D_BASELINE_PRESERVED": d_preserved,
        "V21_096_LEDGER_PRESERVED": master_preserved,
        "RECOMMENDED_NEXT_STAGE": "V21.098_FORWARD_EVENT_CHECKPOINT_MATURITY_MONITOR",
    }
    write_json(out / OUTPUTS[11], summary)
    (out / OUTPUTS[10]).write_text(markdown(
        "V21.097 Event Occurrence and Forward Observation", summary
    ), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run(args.root.resolve())
    for key, value in summary.items():
        if isinstance(value, list):
            value = "|".join(value)
        print(f"{key}={value}")
    return 0 if summary["FINAL_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
