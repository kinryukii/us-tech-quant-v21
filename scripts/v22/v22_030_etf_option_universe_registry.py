#!/usr/bin/env python
"""V22.030 ETF option universe registry.

Static read-only universe freeze for ETF option research. This module does not
fetch option chains or market data, connect to brokers, execute chains, mutate
caches or historical outputs, or generate orders.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


MODULE_ID = "V22.030"
MODULE_NAME = "ETF_OPTION_UNIVERSE_REGISTRY"
STAGE = "V22.030_ETF_OPTION_UNIVERSE_REGISTRY"
OUT_REL = Path("outputs") / "v22" / STAGE
FREEZE_DATE = date(2026, 7, 6).isoformat()

PASS_STATUS = "PASS_V22_030_ETF_OPTION_UNIVERSE_REGISTRY_READY"
READY_DECISION = "ETF_OPTION_UNIVERSE_REGISTRY_READY_RESEARCH_ONLY"

INITIAL_STRATEGIES = ["LONG_CALL", "LONG_PUT", "DEBIT_CALL_SPREAD", "DEBIT_PUT_SPREAD"]
LATER_RESEARCH_STRATEGIES = [
    "LONG_STRADDLE",
    "LONG_STRANGLE",
    "CALL_BUTTERFLY_DEBIT",
    "PUT_BUTTERFLY_DEBIT",
    "CALENDAR_DEBIT_SPREAD",
    "DIAGONAL_DEBIT_SPREAD",
]
BLOCKED_STRATEGIES = [
    "NAKED_SHORT_CALL",
    "NAKED_SHORT_PUT",
    "SHORT_STRADDLE",
    "SHORT_STRANGLE",
    "UNCOVERED_RATIO_SPREAD",
    "SHORT_PREMIUM_0DTE",
    "AUTO_CREDIT_SPREAD",
    "AUTO_IRON_CONDOR",
    "AUTO_TRADE",
]
EXCLUDED_INDEX_OPTIONS = ["SPX", "XSP", "NDX", "XND", "RUT", "RUTW"]

UNIVERSE_SPECS = [
    ("SMH", "SEMICONDUCTOR", "CORE_ETF", "CORE", False, False, 1),
    ("SOXX", "SEMICONDUCTOR", "CORE_ETF", "CORE", False, False, 1),
    ("QQQ", "NASDAQ", "CORE_ETF", "CORE", False, False, 1),
    ("SPY", "SP500", "CORE_ETF", "CORE", False, False, 1),
    ("DIA", "DOW", "CORE_ETF", "CORE", False, False, 1),
    ("SOXL", "SEMICONDUCTOR", "SECONDARY_LEVERAGED_LONG", "SECONDARY_HIGH_RISK", True, False, 3),
    ("TQQQ", "NASDAQ", "SECONDARY_LEVERAGED_LONG", "SECONDARY_HIGH_RISK", True, False, 3),
    ("SPXL", "SP500", "SECONDARY_LEVERAGED_LONG", "SECONDARY_HIGH_RISK", True, False, 3),
    ("UDOW", "DOW", "SECONDARY_LEVERAGED_LONG", "SECONDARY_HIGH_RISK", True, False, 3),
    ("SOXS", "SEMICONDUCTOR", "SECONDARY_LEVERAGED_INVERSE", "SECONDARY_HIGH_RISK", True, True, -3),
    ("SQQQ", "NASDAQ", "SECONDARY_LEVERAGED_INVERSE", "SECONDARY_HIGH_RISK", True, True, -3),
    ("SPXS", "SP500", "SECONDARY_LEVERAGED_INVERSE", "SECONDARY_HIGH_RISK", True, True, -3),
    ("SDOW", "DOW", "SECONDARY_LEVERAGED_INVERSE", "SECONDARY_HIGH_RISK", True, True, -3),
]

NO_ACTION_GATES = {
    "research_only": True,
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

NEXT_RECOMMENDED_MODULES = [
    "V22.031_ETF_OPTION_CONTRACT_SPEC_REGISTRY",
    "V22.032_MOOMOO_ETF_OPTION_CHAIN_SNAPSHOT",
    "V22.033_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT",
    "V22.034_OPTION_PACKAGE_ACCOUNTING_SCHEMA",
]

UNIVERSE_FIELDNAMES = [
    "ticker",
    "theme_bucket",
    "universe_group",
    "universe_tier",
    "leveraged_flag",
    "inverse_flag",
    "leverage_multiple",
    "high_risk_secondary_flag",
    "core_priority_required",
    "option_research_allowed",
    "option_chain_fetch_allowed_in_v22_030",
    "allowed_initial_strategy_scope",
    "allowed_later_research_strategy_scope",
    "blocked_strategy_scope",
    "requires_stronger_signal_than_core",
    "requires_liquidity_check",
    "requires_spread_check",
    "manual_review_required",
    "broker_action_allowed",
    "official_adoption_allowed",
    "trade_allowed",
    "research_only",
    "reason",
]

GROUP_FIELDNAMES = [
    "universe_group",
    "ticker_count",
    "leveraged_count",
    "inverse_count",
    "core_count",
    "high_risk_secondary_count",
    "option_research_allowed_count",
    "option_chain_fetch_allowed_count",
    "broker_action_allowed_count",
    "official_adoption_allowed_count",
    "trade_allowed_count",
    "group_recommendation",
]

STRATEGY_FIELDNAMES = [
    "strategy_name",
    "strategy_group",
    "permission_status",
    "allowed_for_core_etf",
    "allowed_for_secondary_leveraged_long",
    "allowed_for_secondary_leveraged_inverse",
    "initial_phase_allowed",
    "research_only",
    "naked_short_exposure_allowed",
    "defined_risk_required",
    "max_loss_required",
    "broker_action_allowed",
    "trade_allowed",
    "reason",
]

EXCLUSION_FIELDNAMES = [
    "excluded_symbol",
    "excluded_type",
    "reason",
    "option_research_allowed",
    "option_chain_fetch_allowed",
    "broker_action_allowed",
    "official_adoption_allowed",
    "trade_allowed",
]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    if output_dir.resolve() != expected:
        raise ValueError(f"V22.030 output directory must be {expected}, got {output_dir.resolve()}")


def universe_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ticker, theme, group, tier, leveraged, inverse, multiple in UNIVERSE_SPECS:
        high_risk = tier == "SECONDARY_HIGH_RISK"
        rows.append(
            {
                "ticker": ticker,
                "theme_bucket": theme,
                "universe_group": group,
                "universe_tier": tier,
                "leveraged_flag": leveraged,
                "inverse_flag": inverse,
                "leverage_multiple": multiple,
                "high_risk_secondary_flag": high_risk,
                "core_priority_required": high_risk,
                "option_research_allowed": True,
                "option_chain_fetch_allowed_in_v22_030": False,
                "allowed_initial_strategy_scope": ";".join(INITIAL_STRATEGIES),
                "allowed_later_research_strategy_scope": ";".join(LATER_RESEARCH_STRATEGIES),
                "blocked_strategy_scope": ";".join(BLOCKED_STRATEGIES),
                "requires_stronger_signal_than_core": high_risk,
                "requires_liquidity_check": True,
                "requires_spread_check": True,
                "manual_review_required": True,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
                "trade_allowed": False,
                "research_only": True,
                "reason": "Core ETF research universe." if not high_risk else "Secondary leveraged ETF; high-risk manual-review-only research candidate.",
            }
        )
    return rows


def group_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for group in sorted({row["universe_group"] for row in rows}):
        members = [row for row in rows if row["universe_group"] == group]
        summaries.append(
            {
                "universe_group": group,
                "ticker_count": len(members),
                "leveraged_count": sum(1 for row in members if row["leveraged_flag"] is True),
                "inverse_count": sum(1 for row in members if row["inverse_flag"] is True),
                "core_count": sum(1 for row in members if row["universe_tier"] == "CORE"),
                "high_risk_secondary_count": sum(1 for row in members if row["high_risk_secondary_flag"] is True),
                "option_research_allowed_count": sum(1 for row in members if row["option_research_allowed"] is True),
                "option_chain_fetch_allowed_count": 0,
                "broker_action_allowed_count": 0,
                "official_adoption_allowed_count": 0,
                "trade_allowed_count": 0,
                "group_recommendation": "Research-only universe; require manual liquidity/spread review before any future workflow.",
            }
        )
    return summaries


def strategy_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy in INITIAL_STRATEGIES:
        rows.append(strategy_row(strategy, "DEFINED_RISK_DIRECTIONAL", "ALLOWED_INITIAL_RESEARCH", True))
    for strategy in LATER_RESEARCH_STRATEGIES:
        rows.append(strategy_row(strategy, "DEFINED_RISK_COMPLEX", "ALLOWED_LATER_RESEARCH", False))
    for strategy in BLOCKED_STRATEGIES:
        rows.append(strategy_row(strategy, "BLOCKED_SHORT_OR_AUTO", "BLOCKED", False))
    return rows


def strategy_row(strategy: str, group: str, status: str, initial: bool) -> dict[str, Any]:
    blocked = status == "BLOCKED"
    return {
        "strategy_name": strategy,
        "strategy_group": group,
        "permission_status": status,
        "allowed_for_core_etf": not blocked,
        "allowed_for_secondary_leveraged_long": not blocked,
        "allowed_for_secondary_leveraged_inverse": not blocked,
        "initial_phase_allowed": initial,
        "research_only": True,
        "naked_short_exposure_allowed": False,
        "defined_risk_required": True,
        "max_loss_required": True,
        "broker_action_allowed": False,
        "trade_allowed": False,
        "reason": "Research-only strategy permission; no broker or trade permission." if not blocked else "Blocked strategy: short premium, uncovered, or automated exposure is not allowed.",
    }


def exclusion_rows() -> list[dict[str, Any]]:
    return [
        {
            "excluded_symbol": symbol,
            "excluded_type": "CASH_SETTLED_INDEX_OPTION",
            "reason": "Excluded from ETF option universe; cash-settled index options are out of V22.030 scope.",
            "option_research_allowed": False,
            "option_chain_fetch_allowed": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "trade_allowed": False,
        }
        for symbol in EXCLUDED_INDEX_OPTIONS
    ]


def summary_payload(rows: list[dict[str, Any]], strategies: list[dict[str, Any]], exclusions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "stage": STAGE,
        "freeze_date": FREEZE_DATE,
        "final_status": PASS_STATUS,
        "final_decision": READY_DECISION,
        "core_etf_count": sum(1 for row in rows if row["universe_group"] == "CORE_ETF"),
        "secondary_leveraged_long_count": sum(1 for row in rows if row["universe_group"] == "SECONDARY_LEVERAGED_LONG"),
        "secondary_leveraged_inverse_count": sum(1 for row in rows if row["universe_group"] == "SECONDARY_LEVERAGED_INVERSE"),
        "total_universe_count": len(rows),
        "excluded_cash_settled_index_option_count": len(exclusions),
        "allowed_initial_strategy_count": sum(1 for row in strategies if row["permission_status"] == "ALLOWED_INITIAL_RESEARCH"),
        "allowed_later_research_strategy_count": sum(1 for row in strategies if row["permission_status"] == "ALLOWED_LATER_RESEARCH"),
        "blocked_strategy_count": sum(1 for row in strategies if row["permission_status"] == "BLOCKED"),
        "leveraged_etf_count": sum(1 for row in rows if row["leveraged_flag"] is True),
        "inverse_leveraged_etf_count": sum(1 for row in rows if row["inverse_flag"] is True),
        "high_risk_secondary_count": sum(1 for row in rows if row["high_risk_secondary_flag"] is True),
        "option_research_allowed_count": sum(1 for row in rows if row["option_research_allowed"] is True),
        "option_chain_fetch_allowed_count": 0,
        "broker_action_allowed_count": 0,
        "official_adoption_allowed_count": 0,
        "trade_allowed_count": 0,
        "protected_outputs_modified": False,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
        **NO_ACTION_GATES,
    }


def risk_gate_payload() -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "allowed_side_effects": ["create_outputs_v22_030_only"],
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
        **{key: value for key, value in NO_ACTION_GATES.items() if key != "research_only"},
    }


def report_text(summary: dict[str, Any]) -> str:
    lines = [
        "V22.030 ETF Option Universe Registry",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"total_universe_count={summary['total_universe_count']}",
        f"core_etf_count={summary['core_etf_count']}",
        f"leveraged_etf_count={summary['leveraged_etf_count']}",
        f"blocked_strategy_count={summary['blocked_strategy_count']}",
        "option_chain_fetch_allowed=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_allowed=False",
        "protected_outputs_modified=False",
    ]
    return "\n".join(lines) + "\n"


def run(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    universe = universe_rows()
    groups = group_summary_rows(universe)
    strategies = strategy_rows()
    exclusions = exclusion_rows()
    summary = summary_payload(universe, strategies, exclusions)

    write_csv(output_dir / "v22_etf_option_universe_registry.csv", UNIVERSE_FIELDNAMES, universe)
    write_csv(output_dir / "v22_etf_option_universe_group_summary.csv", GROUP_FIELDNAMES, groups)
    write_csv(output_dir / "v22_etf_option_strategy_permission_registry.csv", STRATEGY_FIELDNAMES, strategies)
    write_csv(output_dir / "v22_etf_option_exclusion_registry.csv", EXCLUSION_FIELDNAMES, exclusions)
    write_json(output_dir / "v22_etf_option_universe_summary.json", summary)
    write_json(output_dir / "v22_etf_option_universe_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.030_etf_option_universe_registry_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_etf_option_universe_summary.json'}")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_allowed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
