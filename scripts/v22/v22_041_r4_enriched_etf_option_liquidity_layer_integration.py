#!/usr/bin/env python
"""V22.041 R4 enriched ETF option liquidity layer integration audit."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path
from typing import Any, Callable


MODULE_ID = "V22.041_R4"
MODULE_NAME = "ENRICHED_ETF_OPTION_LIQUIDITY_LAYER_INTEGRATION"
STAGE = "V22.041_R4_ENRICHED_ETF_OPTION_LIQUIDITY_LAYER_INTEGRATION"
OUT_REL = Path("outputs") / "v22" / STAGE
V22_041_OUT_REL = Path("outputs") / "v22" / "V22.041_OPTION_INTRADAY_ETF_ONLY_RESEARCH_LAYER_R1"
R3_OUT_REL = Path("outputs") / "v22" / "V22.041_R3_LIVE_OPTION_QUOTE_ENRICHMENT_FROM_CHAIN_CODES"

PASS_STATUS = "PASS_V22_041_R4_ENRICHED_ETF_OPTION_LIQUIDITY_LAYER_INTEGRATED"
WARN_ZERO_STATUS = "WARN_V22_041_R4_INTEGRATED_BUT_ZERO_LIQUIDITY_CANDIDATES"
WARN_FALLBACK_STATUS = "WARN_V22_041_R4_FALLBACK_ROWS_USED_LIVE_INTEGRATION_NOT_VERIFIED"
PASS_DECISION = "ENRICHED_ETF_OPTION_LIQUIDITY_LAYER_READY_FOR_V22_042_RESEARCH_ONLY"
REVIEW_DECISION = "ENRICHED_ETF_OPTION_LIQUIDITY_LAYER_REVIEW_REQUIRED_RESEARCH_ONLY"

PATCH_FIELDS = ["patch_item", "patch_applied", "evidence"]
RERUN_FIELDS = ["rerun_step", "attempted", "completed", "status", "detail"]
SUMMARY_FIELDS = [
    "final_status", "final_decision", "execution_mode", "opend_port_reachable",
    "moomoo_quote_context_connected", "moomoo_quote_context_disconnected_cleanly",
    "real_readonly_quote_verified", "fallback_rows_used", "v22_041_patch_applied",
    "v22_041_rerun_attempted", "v22_041_rerun_completed", "v22_041_final_status",
    "v22_041_final_decision", "v22_041_quote_access_status", "total_raw_contract_count",
    "total_dte_eligible_count", "enrichment_target_count", "enrichment_success_count",
    "bid_field_mapped", "ask_field_mapped", "volume_field_mapped", "valid_bid_ask_count",
    "finite_spread_pct_count", "spread_pass_count", "volume_positive_count",
    "liquidity_candidate_count", "greeks_missing_warning_only", "trade_context_used",
    "unlock_trade_called", "place_order_called", "broker_action_allowed",
    "official_adoption_allowed", "research_only",
]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise ImportError(f"Unable to load {path}")
    spec.loader.exec_module(module)
    return module


def patch_applied(repo_root: Path) -> tuple[bool, list[dict[str, Any]]]:
    target = repo_root / "scripts" / "v22" / "v22_041_option_intraday_etf_only_research_layer_r1.py"
    text = target.read_text(encoding="utf-8")
    checks = [
        ("r3_module_loader", "v22_041_r3_live_option_quote_enrichment_from_chain_codes.py" in text),
        ("execute_uses_enriched_rows", "read_only_enriched_option_rows" in text),
        ("fallback_disabled_default", "allow_fallback_rows: bool = False" in text),
        ("enriched_quote_status", "READ_ONLY_OPTION_QUOTE_ENRICHED_FROM_CHAIN_CODES" in text),
    ]
    rows = [{"patch_item": item, "patch_applied": ok, "evidence": item} for item, ok in checks]
    return all(ok for _, ok in checks), rows


def report_text(summary: dict[str, Any]) -> str:
    return "\n".join(["V22.041 R4 Enriched ETF Option Liquidity Layer Integration", *[f"{key}={summary.get(key)}" for key in SUMMARY_FIELDS]]) + "\n"


def run(
    repo_root: Path,
    execute: bool = False,
    host: str = "127.0.0.1",
    port: int = 18441,
    max_contracts: int = 1000,
    batch_size: int = 100,
    max_spread_pct: float = 0.30,
    include_zero_dte: bool = False,
    v22_run_func: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    applied, patch_rows = patch_applied(repo_root)
    rerun_attempted = execute
    rerun_completed = False
    rerun_rows: list[dict[str, Any]] = []
    if execute:
        try:
            if v22_run_func is None:
                v22 = load_module(repo_root / "scripts" / "v22" / "v22_041_option_intraday_etf_only_research_layer_r1.py", "v22_041_main_for_r4")
                v22_run_func = v22.run
            v22_summary = v22_run_func(repo_root, True, None, 1, 21, include_zero_dte, max_spread_pct, host, port, max_contracts, batch_size, False)
            rerun_completed = True
            rerun_rows.append({"rerun_step": "v22_041_execute_enriched", "attempted": True, "completed": True, "status": v22_summary.get("final_status", ""), "detail": v22_summary.get("quote_access_status", "")})
        except Exception as exc:  # noqa: BLE001
            v22_summary = {}
            rerun_rows.append({"rerun_step": "v22_041_execute_enriched", "attempted": True, "completed": False, "status": type(exc).__name__, "detail": str(exc)})
    else:
        v22_summary = read_json(repo_root / V22_041_OUT_REL / "v22_041_summary.json")
        rerun_rows.append({"rerun_step": "plan_mode_no_rerun", "attempted": False, "completed": False, "status": "PLAN_MODE", "detail": ""})
    r3_summary = read_json(repo_root / R3_OUT_REL / "v22_041_r3_summary.json")
    fallback = bool(v22_summary.get("fallback_rows_used", False))
    liquidity = int(v22_summary.get("liquidity_candidate_count", r3_summary.get("liquidity_candidate_count", 0)) or 0)
    if fallback:
        final_status, final_decision = WARN_FALLBACK_STATUS, REVIEW_DECISION
    elif liquidity <= 0:
        final_status, final_decision = WARN_ZERO_STATUS, REVIEW_DECISION
    else:
        final_status, final_decision = PASS_STATUS, PASS_DECISION
    summary = {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "final_status": final_status,
        "final_decision": final_decision,
        "execution_mode": "EXECUTE_READ_ONLY" if execute else "PLAN",
        "opend_port_reachable": r3_summary.get("opend_port_reachable", False),
        "moomoo_quote_context_connected": r3_summary.get("moomoo_quote_context_connected", False),
        "moomoo_quote_context_disconnected_cleanly": r3_summary.get("moomoo_quote_context_disconnected_cleanly", False),
        "real_readonly_quote_verified": bool(v22_summary.get("real_readonly_quote_verified", False)),
        "fallback_rows_used": fallback,
        "v22_041_patch_applied": applied,
        "v22_041_rerun_attempted": rerun_attempted,
        "v22_041_rerun_completed": rerun_completed,
        "v22_041_final_status": v22_summary.get("final_status", ""),
        "v22_041_final_decision": v22_summary.get("final_decision", ""),
        "v22_041_quote_access_status": v22_summary.get("quote_access_status", ""),
        "total_raw_contract_count": r3_summary.get("total_raw_contract_count", 0),
        "total_dte_eligible_count": r3_summary.get("total_dte_eligible_count", 0),
        "enrichment_target_count": r3_summary.get("enrichment_target_count", v22_summary.get("enrichment_target_count", 0)),
        "enrichment_success_count": r3_summary.get("enrichment_success_count", v22_summary.get("enrichment_success_count", 0)),
        "bid_field_mapped": r3_summary.get("bid_field_mapped", v22_summary.get("bid_field_mapped", False)),
        "ask_field_mapped": r3_summary.get("ask_field_mapped", v22_summary.get("ask_field_mapped", False)),
        "volume_field_mapped": r3_summary.get("volume_field_mapped", v22_summary.get("volume_field_mapped", False)),
        "valid_bid_ask_count": r3_summary.get("valid_bid_ask_count", v22_summary.get("valid_bid_ask_count", 0)),
        "finite_spread_pct_count": r3_summary.get("finite_spread_pct_count", v22_summary.get("valid_spread_pct_count", 0)),
        "spread_pass_count": r3_summary.get("spread_pass_count", 0),
        "volume_positive_count": r3_summary.get("volume_positive_count", v22_summary.get("valid_volume_count", 0)),
        "liquidity_candidate_count": liquidity,
        "greeks_missing_warning_only": True,
        "trade_context_used": False,
        "unlock_trade_called": False,
        "place_order_called": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }
    write_csv(output_dir / "integration_patch_audit.csv", PATCH_FIELDS, patch_rows)
    write_csv(output_dir / "enriched_v22_041_rerun_audit.csv", RERUN_FIELDS, rerun_rows)
    write_json(output_dir / "v22_041_r4_summary.json", summary)
    (output_dir / "V22.041_R4_enriched_etf_option_liquidity_layer_integration_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18441)
    parser.add_argument("--max-contracts", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-spread-pct", type=float, default=0.30)
    parser.add_argument("--include-zero-dte", action="store_true", default=False)
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.execute, args.host, args.port, args.max_contracts, args.batch_size, args.max_spread_pct, args.include_zero_dte)
    for key in SUMMARY_FIELDS:
        print(f"{key}={summary.get(key)}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_041_r4_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
