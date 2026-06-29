#!/usr/bin/env python
"""V21.107 append-safe live forward tracking for D research views."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


STAGE = "V21.107_LIVE_FORWARD_TRACKING_FOR_D_TOP20_HOLD_AND_D_TOP50_QUARTERLY"
SOURCE_V106_RUN_ID = "20260623_142922"
SOURCE_V106_R1_RUN_ID = "20260623_143953"
OUTPUT_REL = Path("outputs/v21/v21_107_live_forward_tracking")
LEDGER_REL = Path("outputs/v21/live_forward_ledger")
RANKING_GLOB = "outputs/v21/V21.102_FULL_LATEST_DATA_SYSTEM_RERUN/*/full_ranking_D.csv"
PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
BENCH_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv")

CONFIG = "v21_107_config.json"
LEDGER = "v21_107_live_observation_ledger.csv"
TOP20 = "v21_107_top20_hold_only_observations.csv"
TOP50 = "v21_107_top50_quarterly_observations.csv"
MATURITY = "v21_107_maturity_evaluator_results.csv"
BENCHMARK = "v21_107_benchmark_comparison.csv"
TURNOVER = "v21_107_turnover_tracking.csv"
PENDING = "v21_107_pending_observations.csv"
MATURED = "v21_107_matured_observations.csv"
WARNINGS = "v21_107_warning_audit.csv"
README = "v21_107_decision_readme.md"

MASTER_OBSERVATIONS = "v21_107_master_observations.csv"
MASTER_MATURITY = "v21_107_master_maturity_results.csv"
MASTER_TURNOVER = "v21_107_master_turnover.csv"
MASTER_AUDIT = "v21_107_append_audit.csv"

PASS = "PASS_V21_107_LIVE_FORWARD_LEDGER_STARTED"
WAIT = "PARTIAL_PASS_V21_107_LEDGER_STARTED_WAITING_FOR_MATURITY"
DUPLICATE = "PARTIAL_PASS_V21_107_NO_NEW_RANKING_DATE_DUPLICATE_SKIPPED"
FAIL = "FAIL_V21_107_LIVE_FORWARD_LEDGER_OR_LEAKAGE_BLOCKER"

HORIZONS = (21, 63, 126, 189, 252)
BENCHMARKS = ("QQQ", "SPY", "SOXX")

OBS_FIELDS = [
    "observation_id", "ranking_date", "variant", "view_type", "portfolio_size",
    "tickers_json", "ranks_json", "weights_json", "start_prices_json",
    "benchmark_start_prices_json", "maturity_21d", "maturity_63d", "maturity_126d",
    "maturity_189d", "maturity_252d", "status", "source_ranking_path",
    "source_ranking_file_hash", "source_price_file_hash", "source_benchmark_file_hash",
    "created_run_id", "created_at_utc", "live_forward_no_future_leakage",
    "historical_pit_factor_approximation_warning", "historical_survivorship_bias_warning",
    "research_only",
]

MATURITY_FIELDS = [
    "result_id", "observation_id", "ranking_date", "view_type", "horizon_days",
    "target_maturity_date", "evaluation_price_date", "portfolio_return",
    "benchmark_QQQ_return", "benchmark_SPY_return", "benchmark_SOXX_return",
    "excess_vs_QQQ", "excess_vs_SPY", "excess_vs_SOXX", "missing_price_count",
    "maturity_status", "live_forward_no_future_leakage", "first_matured_run_id",
    "first_matured_at_utc", "research_only",
]

TURNOVER_FIELDS = [
    "turnover_id", "observation_id", "ranking_date", "view_type",
    "previous_observation_id", "previous_ranking_date", "holding_overlap",
    "entry_count", "exit_count", "realized_turnover", "entries_json", "exits_json",
    "rebalance_executed", "created_run_id", "research_only",
]


def load_v103(root: Path):
    path = root / "scripts/v21/v21_103_abcd_random_long_horizon_backtest_spec.py"
    spec = importlib.util.spec_from_file_location("v21_103_shared_for_v107", path)
    if not spec or not spec.loader:
        raise RuntimeError("V21.103 shared implementation unavailable.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path, fields: list[str]) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [{field: row.get(field, "") for field in fields} for row in rows]


def immutable_output(root: Path, override: Path | None, run_id: str | None) -> tuple[Path, str]:
    identifier = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output = (override if override and override.is_absolute() else root / (override or OUTPUT_REL / identifier)).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"Immutable output directory is non-empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    return output, identifier


def discover_ranking(root: Path) -> Path:
    candidates = list(root.glob(RANKING_GLOB))
    if not candidates:
        raise RuntimeError("No V21.102 D ranking snapshot found.")
    valid = []
    for path in candidates:
        try:
            frame = pd.read_csv(path, nrows=5)
            if {"ticker", "rank", "as_of_date", "variant_id"}.issubset(frame.columns):
                valid.append((str(frame["as_of_date"].max()), path.stat().st_mtime, path))
        except Exception:
            continue
    if not valid:
        raise RuntimeError("No valid D ranking snapshot found.")
    return max(valid)[2]


def load_price_panels(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    def panel(path: Path) -> pd.DataFrame:
        frame = pd.read_csv(path, usecols=["symbol", "date", "close"], low_memory=False)
        frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
        frame["date"] = frame["date"].astype(str).str.slice(0, 10)
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        return frame.dropna(subset=["close"]).drop_duplicates(["symbol", "date"], keep="last").pivot(
            index="date", columns="symbol", values="close"
        ).sort_index()
    candidate = panel(root / PRICE_REL)
    benchmark = panel(root / BENCH_REL)
    calendar = sorted(set(benchmark.index[benchmark["QQQ"].notna()]))
    return candidate.reindex(calendar), benchmark.reindex(calendar), calendar


def maturity_date(calendar: list[str], ranking_date: str, sessions: int) -> str:
    future = [day for day in calendar if day >= ranking_date]
    if future:
        start = future[0]
        start_index = calendar.index(start)
        target_index = start_index + sessions
        if target_index < len(calendar):
            return calendar[target_index]
    return (pd.Timestamp(ranking_date) + pd.offsets.BDay(sessions)).strftime("%Y-%m-%d")


def observation_id(ranking_date: str, view_type: str) -> str:
    return f"V21_107::{ranking_date}::{view_type}"


def json_list(values: Iterable[object]) -> str:
    return json.dumps(list(values), separators=(",", ":"), default=str)


def make_observation(
    ranking: pd.DataFrame, ranking_date: str, view_type: str, size: int,
    ranking_path: Path, candidate: pd.DataFrame, benchmark: pd.DataFrame,
    calendar: list[str], run_id: str, now: str, root: Path,
) -> dict[str, object]:
    selected = ranking.nsmallest(size, "rank").copy()
    tickers = selected["ticker"].astype(str).tolist()
    ranks = selected["rank"].astype(int).tolist()
    weights = [1.0 / size] * size
    start_prices = {
        ticker: (
            float(candidate.at[ranking_date, ticker])
            if ranking_date in candidate.index and ticker in candidate.columns
            and pd.notna(candidate.at[ranking_date, ticker]) else None
        )
        for ticker in tickers
    }
    benchmark_starts = {
        ticker: (
            float(benchmark.at[ranking_date, ticker])
            if ranking_date in benchmark.index and ticker in benchmark.columns
            and pd.notna(benchmark.at[ranking_date, ticker]) else None
        )
        for ticker in BENCHMARKS
    }
    maturities = {sessions: maturity_date(calendar, ranking_date, sessions) for sessions in HORIZONS}
    return {
        "observation_id": observation_id(ranking_date, view_type),
        "ranking_date": ranking_date, "variant": "D", "view_type": view_type,
        "portfolio_size": size, "tickers_json": json_list(tickers),
        "ranks_json": json_list(ranks), "weights_json": json_list(weights),
        "start_prices_json": json.dumps(start_prices, separators=(",", ":")),
        "benchmark_start_prices_json": json.dumps(benchmark_starts, separators=(",", ":")),
        **{f"maturity_{sessions}d": maturities[sessions] for sessions in HORIZONS},
        "status": "pending", "source_ranking_path": ranking_path.relative_to(root).as_posix(),
        "source_ranking_file_hash": sha256(ranking_path),
        "source_price_file_hash": sha256(root / PRICE_REL),
        "source_benchmark_file_hash": sha256(root / BENCH_REL),
        "created_run_id": run_id, "created_at_utc": now,
        "live_forward_no_future_leakage": "PENDING_PRICE_MATURITY",
        "historical_pit_factor_approximation_warning": "TRUE",
        "historical_survivorship_bias_warning": "TRUE", "research_only": "TRUE",
    }


def sessions_between(calendar: list[str], first: str, second: str) -> int:
    eligible = [day for day in calendar if first <= day <= second]
    return max(len(eligible) - 1, 0)


def quarterly_due(master: list[dict[str, str]], ranking_date: str, calendar: list[str]) -> bool:
    prior = [row for row in master if row["view_type"] == "TOP50_QUARTERLY_REBALANCE"]
    if not prior:
        return True
    latest = max(row["ranking_date"] for row in prior)
    return sessions_between(calendar, latest, ranking_date) >= 63


def make_turnover(new_observation: dict[str, object], master: list[dict[str, str]], run_id: str) -> dict[str, object]:
    prior = [row for row in master if row["view_type"] == "TOP50_QUARTERLY_REBALANCE"]
    current = set(json.loads(str(new_observation["tickers_json"])))
    if prior:
        previous = max(prior, key=lambda row: row["ranking_date"])
        previous_set = set(json.loads(previous["tickers_json"]))
        previous_id, previous_date = previous["observation_id"], previous["ranking_date"]
    else:
        previous_set, previous_id, previous_date = set(), "", ""
    entries, exits = sorted(current - previous_set), sorted(previous_set - current)
    overlap = len(current & previous_set) / len(current) if previous_set else 0.0
    turnover = 1.0 if not previous_set else 1.0 - overlap
    return {
        "turnover_id": f"TURNOVER::{new_observation['observation_id']}",
        "observation_id": new_observation["observation_id"],
        "ranking_date": new_observation["ranking_date"],
        "view_type": new_observation["view_type"],
        "previous_observation_id": previous_id, "previous_ranking_date": previous_date,
        "holding_overlap": overlap, "entry_count": len(entries), "exit_count": len(exits),
        "realized_turnover": turnover, "entries_json": json_list(entries),
        "exits_json": json_list(exits), "rebalance_executed": "TRUE",
        "created_run_id": run_id, "research_only": "TRUE",
    }


def hydrate_pending_start_prices(
    observations: list[dict[str, str]], candidate: pd.DataFrame, benchmark: pd.DataFrame,
) -> int:
    hydrated = 0
    for observation in observations:
        ranking_date = observation["ranking_date"]
        starts = json.loads(observation["start_prices_json"])
        benchmark_starts = json.loads(observation["benchmark_start_prices_json"])
        for ticker in list(starts):
            if starts[ticker] is None and ranking_date in candidate.index and ticker in candidate.columns:
                value = candidate.at[ranking_date, ticker]
                if pd.notna(value):
                    starts[ticker] = float(value)
                    hydrated += 1
        for ticker in BENCHMARKS:
            if benchmark_starts.get(ticker) is None and ranking_date in benchmark.index and ticker in benchmark.columns:
                value = benchmark.at[ranking_date, ticker]
                if pd.notna(value):
                    benchmark_starts[ticker] = float(value)
                    hydrated += 1
        observation["start_prices_json"] = json.dumps(starts, separators=(",", ":"))
        observation["benchmark_start_prices_json"] = json.dumps(benchmark_starts, separators=(",", ":"))
    return hydrated


def evaluate_observation(
    observation: dict[str, str], existing_results: dict[str, dict[str, str]],
    candidate: pd.DataFrame, benchmark: pd.DataFrame, available_dates: set[str],
    run_id: str, now: str,
) -> list[dict[str, object]]:
    output = []
    tickers = json.loads(observation["tickers_json"])
    weights = np.asarray(json.loads(observation["weights_json"]), dtype=float)
    start_prices = json.loads(observation["start_prices_json"])
    benchmark_starts = json.loads(observation["benchmark_start_prices_json"])
    for sessions in HORIZONS:
        result_id = f"{observation['observation_id']}::{sessions}D"
        if result_id in existing_results and existing_results[result_id]["maturity_status"] == "matured":
            output.append(existing_results[result_id])
            continue
        target = observation[f"maturity_{sessions}d"]
        actual_sessions = sorted(day for day in available_dates if day > observation["ranking_date"])
        evaluation_date = actual_sessions[sessions - 1] if len(actual_sessions) >= sessions else ""
        mature = bool(evaluation_date)
        valid_returns, valid_weights = [], []
        missing = 0
        if mature:
            for ticker, weight in zip(tickers, weights):
                start = start_prices.get(ticker)
                end = candidate.at[evaluation_date, ticker] if evaluation_date in candidate.index and ticker in candidate.columns else np.nan
                if start is None or pd.isna(end) or float(start) <= 0:
                    missing += 1
                else:
                    valid_returns.append(float(end) / float(start) - 1)
                    valid_weights.append(weight)
        portfolio_return = (
            float(np.average(valid_returns, weights=valid_weights))
            if valid_returns else np.nan
        )
        benchmark_returns = {}
        for ticker in BENCHMARKS:
            start = benchmark_starts.get(ticker)
            end = benchmark.at[evaluation_date, ticker] if mature and evaluation_date in benchmark.index and ticker in benchmark.columns else np.nan
            benchmark_returns[ticker] = (
                float(end) / float(start) - 1
                if start is not None and pd.notna(end) and float(start) > 0 else np.nan
            )
        matured = mature and pd.notna(portfolio_return) and all(pd.notna(benchmark_returns[x]) for x in BENCHMARKS)
        output.append({
            "result_id": result_id, "observation_id": observation["observation_id"],
            "ranking_date": observation["ranking_date"], "view_type": observation["view_type"],
            "horizon_days": sessions, "target_maturity_date": target,
            "evaluation_price_date": evaluation_date,
            "portfolio_return": portfolio_return,
            "benchmark_QQQ_return": benchmark_returns["QQQ"],
            "benchmark_SPY_return": benchmark_returns["SPY"],
            "benchmark_SOXX_return": benchmark_returns["SOXX"],
            "excess_vs_QQQ": portfolio_return - benchmark_returns["QQQ"] if matured else np.nan,
            "excess_vs_SPY": portfolio_return - benchmark_returns["SPY"] if matured else np.nan,
            "excess_vs_SOXX": portfolio_return - benchmark_returns["SOXX"] if matured else np.nan,
            "missing_price_count": missing,
            "maturity_status": "matured" if matured else "pending",
            "live_forward_no_future_leakage": "TRUE" if matured else "PENDING_PRICE_MATURITY",
            "first_matured_run_id": run_id if matured else "",
            "first_matured_at_utc": now if matured else "", "research_only": "TRUE",
        })
    return output


def update_observation_status(observations: list[dict[str, str]], results: list[dict[str, object]]) -> None:
    status_by_id: dict[str, list[str]] = {}
    for result in results:
        status_by_id.setdefault(str(result["observation_id"]), []).append(str(result["maturity_status"]))
    for observation in observations:
        statuses = status_by_id.get(observation["observation_id"], [])
        matured = statuses.count("matured")
        observation["status"] = "matured" if matured == len(HORIZONS) else "partially_matured" if matured else "pending"
        if matured:
            observation["live_forward_no_future_leakage"] = "TRUE"


def benchmark_summary(results: list[dict[str, object]]) -> list[dict[str, object]]:
    frame = pd.DataFrame(results)
    if frame.empty:
        return []
    frame = frame[frame["maturity_status"] == "matured"].copy()
    numeric = ["portfolio_return", "excess_vs_QQQ", "excess_vs_SPY", "excess_vs_SOXX"]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    output = []
    for (view, horizon), group in frame.groupby(["view_type", "horizon_days"], sort=True):
        row = {
            "view_type": view, "horizon_days": horizon, "matured_sample_count": len(group),
            "mean_portfolio_return": group["portfolio_return"].mean(),
            "median_portfolio_return": group["portfolio_return"].median(),
            "win_rate_vs_QQQ": group["excess_vs_QQQ"].gt(0).mean(),
            "win_rate_vs_SPY": group["excess_vs_SPY"].gt(0).mean(),
            "win_rate_vs_SOXX": group["excess_vs_SOXX"].gt(0).mean(),
            "median_excess_vs_QQQ": group["excess_vs_QQQ"].median(),
            "p5_excess_vs_QQQ": group["excess_vs_QQQ"].quantile(.05) if len(group) >= 20 else np.nan,
            "p5_sufficient_sample": str(len(group) >= 20).upper(), "research_only": "TRUE",
        }
        output.append(row)
    return output


def run_stage(root: Path, output: Path, run_id: str, repair_mode: bool = False) -> dict[str, object]:
    root, output = root.resolve(), output.resolve()
    ledger_dir = (root / LEDGER_REL).resolve()
    ledger_dir.mkdir(parents=True, exist_ok=True)
    v103 = load_v103(root)
    protected = v103.protected_files(root, output)
    protected_before = {path: sha256(path) for path in protected}
    source_guards = [
        root / "outputs/v21/v21_106_long_horizon_and_rebalance_decision_report/20260623_142922/v21_106_decision_readme.md",
        root / "outputs/v21/v21_106_r1_full_pit_factor_replay_feasibility_audit/20260623_143953/v21_106_r1_decision_readme.md",
    ]
    source_before = {path: sha256(path) for path in source_guards}
    now = datetime.now(timezone.utc).isoformat()
    try:
        ranking_path = discover_ranking(root)
        ranking = pd.read_csv(ranking_path)
        ranking["rank"] = pd.to_numeric(ranking["rank"], errors="coerce")
        ranking = ranking.dropna(subset=["ticker", "rank"]).copy()
        ranking["ticker"] = ranking["ticker"].astype(str).str.upper().str.strip()
        ranking_date = str(ranking["as_of_date"].max())[:10]
        ranking = ranking[ranking["as_of_date"].astype(str).str.slice(0, 10) == ranking_date]
        candidate, benchmark, calendar = load_price_panels(root)

        master_path = ledger_dir / MASTER_OBSERVATIONS
        maturity_path = ledger_dir / MASTER_MATURITY
        turnover_path = ledger_dir / MASTER_TURNOVER
        master = read_csv(master_path, OBS_FIELDS)
        old_results = read_csv(maturity_path, MATURITY_FIELDS)
        turnover_master = read_csv(turnover_path, TURNOVER_FIELDS)
        existing_ids = {row["observation_id"] for row in master}
        duplicate_count = 0
        new_rows: list[dict[str, object]] = []
        new_turnover: list[dict[str, object]] = []

        top20 = make_observation(
            ranking, ranking_date, "TOP20_HOLD_ONLY", 20, ranking_path,
            candidate, benchmark, calendar, run_id, now, root,
        )
        if top20["observation_id"] in existing_ids:
            duplicate_count += 1
        else:
            new_rows.append(top20)
            existing_ids.add(str(top20["observation_id"]))

        top50_id = observation_id(ranking_date, "TOP50_QUARTERLY_REBALANCE")
        if top50_id in existing_ids:
            duplicate_count += 1
        elif quarterly_due(master, ranking_date, calendar):
            top50 = make_observation(
                ranking, ranking_date, "TOP50_QUARTERLY_REBALANCE", 50, ranking_path,
                candidate, benchmark, calendar, run_id, now, root,
            )
            new_turnover.append(make_turnover(top50, master, run_id))
            new_rows.append(top50)
            existing_ids.add(top50_id)

        all_master = master + [{field: str(row.get(field, "")) for field in OBS_FIELDS} for row in new_rows]
        hydrated_start_price_count = hydrate_pending_start_prices(all_master, candidate, benchmark)
        existing_result_map = {row["result_id"]: row for row in old_results}
        evaluated: list[dict[str, object]] = []
        available_dates = set(candidate.index) & set(benchmark.index)
        for observation in all_master:
            evaluated.extend(evaluate_observation(
                observation, existing_result_map, candidate, benchmark,
                available_dates, run_id, now,
            ))
        if not repair_mode:
            for result in evaluated:
                old = existing_result_map.get(str(result["result_id"]))
                if old and old["maturity_status"] == "matured":
                    for field in MATURITY_FIELDS:
                        result[field] = old[field]
        update_observation_status(all_master, evaluated)
        all_turnover = turnover_master + [{field: str(row.get(field, "")) for field in TURNOVER_FIELDS} for row in new_turnover]

        write_csv(master_path, all_master, OBS_FIELDS)
        write_csv(maturity_path, evaluated, MATURITY_FIELDS)
        write_csv(ledger_dir / MASTER_TURNOVER, all_turnover, TURNOVER_FIELDS)
        append_audit = [{
            "run_id": run_id, "ranking_date": ranking_date, "new_observation_count": len(new_rows),
            "duplicate_skipped_count": duplicate_count, "master_observation_count": len(all_master),
            "hydrated_start_price_count": hydrated_start_price_count,
            "matured_results_preserved": "TRUE", "repair_mode": str(repair_mode).upper(),
            "research_only": "TRUE",
        }]
        previous_audits = read_csv(ledger_dir / MASTER_AUDIT, list(append_audit[0]))
        write_csv(ledger_dir / MASTER_AUDIT, previous_audits + append_audit, list(append_audit[0]))

        pending_results = [row for row in evaluated if str(row["maturity_status"]) != "matured"]
        matured_results = [row for row in evaluated if str(row["maturity_status"]) == "matured"]
        top20_rows = [row for row in all_master if row["view_type"] == "TOP20_HOLD_ONLY"]
        top50_rows = [row for row in all_master if row["view_type"] == "TOP50_QUARTERLY_REBALANCE"]
        benchmark_rows = benchmark_summary(evaluated)

        write_csv(output / LEDGER, all_master, OBS_FIELDS)
        write_csv(output / TOP20, top20_rows, OBS_FIELDS)
        write_csv(output / TOP50, top50_rows, OBS_FIELDS)
        write_csv(output / MATURITY, evaluated, MATURITY_FIELDS)
        benchmark_fields = list(benchmark_rows[0]) if benchmark_rows else [
            "view_type", "horizon_days", "matured_sample_count", "mean_portfolio_return",
            "median_portfolio_return", "win_rate_vs_QQQ", "win_rate_vs_SPY",
            "win_rate_vs_SOXX", "median_excess_vs_QQQ", "p5_excess_vs_QQQ",
            "p5_sufficient_sample", "research_only",
        ]
        write_csv(output / BENCHMARK, benchmark_rows, benchmark_fields)
        write_csv(output / TURNOVER, all_turnover, TURNOVER_FIELDS)
        write_csv(output / PENDING, pending_results, MATURITY_FIELDS)
        write_csv(output / MATURED, matured_results, MATURITY_FIELDS)

        protected_after = {path: sha256(path) for path in protected}
        source_after = {path: sha256(path) for path in source_guards}
        protected_modified = any(protected_before[path] != protected_after[path] for path in protected)
        source_modified = source_before != source_after
        leakage_failures = sum(
            str(row["maturity_status"]) == "matured"
            and str(row["live_forward_no_future_leakage"]).upper() != "TRUE"
            for row in evaluated
        )
        warnings = [
            {"warning_code": "PIT_FACTOR_APPROXIMATION_WARN", "status": "HISTORICAL_ONLY_ACTIVE",
             "details": "Preserved for V21.104-V21.106 historical conclusions.", "research_only": "TRUE"},
            {"warning_code": "SURVIVORSHIP_BIAS_WARN", "status": "HISTORICAL_ONLY_ACTIVE",
             "details": "Preserved for V21.104-V21.106 historical conclusions.", "research_only": "TRUE"},
            {"warning_code": "LIVE_START_PRICE_MISSING", "status": str(any(
                any(value is None for value in json.loads(row["start_prices_json"]).values())
                for row in all_master
            )).upper(), "details": "Observation remains pending until exact ranking-date prices are available.", "research_only": "TRUE"},
            {"warning_code": "SOURCE_OUTPUTS_MODIFIED", "status": str(source_modified).upper(),
             "details": "V21.106/V21.106-R1 source hash audit.", "research_only": "TRUE"},
            {"warning_code": "PROTECTED_OUTPUTS_MODIFIED", "status": str(protected_modified).upper(),
             "details": "Protected-output hash audit.", "research_only": "TRUE"},
            {"warning_code": "LEAKAGE_FAILURES", "status": str(leakage_failures),
             "details": "Matured rows must be marked LIVE_FORWARD_NO_FUTURE_LEAKAGE.", "research_only": "TRUE"},
        ]
        write_csv(output / WARNINGS, warnings, list(warnings[0]))
        if leakage_failures or protected_modified or source_modified or not top20_rows or not top50_rows:
            status, decision = FAIL, "STOP_LEDGER_OR_LEAKAGE_BLOCKER"
        elif len(new_rows) == 0 and duplicate_count:
            status, decision = DUPLICATE, "NO_NEW_RANKING_DATE_DUPLICATE_SKIPPED"
        elif matured_results:
            status, decision = PASS, "LIVE_FORWARD_LEDGER_ACTIVE_WITH_MATURED_RESULTS"
        else:
            status, decision = WAIT, "LIVE_FORWARD_LEDGER_STARTED_WAITING_FOR_MATURITY"
        config = {
            "stage": STAGE, "run_id": run_id, "generated_at_utc": now,
            "source_v21_106_run_id": SOURCE_V106_RUN_ID,
            "source_v21_106_r1_run_id": SOURCE_V106_R1_RUN_ID,
            "latest_ranking_date": ranking_date,
            "source_ranking_path": ranking_path.relative_to(root).as_posix(),
            "source_ranking_hash": sha256(ranking_path),
            "candidate_price_hash": sha256(root / PRICE_REL),
            "benchmark_price_hash": sha256(root / BENCH_REL),
            "horizons_trading_days": list(HORIZONS), "benchmarks": list(BENCHMARKS),
            "repair_mode": repair_mode, "official_adoption_allowed": False,
            "hydrated_start_price_count": hydrated_start_price_count,
            "broker_action_allowed": False, "research_only": True,
        }
        write_json(output / CONFIG, config)
        readme = f"""# V21.107 Live Forward Tracking

