#!/usr/bin/env python
"""V21.230_R1 Moomoo/Futu OpenD readiness and permission probe.

Probe-only stage. It may connect to local OpenD and perform a tiny quote
snapshot probe, but it never requests bulk historical bars, writes market data
to cache/canonical locations, unlocks trade, or performs broker actions.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import importlib.util
import json
import re
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.230_R1_MOOMOO_OPEND_READINESS_AND_PERMISSION_PROBE"
OUT_REL = Path("outputs/v21") / STAGE
V230_REL = Path("outputs/v21/V21.230_MOOMOO_ONLY_HISTORICAL_REFETCH_DRY_RUN")
NEXT_STAGE = "V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
PASS_STATUS = "PASS_V21_230_R1_MOOMOO_OPEND_READY_FOR_V21_231"
WARN_STATUS = "WARN_V21_230_R1_MOOMOO_OPEND_NOT_READY_FOR_V21_231"
FAIL_POLICY_STATUS = "FAIL_V21_230_R1_POLICY_VIOLATION"
FAIL_INPUT_STATUS = "FAIL_V21_230_R1_MISSING_V21_230_INPUTS"
PASS_DECISION = "MOOMOO_OPEND_READY_FOR_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
WARN_DECISION = "MOOMOO_OPEND_NOT_READY_FIX_CONNECTION_OR_PERMISSION_BEFORE_V21_231"
REQUIRED_V230_ARTIFACTS = [
    "v21_230_summary.json",
    "moomoo_refetch_dry_run_plan.csv",
    "ticker_universe_resolution.csv",
    "moomoo_frequency_plan.csv",
    "moomoo_adjustment_plan.csv",
    "dram_intraday_refetch_plan.csv",
    "abcde_daily_refetch_plan.csv",
    "v21_231_execution_prerequisites.csv",
    "dry_run_policy_gate.json",
]
FORBIDDEN_PROVIDER = "y" + "finance"
FORBIDDEN_PROVIDER_CALL = "yf" + ".download"
SDK_MODULE_NAMES = ["moo" + "moo", "fu" + "tu"]

CONNECTION_FIELDS = ["check_name","host","port","attempted","passed","latency_ms","error_type","error_message","severity","notes"]
ENV_FIELDS = ["check_name","expected","actual","passed","severity","notes"]
IMPORT_FIELDS = ["module_name","import_attempted","import_passed","version","error_type","error_message","notes"]
CAP_FIELDS = ["capability","attempted","passed","required_for_v21_231","severity","error_type","error_message","notes"]
SYMBOL_FIELDS = ["ticker","moomoo_symbol","source_scope","selected_for_probe","symbol_format_valid","market","notes"]
QUOTE_FIELDS = ["ticker","moomoo_symbol","attempted","passed","quote_returned","field_count","error_type","error_message","notes"]
HIST_FIELDS = ["capability","attempted","passed","bulk_fetch_performed","required_for_v21_231","severity","notes"]
PERMISSION_FIELDS = ["permission_or_capability","attempted","passed","required_for_daily_raw","required_for_daily_qfq","required_for_dram_intraday","required_for_v21_231","severity","notes"]
CROSS_FIELDS = ["check_name","expected","actual","passed","severity","notes"]
GATE_FIELDS = ["gate","passed","blocks_v21_231","severity","required_action","notes"]
AUDIT_FIELDS = ["check_name","passed","yfinance_import_present","yfinance_call_present","yahoo_default_allowed","external_fallback_default_allowed","notes"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bool_text(value: bool) -> str:
    return "True" if value else "False"


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def read_csv_rows(path: Path, limit: int = 1000) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = []
            for row in csv.DictReader(handle):
                rows.append({k: (v or "") for k, v in row.items() if k is not None})
                if len(rows) >= limit:
                    break
            return rows
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def load_policy_guard(repo_root: Path):
    guard_path = repo_root / "scripts/v21/v21_data_source_policy_guard.py"
    if not guard_path.exists():
        raise FileNotFoundError(str(guard_path))
    spec = importlib.util.spec_from_file_location("v21_data_source_policy_guard", guard_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load policy guard: {guard_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def policy_gate() -> dict[str, Any]:
    return {
        "policy_version": "V21.230_R1",
        "probe_only": True,
        "bulk_historical_fetch_allowed_now": False,
        "canonical_rebuild_allowed_now": False,
        "overwrite_allowed_now": False,
        "yfinance_allowed": False,
        "yahoo_allowed": False,
        "external_fallback_allowed_for_canonical": False,
        "external_fallback_allowed_for_dram": False,
        "external_fallback_allowed_for_abcde": False,
        "moomoo_import_allowed_now": True,
        "moomoo_opend_probe_allowed_now": True,
        "minimal_quote_probe_allowed_now": True,
        "trade_unlock_allowed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "next_allowed_stage": NEXT_STAGE,
    }


def validate_v230_inputs(v230_dir: Path) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
    summary = read_json(v230_dir / "v21_230_summary.json")
    rows = []
    ok = True
    for name in REQUIRED_V230_ARTIFACTS:
        path = v230_dir / name
        exists = path.exists()
        ok = ok and exists
        rows.append({
            "check_name": f"v21_230_artifact_{name}",
            "expected": "present",
            "actual": "present" if exists else "missing",
            "passed": bool_text(exists),
            "severity": "ERROR" if not exists else "INFO",
            "notes": str(path),
        })
    ready_status = summary.get("final_status", "")
    gate = read_json(v230_dir / "dry_run_policy_gate.json")
    policy_ok = bool(gate.get("dry_run_only") is True and gate.get("actual_historical_fetch_allowed_now") is False)
    rows.append({
        "check_name": "v21_230_dry_run_gate",
        "expected": "dry_run_only true and historical fetch false",
        "actual": json.dumps({"dry_run_only": gate.get("dry_run_only"), "actual_historical_fetch_allowed_now": gate.get("actual_historical_fetch_allowed_now")}, sort_keys=True),
        "passed": bool_text(policy_ok),
        "severity": "ERROR" if not policy_ok else "INFO",
        "notes": ready_status,
    })
    return ok and policy_ok, rows, summary


def select_probe_symbols(v230_dir: Path, max_count: int) -> list[dict[str, Any]]:
    universe = read_csv_rows(v230_dir / "ticker_universe_resolution.csv", limit=10000)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(row: dict[str, str], reason: str) -> None:
        ticker = row.get("ticker", "").strip().upper()
        symbol = row.get("resolved_symbol") or row.get("moomoo_symbol") or (f"US.{ticker}" if ticker else "")
        if not ticker or ticker in seen or len(selected) >= max_count:
            return
        seen.add(ticker)
        selected.append({
            "ticker": ticker,
            "moomoo_symbol": symbol,
            "source_scope": reason,
            "selected_for_probe": "True",
            "symbol_format_valid": bool_text(bool(re.match(r"^[A-Z]{2}\.[A-Z0-9.\-]+$", symbol))),
            "market": row.get("market", "US") or "US",
            "notes": "deterministic V21.230 probe sample",
        })

    for row in universe:
        if row.get("ticker", "").strip().upper() == "DRAM":
            add(row, "DRAM")
            break
    for row in universe:
        if len(selected) >= max_count:
            break
        if row.get("included_in_abcde") == "True" or row.get("included_in_active_universe") == "True":
            add(row, "ABCDE_OR_ACTIVE_UNIVERSE")
    return selected


def socket_probe(host: str, port: int, timeout_seconds: int, disabled: bool) -> tuple[list[dict[str, Any]], bool]:
    if disabled:
        return ([{
            "check_name": "local_opend_socket",
            "host": host,
            "port": port,
            "attempted": "False",
            "passed": "False",
            "latency_ms": "",
            "error_type": "NOT_PROBED_DISABLED_BY_FLAG",
            "error_message": "",
            "severity": "WARN",
            "notes": "network probe disabled by CLI flag",
        }], False)
    start = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_seconds):
            latency = int((time.perf_counter() - start) * 1000)
            return ([{
                "check_name": "local_opend_socket",
                "host": host,
                "port": port,
                "attempted": "True",
                "passed": "True",
                "latency_ms": latency,
                "error_type": "",
                "error_message": "",
                "severity": "INFO",
                "notes": "TCP connection to local OpenD port succeeded",
            }], True)
    except Exception as exc:
        latency = int((time.perf_counter() - start) * 1000)
        return ([{
            "check_name": "local_opend_socket",
            "host": host,
            "port": port,
            "attempted": "True",
            "passed": "False",
            "latency_ms": latency,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "severity": "WARN",
            "notes": "OpenD not reachable; V21.231 should wait for connection repair",
        }], False)


def guarded_import_probe(no_import: bool) -> tuple[list[dict[str, Any]], Any | None, bool]:
    if no_import:
        return ([{
            "module_name": name,
            "import_attempted": "False",
            "import_passed": "False",
            "version": "",
            "error_type": "NOT_PROBED_IMPORT_DISABLED_BY_FLAG",
            "error_message": "",
            "notes": "SDK import disabled by CLI flag",
        } for name in SDK_MODULE_NAMES], None, False)
    rows = []
    primary_module = None
    any_passed = False
    for name in SDK_MODULE_NAMES:
        try:
            module = importlib.import_module(name)
            version = str(getattr(module, "__version__", ""))
            rows.append({
                "module_name": name,
                "import_attempted": "True",
                "import_passed": "True",
                "version": version,
                "error_type": "",
                "error_message": "",
                "notes": "SDK import succeeded",
            })
            if primary_module is None:
                primary_module = module
            any_passed = True
        except Exception as exc:
            rows.append({
                "module_name": name,
                "import_attempted": "True",
                "import_passed": "False",
                "version": "",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "notes": "SDK import failed",
            })
    return rows, primary_module, any_passed


def api_capability_probe(module: Any | None, import_passed: bool, no_import: bool) -> list[dict[str, Any]]:
    required = {
        "OpenQuoteContext": "OpenD quote context",
        "get_market_snapshot": "minimal quote snapshot method",
        "request_history_kline": "historical kline API presence only; not called",
    }
    rows = []
    for capability, note in required.items():
        attempted = import_passed and not no_import
        passed = False
        error_type = ""
        error_message = ""
        if attempted:
            if capability == "OpenQuoteContext":
                passed = hasattr(module, capability)
            elif capability in {"get_market_snapshot", "request_history_kline"}:
                ctx = getattr(module, "OpenQuoteContext", None)
                passed = hasattr(ctx, capability) if ctx is not None else False
            if not passed:
                error_type = "MissingCapability"
                error_message = capability
        rows.append({
            "capability": capability,
            "attempted": bool_text(attempted),
            "passed": bool_text(passed),
            "required_for_v21_231": "True",
            "severity": "ERROR" if attempted and not passed else "INFO",
            "error_type": error_type,
            "error_message": error_message,
            "notes": note,
        })
    return rows


def minimal_quote_probe(module: Any | None, symbols: list[dict[str, Any]], host: str, port: int, import_passed: bool, connection_passed: bool, allow_quote: bool, network_disabled: bool) -> list[dict[str, Any]]:
    rows = []
    attempted = bool(import_passed and connection_passed and allow_quote and not network_disabled and module is not None)
    if not attempted:
        reason = "NOT_ATTEMPTED"
        if not allow_quote:
            reason = "QUOTE_PROBE_DISABLED"
        elif network_disabled:
            reason = "NETWORK_PROBE_DISABLED"
        elif not import_passed:
            reason = "SDK_IMPORT_FAILED_OR_DISABLED"
        elif not connection_passed:
            reason = "OPEND_CONNECTION_FAILED_OR_DISABLED"
        for symbol in symbols:
            rows.append({
                "ticker": symbol["ticker"],
                "moomoo_symbol": symbol["moomoo_symbol"],
                "attempted": "False",
                "passed": "False",
                "quote_returned": "False",
                "field_count": 0,
                "error_type": reason,
                "error_message": "",
                "notes": "minimal quote probe not attempted",
            })
        return rows
    ctx = None
    try:
        quote_cls = getattr(module, "OpenQuoteContext")
        ctx = quote_cls(host=host, port=int(port))
        api_symbols = [s["moomoo_symbol"] for s in symbols]
        ret = ctx.get_market_snapshot(api_symbols)
        ok_code = getattr(module, "RET_OK", 0)
        passed_call = bool(isinstance(ret, tuple) and len(ret) >= 2 and ret[0] == ok_code)
        payload = ret[1] if isinstance(ret, tuple) and len(ret) >= 2 else None
        for symbol in symbols:
            field_count = 0
            quote_returned = False
            if payload is not None:
                if hasattr(payload, "empty"):
                    quote_returned = not bool(getattr(payload, "empty"))
                    field_count = len(getattr(payload, "columns", []))
                elif isinstance(payload, list):
                    quote_returned = bool(payload)
                    field_count = len(payload[0]) if payload and isinstance(payload[0], dict) else 0
                elif isinstance(payload, dict):
                    quote_returned = bool(payload)
                    field_count = len(payload)
            rows.append({
                "ticker": symbol["ticker"],
                "moomoo_symbol": symbol["moomoo_symbol"],
                "attempted": "True",
                "passed": bool_text(passed_call and quote_returned),
                "quote_returned": bool_text(quote_returned),
                "field_count": field_count,
                "error_type": "" if passed_call else "QuoteProbeFailed",
                "error_message": "" if passed_call else str(payload),
                "notes": "tiny market snapshot probe only; no subscription, no historical bars",
            })
    except Exception as exc:
        for symbol in symbols:
            rows.append({
                "ticker": symbol["ticker"],
                "moomoo_symbol": symbol["moomoo_symbol"],
                "attempted": "True",
                "passed": "False",
                "quote_returned": "False",
                "field_count": 0,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "notes": "minimal quote probe failed",
            })
    finally:
        if ctx is not None and hasattr(ctx, "close"):
            try:
                ctx.close()
            except Exception:
                pass
    return rows


def historical_capability_rows(cap_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    api_pass = any(r["capability"] == "request_history_kline" and r["passed"] == "True" for r in cap_rows)
    return [{
        "capability": "request_history_kline_api_presence_only",
        "attempted": "True",
        "passed": bool_text(api_pass),
        "bulk_fetch_performed": "False",
        "required_for_v21_231": "True",
        "severity": "ERROR" if not api_pass else "INFO",
        "notes": "API presence checked only; historical kline method was not called",
    }]


def permission_rows(import_passed: bool, connection_passed: bool, quote_pass_count: int, hist_api_passed: bool) -> list[dict[str, Any]]:
    ready = import_passed and connection_passed and quote_pass_count > 0 and hist_api_passed
    return [
        {
            "permission_or_capability": "OpenD local connection",
            "attempted": "True",
            "passed": bool_text(connection_passed),
            "required_for_daily_raw": "True",
            "required_for_daily_qfq": "True",
            "required_for_dram_intraday": "True",
            "required_for_v21_231": "True",
            "severity": "ERROR" if not connection_passed else "INFO",
            "notes": "TCP readiness only",
        },
        {
            "permission_or_capability": "minimal quote access",
            "attempted": bool_text(import_passed and connection_passed),
            "passed": bool_text(quote_pass_count > 0),
            "required_for_daily_raw": "False",
            "required_for_daily_qfq": "False",
            "required_for_dram_intraday": "False",
            "required_for_v21_231": "True",
            "severity": "WARN" if quote_pass_count == 0 else "INFO",
            "notes": "tiny sample quote confirms market data session without subscriptions",
        },
        {
            "permission_or_capability": "historical kline API capability",
            "attempted": "True",
            "passed": bool_text(hist_api_passed),
            "required_for_daily_raw": "True",
            "required_for_daily_qfq": "True",
            "required_for_dram_intraday": "True",
            "required_for_v21_231": "True",
            "severity": "ERROR" if not hist_api_passed else "INFO",
            "notes": "presence only; no historical request performed",
        },
        {
            "permission_or_capability": "combined V21.231 readiness",
            "attempted": "True",
            "passed": bool_text(ready),
            "required_for_daily_raw": "True",
            "required_for_daily_qfq": "True",
            "required_for_dram_intraday": "True",
            "required_for_v21_231": "True",
            "severity": "ERROR" if not ready else "INFO",
            "notes": "V21.231 should proceed only when required OpenD readiness passes",
        },
    ]


def self_forbidden_audit(repo_root: Path) -> tuple[list[dict[str, Any]], bool]:
    script = repo_root / "scripts/v21/v21_230_r1_moomoo_opend_readiness_and_permission_probe.py"
    text = script.read_text(encoding="utf-8") if script.exists() else ""
    import_present = bool(re.search(r"(^|\n)\s*(import|from)\s+" + re.escape(FORBIDDEN_PROVIDER), text))
    call_present = FORBIDDEN_PROVIDER_CALL in text
    rows = [{
        "check_name": "v21_230_r1_script_forbidden_provider_audit",
        "passed": bool_text(not import_present and not call_present),
        "yfinance_import_present": bool_text(import_present),
        "yfinance_call_present": bool_text(call_present),
        "yahoo_default_allowed": "False",
        "external_fallback_default_allowed": "False",
        "notes": "static audit of probe script; forbidden provider not imported or called",
    }]
    return rows, import_present or call_present


def environment_rows(host: str, port: int, timeout: int, max_symbols: int, disable_network: bool, no_import: bool) -> list[dict[str, Any]]:
    return [
        {"check_name": "opend_host", "expected": "local OpenD host", "actual": host, "passed": bool_text(bool(host)), "severity": "INFO", "notes": "configured by CLI"},
        {"check_name": "opend_port", "expected": "1-65535", "actual": port, "passed": bool_text(0 < int(port) < 65536), "severity": "INFO", "notes": "configured by CLI"},
        {"check_name": "probe_timeout_seconds", "expected": "positive", "actual": timeout, "passed": bool_text(timeout > 0), "severity": "INFO", "notes": "configured by CLI"},
        {"check_name": "max_symbol_probe_count", "expected": "1-5 default bounded", "actual": max_symbols, "passed": bool_text(max_symbols > 0), "severity": "INFO", "notes": "prevents full-universe probing"},
        {"check_name": "disable_network_probe", "expected": "False for wrapper normal probe", "actual": bool_text(disable_network), "passed": "True", "severity": "INFO", "notes": "when true no socket or OpenD API calls are made"},
        {"check_name": "no_moomoo_import", "expected": "False for wrapper normal probe", "actual": bool_text(no_import), "passed": "True", "severity": "INFO", "notes": "when true SDK import is skipped"},
    ]


def go_no_go_rows(policy_ok: bool, inputs_ok: bool, import_passed: bool, connection_passed: bool, quote_pass_count: int, hist_api_passed: bool) -> list[dict[str, Any]]:
    gates = [
        ("policy_guard", policy_ok, True, "Fix V21 data-source policy guard"),
        ("v21_230_inputs", inputs_ok, True, "Regenerate V21.230 dry-run outputs"),
        ("sdk_import", import_passed, False, "Install/repair current venv SDK package"),
        ("opend_connection", connection_passed, False, "Start or repair local OpenD host/port"),
        ("minimal_quote_probe", quote_pass_count > 0, False, "Confirm quote permission/session"),
        ("historical_api_presence", hist_api_passed, False, "Confirm SDK exposes historical kline API"),
        ("no_bulk_historical_fetch", True, True, ""),
        ("no_trade_unlock_or_broker_action", True, True, ""),
    ]
    rows = []
    for gate, passed, hard_block, action in gates:
        rows.append({
            "gate": gate,
            "passed": bool_text(passed),
            "blocks_v21_231": bool_text(not passed),
            "severity": "ERROR" if not passed and hard_block else "WARN" if not passed else "INFO",
            "required_action": action,
            "notes": "probe-only readiness gate",
        })
    return rows


def run(
    repo_root: Path,
    output_dir: Path,
    v21_230_output_dir: Path | None = None,
    opend_host: str = "127.0.0.1",
    opend_port: int = 11111,
    probe_timeout_seconds: int = 10,
    max_symbol_probe_count: int = 5,
    allow_minimal_quote_probe: bool = True,
    disable_network_probe: bool = False,
    no_moomoo_import: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    v230_dir = (v21_230_output_dir or (repo_root / V230_REL)).resolve()
    error_count = 0
    warning_count = 0
    hard_fail = False
    policy_ok = False
    guard_found = (repo_root / "scripts/v21/v21_data_source_policy_guard.py").exists()
    inputs_ok, cross_rows, v230_summary = validate_v230_inputs(v230_dir)
    if not inputs_ok:
        hard_fail = True
        error_count += 1
    try:
        guard = load_policy_guard(repo_root)
        guard.assert_moomoo_only_policy("V21.230_R1 canonical dram abcde OpenD probe")
        policy = guard.load_data_source_policy(repo_root / "config/v21/data_source_policy.json")
        disallowed = [
            "yfinance_allowed_by_default", "yahoo_allowed_by_default",
            "external_fallback_allowed_for_canonical", "external_fallback_allowed_for_dram", "external_fallback_allowed_for_abcde",
            "broker_action_allowed", "official_adoption_allowed",
        ]
        policy_ok = policy.get("default_data_source_policy") == "MOOMOO_ONLY" and policy.get("research_only") is True and all(policy.get(k) is False for k in disallowed)
    except Exception as exc:
        policy_ok = False
        cross_rows.append({"check_name": "policy_guard_import_and_assert", "expected": "pass", "actual": f"{type(exc).__name__}: {exc}", "passed": "False", "severity": "ERROR", "notes": "central guard must pass"})
    else:
        cross_rows.append({"check_name": "policy_guard_import_and_assert", "expected": "pass", "actual": "pass", "passed": bool_text(policy_ok), "severity": "INFO" if policy_ok else "ERROR", "notes": "central guard imported and used"})
    if not policy_ok:
        hard_fail = True
        error_count += 1
    audit_rows, forbidden_violation = self_forbidden_audit(repo_root)
    if forbidden_violation:
        hard_fail = True
        error_count += 1
    symbols = select_probe_symbols(v230_dir, max(1, int(max_symbol_probe_count))) if inputs_ok else []
    connection_rows, connection_passed = socket_probe(opend_host, int(opend_port), int(probe_timeout_seconds), disable_network_probe)
    import_rows, sdk_module, import_passed = guarded_import_probe(no_moomoo_import)
    cap_rows = api_capability_probe(sdk_module, import_passed, no_moomoo_import)
    hist_rows = historical_capability_rows(cap_rows)
    hist_api_passed = hist_rows[0]["passed"] == "True"
    quote_rows = minimal_quote_probe(sdk_module, symbols, opend_host, int(opend_port), import_passed, connection_passed, allow_minimal_quote_probe, disable_network_probe)
    quote_pass_count = sum(1 for r in quote_rows if r["passed"] == "True")
    quote_fail_count = sum(1 for r in quote_rows if r["attempted"] == "True" and r["passed"] != "True")
    perm_rows = permission_rows(import_passed, connection_passed, quote_pass_count, hist_api_passed)
    gate_rows = go_no_go_rows(policy_ok, inputs_ok, import_passed, connection_passed, quote_pass_count, hist_api_passed)
    required_fail_count = sum(1 for r in perm_rows if r["required_for_v21_231"] == "True" and r["passed"] != "True")
    required_pass_count = sum(1 for r in perm_rows if r["required_for_v21_231"] == "True" and r["passed"] == "True")
    v21_231_blockers = sum(1 for r in gate_rows if r["blocks_v21_231"] == "True")
    warning_count += sum(1 for r in connection_rows + import_rows + cap_rows + hist_rows + perm_rows + gate_rows if r.get("severity") == "WARN")
    error_count += 0 if hard_fail else sum(1 for r in cap_rows + hist_rows + perm_rows if r.get("severity") == "ERROR" and r.get("attempted") == "True")

    write_json(output_dir / "opend_probe_policy_gate.json", policy_gate())
    write_csv(output_dir / "opend_connection_probe.csv", connection_rows, CONNECTION_FIELDS)
    write_csv(output_dir / "opend_environment_probe.csv", environment_rows(opend_host, int(opend_port), int(probe_timeout_seconds), int(max_symbol_probe_count), disable_network_probe, no_moomoo_import), ENV_FIELDS)
    write_csv(output_dir / "moomoo_import_probe.csv", import_rows, IMPORT_FIELDS)
    write_csv(output_dir / "moomoo_api_capability_probe.csv", cap_rows, CAP_FIELDS)
    write_csv(output_dir / "ticker_symbol_probe.csv", symbols, SYMBOL_FIELDS)
    write_csv(output_dir / "minimal_quote_probe.csv", quote_rows, QUOTE_FIELDS)
    write_csv(output_dir / "historical_capability_probe_no_bulk_fetch.csv", hist_rows, HIST_FIELDS)
    write_csv(output_dir / "permission_probe.csv", perm_rows, PERMISSION_FIELDS)
    write_csv(output_dir / "v21_230_plan_crosscheck.csv", cross_rows, CROSS_FIELDS)
    write_csv(output_dir / "v21_231_go_no_go_gate.csv", gate_rows, GATE_FIELDS)
    write_csv(output_dir / "no_yfinance_enforcement_audit.csv", audit_rows, AUDIT_FIELDS)

    if forbidden_violation or (not policy_ok and inputs_ok):
        final_status = FAIL_POLICY_STATUS
    elif not inputs_ok:
        final_status = FAIL_INPUT_STATUS
    elif import_passed and connection_passed and quote_pass_count > 0 and hist_api_passed:
        final_status = PASS_STATUS
    else:
        final_status = WARN_STATUS
    final_decision = PASS_DECISION if final_status == PASS_STATUS else WARN_DECISION
    if final_status.startswith("FAIL_"):
        final_decision = WARN_DECISION
    summary = {
        "final_status": final_status,
        "final_decision": final_decision,
        "repo_root": str(repo_root),
        "output_dir": str(output_dir),
        "v21_230_input_found": inputs_ok,
        "policy_guard_found": guard_found,
        "policy_guard_passed": policy_ok,
        "opend_host": opend_host,
        "opend_port": int(opend_port),
        "moomoo_import_attempted": not no_moomoo_import,
        "moomoo_import_passed": import_passed,
        "opend_connection_attempted": not disable_network_probe,
        "opend_connection_passed": connection_passed,
        "minimal_quote_probe_attempted": any(r["attempted"] == "True" for r in quote_rows),
        "minimal_quote_probe_pass_count": quote_pass_count,
        "minimal_quote_probe_fail_count": quote_fail_count,
        "historical_bulk_fetch_performed": False,
        "ticker_probe_count": len(symbols),
        "required_capability_pass_count": required_pass_count,
        "required_capability_fail_count": required_fail_count,
        "v21_231_blocker_count": v21_231_blockers,
        "v21_231_ready": final_status == PASS_STATUS,
        "yfinance_used": False,
        "yahoo_used": False,
        "external_fallback_used": False,
        "data_fetch_used": any(r["passed"] == "True" for r in quote_rows),
        "moomoo_historical_fetch_used": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "warning_count": warning_count,
        "error_count": error_count,
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "v21_230_final_status": v230_summary.get("final_status", ""),
    }
    write_json(output_dir / "v21_230_r1_summary.json", summary)
    report = "\n".join([
        STAGE,
        f"final_status={final_status}",
        f"final_decision={final_decision}",
        f"moomoo_import_passed={import_passed}",
        f"opend_connection_passed={connection_passed}",
        f"ticker_probe_count={len(symbols)}",
        "historical_bulk_fetch_performed=False",
        "canonical_data_rebuilt=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
    ]) + "\n"
    (output_dir / "V21.230_R1_moomoo_opend_readiness_and_permission_probe_report.txt").write_text(report, encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--v21-230-output-dir", type=Path, default=None)
    parser.add_argument("--opend-host", default="127.0.0.1")
    parser.add_argument("--opend-port", type=int, default=11111)
    parser.add_argument("--probe-timeout-seconds", type=int, default=10)
    parser.add_argument("--max-symbol-probe-count", type=int, default=5)
    parser.add_argument("--allow-minimal-quote-probe", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--disable-network-probe", action="store_true", default=False)
    parser.add_argument("--no-moomoo-import", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    out = args.output_dir or (repo_root / OUT_REL)
    summary = run(
        repo_root=repo_root,
        output_dir=out,
        v21_230_output_dir=args.v21_230_output_dir,
        opend_host=args.opend_host,
        opend_port=args.opend_port,
        probe_timeout_seconds=args.probe_timeout_seconds,
        max_symbol_probe_count=args.max_symbol_probe_count,
        allow_minimal_quote_probe=args.allow_minimal_quote_probe,
        disable_network_probe=args.disable_network_probe,
        no_moomoo_import=args.no_moomoo_import,
    )
    print(str(out / "v21_230_r1_summary.json"))
    return 1 if summary["final_status"].startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
