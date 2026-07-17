#!/usr/bin/env python
"""V22.043 R1A forward outcome data fetch and maturity updater."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import socket
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MODULE_ID = "V22.043_R1A"
MODULE_NAME = "FORWARD_OUTCOME_DATA_FETCH_AND_MATURITY_UPDATER"
STAGE = "V22.043_R1A_FORWARD_OUTCOME_DATA_FETCH_AND_MATURITY_UPDATER"
OUT_REL = Path("outputs") / "v22" / STAGE
V22_043_REL = Path("outputs") / "v22" / "V22.043_DIRECTION_GATE_FORWARD_OUTCOME_TRACKER_R1"
R1A_LOG_STAGE = "V22.041_R1A_ETF_OPTION_MOOMOO_READONLY_QUOTE_AND_LOG_PERMISSION_REPAIR"

PASS_STATUS = "PASS_V22_043_R1A_FORWARD_OUTCOME_UPDATED"
PASS_DECISION = "FORWARD_OUTCOME_UPDATED_RESEARCH_ONLY"
WARN_NOT_MATURE = "WARN_V22_043_R1A_FORWARD_OUTCOME_NOT_MATURE_YET"
WARN_BARS_MISSING = "WARN_V22_043_R1A_FORWARD_BARS_MISSING"
WAIT_DECISION = "FORWARD_OUTCOME_WAIT_RESEARCH_ONLY"

TARGETS = ["SOXX", "SOXL", "SOXS", "QQQ", "SPY"]
HORIZON_MINUTES = {"15m": 15, "30m": 30, "60m": 60, "120m": 120}
ET = ZoneInfo("America/New_York")
UTC = timezone.utc

MATURITY_FIELDS = ["event_id", "target_id", "gate_mode", "horizon", "event_timestamp_utc", "event_market_datetime_et", "due_datetime_et", "is_mature", "maturity_status", "unavailable_reason"]
FETCH_FIELDS = ["target_id", "bar_source", "bar_fetch_attempted", "bar_fetch_succeeded", "bar_count", "first_bar_time", "last_bar_time", "fetch_status", "error_message"]
OUTCOME_FIELDS = ["event_id", "gate_mode", "target_type", "target_id", "horizon", "event_timestamp", "due_timestamp", "start_price", "end_price", "forward_return", "outcome_status", "broker_action_allowed", "official_adoption_allowed", "research_only"]
SCORECARD_FIELDS = ["event_id", "gate_mode", "candidate_count", "completed_outcome_count", "average_forward_return", "positive_outcome_count", "negative_outcome_count", "official_adoption_allowed", "broker_action_allowed", "research_only"]
SUMMARY_FIELDS = [
    "final_status", "final_decision", "execution_mode", "ledger_found", "pending_input_count",
    "completed_input_count", "event_count_evaluated", "event_id_latest", "event_timestamp_utc",
    "event_market_datetime_et", "timezone_alignment_ok", "forward_data_attempted",
    "forward_data_available", "local_bar_cache_used", "moomoo_bar_fetch_attempted",
    "moomoo_bar_fetch_succeeded", "horizon_mature_count", "horizon_not_mature_count",
    "forward_bar_available_count", "forward_bar_missing_count", "newly_completed_outcome_count",
    "remaining_pending_outcome_count", "total_completed_outcome_count", "scorecard_available",
    "primary_unavailable_reason", "trade_context_used", "unlock_trade_called", "place_order_called",
    "broker_action_allowed", "official_adoption_allowed", "research_only",
]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return [{k: (v or "") for k, v in row.items() if k is not None} for row in csv.DictReader(handle)]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def numeric(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_utc(text: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        return dt.astimezone(UTC)
    except ValueError:
        return None


def utc_to_et(text: str) -> datetime | None:
    dt = parse_utc(text)
    return dt.astimezone(ET) if dt else None


def session_end_et(dt_et: datetime) -> datetime:
    return datetime.combine(dt_et.date(), time(16, 0), tzinfo=ET)


def next_session_end_et(dt_et: datetime) -> datetime:
    nxt = dt_et.date() + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return datetime.combine(nxt, time(16, 0), tzinfo=ET)


def due_et(event_et: datetime, horizon: str) -> datetime:
    if horizon in HORIZON_MINUTES:
        return event_et + timedelta(minutes=HORIZON_MINUTES[horizon])
    if horizon == "end_of_session":
        return session_end_et(event_et)
    return next_session_end_et(event_et)


def is_mature(event_et: datetime, horizon: str, now_et: datetime) -> tuple[bool, str]:
    due = due_et(event_et, horizon)
    if horizon == "end_of_session" and now_et < due:
        return False, "MARKET_SESSION_NOT_COMPLETED"
    if horizon == "next_completed_session" and now_et < due:
        return False, "MARKET_SESSION_NOT_COMPLETED"
    if now_et < due:
        return False, "HORIZON_NOT_MATURE"
    return True, ""


def configure_safe_env(repo_root: Path) -> None:
    log_dir = repo_root / "outputs" / "v22" / R1A_LOG_STAGE / "provider_logs"
    env_root = log_dir.parent / "provider_env"
    for path in [log_dir, env_root / "userprofile", env_root / "AppData" / "Roaming", env_root / "AppData" / "Local"]:
        path.mkdir(parents=True, exist_ok=True)
    os.environ.update({"FUTU_OPEND_LOG_DIR": str(log_dir), "MOOMOO_LOG_DIR": str(log_dir), "FUTU_LOG_DIR": str(log_dir), "FutuOpenD_LogDir": str(log_dir), "TMP": str(log_dir), "TEMP": str(log_dir)})


def opend_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except Exception:
        return False


def normalize_bar(row: dict[str, Any]) -> dict[str, Any]:
    t = row.get("time_key") or row.get("time") or row.get("datetime") or row.get("date") or ""
    return {"time": str(t), "time_et": utc_to_et(str(t)) if "T" in str(t) else None, "close": numeric(row.get("close"))}


def load_local_bars(repo_root: Path, target: str) -> list[dict[str, Any]]:
    candidates = [
        repo_root / "data" / "moomoo" / "staging" / f"{target}_1m_normalized.csv",
        repo_root / "data" / "moomoo" / "raw" / f"{target}_1m.csv",
    ]
    rows: list[dict[str, Any]] = []
    for path in candidates:
        for row in read_csv_rows(path):
            if str(row.get("internal_symbol", row.get("ticker", target))).upper() in {target, f"US.{target}"}:
                rows.append(normalize_bar(row))
    return [row for row in rows if row.get("close") is not None]


def fetch_moomoo_bars(repo_root: Path, target: str, host: str, port: int, execute: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit = {"target_id": target, "bar_source": "MOOMOO_READ_ONLY", "bar_fetch_attempted": False, "bar_fetch_succeeded": False, "bar_count": 0, "first_bar_time": "", "last_bar_time": "", "fetch_status": "NOT_ATTEMPTED", "error_message": ""}
    if not execute:
        return [], audit
    configure_safe_env(repo_root)
    audit["bar_fetch_attempted"] = True
    if not opend_reachable(host, port):
        audit["fetch_status"] = "PROVIDER_UNAVAILABLE"
        audit["error_message"] = "OpenD port unreachable"
        return [], audit
    try:
        moomoo = __import__("moomoo")
        ctx = moomoo.OpenQuoteContext(host=host, port=port)
        method = getattr(ctx, "request_history_kline", None)
        if method is None:
            audit["fetch_status"] = "TICKER_BAR_FETCH_FAILED"
            audit["error_message"] = "request_history_kline unavailable"
            return [], audit
        result = method(code=f"US.{target}", ktype=getattr(getattr(moomoo, "KLType", None), "K_1M", "K_1M"), max_count=1000)
        data = result[1] if isinstance(result, tuple) and len(result) >= 2 else result
        raw = data.to_dict("records") if hasattr(data, "to_dict") else data if isinstance(data, list) else []
        bars = [normalize_bar(row) for row in raw if isinstance(row, dict) and numeric(row.get("close")) is not None]
        close = getattr(ctx, "close", None)
        if callable(close):
            close()
        audit.update({"bar_fetch_succeeded": bool(bars), "bar_count": len(bars), "first_bar_time": bars[0]["time"] if bars else "", "last_bar_time": bars[-1]["time"] if bars else "", "fetch_status": "FETCH_SUCCEEDED" if bars else "FORWARD_BARS_MISSING"})
        return bars, audit
    except Exception as exc:  # noqa: BLE001
        audit["fetch_status"] = "TICKER_BAR_FETCH_FAILED"
        audit["error_message"] = f"{type(exc).__name__}: {exc}"
        return [], audit


def bar_price_at_or_after(bars: list[dict[str, Any]], due: datetime) -> float | None:
    candidates = []
    for row in bars:
        t = row.get("time_et")
        if t is not None and t >= due and row.get("close") is not None:
            candidates.append((t, row["close"]))
    return sorted(candidates, key=lambda x: x[0])[0][1] if candidates else None


def start_price_at_or_after(bars: list[dict[str, Any]], event_et: datetime) -> float | None:
    return bar_price_at_or_after(bars, event_et)


def evaluate_pending(pending: list[dict[str, str]], bars_by_target: dict[str, list[dict[str, Any]]], now_et: datetime, allow_incomplete: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    updated_pending: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    maturity: list[dict[str, Any]] = []
    for row in pending:
        event_et = utc_to_et(row.get("event_timestamp", ""))
        if event_et is None:
            reason = "EVENT_TIMEZONE_ALIGNMENT_ISSUE"
            updated_pending.append({**row, "outcome_status": reason})
            maturity.append({"event_id": row.get("event_id"), "target_id": row.get("target_id"), "gate_mode": row.get("gate_mode"), "horizon": row.get("horizon"), "event_timestamp_utc": row.get("event_timestamp"), "event_market_datetime_et": "", "due_datetime_et": "", "is_mature": False, "maturity_status": "NOT_MATURE", "unavailable_reason": reason})
            continue
        mature, reason = is_mature(event_et, row.get("horizon", ""), now_et)
        due = due_et(event_et, row.get("horizon", ""))
        bars = bars_by_target.get(row.get("target_id", ""), [])
        unavailable = reason
        if mature:
            start = start_price_at_or_after(bars, event_et)
            end = bar_price_at_or_after(bars, due)
            if start is not None and end is not None:
                completed.append({**row, "start_price": start, "end_price": end, "forward_return": round(end / start - 1, 8), "outcome_status": "COMPLETED", "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True})
                unavailable = ""
            else:
                unavailable = "FORWARD_BARS_MISSING"
                updated_pending.append({**row, "outcome_status": unavailable})
        else:
            updated_pending.append({**row, "outcome_status": reason})
        maturity.append({"event_id": row.get("event_id"), "target_id": row.get("target_id"), "gate_mode": row.get("gate_mode"), "horizon": row.get("horizon"), "event_timestamp_utc": row.get("event_timestamp"), "event_market_datetime_et": event_et.isoformat(), "due_datetime_et": due.isoformat(), "is_mature": mature, "maturity_status": "MATURE" if mature else "NOT_MATURE", "unavailable_reason": unavailable})
    return updated_pending, completed, maturity


def scorecard(completed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for mode in ["strict_official_gate", "semiconductor_only_shadow_gate", "relaxed_broad_shadow_gate"]:
        subset = [row for row in completed if row.get("gate_mode") == mode and row.get("target_type") == "option_candidate"]
        returns = [numeric(row.get("forward_return")) for row in subset if numeric(row.get("forward_return")) is not None]
        rows.append({"event_id": subset[0]["event_id"] if subset else "", "gate_mode": mode, "candidate_count": len({row.get("target_id") for row in subset}), "completed_outcome_count": len(returns), "average_forward_return": "" if not returns else round(sum(returns) / len(returns), 8), "positive_outcome_count": sum(1 for r in returns if r > 0), "negative_outcome_count": sum(1 for r in returns if r < 0), "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True})
    return rows


def primary_reason(maturity: list[dict[str, Any]]) -> str:
    reasons = [row.get("unavailable_reason", "") for row in maturity if row.get("unavailable_reason")]
    for preferred in ["EVENT_TIMEZONE_ALIGNMENT_ISSUE", "HORIZON_NOT_MATURE", "MARKET_SESSION_NOT_COMPLETED", "PROVIDER_UNAVAILABLE", "TICKER_BAR_FETCH_FAILED", "FORWARD_BARS_MISSING"]:
        if preferred in reasons:
            return preferred
    return ""


def build_summary(execution_mode: str, ledger_found: bool, pending_in: int, completed_in: int, events: list[str], event_ts: str, attempted: bool, local_used: bool, moomoo_attempted: bool, moomoo_succeeded: bool, pending: list[dict[str, Any]], completed_new: list[dict[str, Any]], completed_all: list[dict[str, Any]], maturity: list[dict[str, Any]], scores: list[dict[str, Any]]) -> dict[str, Any]:
    mature_count = sum(1 for row in maturity if row.get("is_mature") is True)
    status = PASS_STATUS if completed_new else (WARN_NOT_MATURE if mature_count == 0 else WARN_BARS_MISSING)
    decision = PASS_DECISION if completed_new else WAIT_DECISION
    latest = events[-1] if events else ""
    et = utc_to_et(event_ts)
    return {"module_id": MODULE_ID, "module_name": MODULE_NAME, "final_status": status, "final_decision": decision, "execution_mode": execution_mode, "ledger_found": ledger_found, "pending_input_count": pending_in, "completed_input_count": completed_in, "event_count_evaluated": len(events), "event_id_latest": latest, "event_timestamp_utc": event_ts, "event_market_datetime_et": et.isoformat() if et else "", "timezone_alignment_ok": et is not None, "forward_data_attempted": attempted, "forward_data_available": bool(completed_new), "local_bar_cache_used": local_used, "moomoo_bar_fetch_attempted": moomoo_attempted, "moomoo_bar_fetch_succeeded": moomoo_succeeded, "horizon_mature_count": mature_count, "horizon_not_mature_count": len(maturity) - mature_count, "forward_bar_available_count": len(completed_new), "forward_bar_missing_count": sum(1 for row in maturity if row.get("unavailable_reason") == "FORWARD_BARS_MISSING"), "newly_completed_outcome_count": len(completed_new), "remaining_pending_outcome_count": len(pending), "total_completed_outcome_count": len(completed_all), "scorecard_available": any(int(row.get("completed_outcome_count", 0) or 0) > 0 for row in scores), "primary_unavailable_reason": primary_reason(maturity), "trade_context_used": False, "unlock_trade_called": False, "place_order_called": False, "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True}


def report_text(summary: dict[str, Any]) -> str:
    return "\n".join(["V22.043 R1A Forward Outcome Data Fetch And Maturity Updater", *[f"{k}={summary.get(k)}" for k in SUMMARY_FIELDS]]) + "\n"


def run(repo_root: Path, execute: bool = False, use_moomoo_readonly_bars: bool = True, bar_interval: str = "1m", allow_incomplete_bars: bool = False, event_id: str = "", now_utc: datetime | None = None, injected_bars: dict[str, list[dict[str, Any]]] | None = None, host: str = "127.0.0.1", port: int = 18441) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    out = repo_root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    source = repo_root / V22_043_REL
    ledger = read_csv_rows(source / "direction_gate_event_ledger.csv")
    pending_in = read_csv_rows(source / "direction_gate_forward_outcome_pending.csv")
    completed_in = read_csv_rows(source / "direction_gate_forward_outcome_completed.csv")
    if event_id:
        pending_in = [row for row in pending_in if row.get("event_id") == event_id]
    events = sorted({row.get("event_id", "") for row in pending_in if row.get("event_id")})
    event_ts = next((row.get("event_timestamp", "") for row in pending_in if row.get("event_id") == (events[-1] if events else "")), "")
    targets = sorted({row.get("target_id", "") for row in pending_in if row.get("target_id") in TARGETS})
    bars_by_target: dict[str, list[dict[str, Any]]] = injected_bars or {}
    fetch_rows = []
    local_used = False
    moomoo_attempted = False
    moomoo_succeeded = False
    if not bars_by_target:
        for target in targets:
            local = load_local_bars(repo_root, target)
            if local:
                local_used = True
                bars_by_target[target] = local
                fetch_rows.append({"target_id": target, "bar_source": "LOCAL_CACHE", "bar_fetch_attempted": False, "bar_fetch_succeeded": True, "bar_count": len(local), "first_bar_time": local[0]["time"], "last_bar_time": local[-1]["time"], "fetch_status": "LOCAL_CACHE_USED", "error_message": ""})
            elif execute and use_moomoo_readonly_bars:
                bars, audit = fetch_moomoo_bars(repo_root, target, host, port, True)
                moomoo_attempted = True
                moomoo_succeeded = moomoo_succeeded or bool(bars)
                bars_by_target[target] = bars
                fetch_rows.append(audit)
            else:
                fetch_rows.append({"target_id": target, "bar_source": "NONE", "bar_fetch_attempted": False, "bar_fetch_succeeded": False, "bar_count": 0, "first_bar_time": "", "last_bar_time": "", "fetch_status": "FORWARD_BARS_MISSING", "error_message": ""})
    else:
        for target, bars in bars_by_target.items():
            fetch_rows.append({"target_id": target, "bar_source": "INJECTED", "bar_fetch_attempted": False, "bar_fetch_succeeded": bool(bars), "bar_count": len(bars), "first_bar_time": bars[0]["time"] if bars else "", "last_bar_time": bars[-1]["time"] if bars else "", "fetch_status": "INJECTED_BARS_USED", "error_message": ""})
    now_et = (now_utc or datetime.now(UTC)).astimezone(ET)
    pending_updated, completed_new, maturity = evaluate_pending(pending_in, bars_by_target, now_et, allow_incomplete_bars)
    completed_all = completed_in + completed_new
    scores = scorecard(completed_all)
    summary = build_summary("EXECUTE_READ_ONLY" if execute else "PLAN", bool(ledger), len(pending_in), len(completed_in), events, event_ts, bool(execute), local_used, moomoo_attempted, moomoo_succeeded, pending_updated, completed_new, completed_all, maturity, scores)
    write_csv(out / "forward_outcome_maturity_audit.csv", MATURITY_FIELDS, maturity)
    write_csv(out / "forward_bar_fetch_audit.csv", FETCH_FIELDS, fetch_rows)
    write_csv(out / "forward_outcome_pending_updated.csv", OUTCOME_FIELDS, pending_updated)
    write_csv(out / "forward_outcome_completed_updated.csv", OUTCOME_FIELDS, completed_all)
    write_csv(out / "shadow_vs_strict_scorecard_updated.csv", SCORECARD_FIELDS, scores)
    write_json(out / "v22_043_r1a_summary.json", summary)
    (out / "V22.043_R1A_forward_outcome_data_fetch_and_maturity_updater_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--use-moomoo-readonly-bars", action="store_true", default=True)
    parser.add_argument("--no-use-moomoo-readonly-bars", dest="use_moomoo_readonly_bars", action="store_false")
    parser.add_argument("--bar-interval", default="1m")
    parser.add_argument("--allow-incomplete-bars", action="store_true", default=False)
    parser.add_argument("--event-id", default="")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18441)
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.execute, args.use_moomoo_readonly_bars, args.bar_interval, args.allow_incomplete_bars, args.event_id, host=args.host, port=args.port)
    for key in SUMMARY_FIELDS:
        print(f"{key}={summary.get(key)}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_043_r1a_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