FINAL_STATUS: `{status}`  
DECISION: `{decision}`  
run_id: `{run_id}`  
source V21.106 run_id: `{SOURCE_V106_RUN_ID}`  
source V21.106-R1 run_id: `{SOURCE_V106_R1_RUN_ID}`  
latest ranking date: `{ranking_date}`  
new observations: `{len(new_rows)}`  
duplicate skipped observations: `{duplicate_count}`  
pending result count: `{len(pending_results)}`  
matured result count: `{len(matured_results)}`  
D Top20 hold-only tracked: `{'true' if top20_rows else 'false'}`  
D Top50 quarterly tracked: `{'true' if top50_rows else 'false'}`  
official_adoption_allowed: `false`  
broker_action_allowed: `false`

The master ledger is append-safe. Observation IDs are deterministic, duplicate ranking-date/view pairs are skipped, and matured results are immutable unless repair mode is explicitly requested. Live rows are marked `LIVE_FORWARD_NO_FUTURE_LEAKAGE` only after exact target-date prices mature.
"""
        (output / README).write_text(readme, encoding="utf-8")
    except Exception as exc:
        status, decision = FAIL, "STOP_EXECUTION_OR_LEDGER_BLOCKER"
        protected_modified = False
        source_modified = False
        leakage_failures = 0
        ranking_date, new_rows, duplicate_count = "", [], 0
        pending_results, matured_results, top20_rows, top50_rows = [], [], [], []
        write_json(output / CONFIG, {
            "stage": STAGE, "run_id": run_id, "execution_error": str(exc),
            "official_adoption_allowed": False, "broker_action_allowed": False,
        })
        for name, fields in (
            (LEDGER, OBS_FIELDS), (TOP20, OBS_FIELDS), (TOP50, OBS_FIELDS),
            (MATURITY, MATURITY_FIELDS), (BENCHMARK, ["view_type", "horizon_days"]),
            (TURNOVER, TURNOVER_FIELDS), (PENDING, MATURITY_FIELDS), (MATURED, MATURITY_FIELDS),
        ):
            write_csv(output / name, [], fields)
        write_csv(output / WARNINGS, [{
            "warning_code": "EXECUTION_BLOCKER", "status": "TRUE",
            "details": str(exc), "research_only": "TRUE",
        }], ["warning_code", "status", "details", "research_only"])
        (output / README).write_text(
            f"# V21.107\n\nFINAL_STATUS: `{status}`  \nDECISION: `{decision}`  \n"
            f"source V21.106 run_id: `{SOURCE_V106_RUN_ID}`  \n"
            f"source V21.106-R1 run_id: `{SOURCE_V106_R1_RUN_ID}`  \n"
            "official_adoption_allowed: `false`  \nbroker_action_allowed: `false`\n\n"
            f"Blocking error: {exc}\n", encoding="utf-8"
        )
    result = {
        "FINAL_STATUS": status, "DECISION": decision, "RUN_ID": run_id,
        "LATEST_RANKING_DATE": ranking_date, "NEW_OBSERVATIONS": len(new_rows),
        "DUPLICATE_SKIPPED": duplicate_count, "PENDING_RESULTS": len(pending_results),
        "MATURED_RESULTS": len(matured_results), "LEAKAGE_FAILURES": leakage_failures,
        "SOURCE_OUTPUTS_MODIFIED": source_modified,
        "PROTECTED_OUTPUTS_MODIFIED": protected_modified,
        "OUTPUT_DIR": output.as_posix(), "LEDGER_DIR": ledger_dir.as_posix(),
        "OFFICIAL_ADOPTION_ALLOWED": False, "BROKER_ACTION_ALLOWED": False,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--repair-mode", action="store_true")
    args = parser.parse_args()
    output, run_id = immutable_output(args.root.resolve(), args.output_dir, args.run_id)
    result = run_stage(args.root, output, run_id, args.repair_mode)
    return 1 if str(result["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
