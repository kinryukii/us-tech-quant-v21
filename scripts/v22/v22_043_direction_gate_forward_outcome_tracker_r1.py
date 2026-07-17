#!/usr/bin/env python
"""V22.043 direction gate forward outcome tracker R1.

Research-only persistent ledger for V22.042 direction gate events and later
forward outcome evaluation. No broker actions or official adoption writes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


MODULE_ID = "V22.043"
MODULE_NAME = "DIRECTION_GATE_FORWARD_OUTCOME_TRACKER_R1"
STAGE = "V22.043_DIRECTION_GATE_FORWARD_OUTCOME_TRACKER_R1"
OUT_REL = Path("outputs") / "v22" / STAGE
V22_042_R2_REL = Path("outputs") / "v22" / "V22.042_R2_DIRECTION_GATE_REASON_AND_SHADOW_MODE_AUDIT"
R1A_STAGE = "V22.041_R1A_ETF_OPTION_MOOMOO_READONLY_QUOTE_AND_LOG_PERMISSION_REPAIR"

PASS_PENDING_STATUS = "PASS_V22_043_DIRECTION_GATE_EVENT_ARCHIVED_PENDING_FORWARD_OUTCOME"
PASS_UPDATED_STATUS = "PASS_V22_043_DIRECTION_GATE_FORWARD_OUTCOME_UPDATED"
PENDING_DECISION = "DIRECTION_GATE_EVENT_ARCHIVED_WAIT_FORWARD_OUTCOME_RESEARCH_ONLY"
UPDATED_DECISION = "DIRECTION_GATE_FORWARD_OUTCOME_UPDATED_RESEARCH_ONLY"

HORIZONS = ["15m", "30m", "60m", "120m", "end_of_session", "next_completed_session"]
TARGETS = ["SOXX", "SOXL", "SOXS", "QQQ", "SPY"]
LEDGER_FIELDS = [
    "event_id", "event_timestamp", "event_market_date", "source_summary_path",
    "strict_official_final_direction_label", "strict_official_wait_state",
    "strict_official_promoted_candidate_count", "strict_candidate_ids",
    "semiconductor_only_shadow_direction_label", "semiconductor_only_shadow_candidate_count",
    "semiconductor_shadow_candidate_ids", "relaxed_broad_shadow_direction_label",
    "relaxed_broad_shadow_candidate_count", "relaxed_shadow_candidate_ids",
    "soxx_direction_label", "qqq_confirmation_label", "spy_confirmation_label",
    "primary_wait_reason_code", "secondary_wait_reason_code", "broker_action_allowed",
    "official_adoption_allowed", "research_only",
]
OUTCOME_FIELDS = [
    "event_id", "gate_mode", "target_type", "target_id", "horizon", "event_timestamp",
    "due_timestamp", "start_price", "end_price", "forward_return", "outcome_status",
    "broker_action_allowed", "official_adoption_allowed", "research_only",
]
SCORECARD_FIELDS = [
    "event_id", "gate_mode", "candidate_count", "completed_outcome_count",
    "average_forward_return", "positive_outcome_count", "negative_outcome_count",
    "official_adoption_allowed", "broker_action_allowed", "research_only",
]
SUMMARY_FIELDS = [
    "final_status", "final_decision", "execution_mode", "v22_042_r2_summary_found",
    "event_archived", "event_id", "event_timestamp", "event_market_date",
    "strict_official_final_direction_label", "strict_official_wait_state",
    "strict_official_promoted_candidate_count",
    "semiconductor_only_shadow_direction_label", "semiconductor_only_shadow_candidate_count",
    "relaxed_broad_shadow_direction_label", "relaxed_broad_shadow_candidate_count",
    "primary_wait_reason_code", "secondary_wait_reason_code", "forward_data_attempted",
    "forward_data_available", "pending_outcome_count", "completed_outcome_count",
    "strict_gate_outcome_available", "semiconductor_shadow_outcome_available",
    "relaxed_shadow_outcome_available", "shadow_vs_strict_scorecard_available",
    "trade_context_used", "unlock_trade_called", "place_order_called",
    "broker_action_allowed", "official_adoption_allowed", "research_only",
]


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_time(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def numeric(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def configure_safe_moomoo_environment(repo_root: Path) -> None:
    log_dir = repo_root / "outputs" / "v22" / R1A_STAGE / "provider_logs"
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


def candidate_ids(rows: list[dict[str, str]]) -> str:
    ids = [row.get("contract_id") or row.get("option_code") or f"{row.get('underlying','')}_{row.get('call_put','')}_{row.get('strike','')}" for row in rows]
    return ";".join(sorted(x for x in ids if x))


def load_latest_r2(repo_root: Path) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    root = repo_root / V22_042_R2_REL
    return (
        read_json(root / "v22_042_r2_summary.json"),
        read_csv_rows(root / "strict_official_direction_candidates.csv"),
        read_csv_rows(root / "semiconductor_only_shadow_candidates.csv"),
        read_csv_rows(root / "relaxed_broad_shadow_candidates.csv"),
    )


def event_from_r2(repo_root: Path, summary: dict[str, Any], strict: list[dict[str, str]], semi: list[dict[str, str]], relaxed: list[dict[str, str]], timestamp: str | None = None) -> dict[str, Any]:
    event_ts = timestamp or summary.get("generated_at_utc") or utc_now_text()
    market_date = event_ts[:10]
    seed = "|".join([
        market_date,
        str(summary.get("soxx_direction_label", "")),
        str(summary.get("qqq_confirmation_label", "")),
        str(summary.get("spy_confirmation_label", "")),
        str(summary.get("primary_wait_reason_code", "")),
        candidate_ids(strict),
        candidate_ids(semi),
        candidate_ids(relaxed),
    ])
    event_id = "V22_043_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
    return {
        "event_id": event_id,
        "event_timestamp": event_ts,
        "event_market_date": market_date,
        "source_summary_path": str(repo_root / V22_042_R2_REL / "v22_042_r2_summary.json"),
        "strict_official_final_direction_label": summary.get("strict_official_final_direction_label", ""),
        "strict_official_wait_state": summary.get("strict_official_wait_state", True),
        "strict_official_promoted_candidate_count": summary.get("strict_official_promoted_candidate_count", 0),
        "strict_candidate_ids": candidate_ids(strict),
        "semiconductor_only_shadow_direction_label": summary.get("semiconductor_only_shadow_direction_label", ""),
        "semiconductor_only_shadow_candidate_count": summary.get("semiconductor_only_shadow_candidate_count", 0),
        "semiconductor_shadow_candidate_ids": candidate_ids(semi),
        "relaxed_broad_shadow_direction_label": summary.get("relaxed_broad_shadow_direction_label", ""),
        "relaxed_broad_shadow_candidate_count": summary.get("relaxed_broad_shadow_candidate_count", 0),
        "relaxed_shadow_candidate_ids": candidate_ids(relaxed),
        "soxx_direction_label": summary.get("soxx_direction_label", ""),
        "qqq_confirmation_label": summary.get("qqq_confirmation_label", ""),
        "spy_confirmation_label": summary.get("spy_confirmation_label", ""),
        "primary_wait_reason_code": summary.get("primary_wait_reason_code", ""),
        "secondary_wait_reason_code": summary.get("secondary_wait_reason_code", ""),
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }


def append_ledger(path: Path, event: dict[str, Any], allow_duplicate_same_minute: bool) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = read_csv_rows(path)
    if not allow_duplicate_same_minute and any(row.get("event_id") == event["event_id"] for row in rows):
        return rows, False
    rows.append(event)
    write_csv(path, LEDGER_FIELDS, rows)
    return rows, True


def due_timestamp(event_ts: str, horizon: str) -> str:
    parsed = parse_time(event_ts) or datetime.now(timezone.utc)
    if horizon.endswith("m"):
        return (parsed + timedelta(minutes=int(horizon[:-1]))).isoformat().replace("+00:00", "Z")
    if horizon == "end_of_session":
        return parsed.replace(hour=20, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")
    return (parsed + timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def target_rows_for_event(event: dict[str, Any]) -> list[tuple[str, str, str]]:
    rows = [("underlying", t, "market") for t in TARGETS]
    for mode, field in [("strict_official_gate", "strict_candidate_ids"), ("semiconductor_only_shadow_gate", "semiconductor_shadow_candidate_ids"), ("relaxed_broad_shadow_gate", "relaxed_shadow_candidate_ids")]:
        for cid in str(event.get(field, "")).split(";"):
            if cid:
                rows.append(("option_candidate", cid, mode))
    return rows


def build_pending(event: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for target_type, target_id, gate_mode in target_rows_for_event(event):
        for horizon in HORIZONS:
            out.append({"event_id": event["event_id"], "gate_mode": gate_mode, "target_type": target_type, "target_id": target_id, "horizon": horizon, "event_timestamp": event["event_timestamp"], "due_timestamp": due_timestamp(event["event_timestamp"], horizon), "start_price": "", "end_price": "", "forward_return": "", "outcome_status": "PENDING_FORWARD_DATA", "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True})
    return out


def evaluate_outcomes(pending: list[dict[str, Any]], forward_prices: dict[str, dict[str, float]] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not forward_prices:
        return pending, []
    still_pending, completed = [], []
    for row in pending:
        key = f"{row['target_id']}|{row['horizon']}"
        prices = forward_prices.get(key)
        if not prices:
            still_pending.append(row)
            continue
        start = numeric(prices.get("start"))
        end = numeric(prices.get("end"))
        if start is None or end is None or start == 0:
            still_pending.append(row)
            continue
        completed.append({**row, "start_price": start, "end_price": end, "forward_return": round(end / start - 1, 8), "outcome_status": "COMPLETED"})
    return still_pending, completed


def scorecard(completed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for mode in ["strict_official_gate", "semiconductor_only_shadow_gate", "relaxed_broad_shadow_gate"]:
        subset = [row for row in completed if row.get("gate_mode") == mode and row.get("target_type") == "option_candidate"]
        rets = [numeric(row.get("forward_return")) for row in subset if numeric(row.get("forward_return")) is not None]
        rows.append({"event_id": subset[0]["event_id"] if subset else "", "gate_mode": mode, "candidate_count": len({row.get("target_id") for row in subset}), "completed_outcome_count": len(rets), "average_forward_return": "" if not rets else round(sum(rets) / len(rets), 8), "positive_outcome_count": sum(1 for r in rets if r > 0), "negative_outcome_count": sum(1 for r in rets if r < 0), "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True})
    return rows


def try_fetch_forward_prices(repo_root: Path, host: str, port: int) -> dict[str, dict[str, float]]:
    configure_safe_moomoo_environment(repo_root)
    if not opend_reachable(host, port):
        return {}
    # R1 intentionally does not infer completed forward outcomes from partial live bars.
    return {}


def build_summary(execution_mode: str, r2_found: bool, event_archived: bool, event: dict[str, Any], attempted: bool, pending: list[dict[str, Any]], completed: list[dict[str, Any]], scores: list[dict[str, Any]]) -> dict[str, Any]:
    completed_count = len(completed)
    final_status = PASS_UPDATED_STATUS if completed_count else PASS_PENDING_STATUS
    final_decision = UPDATED_DECISION if completed_count else PENDING_DECISION
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "final_status": final_status,
        "final_decision": final_decision,
        "execution_mode": execution_mode,
        "v22_042_r2_summary_found": r2_found,
        "event_archived": event_archived,
        "event_id": event.get("event_id", ""),
        "event_timestamp": event.get("event_timestamp", ""),
        "event_market_date": event.get("event_market_date", ""),
        "strict_official_final_direction_label": event.get("strict_official_final_direction_label", ""),
        "strict_official_wait_state": bool(event.get("strict_official_wait_state", True)),
        "strict_official_promoted_candidate_count": int(event.get("strict_official_promoted_candidate_count", 0) or 0),
        "semiconductor_only_shadow_direction_label": event.get("semiconductor_only_shadow_direction_label", ""),
        "semiconductor_only_shadow_candidate_count": int(event.get("semiconductor_only_shadow_candidate_count", 0) or 0),
        "relaxed_broad_shadow_direction_label": event.get("relaxed_broad_shadow_direction_label", ""),
        "relaxed_broad_shadow_candidate_count": int(event.get("relaxed_broad_shadow_candidate_count", 0) or 0),
        "primary_wait_reason_code": event.get("primary_wait_reason_code", ""),
        "secondary_wait_reason_code": event.get("secondary_wait_reason_code", ""),
        "forward_data_attempted": attempted,
        "forward_data_available": completed_count > 0,
        "pending_outcome_count": len(pending),
        "completed_outcome_count": completed_count,
        "strict_gate_outcome_available": any(row.get("gate_mode") == "strict_official_gate" for row in completed),
        "semiconductor_shadow_outcome_available": any(row.get("gate_mode") == "semiconductor_only_shadow_gate" for row in completed),
        "relaxed_shadow_outcome_available": any(row.get("gate_mode") == "relaxed_broad_shadow_gate" for row in completed),
        "shadow_vs_strict_scorecard_available": any(int(row.get("completed_outcome_count", 0) or 0) > 0 for row in scores),
        "trade_context_used": False,
        "unlock_trade_called": False,
        "place_order_called": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }


def report_text(summary: dict[str, Any]) -> str:
    return "\n".join(["V22.043 Direction Gate Forward Outcome Tracker R1", *[f"{k}={summary.get(k)}" for k in SUMMARY_FIELDS]]) + "\n"


def run(
    repo_root: Path,
    execute: bool = False,
    use_latest_v22_042_r2: bool = True,
    append_ledger_flag: bool = True,
    evaluate_forward_outcomes: bool = True,
    allow_duplicate_same_minute: bool = False,
    injected_r2_summary: dict[str, Any] | None = None,
    injected_strict: list[dict[str, str]] | None = None,
    injected_semi: list[dict[str, str]] | None = None,
    injected_relaxed: list[dict[str, str]] | None = None,
    forward_prices: dict[str, dict[str, float]] | None = None,
    host: str = "127.0.0.1",
    port: int = 18441,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    out = repo_root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    if injected_r2_summary is not None:
        r2_summary, strict, semi, relaxed = injected_r2_summary, injected_strict or [], injected_semi or [], injected_relaxed or []
    elif use_latest_v22_042_r2:
        r2_summary, strict, semi, relaxed = load_latest_r2(repo_root)
    else:
        r2_summary, strict, semi, relaxed = {}, [], [], []
    r2_found = bool(r2_summary)
    event = event_from_r2(repo_root, r2_summary, strict, semi, relaxed) if r2_found else {}
    ledger_path = out / "direction_gate_event_ledger.csv"
    if append_ledger_flag and event:
        ledger_rows, archived = append_ledger(ledger_path, event, allow_duplicate_same_minute)
    else:
        ledger_rows, archived = read_csv_rows(ledger_path), False
    latest_rows = [event] if event else []
    pending = build_pending(event) if event else []
    attempted = bool(execute and evaluate_forward_outcomes)
    if attempted and forward_prices is None:
        forward_prices = try_fetch_forward_prices(repo_root, host, port)
    pending, completed = evaluate_outcomes(pending, forward_prices if evaluate_forward_outcomes else None)
    scores = scorecard(completed)
    summary = build_summary("EXECUTE_READ_ONLY" if execute else "PLAN", r2_found, archived, event, attempted, pending, completed, scores)
    write_csv(ledger_path, LEDGER_FIELDS, ledger_rows)
    write_csv(out / "direction_gate_event_latest.csv", LEDGER_FIELDS, latest_rows)
    write_csv(out / "direction_gate_forward_outcome_pending.csv", OUTCOME_FIELDS, pending)
    write_csv(out / "direction_gate_forward_outcome_completed.csv", OUTCOME_FIELDS, completed)
    write_csv(out / "direction_gate_shadow_vs_strict_scorecard.csv", SCORECARD_FIELDS, scores)
    write_json(out / "v22_043_summary.json", summary)
    (out / "V22.043_direction_gate_forward_outcome_tracker_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--use-latest-v22-042-r2", action="store_true", default=True)
    parser.add_argument("--no-use-latest-v22-042-r2", dest="use_latest_v22_042_r2", action="store_false")
    parser.add_argument("--append-ledger", action="store_true", default=True)
    parser.add_argument("--no-append-ledger", dest="append_ledger_flag", action="store_false")
    parser.add_argument("--evaluate-forward-outcomes", action="store_true", default=True)
    parser.add_argument("--no-evaluate-forward-outcomes", dest="evaluate_forward_outcomes", action="store_false")
    parser.add_argument("--allow-duplicate-same-minute", action="store_true", default=False)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18441)
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.execute, args.use_latest_v22_042_r2, args.append_ledger_flag, args.evaluate_forward_outcomes, args.allow_duplicate_same_minute, host=args.host, port=args.port)
    for key in SUMMARY_FIELDS:
        print(f"{key}={summary.get(key)}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_043_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
