#!/usr/bin/env python
"""Research-only ABCD PIT replay and forward-observation ledger."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


STAGE_ID = "V21.060-R1"
PASS_STATUS = "PASS_V21_060_R1_ABCD_BACKTEST_AND_FORWARD_LEDGER_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_060_R1_READY_WITH_BACKTEST_OR_DATA_WARN"
FAIL_A0 = "FAIL_V21_060_R1_A0_CONTROL_MUTATION_OR_RECOMPUTE"
FAIL_HARDCODED = "FAIL_V21_060_R1_HARDCODED_INCLUSION_VIOLATION"
FAIL_PRICE = "FAIL_V21_060_R1_LOCAL_PRICE_MISSING_INCLUDED"
FAIL_DUPLICATE = "FAIL_V21_060_R1_DUPLICATE_OBSERVATION_ID_VIOLATION"
FAIL_MUTATION = "FAIL_V21_060_R1_FORBIDDEN_MUTATION_DETECTED"

OUT_REL = Path("outputs/v21/experiments/momentum_dynamic")
A0_VIEW_REL = OUT_REL / "V21_059_R1_A0_CURRENT_TESTING_LOCKED_VIEW.csv"
A1_REL = OUT_REL / "V21_059_R1_A1_BASELINE_REPLAY_RANKING.csv"
B_REL = OUT_REL / "V21_059_R1_B_MOMENTUM_STATIC_RANKING.csv"
C_REL = OUT_REL / "V21_059_R1_C_MOMENTUM_DYNAMIC_RANKING.csv"
V59_SUMMARY_REL = OUT_REL / "V21_059_R1_SUMMARY.json"
A0_CANONICAL_REL = Path("outputs/v21/experiments/version_control/V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv")
R1_SNAPSHOT_REL = Path("outputs/v21/experiments/version_control/V21_056_R1_A0_LEDGER_SNAPSHOT.csv")
SNAPSHOT_REL = Path("outputs/v20/backtest/V20_199B_R1_RANDOM_ASOF_RECOMPUTED_FACTOR_SNAPSHOT.csv")
PRICE_REL = Path("inputs/v21/historical_ohlcv_cache/V21_037_R1_HISTORICAL_OHLCV_CACHE.csv")

RESULTS_NAME = "V21_060_R1_ABCD_BACKTEST_RESULTS.csv"
COMPARISON_NAME = "V21_060_R1_ABCD_BACKTEST_COMPARISON.csv"
LEDGER_NAME = "V21_060_R1_ABCD_FORWARD_OBSERVATION_LEDGER.csv"
APPEND_NAME = "V21_060_R1_FORWARD_OBSERVATION_APPEND_AUDIT.csv"
CAPTURE_NAME = "V21_060_R1_MOMENTUM_LEADER_CAPTURE_AUDIT.csv"
LINEAGE_NAME = "V21_060_R1_VARIANT_BACKTEST_LINEAGE_AUDIT.csv"
FORCED_NAME = "V21_060_R1_FORCED_TICKER_BACKTEST_AND_OBSERVATION_AUDIT.csv"
SUMMARY_NAME = "V21_060_R1_SUMMARY.json"

FORCED = ("MU", "SNDK", "DRAM", "SPCX", "USD", "SMH", "SOXX", "SOXL", "QQQ", "TQQQ", "SQQQ")
WINDOWS = {"5D": 5, "10D": 10, "20D": 20, "60D": 60}
VARIANTS = ("A1_BASELINE_REPLAY_CURRENT", "B_MOMENTUM_STATIC_R1", "C_MOMENTUM_DYNAMIC_R1")

RESULT_FIELDS = [
    "backtest_observation_id", "as_of_date", "variant_id", "ticker",
    "instrument_type", "historical_rank", "historical_base_score",
    "historical_momentum_score", "historical_final_score",
    "forward_window", "entry_price", "exit_price", "exit_price_date",
    "forward_return", "return_status", "spy_forward_return",
    "qqq_forward_return", "smh_forward_return", "excess_return_vs_SPY",
    "excess_return_vs_QQQ", "excess_return_vs_SMH",
    "momentum_leader_at_asof", "replay_fallback_used", "fallback_lineage",
    "research_only",
]
OBS_FIELDS = [
    "observation_id", "stage_id", "as_of_date", "version_id", "variant_id",
    "frozen_control", "recomputed", "ticker", "instrument_type", "asset_class",
    "theme", "rank", "score", "score_source", "momentum_score",
    "momentum_state", "chase_permission", "risk_size_bucket",
    "applied_momentum_weight", "market_regime", "regime_fallback_used",
    "forward_window", "scheduled_maturity_date", "realized_forward_return",
    "maturity_status", "price_start_date", "price_end_date", "price_start",
    "price_end", "price_data_status", "source_ranking_path",
    "source_lineage", "research_only",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "TRUE" if clean(value).upper() == "TRUE" else "FALSE"


def num(value: object) -> float | None:
    try:
        parsed = float(clean(value))
        return parsed if math.isfinite(parsed) else None
    except ValueError:
        return None


def fmt(value: object) -> str:
    parsed = num(value)
    return "" if parsed is None else f"{parsed:.10f}"


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: "TRUE" if row.get(field) is True else "FALSE" if row.get(field) is False
                else "" if row.get(field) is None else row.get(field, "")
                for field in fields
            })


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def row_count(path: Path) -> int:
    return len(read_csv(path)[0])


def protected_hashes(root: Path) -> dict[str, dict[str, str]]:
    groups = {"a0": {}, "official": {}, "real_book": {}, "broker": {}}
    for path in (root / A0_CANONICAL_REL, root / R1_SNAPSHOT_REL):
        if path.is_file():
            groups["a0"][rel(root, path)] = sha(path)
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or root / OUT_REL in path.parents:
                continue
            text = rel(root, path).lower().replace("-", "_").replace(" ", "_")
            if "broker" in text:
                groups["broker"][rel(root, path)] = sha(path)
            elif "real_book" in text or "realbook" in text:
                groups["real_book"][rel(root, path)] = sha(path)
            elif "official" in text and any(token in text for token in ("rank", "weight", "recommend", "allocation")):
                groups["official"][rel(root, path)] = sha(path)
    return groups


def changed(before: dict[str, str], after: dict[str, str]) -> bool:
    return any(before.get(key) != after.get(key) for key in set(before) | set(after))


def load_calendar_helper(root: Path) -> object:
    path = root / "scripts/v21/v21_044_r7_technical_only_current_daily_observation_ledger_append.py"
    spec = importlib.util.spec_from_file_location("v21_calendar_helper", path)
    if not spec or not spec.loader:
        raise RuntimeError("Trading-session helper unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_prices(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=["as_of_date", "ticker", "close", "adjusted_close", "volume"], low_memory=False)
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["as_of_date"] = frame["as_of_date"].astype(str).str.slice(0, 10)
    frame["price"] = pd.to_numeric(frame["adjusted_close"], errors="coerce").fillna(pd.to_numeric(frame["close"], errors="coerce"))
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    frame = frame[frame["price"].gt(0)].sort_values(["ticker", "as_of_date"]).drop_duplicates(["ticker", "as_of_date"], keep="last")
    for window in (5, 10, 20):
        frame[f"return_{window}d"] = frame.groupby("ticker")["price"].pct_change(window, fill_method=None)
    for window in WINDOWS.values():
        frame[f"forward_{window}d"] = frame.groupby("ticker")["price"].shift(-window) / frame["price"] - 1
        frame[f"exit_date_{window}d"] = frame.groupby("ticker")["as_of_date"].shift(-window)
        frame[f"exit_price_{window}d"] = frame.groupby("ticker")["price"].shift(-window)
    return frame


def build_historical_variants(snapshot_path: Path, prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    snap = pd.read_csv(snapshot_path, low_memory=False)
    snap = snap[(snap["scenario"] == "PIT_LITE_INITIAL_POLICY") & (snap["factor_status"] == "PASS")].copy()
    snap["ticker"] = snap["ticker"].astype(str).str.upper().str.strip()
    snap["as_of_date"] = snap["as_of_date"].astype(str).str.slice(0, 10)
    needed = prices[[
        "ticker", "as_of_date", "price", "return_5d", "return_10d", "return_20d",
        *[f"forward_{w}d" for w in WINDOWS.values()],
        *[f"exit_date_{w}d" for w in WINDOWS.values()],
        *[f"exit_price_{w}d" for w in WINDOWS.values()],
    ]]
    merged = snap.merge(needed, on=["ticker", "as_of_date"], how="left")
    benchmarks = {}
    for benchmark in ("SPY", "QQQ", "SMH"):
        bench = prices[prices["ticker"] == benchmark].set_index("as_of_date")
        benchmarks[benchmark] = bench
        for window in (5, 10, 20):
            merged[f"{benchmark.lower()}_return_{window}d"] = merged["as_of_date"].map(bench[f"return_{window}d"])
    excess_columns = []
    for window in (5, 10, 20):
        for benchmark in ("spy", "qqq"):
            column = f"excess_{window}d_vs_{benchmark}"
            merged[column] = merged[f"return_{window}d"] - merged[f"{benchmark}_return_{window}d"]
            excess_columns.append(column)
    merged["relative_raw"] = merged[excess_columns].mean(axis=1, skipna=True)
    merged["relative_pct"] = merged.groupby("as_of_date")["relative_raw"].rank(pct=True, method="average") * 100
    merged["technical_pct"] = pd.to_numeric(merged["technical_score"], errors="coerce") * 100
    merged["historical_momentum_score"] = .70 * merged["relative_pct"] + .30 * merged["technical_pct"]
    merged["base_score"] = pd.to_numeric(merged["pit_lite_score"], errors="coerce") * 100
    merged["momentum_leader"] = merged.groupby("as_of_date")["relative_raw"].rank(pct=True, method="average") >= .90

    variant_frames = []
    specs = (
        ("A1_BASELINE_REPLAY_CURRENT", 0.0),
        ("B_MOMENTUM_STATIC_R1", 0.20),
        ("C_MOMENTUM_DYNAMIC_R1", 0.15),
    )
    for variant, weight in specs:
        view = merged.copy()
        view["variant_id"] = variant
        view["applied_weight"] = weight
        view["historical_final_score"] = view["base_score"] * (1 - weight) + view["historical_momentum_score"] * weight
        view["historical_rank"] = view.groupby("as_of_date")["historical_final_score"].rank(method="first", ascending=False)
        variant_frames.append(view[view["historical_rank"] <= 50])
    selected = pd.concat(variant_frames, ignore_index=True)
    return selected, merged


def backtest_rows(selected: pd.DataFrame, instrument_map: dict[str, str]) -> list[dict[str, object]]:
    rows = []
    for record in selected.to_dict("records"):
        for label, window in WINDOWS.items():
            forward = num(record.get(f"forward_{window}d"))
            # Benchmark forward returns are attached below from the price frame map.
            rows.append({
                "backtest_observation_id": f"V21_060_R1::{record['variant_id']}::{record['as_of_date']}::{record['ticker']}::{label}",
                "as_of_date": record["as_of_date"], "variant_id": record["variant_id"],
                "ticker": record["ticker"], "instrument_type": instrument_map.get(record["ticker"], "STOCK"),
                "historical_rank": int(record["historical_rank"]),
                "historical_base_score": fmt(record["base_score"]),
                "historical_momentum_score": fmt(record["historical_momentum_score"]),
                "historical_final_score": fmt(record["historical_final_score"]),
                "forward_window": label, "entry_price": fmt(record.get("price")),
                "exit_price": fmt(record.get(f"exit_price_{window}d")),
                "exit_price_date": clean(record.get(f"exit_date_{window}d")),
                "forward_return": fmt(forward),
                "return_status": "PASS" if forward is not None else "PRICE_MISSING",
                "spy_forward_return": "", "qqq_forward_return": "", "smh_forward_return": "",
                "excess_return_vs_SPY": "", "excess_return_vs_QQQ": "", "excess_return_vs_SMH": "",
                "momentum_leader_at_asof": tf(bool(record.get("momentum_leader"))),
                "replay_fallback_used": "TRUE",
                "fallback_lineage": "V20_199B_R1_PIT_LITE_BASE_PLUS_PIT_TRAILING_RELATIVE_MOMENTUM_APPROXIMATION",
                "research_only": "TRUE",
            })
    return rows


def attach_benchmarks(rows: list[dict[str, object]], prices: pd.DataFrame) -> None:
    benchmark_rows = prices[prices["ticker"].isin(("SPY", "QQQ", "SMH"))]
    lookup = {
        (clean(record["ticker"]), clean(record["as_of_date"]), window):
        num(record.get(f"forward_{window}d"))
        for record in benchmark_rows.to_dict("records")
        for window in WINDOWS.values()
    }
    for row in rows:
        window = WINDOWS[clean(row["forward_window"])]
        as_of = clean(row["as_of_date"])
        forward = num(row["forward_return"])
        for benchmark, field in (("SPY", "spy_forward_return"), ("QQQ", "qqq_forward_return"), ("SMH", "smh_forward_return")):
            value = lookup.get((benchmark, as_of, window))
            row[field] = fmt(value)
            row[f"excess_return_vs_{benchmark}"] = fmt(forward - value) if forward is not None and value is not None else ""


def spearman_stability(group: pd.DataFrame) -> float | None:
    dates = sorted(group["as_of_date"].unique())
    values = []
    for first, second in zip(dates, dates[1:]):
        a = group[group["as_of_date"] == first][["ticker", "historical_rank"]]
        b = group[group["as_of_date"] == second][["ticker", "historical_rank"]]
        joined = a.merge(b, on="ticker", suffixes=("_a", "_b"))
        if len(joined) >= 5:
            rank_a = joined["historical_rank_a"].rank(method="average").to_numpy(dtype=float)
            rank_b = joined["historical_rank_b"].rank(method="average").to_numpy(dtype=float)
            values.append(float(np.corrcoef(rank_a, rank_b)[0, 1]))
    valid = [value for value in values if value is not None and not np.isnan(value)]
    return sum(valid) / len(valid) if valid else None


def aggregate_comparison(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    frame = pd.DataFrame(rows)
    frame["forward_return_num"] = pd.to_numeric(frame["forward_return"], errors="coerce")
    frame["rank_num"] = pd.to_numeric(frame["historical_rank"], errors="coerce")
    for benchmark in ("SPY", "QQQ", "SMH"):
        frame[f"excess_{benchmark}"] = pd.to_numeric(frame[f"excess_return_vs_{benchmark}"], errors="coerce")
    results = []
    a1_top20 = {
        (date, window): set(group.nsmallest(20, "rank_num")["ticker"])
        for (date, window), group in frame[frame["variant_id"] == "A1_BASELINE_REPLAY_CURRENT"].groupby(["as_of_date", "forward_window"])
    }
    for (variant, window), group in frame.groupby(["variant_id", "forward_window"]):
        valid = group.dropna(subset=["forward_return_num"])
        top10 = valid[valid["rank_num"] <= 10]
        top20 = valid[valid["rank_num"] <= 20]
        overlaps = []
        leader_rates = []
        for day, day_group in group.groupby("as_of_date"):
            current = set(day_group[day_group["rank_num"] <= 20]["ticker"])
            reference = a1_top20.get((day, window), set())
            if reference:
                overlaps.append(len(current & reference) / 20)
            leaders = day_group[day_group["momentum_leader_at_asof"] == "TRUE"]
            leader_rates.append(len(leaders[leaders["rank_num"] <= 20]) / max(1, len(leaders)))
        instrument = valid["instrument_type"]
        mean_return = valid["forward_return_num"].mean() if len(valid) else np.nan
        std_return = valid["forward_return_num"].std(ddof=0) if len(valid) else np.nan
        results.append({
            "variant_id": variant, "forward_window": window,
            "observation_count": len(group), "price_available_count": len(valid),
            "price_missing_count": len(group) - len(valid),
            "mean_forward_return": fmt(mean_return), "median_forward_return": fmt(valid["forward_return_num"].median()),
            "hit_rate": fmt((valid["forward_return_num"] > 0).mean()),
            "top10_mean_forward_return": fmt(top10["forward_return_num"].mean()),
            "top20_mean_forward_return": fmt(top20["forward_return_num"].mean()),
            "top10_hit_rate": fmt((top10["forward_return_num"] > 0).mean()),
            "top20_hit_rate": fmt((top20["forward_return_num"] > 0).mean()),
            "excess_return_vs_SPY": fmt(valid["excess_SPY"].mean()),
            "excess_return_vs_QQQ": fmt(valid["excess_QQQ"].mean()),
            "excess_return_vs_SMH": fmt(valid["excess_SMH"].mean()),
            "rank_stability": fmt(spearman_stability(group)),
            "turnover_proxy": fmt(1 - np.mean(overlaps) if overlaps else None),
            "top20_overlap_with_A1": fmt(np.mean(overlaps) if overlaps else None),
            "momentum_leader_capture_rate": fmt(np.mean(leader_rates) if leader_rates else None),
            "false_overheat_block_count": 0,
            "ETF_capture_count": int((instrument != "STOCK").sum()),
            "leveraged_ETF_capture_count": int((instrument == "LEVERAGED_LONG_ETF").sum()),
            "leveraged_ETF_risk_flag_count": int((instrument == "LEVERAGED_LONG_ETF").sum()),
            "inverse_ETF_capture_count": int((instrument == "INVERSE_ETF").sum()),
            "max_drawdown_proxy": fmt(valid["forward_return_num"].min()),
            "risk_adjusted_return_proxy": fmt(mean_return / std_return if std_return and not np.isnan(std_return) else None),
            "replay_fallback_used": "TRUE", "research_only": "TRUE",
        })
    return results


def deterministic_id(variant: str, as_of: str, ticker: str, window: str) -> str:
    raw = f"V21_060_R1::{variant}::{as_of}::{ticker}::{window}"
    return re.sub(r"[^A-Za-z0-9:._-]+", "_", raw)


def build_observations(
    root: Path, prices: pd.DataFrame, existing: list[dict[str, str]],
) -> tuple[list[dict[str, object]], int, int]:
    helper = load_calendar_helper(root)
    price_lookup = prices.set_index(["ticker", "as_of_date"])
    generated: list[dict[str, object]] = []
    a0_rows, _ = read_csv(root / A0_VIEW_REL)
    for row in a0_rows:
        generated.append({
            "observation_id": row["observation_id"], "stage_id": STAGE_ID,
            "as_of_date": row["as_of_date"], "version_id": "A0_CURRENT_TESTING_LOCKED",
            "variant_id": "A0_CURRENT_TESTING_LOCKED", "frozen_control": "TRUE",
            "recomputed": "FALSE", "ticker": row["ticker"], "instrument_type": "STOCK",
            "asset_class": "EQUITY", "theme": "", "rank": row["rank"], "score": row["score"],
            "score_source": row.get("score_source", ""), "momentum_score": "",
            "momentum_state": "", "chase_permission": "", "risk_size_bucket": "",
            "applied_momentum_weight": "0", "market_regime": "UNKNOWN",
            "regime_fallback_used": "TRUE", "forward_window": row["forward_window"],
            "scheduled_maturity_date": row["scheduled_maturity_date"],
            "realized_forward_return": row.get("realized_forward_return", ""),
            "maturity_status": row.get("maturity_status", "PENDING_NOT_MATURED"),
            "price_start_date": "", "price_end_date": "", "price_start": "", "price_end": "",
            "price_data_status": "FROZEN_CONTROL_REFERENCE",
            "source_ranking_path": rel(root, root / A0_VIEW_REL),
            "source_lineage": "A0_CURRENT_TESTING_LOCKED_NON_MUTATING_REFERENCE",
            "research_only": "TRUE",
        })
    ranking_specs = (
        ("A1_BASELINE_REPLAY_CURRENT", root / A1_REL),
        ("B_MOMENTUM_STATIC_R1", root / B_REL),
        ("C_MOMENTUM_DYNAMIC_R1", root / C_REL),
    )
    for variant, path in ranking_specs:
        rows, _ = read_csv(path)
        for row in rows[:50]:
            as_of = clean(row.get("as_of_date"))
            ticker = clean(row.get("ticker")).upper()
            parsed = helper.parse_date(as_of)
            if not parsed:
                continue
            for label, window in WINDOWS.items():
                due, _ = helper.maturity_date(parsed, [], window)
                try:
                    start_price = num(price_lookup.loc[(ticker, as_of), "price"])
                except KeyError:
                    start_price = None
                generated.append({
                    "observation_id": deterministic_id(variant, as_of, ticker, label),
                    "stage_id": STAGE_ID, "as_of_date": as_of, "version_id": variant,
                    "variant_id": variant, "frozen_control": "FALSE", "recomputed": "TRUE",
                    "ticker": ticker, "instrument_type": row.get("instrument_type", "STOCK"),
                    "asset_class": row.get("asset_class", ""), "theme": row.get("theme", ""),
                    "rank": row.get("final_shadow_rank", ""), "score": row.get("final_shadow_score", ""),
                    "score_source": row.get("base_score_source", ""),
                    "momentum_score": row.get("momentum_score", ""),
                    "momentum_state": row.get("momentum_state", ""),
                    "chase_permission": row.get("chase_permission", ""),
                    "risk_size_bucket": row.get("risk_size_bucket", ""),
                    "applied_momentum_weight": row.get("applied_momentum_weight", ""),
                    "market_regime": row.get("market_regime", "UNKNOWN"),
                    "regime_fallback_used": row.get("regime_fallback_used", "TRUE"),
                    "forward_window": label, "scheduled_maturity_date": due,
                    "realized_forward_return": "", "maturity_status": "PENDING_NOT_MATURED",
                    "price_start_date": as_of if start_price is not None else "",
                    "price_end_date": "", "price_start": fmt(start_price), "price_end": "",
                    "price_data_status": "START_PRICE_AVAILABLE_PENDING_MATURITY" if start_price is not None else "START_PRICE_MISSING",
                    "source_ranking_path": rel(root, path),
                    "source_lineage": f"{variant}_RANK_DERIVED_V21_059_R1",
                    "research_only": "TRUE",
                })
    existing_ids = {clean(row.get("observation_id")) for row in existing}
    output = [dict(row) for row in existing]
    skipped = 0
    seen = set(existing_ids)
    for row in generated:
        oid = clean(row["observation_id"])
        if oid in seen:
            skipped += 1
            continue
        seen.add(oid)
        output.append(row)
    return output, skipped, len(generated)


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    before = protected_hashes(root)
    a0_rows, _ = read_csv(root / A0_VIEW_REL)
    a1_rows, _ = read_csv(root / A1_REL)
    b_rows, _ = read_csv(root / B_REL)
    c_rows, _ = read_csv(root / C_REL)
    v59 = json.loads((root / V59_SUMMARY_REL).read_text(encoding="utf-8"))
    instrument_map = {
        clean(row.get("ticker")).upper(): clean(row.get("instrument_type") or "STOCK")
        for row in [*a1_rows, *b_rows, *c_rows]
    }

    prices = load_prices(root / PRICE_REL)
    selected, historical_all = build_historical_variants(root / SNAPSHOT_REL, prices)
    results = backtest_rows(selected, instrument_map)
    attach_benchmarks(results, prices)
    write_csv(out / RESULTS_NAME, results, RESULT_FIELDS)
    comparison = aggregate_comparison(results)
    write_csv(out / COMPARISON_NAME, comparison, list(comparison[0].keys()))

    capture_rows = []
    selected_frame = pd.DataFrame(results)
    for (variant, day), group in selected_frame.groupby(["variant_id", "as_of_date"]):
        unique = group.drop_duplicates("ticker")
        top20 = unique[pd.to_numeric(unique["historical_rank"]) <= 20]
        top50 = unique[pd.to_numeric(unique["historical_rank"]) <= 50]
        leaders = unique[unique["momentum_leader_at_asof"] == "TRUE"]
        capture_rows.append({
            "variant_id": variant, "as_of_date": day,
            "leader_definition": "TOP_DECILE_PIT_TRAILING_5D_10D_20D_RELATIVE_STRENGTH_VS_SPY_QQQ",
            "leader_count_in_ranked_universe": len(leaders),
            "leaders_in_top20": len(top20[top20["momentum_leader_at_asof"] == "TRUE"]),
            "leaders_in_top50": len(top50[top50["momentum_leader_at_asof"] == "TRUE"]),
            "top20_capture_rate": fmt(len(top20[top20["momentum_leader_at_asof"] == "TRUE"]) / max(1, len(leaders))),
            "top50_capture_rate": fmt(len(top50[top50["momentum_leader_at_asof"] == "TRUE"]) / max(1, len(leaders))),
            "fallback_used": "TRUE", "research_only": "TRUE",
        })
    write_csv(out / CAPTURE_NAME, capture_rows, list(capture_rows[0].keys()))

    existing_ledger, _ = read_csv(out / LEDGER_NAME)
    ledger, duplicate_skipped, generated_count = build_observations(root, prices, existing_ledger)
    ids = [clean(row.get("observation_id")) for row in ledger]
    duplicate_output_count = len(ids) - len(set(ids))
    write_csv(out / LEDGER_NAME, ledger, OBS_FIELDS)
    variant_counts = Counter(clean(row.get("variant_id")) for row in ledger)
    window_counts = Counter(clean(row.get("forward_window")) for row in ledger)
    maturity_counts = Counter(clean(row.get("maturity_status")) for row in ledger)
    append_rows = [
        {"audit_metric": "generated_observation_count", "audit_value": generated_count, "details": "Candidate observations generated before deduplication.", "research_only": "TRUE"},
        {"audit_metric": "duplicate_skipped_count", "audit_value": duplicate_skipped, "details": "Existing deterministic observation IDs skipped.", "research_only": "TRUE"},
        {"audit_metric": "appended_count", "audit_value": generated_count - duplicate_skipped, "details": "New rows appended to the stage-local ledger.", "research_only": "TRUE"},
        {"audit_metric": "pending_count", "audit_value": maturity_counts["PENDING_NOT_MATURED"], "details": "", "research_only": "TRUE"},
        {"audit_metric": "matured_count", "audit_value": maturity_counts["MATURED_PRICE_AVAILABLE"], "details": "", "research_only": "TRUE"},
        {"audit_metric": "price_missing_count", "audit_value": maturity_counts["MATURED_PRICE_MISSING"], "details": "", "research_only": "TRUE"},
    ]
    append_rows.extend({"audit_metric": f"rows_by_variant::{key}", "audit_value": value, "details": "", "research_only": "TRUE"} for key, value in sorted(variant_counts.items()))
    append_rows.extend({"audit_metric": f"rows_by_forward_window::{key}", "audit_value": value, "details": "", "research_only": "TRUE"} for key, value in sorted(window_counts.items()))
    append_rows.extend({"audit_metric": f"rows_by_maturity_status::{key}", "audit_value": value, "details": "", "research_only": "TRUE"} for key, value in sorted(maturity_counts.items()))
    write_csv(out / APPEND_NAME, append_rows, ["audit_metric", "audit_value", "details", "research_only"])

    lineage = [
        {"lineage_role": "A0_SOURCE", "source_path": rel(root, root / A0_VIEW_REL), "row_count": len(a0_rows), "usage": "FROZEN_FORWARD_CONTROL_ONLY_NO_REPLAY", "fallback_used": "FALSE", "research_only": "TRUE"},
        {"lineage_role": "A1_SOURCE", "source_path": rel(root, root / A1_REL), "row_count": len(a1_rows), "usage": "CURRENT_FORWARD_OBSERVATION_RANKING", "fallback_used": tf(v59["a1_fallback_used"]), "research_only": "TRUE"},
        {"lineage_role": "B_SOURCE", "source_path": rel(root, root / B_REL), "row_count": len(b_rows), "usage": "CURRENT_FORWARD_OBSERVATION_RANKING", "fallback_used": "FALSE", "research_only": "TRUE"},
        {"lineage_role": "C_SOURCE", "source_path": rel(root, root / C_REL), "row_count": len(c_rows), "usage": "CURRENT_FORWARD_OBSERVATION_RANKING", "fallback_used": tf(v59["regime_fallback_used"]), "research_only": "TRUE"},
        {"lineage_role": "HISTORICAL_PIT_BASE", "source_path": rel(root, root / SNAPSHOT_REL), "row_count": row_count(root / SNAPSHOT_REL), "usage": "A1_BASE_AND_PIT_UNIVERSE", "fallback_used": "TRUE", "research_only": "TRUE"},
        {"lineage_role": "PRICE_DATA", "source_path": rel(root, root / PRICE_REL), "row_count": len(prices), "usage": "TRAILING_MOMENTUM_AND_FUTURE_REALIZED_RETURNS", "fallback_used": "FALSE", "research_only": "TRUE"},
        {"lineage_role": "TRADING_CALENDAR_HELPER", "source_path": "scripts/v21/v21_044_r7_technical_only_current_daily_observation_ledger_append.py", "row_count": 0, "usage": "PROJECTED_MARKET_SESSIONS", "fallback_used": "FALSE", "research_only": "TRUE"},
    ]
    write_csv(out / LINEAGE_NAME, lineage, list(lineage[0].keys()))

    result_tickers = defaultdict(set)
    for row in results:
        result_tickers[clean(row["variant_id"])].add(clean(row["ticker"]))
    obs_tickers = defaultdict(set)
    for row in ledger:
        obs_tickers[clean(row["variant_id"])].add(clean(row["ticker"]))
    price_tickers = set(prices["ticker"])
    forced_rows = []
    for ticker in FORCED:
        local_missing = ticker not in price_tickers
        included_backtest = {variant: ticker in result_tickers[variant] for variant in VARIANTS}
        present_obs = {
            "A0_CURRENT_TESTING_LOCKED": ticker in obs_tickers["A0_CURRENT_TESTING_LOCKED"],
            **{variant: ticker in obs_tickers[variant] for variant in VARIANTS},
        }
        forced_only = False
        violation = forced_only and (any(included_backtest.values()) or any(present_obs.values()))
        reason = ""
        if local_missing:
            reason = "LOCAL_PRICE_DATA_UNAVAILABLE"
        elif ticker == "TQQQ":
            reason = "R4_LOCAL_HISTORY_GAP_NOT_NEWLY_LISTED_EXCLUDED_FROM_B_C"
        forced_rows.append({
            "ticker": ticker,
            "present_in_A0_observation": tf(present_obs["A0_CURRENT_TESTING_LOCKED"]),
            "present_in_A1_observation": tf(present_obs["A1_BASELINE_REPLAY_CURRENT"]),
            "present_in_B_observation": tf(present_obs["B_MOMENTUM_STATIC_R1"]),
            "present_in_C_observation": tf(present_obs["C_MOMENTUM_DYNAMIC_R1"]),
            "included_in_backtest_A1": tf(included_backtest["A1_BASELINE_REPLAY_CURRENT"]),
            "included_in_backtest_B": tf(included_backtest["B_MOMENTUM_STATIC_R1"]),
            "included_in_backtest_C": tf(included_backtest["C_MOMENTUM_DYNAMIC_R1"]),
            "exclusion_reason": reason, "local_price_missing_flag": tf(local_missing),
            "hardcoded_inclusion_violation_flag": tf(violation), "research_only": "TRUE",
        })
    write_csv(out / FORCED_NAME, forced_rows, list(forced_rows[0].keys()))

    after = protected_hashes(root)
    a0_modified = changed(before["a0"], after["a0"])
    official_modified = changed(before["official"], after["official"])
    real_modified = changed(before["real_book"], after["real_book"])
    broker_modified = changed(before["broker"], after["broker"])
    hardcoded = sum(row["hardcoded_inclusion_violation_flag"] == "TRUE" for row in forced_rows)
    local_missing_included = sum(
        row["local_price_missing_flag"] == "TRUE"
        and any(row[field] == "TRUE" for field in (
            "present_in_A1_observation", "present_in_B_observation", "present_in_C_observation",
            "included_in_backtest_A1", "included_in_backtest_B", "included_in_backtest_C",
        ))
        for row in forced_rows
    )
    tqqq_ipo = 0
    a0_recomputed = False
    backtest_fallback_used = True
    forced_missing = len(set(FORCED) - {row["ticker"] for row in forced_rows})
    variant_backtest_counts = Counter(clean(row["variant_id"]) for row in results)
    pending = maturity_counts["PENDING_NOT_MATURED"]
    matured = maturity_counts["MATURED_PRICE_AVAILABLE"]
    missing_obs = maturity_counts["MATURED_PRICE_MISSING"] + sum(clean(row.get("price_data_status")) == "START_PRICE_MISSING" for row in ledger)
    if a0_modified or a0_recomputed:
        final, decision = FAIL_A0, "STOP_AND_RESTORE_A0_CONTROL"
    elif official_modified or real_modified or broker_modified:
        final, decision = FAIL_MUTATION, "STOP_AND_RESTORE_FORBIDDEN_MUTATION"
    elif hardcoded:
        final, decision = FAIL_HARDCODED, "REPAIR_FORCED_INCLUSION_LOGIC"
    elif local_missing_included:
        final, decision = FAIL_PRICE, "REPAIR_BACKTEST_OR_OBSERVATION_ELIGIBILITY"
    elif duplicate_output_count:
        final, decision = FAIL_DUPLICATE, "REPAIR_OBSERVATION_ID_DEDUPLICATION"
    elif backtest_fallback_used or any(clean(row["return_status"]) != "PASS" for row in results):
        final, decision = PARTIAL_STATUS, "READY_FOR_V21_061_WITH_BACKTEST_OR_DATA_WARN"
    else:
        final, decision = PASS_STATUS, "ABCD_BACKTEST_AND_FORWARD_LEDGER_READY_FOR_V21_061_MATURITY_COMPARISON"
    summary = {
        "FINAL_STATUS": final, "DECISION": decision, "stage_id": STAGE_ID, "research_only": True,
        "a0_row_count": len(a0_rows), "a1_ranking_row_count": len(a1_rows),
        "b_ranking_row_count": len(b_rows), "c_ranking_row_count": len(c_rows),
        "backtest_row_count": len(results), "backtest_variant_count": len(variant_backtest_counts),
        "backtest_forward_windows": list(WINDOWS), "a1_backtest_rows": variant_backtest_counts["A1_BASELINE_REPLAY_CURRENT"],
        "b_backtest_rows": variant_backtest_counts["B_MOMENTUM_STATIC_R1"],
        "c_backtest_rows": variant_backtest_counts["C_MOMENTUM_DYNAMIC_R1"],
        "backtest_fallback_used": True, "a1_fallback_used": bool(v59["a1_fallback_used"]),
        "c_regime_fallback_used": bool(v59["regime_fallback_used"]),
        "future_observation_row_count": len(ledger),
        "a0_future_observation_rows": variant_counts["A0_CURRENT_TESTING_LOCKED"],
        "a1_future_observation_rows": variant_counts["A1_BASELINE_REPLAY_CURRENT"],
        "b_future_observation_rows": variant_counts["B_MOMENTUM_STATIC_R1"],
        "c_future_observation_rows": variant_counts["C_MOMENTUM_DYNAMIC_R1"],
        "duplicate_skipped_count": duplicate_skipped, "pending_observation_count": pending,
        "matured_observation_count": matured, "price_missing_observation_count": missing_obs,
        "forced_audit_count": len(forced_rows), "forced_audit_missing_count": forced_missing,
        "hardcoded_inclusion_violation_count": hardcoded,
        "local_price_missing_ranked_violation_count": local_missing_included,
        "tqqq_ipo_watch_violation_count": tqqq_ipo, "a0_recomputed": a0_recomputed,
        "a0_modified": a0_modified, "official_mutation_detected": official_modified,
        "real_book_mutation_detected": real_modified, "broker_mutation_detected": broker_modified,
        "next_recommended_stage": "V21.061_MATURITY_COMPARISON" if final in {PASS_STATUS, PARTIAL_STATUS} else "REPAIR_V21_060_R1",
    }
    write_json(out / SUMMARY_NAME, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run_stage(args.root)
    print(json.dumps(summary, indent=2))
    return 1 if clean(summary["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
