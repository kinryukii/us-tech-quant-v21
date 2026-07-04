#!/usr/bin/env python
"""V21.201 DRAM Moomoo R4 date alignment and plan refresh."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.v21 import v21_176_daily_dram_premarket_trade_plan_r1 as v176


STAGE = "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH"
OUT = ROOT / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH"
R4_SUMMARY = ROOT / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/v21_199_r4_summary.json"
R4_RAW_CANDIDATE = ROOT / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/moomoo_daily_ohlcv_trade_plan_candidate_r4.csv"
R4_RAW_STAGING = ROOT / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/moomoo_daily_ohlcv_staging_raw_r4.csv"
V197_SUMMARY = ROOT / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/v21_197_summary.json"

POLICY = {
    "daily_frequency_only": True,
    "intraday_required": False,
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "trade_api_called": False,
    "protected_outputs_modified": False,
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def normalize_dram_raw(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", "ticker", "open", "high", "low", "close", "volume"])
    df = frame.rename(columns={c: str(c).strip().lower() for c in frame.columns}).copy()
    if "ticker" not in df:
        if "symbol" in df:
            df["ticker"] = df["symbol"]
        elif "internal_symbol" in df:
            df["ticker"] = df["internal_symbol"]
    if "date" not in df and "time_key" in df:
        df["date"] = df["time_key"]
    df["ticker"] = df.get("ticker", "").astype(str).str.upper().str.strip()
    df = df[df["ticker"].eq("DRAM")].copy()
    df["date"] = pd.to_datetime(df.get("date", pd.Series(dtype=str)), errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df:
            df[col] = 0 if col == "volume" else np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    df = df[(df["open"] > 0) & (df["high"] > 0) & (df["low"] > 0) & (df["close"] > 0)]
    df = df[(df["high"] >= df[["open", "low", "close"]].max(axis=1)) & (df["low"] <= df[["open", "high", "close"]].min(axis=1))]
    return df[["date", "ticker", "open", "high", "low", "close", "volume"]].sort_values("date").drop_duplicates(["date", "ticker"], keep="last").reset_index(drop=True)


def load_dram_raw(candidate_path: Path = R4_RAW_CANDIDATE, staging_path: Path = R4_RAW_STAGING) -> tuple[pd.DataFrame, str]:
    candidate = normalize_dram_raw(read_csv(candidate_path))
    if not candidate.empty:
        return candidate, str(candidate_path)
    staging = normalize_dram_raw(read_csv(staging_path))
    return staging, str(staging_path)


def consolidate_action(final_decision: str) -> tuple[str, str, str, bool]:
    if "NO_CHASE" in str(final_decision):
        return "DRAM_DAILY_NO_CHASE", "CURRENT", "CURRENT_OR_RECENT", False
    if "NO_TRADE" in str(final_decision):
        return "DRAM_DAILY_NO_TRADE", "CURRENT", "CURRENT_OR_RECENT", False
    if "WAIT" in str(final_decision) or "MISSING" in str(final_decision):
        return "DRAM_DAILY_WAIT", "CURRENT", "CURRENT_OR_RECENT", False
    return "DRAM_DAILY_LIMIT_PLAN_ACTIVE", "CURRENT", "CURRENT_OR_RECENT", True


def dates_aligned(r4_date: str, abcde_date: str, dram_plan_date: str) -> bool:
    return bool(r4_date and r4_date == abcde_date and r4_date == dram_plan_date)


def build_plan(dram: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    ind = v176.compute_indicators(dram)
    plan = v176.generate_daily_plan(ind)
    action, currentness, stale, trade_allowed = consolidate_action(str(plan.get("final_decision", "")))
    latest = str(pd.Timestamp(ind.iloc[-1]["date"]).date()) if not ind.empty else ""
    row = {
        **plan,
        "latest_price_date": latest,
        "latest_plan_date": latest,
        "consolidated_action_label": action,
        "trade_plan_currentness": currentness,
        "staleness_status": stale,
        "trade_allowed_current": trade_allowed,
        **POLICY,
    }
    return row, ind


def write_report(summary: dict[str, Any], out_dir: Path) -> None:
    keys = [
        "final_status", "final_decision", "r4_latest_moomoo_broad_honest_date", "abcde_target_rerun_date",
        "dram_raw_latest_completed_date", "latest_price_date", "latest_plan_date", "setup_classification",
        "final_trade_decision", "consolidated_action_label", "planned_entry", "no_chase_above", "stop_loss",
        "take_profit_1", "take_profit_2", "trade_plan_currentness", "staleness_status", "date_alignment_passed",
        "research_only", "official_adoption_allowed", "broker_action_allowed", "trade_api_called",
    ]
    (out_dir / "V21.201_dram_moomoo_r4_date_alignment_report.txt").write_text(
        "\n".join([STAGE] + [f"{k}={summary.get(k, '')}" for k in keys]) + "\n", encoding="utf-8"
    )


def run(
    out_dir: Path = OUT,
    r4_summary_path: Path = R4_SUMMARY,
    raw_candidate_path: Path = R4_RAW_CANDIDATE,
    raw_staging_path: Path = R4_RAW_STAGING,
    abcde_summary_path: Path = V197_SUMMARY,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    r4 = read_json(r4_summary_path)
    abcde = read_json(abcde_summary_path)
    target = str(r4.get("latest_moomoo_broad_honest_date", ""))
    abcde_target = str(abcde.get("target_rerun_date", ""))
    dram, source_path = load_dram_raw(raw_candidate_path, raw_staging_path)
    latest = str(pd.Timestamp(dram["date"].max()).date()) if not dram.empty else ""
    source_audit = {
        "source_path": source_path,
        "dram_row_count": int(len(dram)),
        "dram_raw_latest_completed_date": latest,
        "r4_latest_moomoo_broad_honest_date": target,
        "raw_source_status": "PASS" if not dram.empty else "FAIL_MISSING",
    }
    pd.DataFrame([source_audit]).to_csv(out_dir / "dram_moomoo_raw_source_audit.csv", index=False)
    date_alignment = bool(target and latest == target)
    pd.DataFrame([{
        "r4_latest_moomoo_broad_honest_date": target,
        "abcde_target_rerun_date": abcde_target,
        "dram_raw_latest_completed_date": latest,
        "date_alignment_passed": date_alignment,
        "reason": "" if date_alignment else "DRAM_RAW_MISSING_OR_STALE",
    }]).to_csv(out_dir / "dram_moomoo_completed_date_audit.csv", index=False)
    if not date_alignment:
        empty = {
            "final_status": "FAIL_V21_201_DRAM_MOOMOO_RAW_STALE_OR_MISSING",
            "final_decision": "STOP_DRAM_PLAN_STALE_OR_MISSING",
            "r4_latest_moomoo_broad_honest_date": target,
            "abcde_target_rerun_date": abcde_target,
            "dram_raw_latest_completed_date": latest,
            "latest_price_date": "",
            "latest_plan_date": "",
            "setup_classification": "",
            "final_trade_decision": "",
            "consolidated_action_label": "",
            "planned_entry": None,
            "no_chase_above": None,
            "stop_loss": None,
            "take_profit_1": None,
            "take_profit_2": None,
            "trade_plan_currentness": "STALE_BLOCKED",
            "staleness_status": "STALE_BLOCK",
            "date_alignment_passed": False,
            **POLICY,
        }
        pd.DataFrame([empty]).to_csv(out_dir / "dram_daily_plan_moomoo_r4.csv", index=False)
        pd.DataFrame([empty]).to_csv(out_dir / "dram_daily_plan_moomoo_r4_audit.csv", index=False)
        write_json(out_dir / "v21_201_summary.json", empty)
        write_report(empty, out_dir)
        print(f"final_status={empty['final_status']}")
        return empty

    plan, ind = build_plan(dram)
    plan_row = {
        "plan_date": plan["latest_plan_date"],
        "latest_price_date": plan["latest_price_date"],
        "latest_plan_date": plan["latest_plan_date"],
        "ticker": "DRAM",
        "setup_classification": plan.get("setup_classification", ""),
        "final_trade_decision": plan.get("final_decision", ""),
        "consolidated_action_label": plan["consolidated_action_label"],
        "planned_entry": plan.get("planned_entry_base", np.nan),
        "no_chase_above": plan.get("no_chase_above", np.nan),
        "stop_loss": plan.get("stop_loss_base", np.nan),
        "take_profit_1": plan.get("take_profit_1_base", np.nan),
        "take_profit_2": plan.get("take_profit_2_base", np.nan),
        "trade_plan_currentness": plan["trade_plan_currentness"],
        "staleness_status": plan["staleness_status"],
        **POLICY,
    }
    pd.DataFrame([plan_row]).to_csv(out_dir / "dram_daily_plan_moomoo_r4.csv", index=False)
    audit = {**source_audit, **plan_row, "date_alignment_passed": True, "indicator_row_count": int(len(ind))}
    pd.DataFrame([audit]).to_csv(out_dir / "dram_daily_plan_moomoo_r4_audit.csv", index=False)
    summary = {
        "final_status": "PASS_V21_201_DRAM_MOOMOO_R4_PLAN_READY",
        "final_decision": "DRAM_MOOMOO_R4_PLAN_READY_RESEARCH_ONLY",
        "r4_latest_moomoo_broad_honest_date": target,
        "abcde_target_rerun_date": abcde_target,
        "dram_raw_latest_completed_date": latest,
        **plan_row,
        "date_alignment_passed": True,
    }
    write_json(out_dir / "v21_201_summary.json", summary)
    write_report(summary, out_dir)
    for key in ["final_status", "final_decision", "latest_price_date", "latest_plan_date", "broker_action_allowed"]:
        print(f"{key}={summary.get(key, '')}")
    return summary


if __name__ == "__main__":
    run()
