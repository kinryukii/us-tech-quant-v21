#!/usr/bin/env python
"""V22.020 DRAM daily decision panel R2.

Read-only DRAM research control panel. This module consolidates local DRAM
outputs and V22.015 forward-confirmation governance without running chains,
fetching data, connecting to brokers, mutating caches, placing orders, or
allowing trades.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


MODULE_ID = "V22.020"
MODULE_NAME = "DRAM_DAILY_DECISION_PANEL_R2"
STAGE = "V22.020_DRAM_DAILY_DECISION_PANEL_R2"
OUT_REL = Path("outputs") / "v22" / STAGE
PANEL_DATE_UTC = date(2026, 7, 6).isoformat()
PRIMARY_SYMBOL = "DRAM"
PRIMARY_THEME = "SEMICONDUCTOR_MEMORY"

FORWARD_DASHBOARD_INPUT = Path("outputs") / "v22" / "V22.015_FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD" / "v22_forward_only_factor_confirmation_dashboard.csv"
FORWARD_SUMMARY_INPUT = Path("outputs") / "v22" / "V22.015_FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD" / "v22_forward_only_factor_confirmation_summary.json"

PASS_STATUS = "PASS_V22_020_DRAM_DAILY_DECISION_PANEL_READY"
WARN_STATUS = "WARN_V22_020_DRAM_PANEL_READY_WITH_MISSING_OPTIONAL_SOURCES"
FAIL_STATUS = "FAIL_V22_020_DRAM_PANEL_MISSING_REQUIRED_INPUTS"
READY_DECISION = "DRAM_DAILY_DECISION_PANEL_READY_RESEARCH_ONLY"
FAIL_DECISION = "DRAM_DAILY_DECISION_PANEL_BLOCKED_MISSING_REQUIRED_INPUTS"

NEXT_RECOMMENDED_MODULES = [
    "V22.021_DRAM_SIGNAL_TO_ACTION_TRANSLATOR",
    "V22.022_DRAM_MANUAL_TRADE_JOURNAL_SCHEMA",
    "V22.030_ETF_OPTION_UNIVERSE_REGISTRY",
    "V22.031_ETF_OPTION_CONTRACT_SPEC_REGISTRY",
]

OPTIONAL_SOURCES = [
    ("V21.201_DRAM_PLAN", Path("outputs") / "v21" / "V21.201_DRAM_MOOMOO_R4_PLAN"),
    ("V21.232_DRAM", Path("outputs") / "v21" / "V21.232_DRAM"),
    ("V21.183_DRAM_INTRADAY_FORWARD_OUTCOME_UPDATER", Path("outputs") / "v21" / "V21.183_DRAM_INTRADAY_FORWARD_OUTCOME_UPDATER"),
    ("V21.184_DRAM_INTRADAY_OUTCOME_DASHBOARD_AND_DECISION_SUMMARY", Path("outputs") / "v21" / "V21.184_DRAM_INTRADAY_OUTCOME_DASHBOARD_AND_DECISION_SUMMARY"),
    ("V21.185_DRAM_INTRADAY_TRIGGER_EVENT_ARCHIVE_AND_DAILY_APPEND", Path("outputs") / "v21" / "V21.185_DRAM_INTRADAY_TRIGGER_EVENT_ARCHIVE_AND_DAILY_APPEND"),
    ("V21.186_DRAM_NO_TRADE_GATE", Path("outputs") / "v21" / "V21.186_DRAM_NO_TRADE_GATE"),
    ("V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN", Path("outputs") / "v21" / "V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN"),
    ("V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1", Path("outputs") / "v21" / "V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1"),
    ("V22.002_V21_OUTPUT_MANIFEST", Path("outputs") / "v22" / "V22.002_V21_ACTIVE_DEPRECATED_OUTPUT_MANIFEST" / "v21_output_classification_manifest.csv"),
]

NO_ACTION_GATES = {
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "trade_allowed": False,
    "market_data_fetch_allowed": False,
    "moomoo_connection_allowed": False,
    "option_chain_fetch_allowed": False,
    "daily_chain_execution_allowed": False,
    "historical_outputs_mutation_allowed": False,
    "cache_mutation_allowed": False,
    "factor_promotion_allowed": False,
    "factor_weight_change_allowed": False,
}

DAILY_FIELDNAMES = [
    "panel_date_utc",
    "primary_symbol",
    "primary_theme",
    "source_status",
    "latest_local_plan_source",
    "latest_local_plan_date",
    "latest_price_date_detected",
    "entry_price",
    "no_chase_price",
    "stop_price",
    "take_profit_reference",
    "plan_currentness_status",
    "forward_confirmation_status_from_v22_015",
    "forward_maturity_status",
    "intraday_trigger_status",
    "no_trade_gate_status",
    "outcome_tracking_status",
    "qqq_alignment_status",
    "smh_alignment_status",
    "soxx_alignment_status",
    "etf_option_alignment_status",
    "option_extension_status",
    "primary_blocker",
    "secondary_blockers",
    "final_research_action_label",
    "broker_action_allowed",
    "official_adoption_allowed",
    "trade_allowed",
    "research_only",
    "next_required_validation",
    "reason",
]

SIGNAL_FIELDNAMES = [
    "signal_name",
    "signal_group",
    "signal_status",
    "source_path",
    "source_quality",
    "action_translation",
    "trade_allowed",
    "broker_action_allowed",
    "reason",
]

FORWARD_FIELDNAMES = [
    "item_id",
    "item_name",
    "forward_confirmation_status",
    "forward_5d_status",
    "forward_10d_status",
    "forward_20d_status",
    "matured_forward_observation_count_estimate",
    "supportive_forward_observation_count_estimate",
    "source_summary_only_flag",
    "placeholder_only_flag",
    "primary_blocker",
    "next_required_validation",
    "reason",
]

SOURCE_FIELDNAMES = [
    "source_name",
    "source_path",
    "exists",
    "source_type",
    "parent_output_name",
    "scan_mode",
    "file_count_shallow",
    "file_size_bytes_shallow",
    "detected_json_files",
    "detected_csv_files",
    "detected_report_files",
    "detected_plan_fields",
    "detected_date_fields",
    "detected_price_fields",
    "latest_date_detected",
    "source_status",
    "note",
]

PLAN_FIELD_PATTERNS = {
    "entry_price": [r"\bentry_price\b", r"\bentry\b", r"\bdram_entry\b", r"\bplanned_entry\b"],
    "no_chase_price": [r"\bno_chase_price\b", r"\bno_chase\b", r"\bdram_no_chase\b", r"\bno_chase_above\b"],
    "stop_price": [r"\bstop_price\b", r"\bstop\b", r"\bdram_stop\b", r"\bstop_loss\b"],
    "take_profit_reference": [r"\btake_profit_reference\b", r"\btake_profit\b", r"\btake_profit_1\b"],
    "latest_price_date": [r"\blatest_price_date\b"],
    "latest_plan_date": [r"\blatest_plan_date\b", r"\bplan_date\b"],
}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    if output_dir.resolve() != expected:
        raise ValueError(f"V22.020 output directory must be {expected}, got {output_dir.resolve()}")


def optional_matches(repo_root: Path, rel_path: Path) -> list[Path]:
    direct = repo_root / rel_path
    if direct.exists():
        return [direct]
    parent = direct.parent
    prefix = direct.name
    if not parent.exists():
        return [direct]
    matches = [child for child in parent.iterdir() if child.name.startswith(prefix)]
    return sorted(matches, key=lambda item: item.as_posix().lower()) or [direct]


def output_name_for_path(path: Path) -> str:
    for part in path.parts:
        if part.startswith("V21.") or part.startswith("V22."):
            return part
    return path.parent.name


def source_type(path: Path) -> str:
    if path.is_dir():
        return "directory"
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "file"


def shallow_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return [child for child in path.iterdir() if child.is_file()]
    return []


def parse_date_text(value: str) -> str:
    match = re.search(r"(20\d{2}-\d{2}-\d{2}|20\d{6})", value)
    if not match:
        return ""
    raw = match.group(1)
    if "-" in raw:
        return raw
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def newest_date(values: list[str]) -> str:
    parsed: list[date] = []
    for value in values:
        if not value:
            continue
        try:
            parsed.append(datetime.strptime(value[:10], "%Y-%m-%d").date())
        except ValueError:
            continue
    return max(parsed).isoformat() if parsed else ""


def value_from_row(row: dict[str, Any], patterns: list[str]) -> str:
    for key, value in row.items():
        normalized = str(key).lower()
        if any(re.search(pattern, normalized) for pattern in patterns):
            text = str(value).strip()
            if text:
                return text
    return ""


def scan_csv_plan(path: Path) -> tuple[dict[str, str], list[str]]:
    rows = read_csv_rows(path)
    if not rows:
        return {}, []
    candidates = [row for row in rows if str(row.get("ticker", row.get("symbol", PRIMARY_SYMBOL))).upper() == PRIMARY_SYMBOL]
    row = candidates[-1] if candidates else rows[-1]
    fields = {name: value_from_row(row, patterns) for name, patterns in PLAN_FIELD_PATTERNS.items()}
    dates = [parse_date_text(str(value)) for value in row.values()]
    return fields, [value for value in dates if value]


def scan_text_plan(path: Path) -> tuple[dict[str, str], list[str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}, []
    fields: dict[str, str] = {}
    for name, patterns in PLAN_FIELD_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern + r"\s*[:=,]\s*([A-Za-z0-9_.-]+)", text, flags=re.IGNORECASE)
            if match:
                fields[name] = match.group(1)
                break
    return fields, [parse_date_text(value) for value in re.findall(r"20\d{2}-\d{2}-\d{2}|20\d{6}", text)]


def detect_plan_from_file(path: Path) -> tuple[dict[str, str], list[str]]:
    if path.suffix.lower() == ".csv":
        return scan_csv_plan(path)
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}, []
        text = json.dumps(payload, sort_keys=True)
        return scan_text_plan_from_text(text)
    if path.suffix.lower() == ".txt":
        return scan_text_plan(path)
    return {}, []


def scan_text_plan_from_text(text: str) -> tuple[dict[str, str], list[str]]:
    fields: dict[str, str] = {}
    for name, patterns in PLAN_FIELD_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern + r'["\']?\s*[:=,]\s*["\']?([A-Za-z0-9_.-]+)', text, flags=re.IGNORECASE)
            if match:
                fields[name] = match.group(1)
                break
    return fields, [parse_date_text(value) for value in re.findall(r"20\d{2}-\d{2}-\d{2}|20\d{6}", text)]


def source_audit_rows(repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    rows: list[dict[str, Any]] = []
    best_plan: dict[str, str] = {}
    for source_name, rel_path in OPTIONAL_SOURCES:
        for path in optional_matches(repo_root, rel_path):
            exists = path.exists()
            files = shallow_files(path)
            json_files = [file.name for file in files if file.suffix.lower() == ".json"]
            csv_files = [file.name for file in files if file.suffix.lower() == ".csv"]
            report_files = [file.name for file in files if file.suffix.lower() == ".txt"]
            detected_fields: dict[str, str] = {}
            detected_dates: list[str] = []
            for file in files:
                if file.suffix.lower() not in {".csv", ".json", ".txt"}:
                    continue
                file_fields, file_dates = detect_plan_from_file(file)
                if any(file_fields.values()):
                    detected_fields = {**detected_fields, **{key: value for key, value in file_fields.items() if value}}
                    detected_dates.extend(file_dates)
                    plan_date = file_fields.get("latest_plan_date") or newest_date(file_dates)
                    current_best = best_plan.get("latest_plan_date", "")
                    if not best_plan or (plan_date and plan_date >= current_best):
                        best_plan = {
                            "latest_local_plan_source": file.relative_to(repo_root).as_posix() if repo_root in file.resolve().parents else file.as_posix(),
                            "latest_plan_date": plan_date,
                            "latest_price_date": file_fields.get("latest_price_date", ""),
                            "entry_price": file_fields.get("entry_price", ""),
                            "no_chase_price": file_fields.get("no_chase_price", ""),
                            "stop_price": file_fields.get("stop_price", ""),
                            "take_profit_reference": file_fields.get("take_profit_reference", ""),
                        }
            rel_display = path.relative_to(repo_root).as_posix() if exists and repo_root in path.resolve().parents else path.as_posix()
            rows.append(
                {
                    "source_name": source_name,
                    "source_path": rel_display,
                    "exists": exists,
                    "source_type": source_type(path),
                    "parent_output_name": output_name_for_path(path),
                    "scan_mode": "SHALLOW_FILE_SCAN" if exists else "SOURCE_NOT_FOUND",
                    "file_count_shallow": len(files),
                    "file_size_bytes_shallow": sum(file.stat().st_size for file in files if file.exists()),
                    "detected_json_files": ";".join(json_files),
                    "detected_csv_files": ";".join(csv_files),
                    "detected_report_files": ";".join(report_files),
                    "detected_plan_fields": ";".join(sorted(key for key, value in detected_fields.items() if value)),
                    "detected_date_fields": "latest_plan_date;latest_price_date" if detected_fields.get("latest_plan_date") or detected_fields.get("latest_price_date") else "",
                    "detected_price_fields": ";".join(key for key in ["entry_price", "no_chase_price", "stop_price", "take_profit_reference"] if detected_fields.get(key)),
                    "latest_date_detected": newest_date(detected_dates),
                    "source_status": "SOURCE_FOUND" if exists else "SOURCE_NOT_FOUND",
                    "note": "Shallow local scan only; no market data fetch or chain execution.",
                }
            )
    return rows, best_plan


def forward_rows(forward_dashboard: list[dict[str, str]]) -> list[dict[str, Any]]:
    wanted = {"DRAM_DAILY_PLAN", "DRAM_FORWARD_OUTCOME_TRACKING", "DRAM_INTRADAY_TRIGGER", "DRAM_NO_TRADE_GATE"}
    return [
        {field: row.get(field, "") for field in FORWARD_FIELDNAMES}
        for row in forward_dashboard
        if row.get("item_id") in wanted or row.get("family") == "DRAM"
    ]


def find_forward_row(rows: list[dict[str, str]], item_id: str) -> dict[str, str]:
    for row in rows:
        if row.get("item_id") == item_id:
            return row
    return {}


def plan_currentness(latest_plan_date: str) -> str:
    if not latest_plan_date:
        return "PLAN_DATE_MISSING_REVIEW_REQUIRED"
    try:
        plan_date = datetime.strptime(latest_plan_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return "PLAN_DATE_UNPARSEABLE_REVIEW_REQUIRED"
    age_days = (date(2026, 7, 6) - plan_date).days
    if age_days <= 2:
        return "CURRENT_OR_RECENT"
    if age_days <= 7:
        return "STALE_REVIEW_REQUIRED"
    return "STALE_BLOCKING"


def final_action_label(forward_status: str, local_plan_found: bool, fields_complete: bool, currentness: str, no_trade_gate_status: str) -> str:
    if "BLOCK" in no_trade_gate_status:
        return "DRAM_BLOCKED_BY_NO_TRADE_GATE"
    if not local_plan_found:
        return "DRAM_BLOCKED_BY_NO_LOCAL_PLAN_SOURCE"
    if currentness == "STALE_BLOCKING":
        return "DRAM_BLOCKED_BY_STALE_SOURCE"
    if forward_status == "FORWARD_PENDING_MATURITY":
        return "DRAM_FORWARD_PENDING_MATURITY"
    if not fields_complete:
        return "DRAM_PLAN_SOURCE_FOUND_REVIEW_REQUIRED"
    return "DRAM_RESEARCH_PANEL_READY"


def daily_panel_row(forward_dashboard: list[dict[str, str]], source_audit: list[dict[str, Any]], best_plan: dict[str, str]) -> dict[str, Any]:
    dram_plan = find_forward_row(forward_dashboard, "DRAM_DAILY_PLAN")
    intraday = find_forward_row(forward_dashboard, "DRAM_INTRADAY_TRIGGER")
    no_trade = find_forward_row(forward_dashboard, "DRAM_NO_TRADE_GATE")
    outcome = find_forward_row(forward_dashboard, "DRAM_FORWARD_OUTCOME_TRACKING")
    local_plan_found = bool(best_plan.get("latest_local_plan_source"))
    currentness = plan_currentness(best_plan.get("latest_plan_date", ""))
    fields_complete = all(best_plan.get(key) for key in ["entry_price", "no_chase_price", "stop_price"])
    no_trade_status = "LOCAL_GATE_REVIEW_REQUIRED" if no_trade else "NO_TRADE_GATE_SOURCE_MISSING_REVIEW_REQUIRED"
    forward_status = dram_plan.get("forward_confirmation_status", "REVIEW_REQUIRED")
    blockers = [value for value in [dram_plan.get("primary_blocker", ""), no_trade_status if "MISSING" in no_trade_status else ""] if value]
    label = final_action_label(forward_status, local_plan_found, fields_complete, currentness, no_trade_status)
    return {
        "panel_date_utc": PANEL_DATE_UTC,
        "primary_symbol": PRIMARY_SYMBOL,
        "primary_theme": PRIMARY_THEME,
        "source_status": "LOCAL_DRAM_SOURCE_FOUND" if local_plan_found else "LOCAL_DRAM_SOURCE_MISSING",
        "latest_local_plan_source": best_plan.get("latest_local_plan_source", ""),
        "latest_local_plan_date": best_plan.get("latest_plan_date", ""),
        "latest_price_date_detected": best_plan.get("latest_price_date", ""),
        "entry_price": best_plan.get("entry_price", ""),
        "no_chase_price": best_plan.get("no_chase_price", ""),
        "stop_price": best_plan.get("stop_price", ""),
        "take_profit_reference": best_plan.get("take_profit_reference", ""),
        "plan_currentness_status": currentness,
        "forward_confirmation_status_from_v22_015": forward_status,
        "forward_maturity_status": forward_status,
        "intraday_trigger_status": intraday.get("forward_confirmation_status", "INTRADAY_SOURCE_REVIEW_REQUIRED"),
        "no_trade_gate_status": no_trade_status,
        "outcome_tracking_status": outcome.get("forward_confirmation_status", "OUTCOME_TRACKING_REVIEW_REQUIRED"),
        "qqq_alignment_status": "LOCAL_ALIGNMENT_REVIEW_REQUIRED",
        "smh_alignment_status": "LOCAL_ALIGNMENT_REVIEW_REQUIRED",
        "soxx_alignment_status": "LOCAL_ALIGNMENT_REVIEW_REQUIRED",
        "etf_option_alignment_status": "PLACEHOLDER_PENDING_V22_OPTION_CHAIN",
        "option_extension_status": "NOT_YET_INGESTED",
        "primary_blocker": blockers[0] if blockers else "",
        "secondary_blockers": ";".join(blockers[1:]),
        "final_research_action_label": label,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "trade_allowed": False,
        "research_only": True,
        "next_required_validation": "Review local DRAM plan fields and accumulate forward maturity; execution remains manual research-only.",
        "reason": "DRAM daily panel is read-only and cannot grant broker, trade, or official adoption permission.",
    }


def signal_rows(panel: dict[str, Any]) -> list[dict[str, Any]]:
    specs = [
        ("Local DRAM daily plan", "DAILY_PLAN", panel["source_status"], panel["latest_local_plan_source"], "LOCAL_SOURCE_SCAN"),
        ("V22.015 DRAM forward confirmation", "FORWARD_CONFIRMATION", panel["forward_confirmation_status_from_v22_015"], "outputs/v22/V22.015_FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD/v22_forward_only_factor_confirmation_dashboard.csv", "V22_015_GOVERNANCE"),
        ("DRAM intraday trigger", "INTRADAY_TRIGGER", panel["intraday_trigger_status"], "", "LOCAL_SOURCE_SUMMARY"),
        ("DRAM no-trade gate", "NO_TRADE_GATE", panel["no_trade_gate_status"], "", "LOCAL_SOURCE_SUMMARY"),
        ("DRAM outcome tracking", "OUTCOME_TRACKING", panel["outcome_tracking_status"], "", "LOCAL_SOURCE_SUMMARY"),
        ("ETF alignment placeholder", "ETF_ALIGNMENT_PLACEHOLDER", panel["etf_option_alignment_status"], "", "PLACEHOLDER"),
        ("Option extension placeholder", "OPTION_EXTENSION_PLACEHOLDER", panel["option_extension_status"], "", "PLACEHOLDER"),
        ("Personal risk rule", "PERSONAL_RISK_RULE", "MANUAL_RESEARCH_ONLY", "", "V22_POLICY"),
    ]
    return [
        {
            "signal_name": name,
            "signal_group": group,
            "signal_status": status,
            "source_path": source,
            "source_quality": quality,
            "action_translation": "RESEARCH_ONLY_REVIEW_OR_OBSERVE",
            "trade_allowed": False,
            "broker_action_allowed": False,
            "reason": "Signal is translated to research-only review; no broker or trade permission is granted.",
        }
        for name, group, status, source, quality in specs
    ]


def risk_state_payload() -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "primary_symbol": PRIMARY_SYMBOL,
        "primary_theme": PRIMARY_THEME,
        "max_open_strategy_packages_default": 1,
        "option_stop_loss_pct_reference": -30,
        "premarket_plan_required": True,
        "no_first_day_breakout_chase": True,
        "multi_timeframe_confirmation_required": True,
        "confirmation_order": ["1h", "15m", "1m"],
        "manual_execution_only": True,
        "paper_plan_only": True,
        **NO_ACTION_GATES,
    }


def risk_gate_payload() -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "allowed_side_effects": ["create_outputs_v22_020_only"],
        "forbidden_side_effects": [
            "execute_daily_chain",
            "connect_moomoo",
            "fetch_market_data",
            "fetch_option_chain",
            "mutate_v21_outputs",
            "mutate_cache",
            "create_trade_order",
            "modify_broker_state",
            "promote_factor",
            "promote_strategy",
            "change_factor_weight",
        ],
        **NO_ACTION_GATES,
    }


def summary_payload(repo_root: Path, panel_rows: list[dict[str, Any]], signals: list[dict[str, Any]], forward: list[dict[str, Any]], sources: list[dict[str, Any]], best_plan: dict[str, str]) -> dict[str, Any]:
    input_exists = (repo_root / FORWARD_DASHBOARD_INPUT).exists()
    summary_exists = (repo_root / FORWARD_SUMMARY_INPUT).exists()
    optional_missing = sum(1 for row in sources if row.get("exists") is False)
    local_found = sum(1 for row in sources if row.get("exists") is True and "DRAM" in row.get("source_name", ""))
    if not input_exists or not summary_exists:
        final_status = FAIL_STATUS
        final_decision = FAIL_DECISION
    elif optional_missing:
        final_status = WARN_STATUS
        final_decision = READY_DECISION
    else:
        final_status = PASS_STATUS
        final_decision = READY_DECISION
    panel = panel_rows[0] if panel_rows else {}
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "final_status": final_status,
        "final_decision": final_decision,
        "forward_confirmation_input_exists": input_exists,
        "forward_confirmation_summary_exists": summary_exists,
        "dram_panel_row_count": len(panel_rows),
        "signal_to_action_row_count": len(signals),
        "forward_maturity_row_count": len(forward),
        "source_audit_row_count": len(sources),
        "local_dram_source_found_count": local_found,
        "optional_source_missing_count": optional_missing,
        "latest_local_plan_source": best_plan.get("latest_local_plan_source", ""),
        "latest_local_plan_date": best_plan.get("latest_plan_date", ""),
        "latest_price_date_detected": best_plan.get("latest_price_date", ""),
        "entry_price_detected": bool(best_plan.get("entry_price")),
        "no_chase_price_detected": bool(best_plan.get("no_chase_price")),
        "stop_price_detected": bool(best_plan.get("stop_price")),
        "final_research_action_label": panel.get("final_research_action_label", ""),
        "protected_outputs_modified": False,
        "research_only": True,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
        **NO_ACTION_GATES,
    }


def report_text(summary: dict[str, Any]) -> str:
    lines = [
        "V22.020 DRAM Daily Decision Panel R2",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"dram_panel_row_count={summary['dram_panel_row_count']}",
        f"latest_local_plan_source={summary['latest_local_plan_source']}",
        f"latest_local_plan_date={summary['latest_local_plan_date']}",
        f"final_research_action_label={summary['final_research_action_label']}",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_allowed=False",
        "market_data_fetch_allowed=False",
        "moomoo_connection_allowed=False",
        "option_chain_fetch_allowed=False",
        "daily_chain_execution_allowed=False",
        "protected_outputs_modified=False",
    ]
    return "\n".join(lines) + "\n"


def run(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    forward_dashboard = read_csv_rows(repo_root / FORWARD_DASHBOARD_INPUT)
    _forward_summary = read_json(repo_root / FORWARD_SUMMARY_INPUT)
    sources, best_plan = source_audit_rows(repo_root)
    forward = forward_rows(forward_dashboard)
    panel_rows: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    if (repo_root / FORWARD_DASHBOARD_INPUT).exists() and (repo_root / FORWARD_SUMMARY_INPUT).exists():
        panel = daily_panel_row(forward_dashboard, sources, best_plan)
        panel_rows = [panel]
        signals = signal_rows(panel)
    summary = summary_payload(repo_root, panel_rows, signals, forward, sources, best_plan)

    write_csv(output_dir / "v22_dram_daily_decision_panel.csv", DAILY_FIELDNAMES, panel_rows)
    write_csv(output_dir / "v22_dram_signal_to_action_panel.csv", SIGNAL_FIELDNAMES, signals)
    write_csv(output_dir / "v22_dram_forward_maturity_panel.csv", FORWARD_FIELDNAMES, forward)
    write_csv(output_dir / "v22_dram_source_audit.csv", SOURCE_FIELDNAMES, sources)
    write_json(output_dir / "v22_dram_risk_state.json", risk_state_payload())
    write_json(output_dir / "v22_dram_daily_decision_panel_summary.json", summary)
    write_json(output_dir / "v22_dram_daily_decision_panel_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.020_dram_daily_decision_panel_r2_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_dram_daily_decision_panel_summary.json'}")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_allowed=False")
    return 1 if payload["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
