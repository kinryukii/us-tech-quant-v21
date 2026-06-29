#!/usr/bin/env python
"""V21.120 canonical price refresh audit and maturity gate."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.120_CANONICAL_PRICE_REFRESH_AND_MATURITY_GATE"
OUT = ROOT / "outputs/v21/V21.120_CANONICAL_PRICE_REFRESH_AND_MATURITY_GATE"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
BENCH = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"
REFRESH_SCRIPT = ROOT / "scripts/v20/v20_199d_approved_historical_price_refresh.py"
V116_SUMMARY = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST/V21.116_daily_top50_full_data_ledger_summary.json"
V119_PANEL = ROOT / "outputs/v21/V21.119_FORWARD_MATURITY_UPDATE_FOR_ABCD_AND_D_R2C/forward_maturity_by_date_horizon.csv"

ALLOW_ENV = "V21_120_ALLOW_CANONICAL_PRICE_REFRESH"
UPSTREAM_REFRESH_ENV = "V20_199D_ENABLE_YFINANCE_REFRESH"
STRATEGIES = ["A1_BASELINE_CONTROL", "B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1", "D_R2C_BC_CONFIRMATION_OVERLAY"]
TOP_NS = [20, 50]
HORIZONS = [1, 3, 5, 10, 20]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = list(rows[0].keys()) if rows else ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def audit_price_panel(label: str) -> dict[str, Any]:
    if not PRICE.is_file():
        return {
            "audit_label": label,
            "price_panel_path": rel(PRICE),
            "price_panel_exists": False,
            "latest_price_date": "",
            "row_count": 0,
            "ticker_count": 0,
            "malformed_date_count": 0,
            "duplicated_ticker_date_rows": 0,
            "stale_or_missing_ticker_count": 0,
            "QQQ_available": False,
            "SOXX_available": False,
            "sha256": "",
        }
    df = pd.read_csv(PRICE, usecols=["symbol", "date"], low_memory=False)
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    parsed = pd.to_datetime(df["date"], errors="coerce")
    malformed = int(parsed.isna().sum())
    df["date_str"] = parsed.dt.strftime("%Y-%m-%d")
    latest_by_symbol = df[parsed.notna()].groupby("symbol")["date_str"].max().to_dict()
    latest = max(latest_by_symbol.values()) if latest_by_symbol else ""
    stale = [s for s, d in latest_by_symbol.items() if d < latest]
    dupes = int(df.duplicated(["symbol", "date"]).sum())
    bench_available = set()
    if BENCH.is_file():
        b = pd.read_csv(BENCH, usecols=["symbol", "date"], low_memory=False)
        b["symbol"] = b["symbol"].astype(str).str.upper().str.strip()
        b["date"] = pd.to_datetime(b["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        bench_latest = b.groupby("symbol")["date"].max().to_dict()
        for s in ["QQQ", "SOXX"]:
            if bench_latest.get(s, "") >= latest:
                bench_available.add(s)
    return {
        "audit_label": label,
        "price_panel_path": rel(PRICE),
        "price_panel_exists": True,
        "latest_price_date": latest,
        "row_count": int(len(df)),
        "ticker_count": int(df["symbol"].nunique()),
        "malformed_date_count": malformed,
        "duplicated_ticker_date_rows": dupes,
        "stale_or_missing_ticker_count": len(stale),
        "QQQ_available": "QQQ" in latest_by_symbol or "QQQ" in bench_available,
        "SOXX_available": "SOXX" in latest_by_symbol or "SOXX" in bench_available,
        "sha256": sha256(PRICE),
    }


def run_refresh(refresh_allowed: bool) -> dict[str, Any]:
    log = {
        "approved_refresh_mechanism_found": REFRESH_SCRIPT.is_file(),
        "refresh_allowed": refresh_allowed,
        "refresh_attempted": False,
        "refresh_returncode": "",
        "refresh_status": "REFRESH_NOT_ATTEMPTED",
        "stdout_tail": "",
        "stderr_tail": "",
    }
    if not REFRESH_SCRIPT.is_file():
        log["refresh_status"] = "APPROVED_REFRESH_MECHANISM_NOT_FOUND"
        return log
    if not refresh_allowed:
        log["refresh_status"] = "REFRESH_NOT_ATTEMPTED_NO_ALLOW_FLAG"
        return log
    env = os.environ.copy()
    env[UPSTREAM_REFRESH_ENV] = "TRUE"
    completed = subprocess.run([sys.executable, str(REFRESH_SCRIPT)], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    log.update({
        "refresh_attempted": True,
        "refresh_returncode": completed.returncode,
        "refresh_status": "REFRESH_SUCCEEDED" if completed.returncode == 0 else "REFRESH_FAILED",
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-80:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-80:]),
    })
    return log


def trading_dates_from_price() -> list[str]:
    if not PRICE.is_file():
        return []
    dates = []
    for chunk in pd.read_csv(PRICE, usecols=["date"], chunksize=500_000, low_memory=False):
        parsed = pd.to_datetime(chunk["date"], errors="coerce")
        dates.extend(parsed.dropna().dt.strftime("%Y-%m-%d").tolist())
    return sorted(d for d in set(dates) if pd.Timestamp(d).weekday() < 5 and d != "2026-06-19")


def forward_matured(as_of: str, horizon: int, dates: list[str]) -> tuple[bool, str]:
    if as_of not in dates:
        return False, ""
    idx = dates.index(as_of) + horizon
    if idx >= len(dates):
        return False, ""
    return True, dates[idx]


def maturity_gate(dates: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not V116_SUMMARY.is_file():
        ranking_dates = []
    else:
        ranking_dates = list(json.loads(V116_SUMMARY.read_text(encoding="utf-8")).get("processed_dates", []))
    old = pd.read_csv(V119_PANEL, low_memory=False) if V119_PANEL.is_file() else pd.DataFrame()
    old_matured = set()
    if not old.empty:
        for row in old[old["matured"].astype(str).str.upper().eq("TRUE")].to_dict("records"):
            old_matured.add((str(row["ranking_date"]), str(row["strategy"]), int(row["top_n"]), str(row["horizon"])))
    rows = []
    new_count = 0
    still_unmatured = 0
    old_count = 0
    for ranking_date in ranking_dates:
        for strategy in STRATEGIES:
            for topn in TOP_NS:
                for h in HORIZONS:
                    horizon = f"{h}D"
                    matured, end = forward_matured(ranking_date, h, dates)
                    key = (ranking_date, strategy, topn, horizon)
                    was_matured = key in old_matured
                    newly = matured and not was_matured
                    if newly:
                        new_count += 1
                    elif matured and was_matured:
                        old_count += 1
                    elif not matured:
                        still_unmatured += 1
                    rows.append({
                        "ranking_date": ranking_date,
                        "strategy": strategy,
                        "top_n": topn,
                        "horizon": horizon,
                        "currently_matured": matured,
                        "end_date_if_matured": end,
                        "was_matured_in_v21_119": was_matured,
                        "newly_matured_vs_v21_119": newly,
                    })
    summary = {
        "ranking_date_count": len(ranking_dates),
        "old_matured_observation_count": old_count,
        "newly_matured_observation_count": new_count,
        "still_unmatured_observation_count": still_unmatured,
        "rerun_V21_119_R1_recommended": new_count > 0,
    }
    return rows, summary


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    refresh_allowed = os.environ.get(ALLOW_ENV, "").upper() == "TRUE"
    before = audit_price_panel("before_refresh")
    write_csv(OUT / "price_panel_audit_before_refresh.csv", [before])

    if not before["price_panel_exists"]:
        final_status = "BLOCKED_V21_120_PRICE_PANEL_MISSING"
        decision = "DO_NOT_RUN_MATURITY_GATE"
        refresh_log = run_refresh(False)
        after = before
        gate_rows, gate_summary = [], {"newly_matured_observation_count": 0, "still_unmatured_observation_count": 0, "rerun_V21_119_R1_recommended": False}
    else:
        refresh_log = run_refresh(refresh_allowed)
        after = audit_price_panel("after_refresh")
        dates = trading_dates_from_price()
        gate_rows, gate_summary = maturity_gate(dates)
        if refresh_log["refresh_attempted"] and refresh_log["refresh_returncode"] != 0:
            final_status = "BLOCKED_V21_120_REFRESH_FAILED"
            decision = "DO_NOT_USE_REFRESHED_PRICE_PANEL"
        elif refresh_log["refresh_attempted"] and gate_summary["newly_matured_observation_count"] > 0:
            final_status = "PASS_V21_120_REFRESHED_NEW_MATURITY_AVAILABLE"
            decision = "RUN_V21_119_R1_RECOMMENDED_RESEARCH_ONLY"
        elif refresh_log["refresh_attempted"]:
            final_status = "PARTIAL_PASS_V21_120_REFRESHED_NO_NEW_MATURITY"
            decision = "WAIT_FOR_MORE_MATURITY_RESEARCH_ONLY"
        else:
            final_status = "WARN_V21_120_REFRESH_NOT_ATTEMPTED_STALE_OR_NO_ALLOW_FLAG"
            decision = "REFRESH_NOT_ATTEMPTED_WAIT_OR_SET_ALLOW_FLAG"

    write_csv(OUT / "price_panel_audit_after_refresh.csv", [after])
    log_text = [
        f"approved_refresh_mechanism_found={refresh_log['approved_refresh_mechanism_found']}",
        f"refresh_allowed={refresh_log['refresh_allowed']}",
        f"refresh_attempted={refresh_log['refresh_attempted']}",
        f"refresh_status={refresh_log['refresh_status']}",
        f"refresh_returncode={refresh_log['refresh_returncode']}",
        "",
        "STDOUT_TAIL",
        refresh_log.get("stdout_tail", ""),
        "",
        "STDERR_TAIL",
        refresh_log.get("stderr_tail", ""),
    ]
    (OUT / "price_refresh_log.txt").write_text("\n".join(map(str, log_text)) + "\n", encoding="utf-8")
    write_csv(OUT / "maturity_gate_by_ranking_date_horizon.csv", gate_rows)
    write_csv(OUT / "maturity_gate_summary.csv", [gate_summary])

    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_before_refresh": before["latest_price_date"],
        "latest_price_date_after_refresh": after["latest_price_date"],
        "refresh_attempted": bool(refresh_log["refresh_attempted"]),
        "refresh_allowed": refresh_allowed,
        "approved_refresh_mechanism_found": bool(refresh_log["approved_refresh_mechanism_found"]),
        "refresh_status": refresh_log["refresh_status"],
        "QQQ_available": bool(after["QQQ_available"]),
        "SOXX_available": bool(after["SOXX_available"]),
        "newly_matured_observation_count": int(gate_summary["newly_matured_observation_count"]),
        "still_unmatured_observation_count": int(gate_summary["still_unmatured_observation_count"]),
        "rerun_V21_119_R1_recommended": bool(gate_summary["rerun_V21_119_R1_recommended"]),
        "protected_outputs_modified": bool(refresh_log["refresh_attempted"]),
        "protected_outputs_modified_note": "Only approved canonical price refresh may mutate canonical price files when allow flag is true." if refresh_log["refresh_attempted"] else "",
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "model_parameters_changed": False,
        "strategy_rankings_changed": False,
        "new_strategy_variants_created": False,
        "allow_env": ALLOW_ENV,
    }
    write_json(OUT / "V21.120_manifest.json", manifest)
    report = [
        f"{STAGE}",
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_before_refresh={before['latest_price_date']}",
        f"latest_price_date_after_refresh={after['latest_price_date']}",
        f"refresh_attempted={str(refresh_log['refresh_attempted']).lower()}",
        f"refresh_allowed={str(refresh_allowed).lower()}",
        f"approved_refresh_mechanism_found={str(refresh_log['approved_refresh_mechanism_found']).lower()}",
        f"QQQ_available={str(after['QQQ_available']).lower()}",
        f"SOXX_available={str(after['SOXX_available']).lower()}",
        f"newly_matured_observation_count={gate_summary['newly_matured_observation_count']}",
        f"still_unmatured_observation_count={gate_summary['still_unmatured_observation_count']}",
        f"rerun_V21_119_R1_recommended={str(gate_summary['rerun_V21_119_R1_recommended']).lower()}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.120_price_refresh_and_maturity_gate_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
