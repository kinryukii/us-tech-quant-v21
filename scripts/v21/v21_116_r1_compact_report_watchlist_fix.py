#!/usr/bin/env python
"""Fix V21.116 compact report watchlist sections using D ranking only."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.116_R1_COMPACT_REPORT_WATCHLIST_FIX"
OUT = ROOT / "outputs/v21/V21.116_R1_COMPACT_REPORT_WATCHLIST_FIX"
SOURCE_115 = ROOT / "outputs/v21/V21.115_DAILY_TRUE_RECOMPUTE_LEDGER_20260616_TO_20260625"
SOURCE_116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
SOURCE_116_SUMMARY = SOURCE_116 / "V21.116_daily_top50_full_data_ledger_summary.json"

WATCHLIST = ["DRAM", "MU", "SNDK", "WDC", "STX", "AMAT", "LRCX", "KLAC", "KLIC", "TER", "MKSI", "ICHR", "AMKR", "SOXX", "SMH", "AMD", "INTC"]
STORAGE = ["DRAM", "MU", "SNDK", "WDC", "STX"]
EQUIPMENT = ["AMAT", "LRCX", "KLAC", "KLIC", "TER", "MKSI", "ICHR", "AMKR", "COHU", "ENTG", "ASML"]


def clean(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


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


def chunks(values: list[str], size: int = 10) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def load_dates() -> list[str]:
    if SOURCE_116_SUMMARY.is_file():
        summary = json.loads(SOURCE_116_SUMMARY.read_text(encoding="utf-8"))
        return list(summary.get("processed_dates", []))
    return sorted(p.name.replace("asof_", "") for p in SOURCE_115.glob("asof_*") if p.is_dir())


def load_d_ranking(as_of: str) -> pd.DataFrame:
    candidates = [
        SOURCE_115 / f"asof_{as_of}" / f"D_WEIGHT_OPTIMIZED_R1_ranking_{as_of}.csv",
        SOURCE_116 / f"asof_{as_of}" / f"D_WEIGHT_OPTIMIZED_R1_top50_{as_of}.csv",
    ]
    for path in candidates:
        if path.is_file():
            frame = pd.read_csv(path, low_memory=False)
            frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
            frame["rank"] = pd.to_numeric(frame["rank"], errors="coerce")
            frame["final_score"] = pd.to_numeric(frame["final_score"], errors="coerce")
            return frame.sort_values(["rank", "ticker"], na_position="last").reset_index(drop=True)
    raise FileNotFoundError(f"Missing D ranking for {as_of}")


def fmt_rank(value: Any) -> str:
    if pd.isna(value) or clean(value) == "":
        return "NA"
    return str(int(float(value)))


def fmt_score(value: Any) -> str:
    if pd.isna(value) or clean(value) == "":
        return "nan"
    return f"{float(value):.2f}"


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    dates = load_dates()
    rankings: dict[str, pd.DataFrame] = {as_of: load_d_ranking(as_of) for as_of in dates}

    watch_rows: list[dict[str, Any]] = []
    consistency: list[dict[str, Any]] = []
    storage_summary: list[dict[str, Any]] = []
    equipment_summary: list[dict[str, Any]] = []

    for as_of, frame in rankings.items():
        top20 = frame[pd.to_numeric(frame["rank"], errors="coerce").le(20)].copy()
        top50 = frame[pd.to_numeric(frame["rank"], errors="coerce").le(50)].copy()
        top20_tickers = set(top20["ticker"])
        top50_tickers = set(top50["ticker"])
        by_ticker = frame.set_index("ticker", drop=False)
        for ticker in WATCHLIST:
            if ticker in by_ticker.index:
                row = by_ticker.loc[ticker]
                rank = int(row["rank"]) if not pd.isna(row["rank"]) else ""
                score = row["final_score"]
                in20 = ticker in top20_tickers
                in50 = ticker in top50_tickers
            else:
                rank, score, in20, in50 = "", "", False, False
            watch_rows.append({
                "as_of_date": as_of,
                "ticker": ticker,
                "d_rank": rank,
                "d_final_score": score,
                "top20": in20,
                "top50": in50,
                "source": "D_WEIGHT_OPTIMIZED_R1_full_ranking",
            })
            expected_top20 = bool(rank != "" and int(rank) <= 20)
            expected_top50 = bool(rank != "" and int(rank) <= 50)
            consistency.append({
                "as_of_date": as_of,
                "ticker": ticker,
                "d_rank": rank,
                "appears_in_d_top20": ticker in top20_tickers,
                "appears_in_d_top50": ticker in top50_tickers,
                "reported_top20": in20,
                "reported_top50": in50,
                "rank_matches_top50_rank": True if ticker not in top50_tickers else rank == int(top50[top50["ticker"].eq(ticker)].iloc[0]["rank"]),
                "top20_flag_correct": in20 == expected_top20,
                "top50_flag_correct": in50 == expected_top50,
                "consistent": (in20 == expected_top20) and (in50 == expected_top50) and (ticker not in top50_tickers or rank == int(top50[top50["ticker"].eq(ticker)].iloc[0]["rank"])),
            })
        for group_name, group, target in [("storage_chain", STORAGE, storage_summary), ("equipment_chain", EQUIPMENT, equipment_summary)]:
            present = [t for t in group if t in top50_tickers]
            target.append({
                "as_of_date": as_of,
                "group": group_name,
                "present_count": len(present),
                "present_tickers": "|".join(present),
                "missing_tickers": "|".join([t for t in group if t not in top50_tickers]),
            })

    inconsistency_count = sum(1 for row in consistency if not row["consistent"])
    write_csv(OUT / "watchlist_consistency_check.csv", consistency)
    write_csv(OUT / "fixed_d_watchlist_rows.csv", watch_rows)
    write_csv(OUT / "fixed_storage_chain_summary.csv", storage_summary)
    write_csv(OUT / "fixed_semiconductor_equipment_chain_summary.csv", equipment_summary)

    lines = [
        "=" * 100,
        "V21.116 R1 COMPACT DAILY TOP50 REPORT - WATCHLIST FIXED",
        "=" * 100,
        "Scope: 2026-06-16 to latest completed daily OHLCV",
        "Fix: sections 3-5 use D_WEIGHT_OPTIMIZED_R1 full ranking only for D ranks and membership flags.",
        "",
        "=" * 100,
        "1) D TOP50 TICKERS BY DATE",
        "=" * 100,
        "",
    ]
    for as_of in dates:
        tickers = list(rankings[as_of][rankings[as_of]["rank"].le(50)]["ticker"])
        lines.append(f"[{as_of}]")
        for part in chunks(tickers, 10):
            lines.append("  " + ", ".join(part))
        lines.append("")
    lines.extend(["=" * 100, "2) D TOP20 TICKERS BY DATE", "=" * 100, ""])
    for as_of in dates:
        tickers = list(rankings[as_of][rankings[as_of]["rank"].le(20)]["ticker"])
        lines.append(f"[{as_of}]")
        lines.append("  " + ", ".join(tickers))
        lines.append("")
    lines.extend(["=" * 100, "3) WATCHLIST D RANKS BY DATE", "=" * 100, ""])
    by_date = {}
    for row in watch_rows:
        by_date.setdefault(row["as_of_date"], []).append(row)
    for as_of in dates:
        lines.append(f"[{as_of}]")
        for row in by_date.get(as_of, []):
            ticker = row["ticker"]
            rank = fmt_rank(row["d_rank"])
            score = fmt_score(row["d_final_score"])
            lines.append(f"  {ticker:<5} rank={rank:<4} score={score:<6} top20={row['top20']} top50={row['top50']}")
        lines.append("")
    lines.extend(["=" * 100, "4) STORAGE CHAIN SUMMARY", "=" * 100, ""])
    for row in storage_summary:
        present = row["present_tickers"].replace("|", ", ") or "none"
        missing = row["missing_tickers"].replace("|", ", ") or "none"
        lines.append(f"[{row['as_of_date']}] present={row['present_count']}: {present}; missing: {missing}")
    lines.extend(["", "=" * 100, "5) SEMICONDUCTOR EQUIPMENT CHAIN SUMMARY", "=" * 100, ""])
    for row in equipment_summary:
        present = row["present_tickers"].replace("|", ", ") or "none"
        missing = row["missing_tickers"].replace("|", ", ") or "none"
        lines.append(f"[{row['as_of_date']}] present={row['present_count']}: {present}; missing: {missing}")
    lines.extend(["", "=" * 100, "VALIDATION", "=" * 100, f"inconsistency_count={inconsistency_count}", "source_for_d_watchlist_ranks=D_WEIGHT_OPTIMIZED_R1_full_ranking"])

    report = OUT / "V21.116_R1_compact_readable_top50_report_FIXED.txt"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    final_status = "PASS_V21_116_R1_COMPACT_REPORT_WATCHLIST_FIXED" if inconsistency_count == 0 else "BLOCKED_V21_116_R1_COMPACT_REPORT_WATCHLIST_INCONSISTENT"
    decision = "FIXED_COMPACT_REPORT_READY_RESEARCH_ONLY" if inconsistency_count == 0 else "DO_NOT_USE_FIXED_REPORT_INCONSISTENCIES_REMAIN"
    summary = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "processed_dates": dates,
        "inconsistency_count": inconsistency_count,
        "fixed_report_path": rel(report),
        "watchlist_consistency_check_path": rel(OUT / "watchlist_consistency_check.csv"),
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }
    write_json(OUT / "V21.116_R1_compact_report_watchlist_fix_summary.json", summary)
    print(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    run()
